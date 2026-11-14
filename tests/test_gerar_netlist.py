"""Testes do gerador de netlist a partir do estado do agente (Marco 4, Parte 4).

A validação principal: as ligações do ``circuito.py``, escritas à mão no formato das
ferramentas do agente (uma referência por peça, pinos pelo nome da base), passam pelas
ferramentas reais, viram netlist pelo SKiDL e saem equivalentes ao ``gabarito.net`` segundo o
eval da Parte 5. Uma ligação trocada no estado tem de sair diferente.

Os testes de ``planejar`` não precisam do SKiDL e rodam no GitHub Actions; os que geram a
netlist são pulados sem ele.
"""
import importlib.util
import re
from pathlib import Path

import pytest

from src.agente.ferramentas import Ferramentas
from src.componentes.carregar import carregar_todos
from src.evals.comparar import ErroNetlist, comparar, ler_estrutura
from src.gerar_netlist import ErroGeracao, planejar

RAIZ = Path(__file__).resolve().parents[1]
PASTA = RAIZ / "placas" / "monitor-umidade"
GABARITO = PASTA / "gabarito.net"
BASE = carregar_todos()

ESP, LCD, SENSOR, CONV = ("esp32-devkitc-v4", "display-lcd-1602-i2c",
                          "sensor-umidade-capacitivo", "conversor-nivel-logico-4-canais")

# As peças e as ligações do circuito.py, escritas à mão como o agente as faria: uma
# referência por peça (não por fileira) e o nome do pino na base. "GND" na peça liga todos
# os pinos GND dela, como a ferramenta conectar faz.
SELECOES = {"U1": ESP, "LCD1": LCD, "S1": SENSOR, "U2": CONV}
LIGACOES_A_MAO = {
    "+5V": [("U1", "5V"), ("LCD1", "VCC"), ("U2", "HV")],
    "+3V3": [("U1", "3V3"), ("S1", "VCC"), ("U2", "LV")],
    "GND": [("U1", "GND"), ("LCD1", "GND"), ("S1", "GND"), ("U2", "GND")],
    "SENSOR": [("S1", "AOUT"), ("U1", "IO34")],
    "SDA_3V3": [("U1", "IO21"), ("U2", "LV1")],
    "SCL_3V3": [("U1", "IO22"), ("U2", "LV2")],
    "SDA_5V": [("U2", "HV1"), ("LCD1", "SDA")],
    "SCL_5V": [("U2", "HV2"), ("LCD1", "SCL")],
}


def _ferramentas(ligacoes=LIGACOES_A_MAO, selecoes=SELECOES):
    """Passa as ligações pelas ferramentas reais da Parte 3, como o agente faria."""
    f = Ferramentas(BASE)
    for ref, id_ in selecoes.items():
        assert f.selecionar_componente(id_, ref)["ok"], (ref, id_)
    for rede, pinos in ligacoes.items():
        for ref, pino in pinos:
            resultado = f.conectar(ref, pino, rede)
            assert resultado["ok"], resultado
    return f


def _estado(ligacoes=LIGACOES_A_MAO, selecoes=SELECOES):
    return _ferramentas(ligacoes, selecoes).estado()


def _carregar_circuito():
    spec = importlib.util.spec_from_file_location("circuito_monitor", PASTA / "circuito.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


# --- A transcrição à mão confere com o circuito.py (sem SKiDL) ---------------------------------

def _ligacoes_do_circuito_py():
    """As LIGACOES e NAO_USADOS do circuito.py, lidas do texto, sem importar o SKiDL."""
    import ast
    arvore = ast.parse((PASTA / "circuito.py").read_text(encoding="utf-8"))
    tabelas = {}
    for no in arvore.body:
        if isinstance(no, ast.Assign) and isinstance(no.targets[0], ast.Name) and \
                no.targets[0].id in ("PECAS", "LIGACOES", "NAO_USADOS"):
            tabelas[no.targets[0].id] = ast.literal_eval(no.value)
    return tabelas


def test_ligacoes_a_mao_sao_as_do_circuito_py():
    t = _ligacoes_do_circuito_py()
    peca = {ref: id_ for ref, (id_, _) in t["PECAS"].items()}
    do_circuito = {rede: {(peca[ref], nome) for ref, nome in pinos}
                   for rede, pinos in t["LIGACOES"].items()}
    a_mao = {rede: {(SELECOES[ref], nome) for ref, nome in pinos}
             for rede, pinos in LIGACOES_A_MAO.items()}
    assert a_mao == do_circuito


def test_pinos_sem_ligacao_sao_os_nao_usados_do_circuito_py():
    t = _ligacoes_do_circuito_py()
    peca = {ref: id_ for ref, (id_, _) in t["PECAS"].items()}
    nao_usados = {}
    for ref, nomes in t["NAO_USADOS"].items():
        nao_usados.setdefault(peca[ref], set()).update(nomes)
    plano = planejar(_estado(), BASE)
    sem_ligacao = {SELECOES[ref]: set(nomes) for ref, nomes in plano.sem_ligacao_por_peca.items()}
    assert sem_ligacao == {k: v for k, v in nao_usados.items() if v}


# --- planejar (sem SKiDL) ----------------------------------------------------------------------

def test_planejar_abre_cada_peca_nos_seus_conectores():
    plano = planejar(_estado(), BASE)
    assert [(c.ref, c.ref_agente, c.valor) for c in plano.conectores] == [
        ("J1", "U1", f"{ESP} J2"), ("J2", "U1", f"{ESP} J3"), ("J3", "LCD1", LCD),
        ("J4", "S1", SENSOR), ("J5", "U2", f"{CONV} HV"), ("J6", "U2", f"{CONV} LV")]
    j1 = plano.conectores[0]
    assert j1.footprint == "Connector_PinHeader_2.54mm:PinHeader_1x19_P2.54mm_Vertical"
    assert j1.simbolo == "Connector_Generic:Conn_01x19"
    assert j1.pinos[0] == (1, "3V3") and j1.pinos[-1] == (19, "5V")
    assert plano.conectores[1].pinos[0] == (20, "GND")


def test_planejar_poe_cada_pino_numa_rede_ou_sem_ligacao():
    plano = planejar(_estado(), BASE)
    ligados = [p for pinos in plano.redes.values() for p in pinos]
    todos = {(c.ref, i) for c in plano.conectores for i in range(1, len(c.pinos) + 1)}
    assert len(ligados) == len(set(ligados)) == 23        # 8 + 4 + 3 + 8 (pecas.md, tabela 3)
    assert set(ligados) | set(plano.sem_ligacao) == todos
    assert not set(ligados) & set(plano.sem_ligacao)
    assert sorted(plano.redes["GND"]) == [("J1", 14), ("J2", 1), ("J2", 7), ("J3", 1),
                                          ("J4", 1), ("J5", 4), ("J6", 4)]


def test_planejar_lista_os_pinos_sem_ligacao_por_peca():
    plano = planejar(_estado(), BASE)
    assert plano.sem_ligacao_por_peca["U2"] == ["HV3", "HV4", "LV3", "LV4"]
    assert "LCD1" not in plano.sem_ligacao_por_peca and "S1" not in plano.sem_ligacao_por_peca
    assert len(plano.sem_ligacao_por_peca["U1"]) == 30


def test_planejar_marca_nome_repetido_com_o_numero():
    estado = _estado({"GND": [("U2", 4), ("S1", "GND")]})   # só o GND#4 do conversor
    plano = planejar(estado, BASE)
    assert "GND#10" in plano.sem_ligacao_por_peca["U2"]


def test_peca_selecionada_sem_ligacao_entra_inteira_sem_ligacao():
    estado = _estado(selecoes=dict(SELECOES, S2=SENSOR))
    plano = planejar(estado, BASE)
    assert [c.ref_agente for c in plano.conectores][-1] == "S2"
    assert plano.sem_ligacao_por_peca["S2"] == ["GND", "VCC", "AOUT"]


def _problemas(estado):
    with pytest.raises(ErroGeracao) as erro:
        planejar(estado, BASE)
    return erro.value.problemas


def test_planejar_confere_o_estado_sem_confiar_nas_ferramentas():
    estado = {
        "selecoes": {"U1": ESP, "X1": "peca-inventada", "u1": LCD},
        "ligacoes": [
            {"ref": "U1", "pino": 99, "rede": "A"},                     # pino inexistente
            {"ref": "U9", "pino": 1, "rede": "A"},                      # peça não selecionada
            {"ref": "U1", "pino": 1, "nome": "5V", "rede": "A"},        # nome não confere
            {"ref": "U1", "pino": "3V3", "rede": "A"},                  # nome no lugar do número
            {"ref": "U1", "pino": 2, "rede": "B C"},                    # rede com espaço
            {"ref": "U1", "pino": 3, "rede": "D"},
            {"ref": "U1", "pino": 3, "rede": "E"},                      # pino em duas redes
            {"ref": "U1", "rede": "F"},                                 # sem pino
        ],
    }
    problemas = _problemas(estado)
    esperados = ["peça 'peca-inventada' não está na base", "referências repetidas",
                 "não tem o pino 99", "'U9' não foi selecionada", "se chama '3V3', não '5V'",
                 "número inteiro", "com espaços", "já está na rede 'D'", "precisa de 'ref'",
                 "rede 'D': só 1 pino"]
    for trecho in esperados:
        assert any(trecho in p for p in problemas), (trecho, problemas)


def test_planejar_recusa_pino_nao_usado_ligado():
    # Nenhuma peça da base tem pino nao_usado hoje: a cópia do sensor marca o AOUT assim.
    sensor = BASE[SENSOR]
    pinos = [p.model_copy(update={"tipo": "nao_usado"}) if p.nome == "AOUT" else p
             for p in sensor.pinos]
    base = dict(BASE, **{SENSOR: sensor.model_copy(update={"pinos": pinos})})
    estado = {"selecoes": {"S1": SENSOR, "U1": ESP}, "ligacoes": [
        {"ref": "S1", "pino": 3, "rede": "A"}, {"ref": "U1", "pino": 5, "rede": "A"}]}
    with pytest.raises(ErroGeracao, match="'nao_usado' na base"):
        planejar(estado, base)


def test_planejar_recusa_estado_vazio_ou_malformado():
    assert _problemas({"selecoes": {}, "ligacoes": []}) == ["nenhuma peça selecionada"]
    assert "'selecoes' (mapa)" in _problemas({"ligacoes": []})[0]


def test_ligacao_repetida_na_mesma_rede_nao_muda_nada():
    estado = _estado()
    estado["ligacoes"].append(dict(estado["ligacoes"][0]))
    assert planejar(estado, BASE).redes == planejar(_estado(), BASE).redes


# --- A netlist pelo SKiDL ----------------------------------------------------------------------

precisa_do_skidl = pytest.mark.skipif(importlib.util.find_spec("skidl") is None,
                                      reason="o SKiDL só está no container")


@pytest.fixture
def gerar(tmp_path):
    from src.gerar_netlist import gerar_netlist

    def _gerar(estado, nome="agente.net"):
        arquivo = tmp_path / nome
        gerar_netlist(estado, arquivo, BASE)
        return arquivo
    return _gerar


@precisa_do_skidl
def test_ligacoes_a_mao_geram_netlist_equivalente_ao_gabarito(gerar):
    arquivo = gerar(_estado())
    resultado = comparar(GABARITO, arquivo, BASE)
    assert resultado.equivalente, resultado.resumo()
    # E não por acaso: a estrutura tem os 6 conectores e as 8 redes do gabarito.
    estrutura = ler_estrutura(arquivo, BASE)
    assert len(estrutura.componentes) == 6 and len(estrutura.grupos) == 8


@precisa_do_skidl
def test_netlist_gerada_tem_os_componentes_do_gabarito(gerar):
    texto = gerar(_estado()).read_text(encoding="utf-8")
    gabarito = GABARITO.read_text(encoding="utf-8")

    def componentes(t):
        return sorted(re.findall(r'\(value "([^"]+)"\)\s+\(description "[^"]*"\)\s+'
                                 r'\(footprint "([^"]+)"\)', t))
    assert componentes(texto) == componentes(gabarito)
    assert len(componentes(texto)) == 6


@precisa_do_skidl
def test_netlist_gerada_e_equivalente_a_do_circuito_py(gerar, tmp_path):
    circuito = _carregar_circuito()
    manual = tmp_path / "circuito.net"
    circuito.montar().generate_netlist(file_=str(manual))
    assert comparar(manual, gerar(_estado()), BASE).equivalente


@precisa_do_skidl
def test_uma_ligacao_trocada_no_estado_e_detectada(gerar):
    trocada = dict(LIGACOES_A_MAO, SDA_5V=[("U2", "HV1"), ("LCD1", "SCL")],
                   SCL_5V=[("U2", "HV2"), ("LCD1", "SDA")])
    resultado = comparar(GABARITO, gerar(_estado(trocada)), BASE)
    assert not resultado.equivalente
    assert set(resultado.pinos_divergentes) == {f"{CONV}: HV1", f"{CONV}: HV2",
                                                f"{LCD}: SDA", f"{LCD}: SCL"}


@precisa_do_skidl
def test_ligacao_esquecida_no_estado_e_detectada(gerar):
    sem_sensor = {k: v for k, v in LIGACOES_A_MAO.items() if k != "SENSOR"}
    resultado = comparar(GABARITO, gerar(_estado(sem_sensor)), BASE)
    assert not resultado.equivalente
    assert resultado.grupos_faltando == [[f"{ESP}: IO34", f"{SENSOR}: AOUT"]]


@precisa_do_skidl
def test_gnd_parcial_no_estado_e_detectado(gerar):
    # Ligar só um dos dois GND do conversor (pelo número) deixa o outro de fora.
    gnd = [p for p in LIGACOES_A_MAO["GND"] if p[0] != "U2"] + [("U2", 4)]
    resultado = comparar(GABARITO, gerar(_estado(dict(LIGACOES_A_MAO, GND=gnd))), BASE)
    assert not resultado.equivalente
    assert list(resultado.pinos_divergentes)[0] == f"{CONV}: GND#10"


@precisa_do_skidl
def test_segunda_unidade_da_mesma_peca_e_recusada_pelo_eval(gerar):
    # Duas unidades da mesma peça ainda não são comparáveis (ADR-012): o eval recusa em vez
    # de adivinhar qual sensor do gabarito corresponde a qual do agente.
    arquivo = gerar(_estado(selecoes=dict(SELECOES, S2=SENSOR)))
    with pytest.raises(ErroNetlist, match="aparece 2 vezes"):
        comparar(GABARITO, arquivo, BASE)


@precisa_do_skidl
def test_peca_faltando_no_estado_e_detectada(gerar):
    selecoes = {k: v for k, v in SELECOES.items() if k != "S1"}
    ligacoes = {k: [p for p in v if p[0] != "S1"] for k, v in LIGACOES_A_MAO.items()}
    ligacoes = {k: v for k, v in ligacoes.items() if len(v) >= 2}
    resultado = comparar(GABARITO, gerar(_estado(ligacoes, selecoes)), BASE)
    assert not resultado.equivalente
    assert resultado.componentes_faltando == [SENSOR]


@precisa_do_skidl
def test_netlist_gerada_e_reprodutivel(gerar):
    textos = [re.sub(r'\(date "[^"]*"\)', "", gerar(_estado(), f"n{i}.net").read_text())
              for i in range(2)]
    assert textos[0] == textos[1]


@precisa_do_skidl
def test_erc_sem_erros_nem_avisos():
    from skidl.logger import erc_logger

    from src.gerar_netlist import montar_circuito
    circuito, _ = montar_circuito(_estado(), BASE)
    circuito.ERC()
    assert erc_logger.error.count == 0
    assert erc_logger.warning.count == 0


@precisa_do_skidl
def test_estado_invalido_nao_gera_arquivo(tmp_path):
    from src.gerar_netlist import gerar_netlist
    arquivo = tmp_path / "nao.net"
    with pytest.raises(ErroGeracao):
        gerar_netlist({"selecoes": {"U1": "peca-inventada"}, "ligacoes": []}, arquivo, BASE)
    assert not arquivo.exists()
