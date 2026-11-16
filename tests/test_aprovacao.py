"""Testes das duas aprovações (Marco 5, Partes 2 e 5; ADR-016 e ADR-019).

O resumo é montado a partir de uma especificação válida e da base; a resposta do usuário é
uma lista de linhas. Nenhum modelo de IA é chamado. Rodam também no GitHub Actions.
"""
from pathlib import Path

import pytest

from src.agente.ferramentas import Pendencia
from src.aprovacao import (PERGUNTA, SEM_PRECOS, Veredito, interpretar, interpretar_da_fabrica,
                           pedir_aprovacao, pedir_segunda_aprovacao, resumir, rotulo,
                           valor_da_decisao)
from src.briefing import validar
from src.componentes.carregar import carregar_todos
from src.especificacao import ler_especificacao

from exemplo_briefing import ENTREGA, entrega as _entrega


@pytest.fixture(scope="module")
def base():
    return carregar_todos()


@pytest.fixture(scope="module")
def spec(base):
    spec, problemas = validar(ENTREGA, base, [])
    assert problemas == []
    return spec


@pytest.mark.parametrize("resposta", ["s", " S ", "sim", "Sim\n"])
def test_s_aprova(resposta):
    assert interpretar(resposta) == Veredito(aprovada=True)


@pytest.mark.parametrize("resposta", ["", "   ", "\n"])
def test_resposta_vazia_pergunta_de_novo(resposta):
    assert interpretar(resposta) is None


@pytest.mark.parametrize("resposta", ["troque o LCD por um OLED", "n", "não", "sem display"])
def test_outro_texto_e_correcao(resposta):
    assert interpretar(resposta) == Veredito(aprovada=False, correcao=resposta.strip())


def test_rotulos(spec):
    assert rotulo("modulos.2", spec) == 'módulo "display"'
    assert rotulo("modulos.1.requisitos.0", spec) == 'requisito 1 do módulo "sensor de umidade"'
    assert rotulo("restricoes.contorno", spec) == "contorno"
    assert rotulo("alimentacao", spec) == "alimentação"


def test_resumo_mostra_componentes(spec, base):
    texto = resumir(spec, base)
    assert "Monitor de umidade do solo (monitor-umidade)" in texto
    for m in spec.modulos:
        assert f"{m.papel}: {m.componente} ({base[m.componente].descricao})" in texto
    # ESP32 e LCD ainda estão em rascunho na base: o usuário precisa saber.
    linha_lcd = next(l for l in texto.splitlines() if "display-lcd-1602-i2c (" in l)
    assert "rascunho" in linha_lcd
    linha_sensor = next(l for l in texto.splitlines() if "sensor-umidade-capacitivo (" in l)
    assert "rascunho" not in linha_sensor
    assert "usb_do_devkit, 5 V" in texto and "2 camada(s), 100 x 100 mm" in texto


def test_resumo_mostra_so_as_decisoes_do_agente(spec, base):
    texto = resumir(spec, base)
    secao = texto.split("Decisões tomadas pelo agente")[1].split("Pendências")[0]
    do_agente = [c for c, d in spec.decisoes() if d.decidido_por == "agente"]
    assert f"({len(do_agente)})" in secao
    for caminho in do_agente:
        assert rotulo(caminho, spec) in secao
    assert 'módulo "conversor de nível lógico": conversor-nivel-logico-4-canais' in secao
    assert "regra i2c-voltage-compatibility de display-lcd-1602-i2c" in secao
    assert "fonte: componentes/esp32-devkitc-v4.yaml; regra adc2-wifi de esp32-devkitc-v4" in secao
    assert "montagem: barra_pinos_macho" in secao
    assert 'módulo "display"' not in secao          # decisão do usuário


def test_resumo_sem_decisoes_do_agente(base):
    texto = _entrega(**{
        "modulos.1.requisitos": [], "modulos.3": None,
        "restricoes.camadas": {"valor": 2, "decidido_por": "usuario"},
        "restricoes.contorno": {"largura": 50, "altura": 40, "decidido_por": "usuario"},
        "restricoes.montagem": {"valor": "barra_pinos_femea", "decidido_por": "usuario"}})
    spec, problemas = validar(texto, base, [])       # sem o conversor (modulos.3)
    assert problemas == [], problemas
    secao = resumir(spec, base).split("Decisões tomadas pelo agente (0):")[1]
    assert secao.lstrip().startswith("(nenhuma)")


def test_resumo_mostra_pendencias_e_custo(spec, base):
    texto = resumir(spec, base, [Pendencia("buzzer", "o usuário pediu um alarme")])
    assert "Pendências (1):\n  - buzzer: o usuário pediu um alarme" in texto
    assert f"Custo estimado: {SEM_PRECOS}" in texto
    assert "US$" not in texto                       # nenhum preço inventado
    assert "Pendências (0):\n  (nenhuma)" in resumir(spec, base)


def test_pedir_aprovacao_repete_ate_ter_resposta(spec, base):
    linhas, prompts, saida = ["", "  ", "use 80 x 60 mm"], [], []

    def ler(prompt):
        prompts.append(prompt)
        return linhas.pop(0)

    veredito = pedir_aprovacao(spec, base, ler=ler, escrever=saida.append)
    assert veredito == Veredito(False, "use 80 x 60 mm")
    assert prompts == [PERGUNTA] * 3 and len(saida) == 1 and "Componentes escolhidos" in saida[0]


def test_pedir_aprovacao_deixa_o_cancelamento_para_quem_chamou(spec, base):
    def ler(_prompt):
        raise EOFError

    with pytest.raises(EOFError):
        pedir_aprovacao(spec, base, ler=ler, escrever=lambda _t: None)


# --- Segunda aprovação (Parte 5; ADR-019) -----------------------------------------------------

@pytest.mark.parametrize("resposta,esperado", [
    ("s", Veredito(aprovada=True)), (" SIM ", Veredito(aprovada=True)),
    ("n", Veredito(aprovada=False)), ("Não", Veredito(aprovada=False)),
    ("nao", Veredito(aprovada=False)),
    ("use o IO35", Veredito(aprovada=False, correcao="use o IO35")),
    ("  ", None)])
def test_interpretar_da_fabrica(resposta, esperado):
    assert interpretar_da_fabrica(resposta) == esperado


def test_segunda_aprovacao_mostra_o_resumo_e_insiste_ate_ter_resposta():
    respostas, escrito = ["", "n"], []
    veredito = pedir_segunda_aprovacao("RESUMO DAS VERIFICAÇÕES", ler=lambda _: respostas.pop(0),
                                       escrever=escrito.append)
    assert veredito == Veredito(aprovada=False) and respostas == []
    assert "RESUMO DAS VERIFICAÇÕES" in escrito[0]


def test_wifi_tem_rotulo_e_valor():
    spec = ler_especificacao(Path(__file__).resolve().parents[1] / "placas" /
                             "monitor-umidade" / "spec.yaml")
    assert rotulo("wifi", spec) == "Wi-Fi"
    assert valor_da_decisao("wifi", spec, spec.wifi) == "ligado"
