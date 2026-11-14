"""Testes da base de componentes: modelo, carregador e referências ao KiCad (Marco 3).

O sensor de umidade (componentes/sensor-umidade-capacitivo.yaml) é o caso de referência:
os testes de erro partem de uma cópia dele, estragada de um jeito por vez, gravada numa
pasta temporária. O arquivo real nunca é alterado.
"""
import copy
import os
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from src.componentes.carregar import PASTA, ErroBase, carregar_todos, ler_arquivo
from src.componentes.kicad import (footprint_existe, pastas_do_ambiente, referencias_ausentes,
                                   simbolo_existe)
from src.componentes.modelo import Componente

SENSOR = PASTA / "sensor-umidade-capacitivo.yaml"


# --- Os dois testes da Parte 4 do guia ---------------------------------------------------

def test_todos_os_componentes_sao_validos():
    base = carregar_todos()
    assert len(base) > 0


def test_componente_invalido_e_rejeitado():
    with pytest.raises(ValidationError):
        Componente(id="Nome Com Espaço", descricao="x", kicad_simbolo="x",
                   kicad_footprint="x", alimentacao_min=3.3,
                   alimentacao_max=5, pinos=[], status="talvez")


# --- O sensor de umidade, caso de referência --------------------------------------------

def _dados_do_sensor() -> dict:
    return yaml.safe_load(SENSOR.read_text(encoding="utf-8"))


@pytest.fixture
def sensor() -> dict:
    """Cópia do YAML do sensor, ponto de partida dos casos de erro.

    Se o próprio YAML de referência estiver inválido, os casos que partem dele não dizem
    nada; eles falham com esta mensagem, e o erro real aparece em
    test_todos_os_componentes_sao_validos.
    """
    try:
        ler_arquivo(SENSOR)
    except ErroBase as e:
        pytest.fail(f"o YAML de referência do sensor está inválido, corrija-o primeiro:\n{e}",
                    pytrace=False)
    return copy.deepcopy(_dados_do_sensor())


def test_sensor_carregado_com_os_dados_do_yaml():
    comp = carregar_todos()["sensor-umidade-capacitivo"]
    assert comp.kicad_simbolo == "Connector_Generic:Conn_01x03"
    assert comp.kicad_footprint == "Connector_PinSocket_2.54mm:PinSocket_1x03_P2.54mm_Vertical"
    assert (comp.alimentacao_min, comp.alimentacao_max) == (3.3, 5.5)
    assert [(p.numero, p.nome, p.tipo) for p in comp.pinos] == [
        (1, "GND", "terra"), (2, "VCC", "alimentacao"), (3, "AOUT", "analogico")]
    assert all(p.fonte.documento for p in comp.pinos)
    assert comp.status == "rascunho"


def test_id_de_cada_componente_e_unico_e_bate_com_a_chave():
    base = carregar_todos()
    assert all(chave == comp.id for chave, comp in base.items())


def test_carregar_e_reprodutivel():
    assert carregar_todos() == carregar_todos()


def test_carregador_nao_altera_o_arquivo_do_sensor():
    antes = SENSOR.read_bytes()
    carregar_todos()
    assert SENSOR.read_bytes() == antes


# --- Ferramentas para os casos de erro ---------------------------------------------------

def _gravar(pasta: Path, nome: str, dados) -> Path:
    arquivo = pasta / nome
    texto = dados if isinstance(dados, str) else yaml.safe_dump(dados, allow_unicode=True)
    arquivo.write_text(texto, encoding="utf-8")
    return arquivo


def _erros(pasta: Path) -> list[str]:
    with pytest.raises(ErroBase) as exc:
        carregar_todos(pasta)
    return [str(p) for p in exc.value.problemas]


def _um_erro(pasta: Path, dados, nome="peca.yaml") -> str:
    _gravar(pasta, nome, dados)
    erros = _erros(pasta)
    assert len(erros) == 1, erros
    assert erros[0].startswith(f"{nome}: ")
    return erros[0]


def test_copia_intacta_do_sensor_e_aceita(tmp_path, sensor):
    _gravar(tmp_path, "peca.yaml", sensor)
    assert list(carregar_todos(tmp_path)) == ["sensor-umidade-capacitivo"]


# --- Checagem do guia: apagar a linha "status" -------------------------------------------

def test_sem_status_o_erro_diz_o_campo(tmp_path):
    texto = SENSOR.read_text(encoding="utf-8")
    linhas = [linha for linha in texto.splitlines() if not linha.startswith("status:")]
    assert len(linhas) < len(texto.splitlines())   # a linha existia e foi apagada
    erro = _um_erro(tmp_path, "\n".join(linhas) + "\n")
    assert "status: Field required" in erro


# --- Campos obrigatórios ausentes --------------------------------------------------------

@pytest.mark.parametrize("campo", ["id", "descricao", "kicad_simbolo", "kicad_footprint",
                                   "alimentacao_min", "alimentacao_max", "pinos", "status"])
def test_campo_obrigatorio_ausente(tmp_path, sensor, campo):
    del sensor[campo]
    assert f"{campo}: Field required" in _um_erro(tmp_path, sensor)


@pytest.mark.parametrize("campo", ["numero", "nome", "tipo", "fonte"])
def test_campo_obrigatorio_do_pino_ausente(tmp_path, sensor, campo):
    del sensor["pinos"][1][campo]
    assert f"pinos.1.{campo}: Field required" in _um_erro(tmp_path, sensor)


def test_fonte_sem_documento(tmp_path, sensor):
    sensor["pinos"][0]["fonte"] = {"pagina": 2}
    assert "pinos.0.fonte.documento: Field required" in _um_erro(tmp_path, sensor)


@pytest.mark.parametrize("campo", ["id", "descricao", "severidade"])
def test_campo_obrigatorio_da_regra_ausente(tmp_path, sensor, campo):
    regra = {"id": "r1", "descricao": "uma regra", "severidade": "aviso"}
    del regra[campo]
    sensor["regras"] = [regra]
    assert f"regras.0.{campo}: Field required" in _um_erro(tmp_path, sensor)


# --- Campos opcionais aceitos ------------------------------------------------------------

def test_campos_opcionais_validos_sao_aceitos(tmp_path, sensor):
    sensor["nivel_logico"] = 3.3
    sensor["pinos"][2].update(tensao_max=3.0, funcoes=["saida analogica"])
    sensor["pinos"][2]["fonte"]["pagina"] = 2
    sensor["regras"] = [{"id": "r1", "descricao": "uma regra", "severidade": "erro"}]
    _gravar(tmp_path, "peca.yaml", sensor)
    comp = carregar_todos(tmp_path)["sensor-umidade-capacitivo"]
    assert comp.nivel_logico == 3.3
    assert comp.pinos[2].tensao_max == 3.0
    assert comp.pinos[2].fonte.pagina == 2
    assert comp.regras[0].severidade == "erro"


def test_pinos_de_mesmo_nome_sao_aceitos(tmp_path, sensor):
    # Módulos reais têm vários pinos GND; o que não pode repetir é o número.
    sensor["pinos"].append({"numero": 4, "nome": "GND", "tipo": "terra",
                            "fonte": {"documento": "medição própria"}})
    _gravar(tmp_path, "peca.yaml", sensor)
    assert len(carregar_todos(tmp_path)["sensor-umidade-capacitivo"].pinos) == 4


# --- Campos desconhecidos (erros de digitação) -------------------------------------------

@pytest.mark.parametrize("onde,local", [
    (lambda d: d, "tensao_maxima"),
    (lambda d: d["pinos"][0], "pinos.0.tensao_maxima"),
    (lambda d: d["pinos"][0]["fonte"], "pinos.0.fonte.tensao_maxima"),
])
def test_campo_desconhecido_e_recusado(tmp_path, sensor, onde, local):
    onde(sensor)["tensao_maxima"] = 5.0
    assert f"{local}: Extra inputs are not permitted" in _um_erro(tmp_path, sensor)


# --- Tipos incorretos --------------------------------------------------------------------

@pytest.mark.parametrize("mudar,local", [
    (lambda d: d.update(alimentacao_min="3.3"), "alimentacao_min"),     # texto, não número
    (lambda d: d.update(alimentacao_max=True), "alimentacao_max"),
    (lambda d: d.update(nivel_logico="3,3 V"), "nivel_logico"),
    (lambda d: d.update(pinos={"numero": 1}), "pinos"),                 # mapa, não lista
    (lambda d: d.update(regras="nenhuma"), "regras"),
    (lambda d: d.update(descricao=123), "descricao"),
    (lambda d: d["pinos"][0].update(numero="1"), "pinos.0.numero"),
    (lambda d: d["pinos"][0].update(numero=1.5), "pinos.0.numero"),
    (lambda d: d["pinos"][0].update(numero=True), "pinos.0.numero"),
    (lambda d: d["pinos"][0].update(funcoes="ADC1_CH6"), "pinos.0.funcoes"),
    (lambda d: d["pinos"][0].update(fonte="medição própria"), "pinos.0.fonte"),
    (lambda d: d["pinos"][0]["fonte"].update(pagina="3"), "pinos.0.fonte.pagina"),
])
def test_tipo_incorreto_e_recusado(tmp_path, sensor, mudar, local):
    mudar(sensor)
    assert f"{local}: " in _um_erro(tmp_path, sensor)


def test_inteiro_vale_como_tensao(tmp_path, sensor):
    sensor["alimentacao_max"] = 5
    _gravar(tmp_path, "peca.yaml", sensor)
    assert carregar_todos(tmp_path)["sensor-umidade-capacitivo"].alimentacao_max == 5.0


# --- Valores fora do permitido -----------------------------------------------------------

@pytest.mark.parametrize("mudar,local", [
    (lambda d: d.update(id="Sensor Umidade"), "id"),
    (lambda d: d.update(id="sensor_umidade"), "id"),
    (lambda d: d.update(status="talvez"), "status"),
    (lambda d: d.update(descricao="   "), "descricao"),
    (lambda d: d.update(kicad_simbolo="Conn_01x03"), "kicad_simbolo"),            # sem biblioteca
    (lambda d: d.update(kicad_footprint="Connector:"), "kicad_footprint"),
    (lambda d: d.update(kicad_footprint="A:B:C"), "kicad_footprint"),
    (lambda d: d.update(alimentacao_min=0), "alimentacao_min"),
    (lambda d: d.update(alimentacao_max=-5.0), "alimentacao_max"),
    (lambda d: d.update(nivel_logico=0.0), "nivel_logico"),
    (lambda d: d.update(pinos=[]), "pinos"),
    (lambda d: d["pinos"][0].update(tipo="power"), "pinos.0.tipo"),
    (lambda d: d["pinos"][0].update(numero=0), "pinos.0.numero"),
    (lambda d: d["pinos"][0].update(nome=""), "pinos.0.nome"),
    (lambda d: d["pinos"][0].update(tensao_max=0), "pinos.0.tensao_max"),
    (lambda d: d["pinos"][0].update(funcoes=[""]), "pinos.0.funcoes.0"),
    (lambda d: d["pinos"][0]["fonte"].update(documento=""), "pinos.0.fonte.documento"),
    (lambda d: d["pinos"][0]["fonte"].update(pagina=0), "pinos.0.fonte.pagina"),
    (lambda d: d.update(regras=[{"id": "r", "descricao": "x", "severidade": "fatal"}]),
     "regras.0.severidade"),
])
def test_valor_fora_do_permitido_e_recusado(tmp_path, sensor, mudar, local):
    mudar(sensor)
    assert f"{local}: " in _um_erro(tmp_path, sensor)


# --- Valores inconsistentes entre campos -------------------------------------------------

def test_alimentacao_min_maior_que_max(tmp_path, sensor):
    sensor["alimentacao_min"], sensor["alimentacao_max"] = 5.5, 3.3
    erro = _um_erro(tmp_path, sensor)
    assert "alimentacao_min (5.5 V) é maior que alimentacao_max (3.3 V)" in erro


def test_alimentacao_min_igual_a_max_e_aceita(tmp_path, sensor):
    sensor["alimentacao_min"] = sensor["alimentacao_max"] = 5.0
    _gravar(tmp_path, "peca.yaml", sensor)
    assert carregar_todos(tmp_path)


def test_numero_de_pino_repetido(tmp_path, sensor):
    sensor["pinos"][2]["numero"] = 1
    assert "número de pino repetido: [1]" in _um_erro(tmp_path, sensor)


def test_id_de_regra_repetido(tmp_path, sensor):
    regra = {"id": "adc2-wifi", "descricao": "x", "severidade": "aviso"}
    sensor["regras"] = [regra, dict(regra)]
    assert "id de regra repetido: ['adc2-wifi']" in _um_erro(tmp_path, sensor)


# --- Problemas no arquivo YAML -----------------------------------------------------------

def test_chave_repetida_no_yaml_e_recusada(tmp_path):
    # Sem a proteção, o PyYAML ficaria com o segundo valor e descartaria o primeiro.
    texto = SENSOR.read_text(encoding="utf-8") + "\nalimentacao_max: 12\n"
    erro = _um_erro(tmp_path, texto)
    assert "YAML inválido" in erro and "chave repetida: 'alimentacao_max'" in erro


def test_yaml_com_sintaxe_quebrada(tmp_path):
    assert "YAML inválido" in _um_erro(tmp_path, "id: x\npinos: [\n")


@pytest.mark.parametrize("texto,tipo", [("", "vazio"), ("# só um comentário\n", "vazio"),
                                        ("- a\n- b\n", "list"), ("texto solto\n", "str")])
def test_conteudo_que_nao_e_mapa(tmp_path, texto, tipo):
    assert f"precisa ser um mapa de campos, mas é {tipo}" in _um_erro(tmp_path, texto)


def test_arquivo_que_nao_e_utf8(tmp_path):
    (tmp_path / "peca.yaml").write_bytes("descricao: Módulo\n".encode("latin-1"))
    assert _erros(tmp_path) == ["peca.yaml: o arquivo não está em UTF-8"]


def test_tag_python_do_yaml_nao_e_executada(tmp_path):
    erro = _um_erro(tmp_path, "id: !!python/object/apply:os.system ['echo oi']\n")
    assert "YAML inválido" in erro


# --- Problemas na pasta ------------------------------------------------------------------

def test_id_repetido_em_dois_arquivos(tmp_path, sensor):
    _gravar(tmp_path, "a.yaml", sensor)
    _gravar(tmp_path, "b.yaml", sensor)
    assert _erros(tmp_path) == [
        "b.yaml: id 'sensor-umidade-capacitivo' repetido (já usado em a.yaml)"]


def test_arquivo_yml_nao_e_ignorado_em_silencio(tmp_path, sensor):
    _gravar(tmp_path, "peca.yml", sensor)
    assert _erros(tmp_path) == ["peca.yml: use a extensão .yaml (arquivos .yml não são lidos)"]


def test_pasta_inexistente(tmp_path):
    erros = _erros(tmp_path / "nao-existe")
    assert erros == ["nao-existe: a pasta da base de componentes não existe"]


def test_pasta_vazia_devolve_base_vazia(tmp_path):
    assert carregar_todos(tmp_path) == {}


def test_um_arquivo_ruim_derruba_a_base_inteira_e_todos_os_erros_aparecem(tmp_path, sensor):
    _gravar(tmp_path, "a-bom.yaml", sensor)
    ruim = copy.deepcopy(sensor)
    ruim["id"] = "outro"
    del ruim["status"]
    ruim["pinos"][0]["tipo"] = "power"
    _gravar(tmp_path, "b-ruim.yaml", ruim)
    _gravar(tmp_path, "c-quebrado.yaml", "id: [\n")
    erros = _erros(tmp_path)
    assert len(erros) == 3, erros
    assert erros[0].startswith("b-ruim.yaml: pinos.0.tipo: ")
    assert erros[1] == "b-ruim.yaml: status: Field required"
    assert erros[2].startswith("c-quebrado.yaml: YAML inválido")


def test_mensagem_do_erro_lista_cada_problema(tmp_path, sensor):
    del sensor["status"]
    _gravar(tmp_path, "peca.yaml", sensor)
    with pytest.raises(ErroBase, match=r"\(1 problema\(s\)\):\n  - peca.yaml: status: Field required"):
        carregar_todos(tmp_path)


def test_ler_arquivo_sozinho(sensor, tmp_path):
    assert ler_arquivo(SENSOR).id == "sensor-umidade-capacitivo"
    del sensor["pinos"]
    with pytest.raises(ErroBase):
        ler_arquivo(_gravar(tmp_path, "peca.yaml", sensor))


# --- Referências às bibliotecas do KiCad -------------------------------------------------

@pytest.fixture
def bibliotecas_falsas(tmp_path):
    simbolos, footprints = tmp_path / "symbols", tmp_path / "footprints"
    simbolos.mkdir()
    (simbolos / "Connector_Generic.kicad_sym").write_text(
        '(kicad_symbol_lib\n  (symbol "Conn_01x03"\n    (pin_numbers hide))\n)\n',
        encoding="utf-8")
    (simbolos / "Pasta.kicad_symdir").mkdir()
    (simbolos / "Pasta.kicad_symdir" / "Um.kicad_sym").write_text("()", encoding="utf-8")
    pretty = footprints / "Connector_PinSocket_2.54mm.pretty"
    pretty.mkdir(parents=True)
    (pretty / "PinSocket_1x03_P2.54mm_Vertical.kicad_mod").write_text("()", encoding="utf-8")
    return simbolos, footprints


def test_referencias_do_sensor_existem_nas_bibliotecas_falsas(bibliotecas_falsas):
    comp = carregar_todos()["sensor-umidade-capacitivo"]
    assert referencias_ausentes(comp, *bibliotecas_falsas) == []


@pytest.mark.parametrize("referencia,existe", [
    ("Connector_Generic:Conn_01x03", True),
    ("Connector_Generic:Conn_01x0", False),       # prefixo de um nome que existe
    ("Connector_Generic:Conn_01x04", False),
    ("Biblioteca_Inexistente:Conn_01x03", False),
    ("Pasta:Um", True),
    ("Pasta:Dois", False),
])
def test_simbolo_existe(bibliotecas_falsas, referencia, existe):
    assert simbolo_existe(referencia, bibliotecas_falsas[0]) is existe


@pytest.mark.parametrize("referencia,existe", [
    ("Connector_PinSocket_2.54mm:PinSocket_1x03_P2.54mm_Vertical", True),
    ("Connector_PinSocket_2.54mm:PinSocket_1x04_P2.54mm_Vertical", False),
    ("Connector_PinHeader_2.54mm:PinSocket_1x03_P2.54mm_Vertical", False),
])
def test_footprint_existe(bibliotecas_falsas, referencia, existe):
    assert footprint_existe(referencia, bibliotecas_falsas[1]) is existe


def test_referencia_inexistente_e_apontada(bibliotecas_falsas, sensor):
    sensor["kicad_simbolo"] = "Connector_Generic:Conn_01x04"
    sensor["kicad_footprint"] = "Connector_PinSocket_2.54mm:Nao_Existe"
    ausentes = referencias_ausentes(Componente.model_validate(sensor), *bibliotecas_falsas)
    assert len(ausentes) == 2
    assert "símbolo 'Connector_Generic:Conn_01x04' não existe" in ausentes[0]
    assert "footprint 'Connector_PinSocket_2.54mm:Nao_Existe' não existe" in ausentes[1]


def test_pastas_do_ambiente_sem_variaveis(monkeypatch):
    monkeypatch.delenv("KICAD10_SYMBOL_DIR", raising=False)
    monkeypatch.delenv("KICAD10_FOOTPRINT_DIR", raising=False)
    assert pastas_do_ambiente() is None


BIBLIOTECAS_REAIS = pastas_do_ambiente()


@pytest.mark.skipif(BIBLIOTECAS_REAIS is None,
                    reason="bibliotecas do KiCad ausentes (só existem no container: make testes)")
def test_referencias_da_base_existem_nas_bibliotecas_do_kicad():
    simbolos, footprints = BIBLIOTECAS_REAIS
    ausentes = [a for comp in carregar_todos().values()
                for a in referencias_ausentes(comp, simbolos, footprints)]
    assert ausentes == [], "\n".join(ausentes)


def test_variaveis_do_kicad_no_container_apontam_para_pastas_reais():
    # Dentro do container (o Makefile define as variáveis), as bibliotecas precisam
    # existir; senão o teste acima seria pulado sem ninguém perceber.
    if "KICAD10_SYMBOL_DIR" in os.environ:
        assert BIBLIOTECAS_REAIS is not None


# --- Conectores por peça (ADR-007) -------------------------------------------------------

def _com_conectores(sensor, conectores):
    """O sensor com seus 3 pinos repartidos em conectores (só para testar o formato)."""
    del sensor["kicad_simbolo"], sensor["kicad_footprint"]
    sensor["conectores"] = conectores
    return sensor


def _conector(nome, pinos, n=None):
    n = n or len(pinos)
    return {"nome": nome, "kicad_simbolo": f"Connector_Generic:Conn_01x{n:02d}",
            "kicad_footprint": f"Connector_PinSocket_2.54mm:PinSocket_1x{n:02d}_P2.54mm_Vertical",
            "pinos": pinos}


def test_sem_conectores_a_peca_tem_um_conector_com_todos_os_pinos():
    comp = carregar_todos()["sensor-umidade-capacitivo"]
    assert comp.conectores == []
    [con] = comp.conectores_fisicos()
    assert (con.nome, con.kicad_simbolo, con.kicad_footprint, con.pinos) == (
        "sensor-umidade-capacitivo", comp.kicad_simbolo, comp.kicad_footprint, [1, 2, 3])


def test_conectores_validos_sao_aceitos(tmp_path, sensor):
    _gravar(tmp_path, "peca.yaml",
            _com_conectores(sensor, [_conector("a", [3, 1]), _conector("b", [2])]))
    comp = carregar_todos(tmp_path)["sensor-umidade-capacitivo"]
    assert [(c.nome, c.pinos) for c in comp.conectores_fisicos()] == [("a", [3, 1]), ("b", [2])]
    assert comp.kicad_simbolo is None and comp.kicad_footprint is None


@pytest.mark.parametrize("conectores,mensagem", [
    ([_conector("a", [1, 2])], "pinos fora de qualquer conector: [3]"),
    ([_conector("a", [1, 2]), _conector("b", [2, 3])],
     "pino em mais de um conector (ou repetido): [2]"),
    ([_conector("a", [1, 1, 2, 3])], "pino em mais de um conector (ou repetido): [1]"),
    ([_conector("a", [1, 2, 3, 4])], "conectores citam pinos que a peça não tem: [4]"),
    ([_conector("a", [1, 2]), _conector("a", [3])], "nome de conector repetido: ['a']"),
])
def test_conectores_inconsistentes(tmp_path, sensor, conectores, mensagem):
    assert mensagem in _um_erro(tmp_path, _com_conectores(sensor, conectores))


@pytest.mark.parametrize("mudar,local", [
    (lambda c: c.update(pinos=[]), "conectores.0.pinos"),
    (lambda c: c.update(pinos=[0, 1, 2, 3]), "conectores.0.pinos.0"),
    (lambda c: c.update(nome=""), "conectores.0.nome"),
    (lambda c: c.update(kicad_simbolo="Conn_01x03"), "conectores.0.kicad_simbolo"),
    (lambda c: c.pop("kicad_footprint"), "conectores.0.kicad_footprint"),
    (lambda c: c.update(fileira=1), "conectores.0.fileira"),
])
def test_campo_do_conector_invalido(tmp_path, sensor, mudar, local):
    conector = _conector("a", [1, 2, 3])
    mudar(conector)
    assert f"{local}: " in _um_erro(tmp_path, _com_conectores(sensor, [conector]))


def test_conectores_e_simbolo_da_peca_juntos_sao_recusados(tmp_path, sensor):
    sensor["conectores"] = [_conector("a", [1, 2, 3])]
    erro = _um_erro(tmp_path, sensor)
    assert "com conectores, deixe de fora ['kicad_simbolo', 'kicad_footprint']" in erro


def test_referencias_de_cada_conector_sao_conferidas(bibliotecas_falsas, sensor):
    # Na biblioteca falsa só existem Conn_01x03 e PinSocket_1x03: o conector "a" existe e
    # o "b" (de 4 pinos) não.
    _com_conectores(sensor, [_conector("a", [1, 2], n=3), _conector("b", [3], n=4)])
    ausentes = referencias_ausentes(Componente.model_validate(sensor), *bibliotecas_falsas)
    assert len(ausentes) == 2, ausentes
    assert ausentes[0].startswith(
        "sensor-umidade-capacitivo (conector b): símbolo 'Connector_Generic:Conn_01x04'")
    assert ausentes[1].startswith(
        "sensor-umidade-capacitivo (conector b): footprint "
        "'Connector_PinSocket_2.54mm:PinSocket_1x04_P2.54mm_Vertical'")
