"""Testes do andamento do agente no terminal (src/agente/terminal.py)."""
import re

from src.agente.laco import Chamada, Evento, Resposta
from src.agente.terminal import LARGURA, RECUO, Terminal, dolares


def _terminal():
    linhas: list[str] = []
    return Terminal(linhas.append), linhas


def test_dolares():
    assert dolares(0.0021) == "US$ 0,0021"
    assert dolares(1.5) == "US$ 1,5000"
    assert dolares(None) == "?"


def test_passo_mostra_tempo_tokens_custo_e_o_que_o_modelo_pensou():
    terminal, linhas = _terminal()
    resposta = Resposta(texto="Vou procurar\n os componentes.",
                        chamadas=(Chamada("buscar_componente", {"termo": "esp32"}),),
                        tokens_entrada=12345, tokens_saida=800, custo_usd=0.0021)
    terminal(Evento("resposta", 1, resposta=resposta, segundos=5.84))
    terminal(Evento("resposta", 2, resposta=Resposta(custo_usd=0.001), segundos=1))
    assert re.fullmatch(r"\[\d\d:\d\d:\d\d\] passo 1 · 5\.8 s · 12\.345 \+ 800 tokens · "
                        r"US\$ 0,0021 \(até agora US\$ 0,0021\) · 1 ferramenta\(s\)", linhas[0])
    assert linhas[1] == RECUO + "pensa: Vou procurar os componentes."
    assert linhas[2].endswith("(até agora US$ 0,0031) · terminou")


def test_custo_desconhecido_fica_desconhecido_ate_reiniciar():
    terminal, linhas = _terminal()
    terminal(Evento("resposta", 1, resposta=Resposta(custo_usd=None)))
    terminal(Evento("resposta", 2, resposta=Resposta(custo_usd=0.5)))
    assert "(até agora ?)" in linhas[-1]
    terminal.reiniciar()
    terminal(Evento("resposta", 1, resposta=Resposta(custo_usd=0.5)))
    assert "(até agora US$ 0,5000)" in linhas[-1]


def test_chamada_mostra_ok_ou_erro_com_o_motivo():
    terminal, linhas = _terminal()
    terminal(Evento("chamada", 1, chamada=Chamada("conectar", {"ref": "U1", "pino": 3,
                                                               "rede": "GND"}),
                    saida={"ok": True}))
    terminal(Evento("chamada", 1, chamada=Chamada("selecionar_componente",
                                                  {"id": "x", "ref": "U9"}),
                    saida={"ok": False, "erro": "componente_inexistente",
                           "mensagem": "o componente 'x' não está na base"}))
    assert linhas[0] == RECUO + "ok   conectar(ref='U1', pino=3, rede='GND')"
    assert linhas[1] == (RECUO + "ERRO selecionar_componente(id='x', ref='U9') -> "
                         "componente_inexistente: o componente 'x' não está na base")


def test_linha_longa_e_cortada():
    terminal, linhas = _terminal()
    terminal.detalhe("x" * 500, "ok")
    assert len(linhas[0]) == len(RECUO) + 5 + LARGURA and linhas[0].endswith("...")


def test_info_tem_a_hora():
    terminal, linhas = _terminal()
    terminal.info("começou")
    assert re.fullmatch(r"\[\d\d:\d\d:\d\d\] começou", linhas[0])
