"""Testes da especificação da placa: modelo, leitura do YAML e referências à base (Marco 4).

O spec.yaml do monitor de umidade é o caso de referência. Os casos de erro partem de uma
cópia dele, estragada de um jeito por vez e gravada numa pasta temporária; o arquivo real
nunca é alterado. Estes testes só precisam do Pydantic e do PyYAML, então também rodam no
GitHub Actions.
"""
import copy
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.componentes.carregar import carregar_todos
from src.especificacao import (Especificacao, ErroEspecificacao, ler_especificacao,
                               referencias_invalidas)

SPEC = Path(__file__).resolve().parents[1] / "placas" / "monitor-umidade" / "spec.yaml"


@pytest.fixture(scope="module")
def base():
    return carregar_todos()


@pytest.fixture
def dados() -> dict:
    """Cópia do spec.yaml, ponto de partida dos casos de erro."""
    try:
        ler_especificacao(SPEC)
    except ErroEspecificacao as e:
        pytest.fail(f"o spec.yaml de referência está inválido, corrija-o primeiro:\n{e}",
                    pytrace=False)
    return copy.deepcopy(yaml.safe_load(SPEC.read_text(encoding="utf-8")))


def _gravar(tmp_path: Path, dados) -> Path:
    arquivo = tmp_path / "spec.yaml"
    arquivo.write_text(yaml.safe_dump(dados, allow_unicode=True, sort_keys=False),
                       encoding="utf-8")
    return arquivo


def _mensagens(erro: ErroEspecificacao) -> str:
    return "\n".join(p.mensagem for p in erro.problemas)


def _falha(tmp_path, dados, trecho: str, base=None):
    with pytest.raises(ErroEspecificacao) as e:
        ler_especificacao(_gravar(tmp_path, dados), base)
    assert trecho in _mensagens(e.value), _mensagens(e.value)


# --- O teste da Parte 2 do guia ----------------------------------------------------------

def test_spec_do_monitor_e_valida_e_so_cita_componentes_da_base(base):
    spec = ler_especificacao(SPEC, base)        # forma e referências
    assert isinstance(spec, Especificacao)
    assert spec.projeto.id == SPEC.parent.name
    citados = {m.componente for m in spec.modulos}
    assert citados <= set(base), f"fora da base: {citados - set(base)}"
    assert referencias_invalidas(spec, base) == []


def test_spec_do_monitor_tem_os_quatro_modulos_da_placa(base):
    spec = ler_especificacao(SPEC, base)
    assert {m.componente for m in spec.modulos} == {
        "esp32-devkitc-v4", "sensor-umidade-capacitivo",
        "display-lcd-1602-i2c", "conversor-nivel-logico-4-canais"}


def test_spec_do_monitor_registra_quem_decidiu_cada_coisa(base):
    spec = ler_especificacao(SPEC, base)
    por_caminho = dict(spec.decisoes())
    assert {d.decidido_por for d in por_caminho.values()} == {"usuario", "agente"}
    # O conversor é a decisão do agente que a proposta usa como exemplo (página 9).
    conversor = next(m for m in spec.modulos if m.componente.startswith("conversor"))
    assert conversor.decidido_por == "agente"
    for caminho, d in spec.decisoes():
        if d.decidido_por == "agente":
            assert d.motivo and d.fonte, caminho


def test_regras_citadas_no_spec_existem_na_base(base):
    spec = ler_especificacao(SPEC, base)
    citadas = [(c.componente, c.regra) for _, d in spec.decisoes() for c in d.regras]
    assert citadas, "o spec.yaml deveria citar as regras que motivaram as decisões"
    for comp, regra in citadas:
        assert regra in {r.id for r in base[comp].regras}, (comp, regra)


# --- Referências à base ------------------------------------------------------------------

def test_componente_fora_da_base_e_recusado(tmp_path, dados, base):
    dados["modulos"][0]["componente"] = "esp32-que-nao-existe"
    _falha(tmp_path, dados, "'esp32-que-nao-existe' não está na base", base)


def test_regra_inexistente_e_recusada(tmp_path, dados, base):
    dados["modulos"][3]["regras"][0]["regra"] = "regra-inventada"
    _falha(tmp_path, dados, "não tem a regra 'regra-inventada'", base)


def test_regra_de_componente_fora_da_placa_e_recusada(tmp_path, dados, base):
    comp = next(iter(base.values()))
    outra_base = dict(base, **{"peca-extra": comp.model_copy(update={"id": "peca-extra"})})
    dados["modulos"][3]["regras"][0]["componente"] = "peca-extra"
    _falha(tmp_path, dados, "não é módulo desta placa", outra_base)


def test_regra_de_componente_fora_da_base_e_recusada(tmp_path, dados, base):
    dados["modulos"][1]["requisitos"][0]["regras"][0]["componente"] = "nao-existe"
    _falha(tmp_path, dados, "'nao-existe' não está na base", base)


def test_todos_os_problemas_de_referencia_aparecem_juntos(tmp_path, dados, base):
    dados["modulos"][0]["componente"] = "a-inexistente"
    dados["modulos"][2]["componente"] = "b-inexistente"
    with pytest.raises(ErroEspecificacao) as e:
        ler_especificacao(_gravar(tmp_path, dados), base)
    msgs = _mensagens(e.value)
    assert "a-inexistente" in msgs and "b-inexistente" in msgs
    assert all(p.arquivo.name == "spec.yaml" for p in e.value.problemas)


def test_sem_base_explicita_le_a_base_do_repositorio():
    assert ler_especificacao(SPEC).projeto.id == "monitor-umidade"


# --- decidido_por --------------------------------------------------------------------------

@pytest.mark.parametrize("valor", ["Usuario", "usuário", "ia", "", None, 1])
def test_decidido_por_so_aceita_usuario_ou_agente(tmp_path, dados, base, valor):
    dados["alimentacao"]["decidido_por"] = valor
    _falha(tmp_path, dados, "alimentacao.decidido_por", base)


@pytest.mark.parametrize("caminho", [
    ("modulos", 0), ("modulos", 1, "requisitos", 0), ("alimentacao",),
    ("restricoes", "camadas"), ("restricoes", "contorno"), ("restricoes", "montagem"),
])
def test_toda_decisao_exige_decidido_por(tmp_path, dados, base, caminho):
    alvo = dados
    for parte in caminho:
        alvo = alvo[parte]
    del alvo["decidido_por"]
    local = ".".join(str(p) for p in caminho) + ".decidido_por"
    _falha(tmp_path, dados, f"{local}: Field required", base)


@pytest.mark.parametrize("campo", ["motivo", "fonte"])
def test_decisao_do_agente_exige_motivo_e_fonte(tmp_path, dados, base, campo):
    assert dados["modulos"][3]["decidido_por"] == "agente"
    del dados["modulos"][3][campo]
    _falha(tmp_path, dados, f"decisão do agente precisa de ['{campo}']", base)


def test_decisao_do_usuario_nao_exige_motivo(tmp_path, dados, base):
    assert dados["alimentacao"]["decidido_por"] == "usuario"
    dados["alimentacao"].pop("motivo", None)
    dados["alimentacao"].pop("fonte", None)
    ler_especificacao(_gravar(tmp_path, dados), base)


# --- Forma do arquivo (mesmas regras da base, ADR-006) --------------------------------------

def test_campo_desconhecido_e_recusado(tmp_path, dados, base):
    dados["alimentacao"]["tensao_maxima"] = 5.0
    _falha(tmp_path, dados, "alimentacao.tensao_maxima: Extra inputs are not permitted", base)


def test_tipo_nao_e_convertido(tmp_path, dados, base):
    dados["alimentacao"]["tensao"] = "5.0"
    _falha(tmp_path, dados, "alimentacao.tensao", base)


def test_camadas_nao_aceita_numero_quebrado(tmp_path, dados, base):
    dados["restricoes"]["camadas"]["valor"] = 2.0
    _falha(tmp_path, dados, "restricoes.camadas.valor", base)


@pytest.mark.parametrize("valor", [0, -5.0])
def test_medidas_e_tensoes_sao_positivas(tmp_path, dados, base, valor):
    dados["restricoes"]["contorno"]["largura"] = valor
    dados["alimentacao"]["tensao"] = valor
    with pytest.raises(ErroEspecificacao) as e:
        ler_especificacao(_gravar(tmp_path, dados), base)
    msgs = _mensagens(e.value)
    assert "restricoes.contorno.largura" in msgs and "alimentacao.tensao" in msgs


def test_origem_da_alimentacao_desconhecida_e_recusada(tmp_path, dados, base):
    dados["alimentacao"]["origem"] = "bateria"
    _falha(tmp_path, dados, "alimentacao.origem", base)


def test_montagem_desconhecida_e_recusada(tmp_path, dados, base):
    dados["restricoes"]["montagem"]["valor"] = "solda_direta"
    _falha(tmp_path, dados, "restricoes.montagem.valor", base)


def test_texto_vazio_e_recusado(tmp_path, dados, base):
    dados["projeto"]["nome"] = "   "
    _falha(tmp_path, dados, "projeto.nome", base)


def test_id_do_componente_fora_do_formato_e_recusado(tmp_path, dados, base):
    dados["modulos"][0]["componente"] = "ESP32 DevKit"
    _falha(tmp_path, dados, "modulos.0.componente", base)


def test_papel_repetido_e_recusado(tmp_path, dados, base):
    dados["modulos"][1]["papel"] = dados["modulos"][0]["papel"]
    _falha(tmp_path, dados, "papel de módulo repetido", base)


def test_especificacao_sem_modulos_e_recusada(tmp_path, dados, base):
    dados["modulos"] = []
    _falha(tmp_path, dados, "modulos", base)


@pytest.mark.parametrize("secao", ["projeto", "modulos", "alimentacao", "restricoes"])
def test_secao_obrigatoria(tmp_path, dados, base, secao):
    del dados[secao]
    _falha(tmp_path, dados, f"{secao}: Field required", base)


def test_modelo_recusa_sem_passar_pelo_arquivo():
    with pytest.raises(ValidationError):
        Especificacao.model_validate({"projeto": {"id": "x", "nome": "x", "descricao": "x"}})


# --- Leitura do arquivo ----------------------------------------------------------------------

def test_chave_repetida_no_yaml_e_recusada(tmp_path, base):
    texto = SPEC.read_text(encoding="utf-8").replace(
        "  tensao: 5.0\n", "  tensao: 5.0\n  tensao: 3.3\n")
    arquivo = tmp_path / "spec.yaml"
    arquivo.write_text(texto, encoding="utf-8")
    with pytest.raises(ErroEspecificacao, match="chave repetida: 'tensao'"):
        ler_especificacao(arquivo, base)


@pytest.mark.parametrize("conteudo, trecho", [
    ("", "mas é vazio"),
    ("- a\n- b\n", "mas é list"),
    ("projeto: [\n", "YAML inválido"),
])
def test_conteudo_que_nao_e_um_mapa_e_recusado(tmp_path, base, conteudo, trecho):
    arquivo = tmp_path / "spec.yaml"
    arquivo.write_text(conteudo, encoding="utf-8")
    with pytest.raises(ErroEspecificacao, match=trecho):
        ler_especificacao(arquivo, base)


def test_arquivo_inexistente_e_recusado(tmp_path, base):
    with pytest.raises(ErroEspecificacao, match="o arquivo não existe"):
        ler_especificacao(tmp_path / "nao-existe.yaml", base)


def test_arquivo_fora_de_utf8_e_recusado(tmp_path, base):
    arquivo = tmp_path / "spec.yaml"
    arquivo.write_bytes("projeto: Ação".encode("latin-1"))
    with pytest.raises(ErroEspecificacao, match="UTF-8"):
        ler_especificacao(arquivo, base)


def test_texto_valida_igual_ao_arquivo(base):
    """especificacao_de_texto (usada pelo briefing, ADR-016) é o mesmo caminho do arquivo."""
    from src.especificacao import especificacao_de_texto
    texto = SPEC.read_text(encoding="utf-8")
    assert especificacao_de_texto(texto, Path("x"), base) == ler_especificacao(SPEC, base)
    with pytest.raises(ErroEspecificacao) as erro:
        especificacao_de_texto("projeto: [", Path("entrega"), base)
    assert str(erro.value.problemas[0]).startswith("entrega: YAML inválido")
