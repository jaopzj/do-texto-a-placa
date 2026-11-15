"""Testes do eval que roda o agente N vezes (Marco 4, Parte 6).

Nenhum teste chama a API. O agente roda com um provedor de roteiro, que pede as mesmas
ferramentas que o agente pediria, com as ligações do circuito.py (as mesmas de
``tests/test_gerar_netlist.py``). As medidas, a tabela e o custo não precisam do SKiDL e
rodam no GitHub Actions; os testes que geram a netlist rodam no container.
"""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from src.agente.laco import Chamada, Resposta, rodar_agente
from src.agente.ferramentas import Ferramentas
from src.agente.provedores.claude import PRECOS, custo, traduzir
from src.componentes.carregar import carregar_todos
from src.evals import rodar
from src.evals.rodar import (CABECALHO, MARCADOR, ResultadoExecucao, Rodada, registrar,
                             rodar_eval)

from test_gerar_netlist import LIGACOES_A_MAO, SELECOES

BASE = carregar_todos()
precisa_do_skidl = pytest.mark.skipif(importlib.util.find_spec("skidl") is None,
                                      reason="o SKiDL só está no container")


def _chamadas(ligacoes=LIGACOES_A_MAO, selecoes=SELECOES, extra=()):
    pedidos = [("selecionar_componente", {"id": id_, "ref": ref}) for ref, id_ in selecoes.items()]
    pedidos += [("conectar", {"ref": ref, "pino": pino, "rede": rede})
                for rede, pinos in ligacoes.items() for ref, pino in pinos]
    return tuple(Chamada(n, a, f"t{i}") for i, (n, a) in enumerate(list(extra) + pedidos))


class ProvedorRoteiro:
    """Primeiro pede ``chamadas`` num passo só; depois responde com texto e para."""

    def __init__(self, chamadas, custo_usd=0.01, falhar=False, sem_fim=False):
        self.chamadas, self.custo_usd = chamadas, custo_usd
        self.falhar, self.sem_fim = falhar, sem_fim

    def iniciar(self, sistema, contratos, pedido):
        if self.falhar:
            raise ConnectionError("sem rede")
        return Resposta(chamadas=self.chamadas, tokens_entrada=1000, tokens_saida=100,
                        custo_usd=self.custo_usd)

    def continuar(self, resultados):
        if self.sem_fim:
            return Resposta(chamadas=(Chamada("buscar_componente", {"termo": "x"}),),
                            custo_usd=self.custo_usd)
        return Resposta(texto="Pronto.", tokens_entrada=1200, tokens_saida=50,
                        custo_usd=self.custo_usd)


def _execucao(indice=1, equivalente=True, custo_usd=0.10, inexistentes=0, chamadas=30):
    return ResultadoExecucao(indice=indice, equivalente=equivalente, motivo="m",
                             terminou=True, passos=2, chamadas=chamadas,
                             tentativas_inexistentes=inexistentes, pendencias=0,
                             tokens_entrada=1, tokens_saida=1, custo_usd=custo_usd, segundos=1)


def _rodada(*execucoes):
    return Rodada(data="2026-11-14", versao_do_prompt="1", modelo="claude-opus-5-5",
                  esforco="high", execucoes=list(execucoes))


# --- Medidas da rodada (sem SKiDL) -------------------------------------------------------------

def test_meta_e_4_de_5():
    assert _rodada(*[_execucao(i, i != 5) for i in range(1, 6)]).meta_atingida
    assert not _rodada(*[_execucao(i, i > 2) for i in range(1, 6)]).meta_atingida
    assert _rodada(*[_execucao(i) for i in range(1, 11)]).meta_atingida
    assert not _rodada(*[_execucao(i, i > 3) for i in range(1, 11)]).meta_atingida  # 7 de 10
    assert not _rodada().meta_atingida


def test_linha_da_tabela():
    rodada = _rodada(_execucao(1, True, 0.30, 0, 40), _execucao(2, False, 0.40, 2, 50))
    assert rodada.linha_markdown("primeira | rodada") == (
        "| 2026-11-14 | 1 | claude-opus-5-5 | high | 1 de 2 | não | 2 | 45.0 | 0.35 | 0.70 "
        "| primeira / rodada |")
    assert rodada.linha_markdown().endswith("| - |")


def test_custo_desconhecido_nao_vira_zero():
    rodada = _rodada(_execucao(1, custo_usd=0.30), _execucao(2, custo_usd=None))
    assert rodada.custo_total is None
    assert "| ? | ? |" in rodada.linha_markdown()


def test_registrar_acrescenta_a_linha_na_tabela(tmp_path):
    arquivo = tmp_path / "evals.md"
    arquivo.write_text(rodar.EVALS_MD.read_text(encoding="utf-8") + "\n## Notas\n\ntexto\n",
                       encoding="utf-8")
    registrar(_rodada(_execucao()), arquivo, "teste")
    registrar(_rodada(_execucao(), _execucao(2)), arquivo)
    texto = arquivo.read_text(encoding="utf-8")
    tabela = texto.split(MARCADOR)[1].strip().split("\n")
    assert "\n".join(tabela[:2]) == CABECALHO
    assert tabela[2].startswith("| 2026-11-14 | 1 |") and tabela[2].endswith("| teste |")
    assert "| 2 de 2 |" in tabela[3]
    assert "(nenhuma rodada" not in texto
    assert texto.rstrip().endswith("## Notas\n\ntexto")


def test_registrar_sem_marcador_e_erro(tmp_path):
    arquivo = tmp_path / "evals.md"
    arquivo.write_text("# Evals\n", encoding="utf-8")
    with pytest.raises(ValueError, match="marcador"):
        registrar(_rodada(_execucao()), arquivo)


def test_docs_evals_tem_o_cabecalho_da_tabela():
    texto = rodar.EVALS_MD.read_text(encoding="utf-8")
    assert MARCADOR + "\n" + CABECALHO in texto


def test_n_invalido_e_recusado(tmp_path):
    with pytest.raises(ValueError, match="pelo menos 1"):
        rodar_eval(0, lambda: None, "m", "high", base=BASE, saida=tmp_path, avisar=None)


# --- Custo (sem a biblioteca anthropic) --------------------------------------------------------

def test_custo_pela_tabela_de_precos():
    # 1 milhão de cada: 4 + 20 + 0,20 + 5 dólares no Opus 5.5.
    assert custo("claude-opus-5-5", 10**6, 10**6, 10**6, 10**6) == pytest.approx(29.20)
    assert custo("claude-opus-5-5", 1000, 0, 0, 0) == pytest.approx(0.004)
    assert custo("claude-sonnet-5-5", 0, 10**6, 0, 0) == pytest.approx(10.0)
    assert custo("modelo-sem-preco", 1, 1, 1, 1) is None
    assert custo(None, 1, 1, 1, 1) is None
    assert set(PRECOS) == {"claude-opus-5-5", "claude-sonnet-5-5", "claude-haiku-5-5"}


def test_haiku_cobra_mais_acima_de_100_mil_tokens_de_prompt():
    # Até 100 mil tokens de prompt (entrada + cache): 0,10 / 0,50 / 0,01 / 0,125 por milhão.
    assert custo("claude-haiku-5-5", 10_000, 1_000, 80_000, 10_000) == pytest.approx(
        (10_000 * 0.10 + 1_000 * 0.50 + 80_000 * 0.01 + 10_000 * 0.125) / 1e6)
    assert custo("claude-haiku-5-5", 100_000, 0, 0, 0) == pytest.approx(0.01)
    # Acima disso, a faixa cara vale para o pedido inteiro: 0,50 / 2,50 / 0,05 / 0,625.
    assert custo("claude-haiku-5-5", 100_001, 1_000, 0, 0) == pytest.approx(
        (100_001 * 0.50 + 1_000 * 2.50) / 1e6)
    assert custo("claude-haiku-5-5", 1_000, 0, 99_001, 0) == pytest.approx(
        (1_000 * 0.50 + 99_001 * 0.05) / 1e6)


def test_traduzir_separa_o_cache_e_calcula_o_custo():
    resposta = SimpleNamespace(
        content=[], stop_reason="end_turn", model="claude-opus-5-5",
        usage=SimpleNamespace(input_tokens=1000, output_tokens=500,
                              cache_read_input_tokens=20000, cache_creation_input_tokens=3000))
    r = traduzir(resposta)
    assert (r.tokens_entrada, r.tokens_saida) == (24000, 500)
    assert (r.tokens_cache_leitura, r.tokens_cache_escrita) == (20000, 3000)
    assert r.custo_usd == pytest.approx((1000 * 4 + 500 * 20 + 20000 * 0.2 + 3000 * 5) / 1e6)


def test_traduzir_usa_o_modelo_que_respondeu():
    resposta = SimpleNamespace(content=[], stop_reason="end_turn", model="outro-modelo",
                               usage=SimpleNamespace(input_tokens=1, output_tokens=1))
    assert traduzir(resposta).custo_usd is None


def test_laco_soma_tokens_e_custo():
    provedor = ProvedorRoteiro(_chamadas(), custo_usd=0.25)
    execucao = rodar_agente("pedido", provedor, Ferramentas(BASE), registrar=None)
    assert execucao.custo_usd == pytest.approx(0.50)
    assert (execucao.tokens_entrada, execucao.tokens_saida) == (2200, 150)


def test_laco_com_um_custo_desconhecido_fica_desconhecido():
    provedor = ProvedorRoteiro(_chamadas(), custo_usd=None)
    assert rodar_agente("pedido", provedor, Ferramentas(BASE), registrar=None).custo_usd is None


# --- O eval inteiro com o agente de roteiro (precisa do SKiDL) ---------------------------------

def _rodar(tmp_path, *provedores):
    fila = list(provedores)
    return rodar_eval(len(fila), lambda: fila.pop(0), "roteiro", "-", base=BASE,
                      saida=tmp_path, avisar=None)


@precisa_do_skidl
def test_execucao_certa_bate_com_o_gabarito(tmp_path):
    rodada = _rodar(tmp_path, ProvedorRoteiro(_chamadas()))
    [r] = rodada.execucoes
    assert r.equivalente and r.terminou, r.motivo
    assert r.motivo == "equivalente ao gabarito"
    assert r.chamadas == 4 + 20 and r.passos == 2     # 4 seleções e 20 conectar
    assert r.tentativas_inexistentes == 0 and r.pendencias == 0
    assert r.custo_usd == pytest.approx(0.02)
    [pasta] = tmp_path.iterdir()
    assert {p.name for p in (pasta / "1").iterdir()} == {
        "registro.txt", "estado.json", "agente.net", "resultado.json"}
    assert json.loads((pasta / "1" / "resultado.json").read_text())["equivalente"] is True
    assert "AGE: conectar" in (pasta / "1" / "registro.txt").read_text(encoding="utf-8")
    assert (pasta / "rodada.md").exists()


@precisa_do_skidl
def test_rodada_mede_cada_execucao(tmp_path):
    trocada = dict(LIGACOES_A_MAO, SDA_5V=[("U2", "HV1"), ("LCD1", "SCL")],
                   SCL_5V=[("U2", "HV2"), ("LCD1", "SDA")])
    inventada = (("selecionar_componente", {"id": "display-oled-inventado", "ref": "D1"}),)
    rodada = _rodar(tmp_path,
                    ProvedorRoteiro(_chamadas()),
                    ProvedorRoteiro(_chamadas(trocada)),
                    ProvedorRoteiro(_chamadas(extra=inventada)),
                    ProvedorRoteiro(_chamadas(), falhar=True),
                    ProvedorRoteiro(_chamadas()))
    certo, trocado, com_inexistente, falhou, certo2 = rodada.execucoes
    assert [r.equivalente for r in rodada.execucoes] == [True, False, True, False, True]
    assert "SDA" in trocado.motivo and "diferente do gabarito" in trocado.motivo
    assert com_inexistente.tentativas_inexistentes == 1
    assert falhou.motivo == "o agente falhou: ConnectionError: sem rede"
    assert falhou.custo_usd is None and rodada.custo_total is None
    assert rodada.acertos == 3 and not rodada.meta_atingida
    assert [r.indice for r in rodada.execucoes] == [1, 2, 3, 4, 5]


@precisa_do_skidl
def test_estado_que_nao_vira_netlist_conta_como_nao_equivalente(tmp_path):
    solta = dict(LIGACOES_A_MAO, SOLTA=[("U1", "IO23")])            # rede de um pino só
    [r] = _rodar(tmp_path, ProvedorRoteiro(_chamadas(solta))).execucoes
    assert not r.equivalente
    assert "rede 'SOLTA': só 1 pino" in r.motivo
    [pasta] = tmp_path.iterdir()
    assert not (pasta / "1" / "agente.net").exists()


@precisa_do_skidl
def test_agente_que_nao_termina_e_apontado(tmp_path):
    [r] = _rodar(tmp_path, ProvedorRoteiro(_chamadas(), sem_fim=True)).execucoes
    assert not r.terminou and r.passos == 30
    assert "o agente não terminou" in r.motivo


@precisa_do_skidl
def test_main_registra_a_rodada(tmp_path, monkeypatch):
    evals = tmp_path / "evals.md"
    evals.write_text(rodar.EVALS_MD.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(rodar, "EVALS_MD", evals)
    import src.agente.provedores.claude as claude
    monkeypatch.setattr(claude, "ProvedorClaude",
                        lambda modelo, esforco: ProvedorRoteiro(_chamadas()))
    codigo = rodar.main(["--n", "2", "--registrar", "--observacao", "roteiro",
                         "--saida", str(tmp_path / "saida")])
    assert codigo == 0
    assert "| 2 de 2 | sim |" in evals.read_text(encoding="utf-8")


def test_main_recusa_n_zero():
    with pytest.raises(SystemExit):
        rodar.main(["--n", "0"])


def test_pasta_do_eval_fica_fora_do_git():
    raiz = Path(rodar.__file__).resolve().parents[2]
    assert rodar.SAIDA.relative_to(raiz).parts[0] == "saida"
    assert "saida/" in (raiz / ".gitignore").read_text(encoding="utf-8").split()


@precisa_do_skidl
def test_eval_mostra_o_andamento_no_terminal(tmp_path):
    linhas: list[str] = []
    inventada = (("selecionar_componente", {"id": "display-oled-inventado", "ref": "D1"}),)
    rodar_eval(1, lambda: ProvedorRoteiro(_chamadas(extra=inventada)), "claude-haiku-5-5",
               "medium", base=BASE, saida=tmp_path, avisar=linhas.append)
    texto = "\n".join(linhas)
    for trecho in ["eval: 1 execução(ões) · claude-haiku-5-5 · esforço medium",
                   "=== execução 1 de 1 ===", "passo 1 ·", "25 ferramenta(s)",
                   "ERRO selecionar_componente(id='display-oled-inventado'",
                   "ok   conectar(ref='U1', pino='5V', rede='+5V')",
                   "gerando a netlist", "comparando com gabarito.net", "[1] BATEU",
                   "1 de 1 equivalentes ao gabarito (meta: atingida)"]:
        assert trecho in texto, trecho


def test_eval_em_silencio_por_padrao(tmp_path, capsys):
    rodar_eval(1, lambda: ProvedorRoteiro(_chamadas(), falhar=True), "m", "high", base=BASE,
               saida=tmp_path)
    assert capsys.readouterr().out == ""


# --- Equivalências de pinos (ADR-015) ----------------------------------------------------------

def test_equivalencias_com_problema_param_antes_de_chamar_a_api(tmp_path):
    ruim = tmp_path / "equivalencias.yaml"
    ruim.write_text('equivalencias:\n  - pino: "esp32-devkitc-v4: IO34"\n    funcao: ADC1_\n'
                    "    requisito: Um requisito que o spec não tem.\n", encoding="utf-8")
    def nunca():
        raise AssertionError("não devia criar o provedor")
    with pytest.raises(ValueError, match="não está no spec"):
        rodar_eval(1, nunca, "m", "high", base=BASE, saida=tmp_path / "saida", avisar=None,
                   equivalencias=ruim)


@precisa_do_skidl
def test_sensor_em_outro_pino_do_adc1_bate_com_o_gabarito(tmp_path):
    ligacoes = dict(LIGACOES_A_MAO, SENSOR=[("S1", "AOUT"), ("U1", "IO32")])
    rodada = _rodar(tmp_path, ProvedorRoteiro(_chamadas(ligacoes)))
    [r] = rodada.execucoes
    assert r.equivalente, r.motivo
    assert r.motivo == ("equivalente ao gabarito (troca aceita: esp32-devkitc-v4: IO32 "
                        "no lugar de esp32-devkitc-v4: IO34)")


@precisa_do_skidl
def test_sem_equivalencias_o_sensor_em_outro_pino_nao_bate(tmp_path):
    ligacoes = dict(LIGACOES_A_MAO, SENSOR=[("S1", "AOUT"), ("U1", "IO32")])
    rodada = rodar_eval(1, lambda: ProvedorRoteiro(_chamadas(ligacoes)), "roteiro", "-",
                        base=BASE, saida=tmp_path, avisar=None, equivalencias=None)
    assert not rodada.execucoes[0].equivalente
