"""Testes do eval de equivalência entre netlists (Marco 4, Parte 5).

Só precisam da base (Pydantic e PyYAML): o comparador lê a netlist sem o SKiDL, e por isso
estes testes rodam também no GitHub Actions.

As variações do gabarito são feitas de dois jeitos: editando o texto do ``gabarito.net`` (o
arquivo de verdade) e escrevendo netlists pequenas com ``_netlist``, no mesmo formato.
"""
import re
from pathlib import Path

import pytest

from src.componentes.carregar import carregar_todos
from src.evals.comparar import (Comparacao, ErroNetlist, Estrutura, comparar, ler_estrutura,
                                ler_sexpr)

GABARITO = Path(__file__).resolve().parents[1] / "placas" / "monitor-umidade" / "gabarito.net"
BASE = carregar_todos()

ESP, LCD, SENSOR, CONV = ("esp32-devkitc-v4", "display-lcd-1602-i2c",
                          "sensor-umidade-capacitivo", "conversor-nivel-logico-4-canais")

# A estrutura do gabarito, escrita à mão a partir do pecas.md (Parte 3, tabela 1), sem passar
# pelo circuito.py nem pelo comparador. Os nomes com "#" são os que se repetem na peça.
GRUPOS_DO_GABARITO = {
    frozenset({f"{ESP}: 5V", f"{LCD}: VCC", f"{CONV}: HV"}),
    frozenset({f"{ESP}: 3V3", f"{SENSOR}: VCC", f"{CONV}: LV"}),
    frozenset({f"{ESP}: GND#14", f"{ESP}: GND#20", f"{ESP}: GND#26", f"{LCD}: GND",
               f"{SENSOR}: GND", f"{CONV}: GND#4", f"{CONV}: GND#10"}),
    frozenset({f"{SENSOR}: AOUT", f"{ESP}: IO34"}),
    frozenset({f"{ESP}: IO21", f"{CONV}: LV1"}),
    frozenset({f"{ESP}: IO22", f"{CONV}: LV2"}),
    frozenset({f"{CONV}: HV1", f"{LCD}: SDA"}),
    frozenset({f"{CONV}: HV2", f"{LCD}: SCL"}),
}
COMPONENTES_DO_GABARITO = {f"{ESP}/J2", f"{ESP}/J3", LCD, SENSOR, f"{CONV}/HV", f"{CONV}/LV"}


def _texto():
    return GABARITO.read_text(encoding="utf-8")


def _comparar(obtido, esperado=None):
    return comparar(GABARITO if esperado is None else esperado, obtido, BASE)


# Conectores do gabarito: ref -> (value, footprint, símbolo).
_PINHEADER = "Connector_PinHeader_2.54mm:PinHeader_1x{:02d}_P2.54mm_Vertical"
CONECTORES = {
    "J1": (f"{ESP} J2", 19), "J2": (f"{ESP} J3", 19), "J3": (LCD, 4), "J4": (SENSOR, 3),
    "J5": (f"{CONV} LV", 6), "J6": (f"{CONV} HV", 6),
}


def _netlist(redes, conectores=CONECTORES, extra_comp=""):
    """Netlist mínima no formato do KiCad: ``redes`` é {nome: [(ref, pino), ...]}."""
    comps = "".join(
        f'(comp (ref "{ref}") (value "{valor}") (footprint "{_PINHEADER.format(n)}")'
        f' (libsource (lib "Connector_Generic") (part "Conn_01x{n:02d}")))'
        for ref, (valor, n) in conectores.items())
    nets = "".join(
        f'(net (code "{i}") (name "{nome}")'
        + "".join(f'(node (ref "{r}") (pin "{p}"))' for r, p in pinos) + ")"
        for i, (nome, pinos) in enumerate(redes.items(), start=1))
    return f'(export (version "D") (components {comps}{extra_comp}) (nets {nets}))'


# Redes do gabarito por (ref, número do pino no conector), lidas do pecas.md.
REDES = {
    "+3V3": [("J1", 1), ("J4", 2), ("J5", 3)],
    "+5V": [("J1", 19), ("J3", 2), ("J6", 3)],
    "GND": [("J1", 14), ("J2", 1), ("J2", 7), ("J3", 1), ("J4", 1), ("J5", 4), ("J6", 4)],
    "SCL_3V3": [("J2", 3), ("J5", 2)],
    "SCL_5V": [("J3", 4), ("J6", 2)],
    "SDA_3V3": [("J2", 6), ("J5", 1)],
    "SDA_5V": [("J3", 3), ("J6", 1)],
    "SENSOR": [("J1", 5), ("J4", 3)],
}


# --- O gabarito -------------------------------------------------------------------------------

def test_estrutura_do_gabarito_bate_com_o_pecas_md():
    estrutura = ler_estrutura(GABARITO, BASE)
    assert estrutura.componentes == COMPONENTES_DO_GABARITO
    assert estrutura.grupos == GRUPOS_DO_GABARITO
    assert estrutura.isolados == frozenset()


def test_gabarito_contra_ele_mesmo_e_equivalente():
    resultado = _comparar(GABARITO)
    assert resultado.equivalente
    assert resultado == Comparacao(equivalente=True)
    assert resultado.resumo() == "equivalente ao gabarito"


def test_netlist_minima_tem_a_estrutura_do_gabarito():
    # A netlist escrita com _netlist (sem tstamps, campos nem pintype) é o mesmo circuito.
    assert _comparar(_netlist(REDES)).equivalente


def test_aceita_caminho_texto_e_estrutura():
    estrutura = ler_estrutura(GABARITO, BASE)
    assert comparar(str(GABARITO), _texto(), BASE).equivalente
    assert comparar(estrutura, GABARITO, BASE).equivalente
    assert isinstance(estrutura, Estrutura)


# --- Mudanças que não mudam o circuito --------------------------------------------------------

def test_nomes_de_rede_diferentes_sao_equivalentes():
    texto = _texto()
    for antigo, novo in [("+3V3", "VCC_LOGICA"), ("+5V", "N$1"), ("GND", "TERRA"),
                         ("SDA_3V3", "i2c_dados"), ("SENSOR", "Net-(J4-Pin_3)")]:
        texto = texto.replace(f'(name "{antigo}")', f'(name "{novo}")')
    assert '(name "GND")' not in texto
    assert _comparar(texto).equivalente


def test_ordem_das_pecas_das_redes_e_dos_pinos_nao_importa():
    redes = {nome: list(reversed(pinos)) for nome, pinos in reversed(list(REDES.items()))}
    conectores = dict(reversed(list(CONECTORES.items())))
    assert _comparar(_netlist(redes, conectores)).equivalente


def test_referencias_trocadas_sao_equivalentes():
    # J5 <-> J6 e J1 -> J9: as referências mudam em todo o arquivo, o circuito não.
    texto = re.sub(r'\(ref "J([156])"\)',
                   lambda m: {"1": '(ref "J9")', "5": '(ref "J6")', "6": '(ref "J5")'}[m[1]],
                   _texto())
    assert '(ref "J1")' not in texto
    assert _comparar(texto).equivalente


def test_campos_de_desenho_nao_importam():
    texto = re.sub(r'\(date "[^"]*"\)', '(date "01/01/2030")', _texto())
    texto = re.sub(r'\(tstamps "[0-9a-f-]+"\)', '(tstamps "0")', texto)
    texto = texto.replace('"circuito.py:160"', '"outro.py:1"')
    assert _comparar(texto).equivalente


def test_rede_de_um_pino_so_vale_como_pino_sem_ligacao():
    # O KiCad escreve pinos soltos em redes "unconnected-(...)": não é ligação nenhuma.
    redes = dict(REDES, **{"unconnected-(J5-Pin_5)": [("J5", 5)], "solta": [("J2", 2)]})
    estrutura = ler_estrutura(_netlist(redes), BASE)
    assert estrutura.isolados == {f"{CONV}: LV3", f"{ESP}: IO23"}
    assert _comparar(estrutura).equivalente


# --- Mudanças que mudam o circuito ------------------------------------------------------------

def test_uma_ligacao_trocada_e_detectada():
    # SDA e SCL do LCD trocados no gabarito: J3 pino 3 passa para SCL_5V e o 4 para SDA_5V.
    texto = _texto()
    sda = '(ref "J3")\n        (pin "3")'
    scl = '(ref "J3")\n        (pin "4")'
    assert texto.count(sda) == texto.count(scl) == 1
    texto = texto.replace(sda, "@").replace(scl, sda).replace("@", scl)
    resultado = _comparar(texto)
    assert not resultado.equivalente
    assert resultado.componentes_faltando == resultado.componentes_sobrando == []
    assert resultado.pinos_divergentes == {
        f"{CONV}: HV1": ([f"{LCD}: SDA"], [f"{LCD}: SCL"]),
        f"{CONV}: HV2": ([f"{LCD}: SCL"], [f"{LCD}: SDA"]),
        f"{LCD}: SCL": ([f"{CONV}: HV2"], [f"{CONV}: HV1"]),
        f"{LCD}: SDA": ([f"{CONV}: HV1"], [f"{CONV}: HV2"]),
    }
    assert resultado.grupos_faltando == [[f"{CONV}: HV1", f"{LCD}: SDA"],
                                         [f"{CONV}: HV2", f"{LCD}: SCL"]]
    assert resultado.grupos_sobrando == [[f"{CONV}: HV1", f"{LCD}: SCL"],
                                         [f"{CONV}: HV2", f"{LCD}: SDA"]]
    assert "esperado com" in resultado.resumo()


def test_pino_de_gnd_trocado_por_outro_gnd_da_mesma_peca_e_detectado():
    # Os GND repetidos não se confundem: tirar o GND#26 e pôr o IO23 no lugar é diferente.
    redes = dict(REDES, GND=[p for p in REDES["GND"] if p != ("J2", 7)] + [("J2", 2)])
    resultado = _comparar(_netlist(redes))
    assert not resultado.equivalente
    assert set(resultado.pinos_divergentes) >= {f"{ESP}: GND#26", f"{ESP}: IO23"}


def test_pino_a_menos_numa_rede_e_detectado():
    redes = dict(REDES, GND=[p for p in REDES["GND"] if p != ("J4", 1)])
    resultado = _comparar(_netlist(redes))
    assert not resultado.equivalente
    assert resultado.pinos_divergentes[f"{SENSOR}: GND"][1] == []


def test_pino_a_mais_numa_rede_e_detectado():
    redes = dict(REDES, SDA_3V3=REDES["SDA_3V3"] + [("J5", 5)])       # LV3 ligado ao SDA
    resultado = _comparar(_netlist(redes))
    assert not resultado.equivalente
    assert resultado.pinos_divergentes[f"{CONV}: LV3"] == (
        [], [f"{CONV}: LV1", f"{ESP}: IO21"])


def test_ligacao_ausente_e_detectada():
    redes = {k: v for k, v in REDES.items() if k != "SENSOR"}
    resultado = _comparar(_netlist(redes))
    assert not resultado.equivalente
    assert resultado.grupos_faltando == [[f"{ESP}: IO34", f"{SENSOR}: AOUT"]]
    assert resultado.grupos_sobrando == []


def test_ligacao_a_mais_e_detectada():
    redes = dict(REDES, EXTRA=[("J1", 2), ("J2", 2)])                  # EN com IO23
    resultado = _comparar(_netlist(redes))
    assert not resultado.equivalente
    assert resultado.grupos_sobrando == [[f"{ESP}: EN", f"{ESP}: IO23"]]
    assert resultado.grupos_faltando == []


def test_duas_redes_juntadas_sao_detectadas():
    redes = {k: v for k, v in REDES.items() if k not in ("+5V", "+3V3")}
    redes["ALIMENTACAO"] = REDES["+5V"] + REDES["+3V3"]
    resultado = _comparar(_netlist(redes))
    assert not resultado.equivalente
    assert len(resultado.grupos_faltando) == 2 and len(resultado.grupos_sobrando) == 1


def test_rede_partida_em_duas_e_detectada():
    gnd = REDES["GND"]
    redes = dict(REDES, GND=gnd[:3], GND2=gnd[3:])
    resultado = _comparar(_netlist(redes))
    assert not resultado.equivalente
    assert len(resultado.grupos_faltando) == 1 and len(resultado.grupos_sobrando) == 2


def test_componente_ausente_e_detectado():
    conectores = {k: v for k, v in CONECTORES.items() if k != "J4"}
    redes = {k: [p for p in v if p[0] != "J4"] for k, v in REDES.items()}
    resultado = _comparar(_netlist(redes, conectores))
    assert not resultado.equivalente
    assert resultado.componentes_faltando == [SENSOR]
    assert resultado.componentes_sobrando == []
    assert f"- falta o componente {SENSOR}" in resultado.resumo()


def test_componente_a_mais_e_detectado_mesmo_sem_ligacoes():
    # O mesmo par ao contrário: o esperado não tem o sensor, o obtido tem, sem nenhuma rede.
    conectores = {k: v for k, v in CONECTORES.items() if k != "J4"}
    redes = {k: [p for p in v if p[0] != "J4"] for k, v in REDES.items()}
    sem_sensor = _netlist(redes, conectores)
    com_sensor_solto = _netlist(redes)
    resultado = comparar(sem_sensor, com_sensor_solto, BASE)
    assert not resultado.equivalente
    assert resultado.componentes_sobrando == [SENSOR]
    assert resultado.grupos_faltando == resultado.grupos_sobrando == []


def test_conector_de_uma_peca_ausente_e_detectado():
    conectores = {k: v for k, v in CONECTORES.items() if k != "J6"}      # sem o lado HV
    redes = {k: [p for p in v if p[0] != "J6"] for k, v in REDES.items()}
    redes = {k: v for k, v in redes.items() if len(v) >= 2}
    resultado = _comparar(_netlist(redes, conectores))
    assert not resultado.equivalente
    assert resultado.componentes_faltando == [f"{CONV}/HV"]


# --- Netlists que não dá para ler sem adivinhar ------------------------------------------------

@pytest.mark.parametrize("troca, erro", [
    (("J3", ("lcd-que-nao-existe", 4)), "não começa pelo id de uma peça da base"),
    (("J1", (f"{ESP} J9", 19)), "não tem o conector 'J9'"),
    (("J1", (ESP, 19)), "não tem o conector ''"),
    (("J3", (f"{LCD} X", 4)), "tem um conector só"),
    (("J3", (LCD, 5)), "footprint"),
])
def test_componente_que_nao_confere_com_a_base_e_erro(troca, erro):
    ref, dados = troca
    conectores = dict(CONECTORES, **{ref: dados})
    with pytest.raises(ErroNetlist, match=re.escape(erro)):
        ler_estrutura(_netlist(REDES, conectores), BASE)


def test_simbolo_diferente_da_base_e_erro():
    texto = _texto().replace('(part "Conn_01x04")', '(part "Conn_01x04_Socket")')
    with pytest.raises(ErroNetlist, match="símbolo"):
        ler_estrutura(texto, BASE)


def test_componente_sem_value_e_erro():
    texto = _texto().replace('(value "display-lcd-1602-i2c")', "")
    with pytest.raises(ErroNetlist, match="sem 'value'"):
        ler_estrutura(texto, BASE)


def test_pino_que_o_conector_nao_tem_e_erro():
    redes = dict(REDES, SENSOR=[("J1", 5), ("J4", 4)])                 # o sensor tem 3 pinos
    with pytest.raises(ErroNetlist, match="J4 não tem o pino '4'"):
        ler_estrutura(_netlist(redes), BASE)


def test_no_de_componente_inexistente_e_erro():
    redes = dict(REDES, SENSOR=[("J1", 5), ("J7", 1)])
    with pytest.raises(ErroNetlist, match="'J7' não existe"):
        ler_estrutura(_netlist(redes), BASE)


def test_pino_em_duas_redes_e_erro():
    redes = dict(REDES, SENSOR=[("J1", 5), ("J4", 3), ("J4", 1)])      # GND do sensor 2 vezes
    with pytest.raises(ErroNetlist, match="está nas redes"):
        ler_estrutura(_netlist(redes), BASE)


def test_duas_unidades_da_mesma_peca_e_erro():
    conectores = dict(CONECTORES, J7=(SENSOR, 3))
    with pytest.raises(ErroNetlist, match="aparece 2 vezes"):
        ler_estrutura(_netlist(REDES, conectores), BASE)


def test_referencia_repetida_e_erro():
    extra = (f'(comp (ref "J4") (value "{SENSOR}") (footprint "{_PINHEADER.format(3)}")'
             ' (libsource (lib "Connector_Generic") (part "Conn_01x03")))')
    with pytest.raises(ErroNetlist, match="referência J4 repetida"):
        ler_estrutura(_netlist(REDES, extra_comp=extra), BASE)


@pytest.mark.parametrize("texto, erro", [
    ("(export (components)", "sem fechar"),
    ("(export))", "sem '(' correspondente"),
    ('(export (x "abc', "aspas sem fechar"),
    ("(export) (export)", "uma única expressão"),
    ("(kicad_pcb)", "esperava (export ...)"),
])
def test_arquivo_malformado_e_erro(texto, erro):
    with pytest.raises(ErroNetlist, match=re.escape(erro)):
        ler_estrutura(texto, BASE)


def test_aspas_escapadas_sao_lidas():
    assert ler_sexpr(r'(a "x \"y\" z" (b c))') == ["a", 'x "y" z', ["b", "c"]]


def test_erro_lista_todos_os_problemas():
    redes = dict(REDES, SENSOR=[("J1", 5), ("J4", 9)], EXTRA=[("J8", 1), ("J1", 2)])
    with pytest.raises(ErroNetlist) as erro:
        ler_estrutura(_netlist(redes), BASE)
    assert len(erro.value.problemas) == 2
