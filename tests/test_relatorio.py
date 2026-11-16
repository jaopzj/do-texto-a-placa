"""Testes do relatório de projeto (Marco 5, Parte 5; ADR-019)."""
from pathlib import Path

from src.componentes.carregar import carregar_todos
from src.correcao import Problema, ResultadoDoLaco, Rodada
from src.drc import ItemDRC, ResultadoPlaca
from src.especificacao import ler_especificacao
from src.fabrica import ResultadoFabrica
from src.regras import verificar
from src.relatorio import TITULOS, Andamento, gravar, montar

from exemplo_circuito import REFERENCIA, SELECOES

RAIZ = Path(__file__).resolve().parents[1]
BASE = carregar_todos()
SPEC_ARQUIVO = RAIZ / "placas" / "monitor-umidade" / "spec.yaml"
SPEC = ler_especificacao(SPEC_ARQUIVO, BASE)


def _estado():
    """O circuito de referência, como ``conectar`` o deixa (um nome liga todos os pinos dele)."""
    ligacoes = [{"ref": ref, "pino": p.numero, "nome": nome, "rede": rede}
                for rede, pinos in REFERENCIA.items() for ref, nome in pinos
                for p in BASE[SELECOES[ref]].pinos if p.nome == nome]
    return {"selecoes": dict(SELECOES), "ligacoes": ligacoes, "pendencias": [],
            "decisoes": [{"decisao": "sensor no IO34", "motivo": "ADC1 | com Wi-Fi",
                          "fontes": ["componente:esp32-devkitc-v4/regra:adc2-wifi"]}]}


def _laco(placa=None, problemas=()):
    estado = _estado()
    regras = verificar(estado, BASE, wifi=True)
    rodadas = [Rodada(0, list(problemas), regras=regras, placa=placa)]
    return ResultadoDoLaco(not problemas, "aprovado" if not problemas else "limite", rodadas,
                           estado)


def _andamento(**extra):
    dados = dict(pedido="quero um monitor", spec=SPEC, arquivo_spec=SPEC_ARQUIVO,
                 situacao="aguardando", explicacao="Tudo certo.")
    dados.update(extra)
    return Andamento(**dados)


def test_relatorio_tem_decisoes_com_fonte_inclusive_o_wifi():
    texto = montar(_andamento(laco=_laco()), BASE)
    assert "# Relatório do projeto: " in texto and TITULOS["aguardando"] in texto
    assert "| Wi-Fi | ligado | usuario |" in texto
    assert "Do-texto-a-placa-proposta.pdf, p. 9" in texto
    # A barra vertical do motivo não quebra a tabela.
    assert "ADC1 \\| com Wi-Fi" in texto


def test_relatorio_lista_cada_regra_e_a_bom():
    texto = montar(_andamento(laco=_laco()), BASE)
    assert "**APROVADO**, 12 ok" in texto and "Wi-Fi: sim" in texto
    assert "| U1 | esp32-devkitc-v4 | adc2-wifi | erro | ok |" in texto
    assert "conferir à mão:" in texto
    assert "| J1 | U1 | esp32-devkitc-v4 | J2 |" in texto
    assert "Não gerados: aguardando a segunda aprovação." in texto


def test_relatorio_sem_circuito():
    texto = montar(_andamento(situacao="pendencias", explicacao="Parou.",
                              pendencias=[{"origem": "briefing", "necessidade": "relé",
                                           "motivo": "a base não tem"}]), BASE)
    assert "Não verificadas: o agente não montou o circuito." in texto
    assert "Nenhuma conferência" in texto and "Sem circuito, sem BOM." in texto
    assert "- (briefing) **relé**: a base não tem" in texto
    assert "o projeto parou antes" in texto


def test_relatorio_reprovado_mostra_os_problemas_das_conferencias():
    problema = Problema("regras", "esp32-devkitc-v4/adc2-wifi", "U1:9 (IO25)", "ADC2 com Wi-Fi",
                        "use o ADC1")
    laco = _laco(problemas=[problema])
    texto = montar(_andamento(situacao="reprovado", laco=laco, historico=laco.rodadas,
                              explicacao="Não resolveu."), BASE)
    assert "1. circuito entregue: 1 problema(s)." in texto
    assert "- [regras] esp32-devkitc-v4/adc2-wifi, em U1:9 (IO25): ADC2 com Wi-Fi" in texto


def test_relatorio_com_drc_e_arquivos(tmp_path):
    placa = ResultadoPlaca((ItemDRC("x", "ignore", "ignorado"),), tmp_path / "r.kicad_pcb",
                           tmp_path / "drc.json")
    arquivo = tmp_path / "fabrica" / "placa.drl"
    arquivo.parent.mkdir()
    arquivo.write_text("M48\nM30\n", encoding="utf-8")
    fabrica = ResultadoFabrica(arquivo.parent, (arquivo,), "OK: conferido")
    laco = _laco(placa=placa)
    caminho = gravar(_andamento(situacao="fabrica", laco=laco, historico=laco.rodadas,
                                fabrica=fabrica), BASE, tmp_path)
    texto = caminho.read_text(encoding="utf-8")
    assert caminho.name == "relatorio.md"
    assert "**0 item(ns)**" in texto                  # o item "ignore" não conta
    assert "- `placa.drl` (8 bytes)" in texto and "OK: conferido" in texto


def test_custos_no_relatorio():
    custos = {"execucoes": 1, "etapas": {"motor_de_regras": {
        "chamadas_llm": 0, "operacoes": 1, "tokens_entrada": 0, "tokens_saida": 0,
        "custo_calculado_usd": 0.0, "custo_completo": True, "segundos": 0.01}},
        "total": {"chamadas_llm": 0, "operacoes": 1, "tokens_entrada": 0, "tokens_saida": 0,
                  "custo_calculado_usd": 0.0, "custo_completo": True, "segundos": 0.01}}
    texto = montar(_andamento(custos=custos), BASE)
    assert "| motor_de_regras | 0 | 1 | 0 + 0 | sem custo de API" in texto
