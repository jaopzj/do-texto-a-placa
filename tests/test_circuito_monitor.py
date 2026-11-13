"""Testes da netlist em SKiDL da placa de referência (Marco 2, Parte 4).

A tabela esperada abaixo foi transcrita à mão do ``pecas.md`` (Parte 3), de forma
independente do ``circuito.py``. A pinagem física é lida direto do ``pecas.md``. Assim,
os testes conferem a cadeia inteira: pecas.md -> circuito.py -> netlist gerada.
"""

import importlib.util
import re
from pathlib import Path

import pytest
from skidl.logger import erc_logger

PASTA = Path(__file__).resolve().parents[1] / "placas" / "monitor-umidade"


def _carregar_circuito():
    spec = importlib.util.spec_from_file_location("circuito_monitor", PASTA / "circuito.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


circuito = _carregar_circuito()


def pinagens_do_pecas_md():
    """Referência -> nomes dos pinos, lidos dos blocos ``text`` do pecas.md."""
    texto = (PASTA / "pecas.md").read_text(encoding="utf-8")
    blocos = re.findall(r"``` text\n(.*?)\n```", texto)
    linhas = [tuple(p.strip() for p in b.split("|")) for b in blocos if "|" in b]
    # Ordem dos blocos no pecas.md: ESP32 superior, ESP32 inferior, LCD, sensor,
    # conversor HV, conversor LV.
    assert len(linhas) == 6, linhas
    return dict(zip(("J1", "J2", "J3", "J4", "J6", "J5"), linhas))


# Transcrição da tabela 1 da Parte 3 (pecas.md).
LIGACOES_ESPERADAS = {
    "+5V": {("J1", "VIN"), ("J3", "VCC"), ("J6", "HV")},
    "+3V3": {("J2", "3V3"), ("J4", "VCC"), ("J5", "LV")},
    "GND": {("J1", "GND"), ("J2", "GND"), ("J3", "GND"), ("J4", "GND"),
            ("J5", "GND"), ("J6", "GND")},
    "SENSOR": {("J4", "A0"), ("J1", "D34")},
    "SDA_3V3": {("J2", "D21"), ("J5", "A1")},
    "SCL_3V3": {("J2", "D22"), ("J5", "A2")},
    "SDA_5V": {("J6", "B1"), ("J3", "SDA")},
    "SCL_5V": {("J6", "B2"), ("J3", "SCL")},
}

# Transcrição da tabela 2 da Parte 3 (pecas.md).
NAO_USADOS_ESPERADOS = {
    ("J1", p) for p in ("D13", "D12", "D14", "D27", "D26", "D25", "D33", "D32",
                        "D35", "VN", "VP", "EN")
} | {
    ("J2", p) for p in ("D15", "D2", "D4", "RX2", "TX2", "D5", "D18", "D19",
                        "RX0", "TX0", "D23")
} | {("J4", "D0"), ("J5", "A3"), ("J5", "A4"), ("J6", "B3"), ("J6", "B4")}

# Contagens da tabela 3 da Parte 3 (pecas.md): pinos ligados por módulo.
LIGADOS_POR_MODULO = {"ESP32": 7, "LCD": 4, "sensor": 3, "conversor": 8}
MODULO = {"J1": "ESP32", "J2": "ESP32", "J3": "LCD", "J4": "sensor",
          "J5": "conversor", "J6": "conversor"}


def ler_netlist(caminho):
    """Lê a netlist KiCad: devolve (componentes, redes) com números de pino."""
    texto = Path(caminho).read_text(encoding="utf-8")
    componentes = {
        ref: footprint
        for ref, footprint in re.findall(
            r'\(comp\s+\(ref "([^"]+)"\).*?\(footprint "([^"]+)"\)', texto, flags=re.S
        )
    }
    redes = {}
    for bloco in re.split(r"\(net\s", texto.split("(nets", 1)[1])[1:]:
        nome = re.search(r'\(name "([^"]+)"\)', bloco).group(1)
        redes[nome] = set(re.findall(r'\(ref "([^"]+)"\)\s+\(pin "([^"]+)"\)', bloco))
    return texto, componentes, redes


@pytest.fixture
def netlist(tmp_path):
    arquivo = tmp_path / "monitor-umidade.net"
    circ = circuito.montar()
    circ.generate_netlist(file_=str(arquivo))
    return ler_netlist(arquivo)


def test_pinagem_do_circuito_bate_com_o_pecas_md():
    pinagens = pinagens_do_pecas_md()
    assert {ref: pinos for ref, (_, pinos) in circuito.CONECTORES.items()} == pinagens


def test_tabelas_do_circuito_batem_com_a_parte_3():
    ligacoes = {rede: set(p) for rede, p in circuito.LIGACOES.items()}
    assert ligacoes == LIGACOES_ESPERADAS
    nao_usados = {(ref, p) for ref, ps in circuito.NAO_USADOS.items() for p in ps}
    assert nao_usados == NAO_USADOS_ESPERADOS


def test_validar_aceita_a_tabela_atual():
    circuito.validar()


def test_validar_recusa_pino_esquecido(monkeypatch):
    sem_d0 = dict(circuito.NAO_USADOS, J4=())
    monkeypatch.setattr(circuito, "NAO_USADOS", sem_d0)
    with pytest.raises(ValueError, match=r"\('J4', 'D0'\) aparece 0 vez"):
        circuito.validar()


def test_validar_recusa_pino_em_duas_redes(monkeypatch):
    ligacoes = dict(circuito.LIGACOES, SENSOR=(("J4", "A0"), ("J1", "VIN")))
    monkeypatch.setattr(circuito, "LIGACOES", ligacoes)
    with pytest.raises(ValueError, match=r"\('J1', 'VIN'\) aparece 2 vez"):
        circuito.validar()


def test_validar_recusa_pino_inexistente(monkeypatch):
    ligacoes = dict(circuito.LIGACOES, SENSOR=(("J4", "AOUT"), ("J1", "D34")))
    monkeypatch.setattr(circuito, "LIGACOES", ligacoes)
    with pytest.raises(ValueError, match="pino inexistente"):
        circuito.validar()


def test_erc_sem_erros_nem_avisos():
    circuito.montar().ERC()
    assert erc_logger.error.count == 0
    assert erc_logger.warning.count == 0


def test_componentes_e_footprints(netlist):
    _, componentes, _ = netlist
    esperado = {
        ref: f"Connector_PinSocket_2.54mm:PinSocket_1x{len(p):02d}_P2.54mm_Vertical"
        for ref, p in pinagens_do_pecas_md().items()
    }
    assert componentes == esperado


def test_redes_da_netlist_batem_com_a_parte_3(netlist):
    _, _, redes = netlist
    pinagens = pinagens_do_pecas_md()
    por_nome = {
        rede: {(ref, pinagens[ref][int(num) - 1]) for ref, num in pinos}
        for rede, pinos in redes.items()
    }
    assert por_nome == LIGACOES_ESPERADAS


def test_todo_pino_esta_numa_rede_ou_nao_usado(netlist):
    _, _, redes = netlist
    pinagens = pinagens_do_pecas_md()
    ligados = [(ref, pinagens[ref][int(n) - 1]) for pinos in redes.values() for ref, n in pinos]
    assert len(ligados) == len(set(ligados)), "pino ligado a mais de uma rede"
    todos = {(ref, p) for ref, ps in pinagens.items() for p in ps}
    assert set(ligados) | NAO_USADOS_ESPERADOS == todos
    assert not set(ligados) & NAO_USADOS_ESPERADOS
    contagem = {}
    for ref, _ in ligados:
        contagem[MODULO[ref]] = contagem.get(MODULO[ref], 0) + 1
    assert contagem == LIGADOS_POR_MODULO


def test_netlist_reprodutivel(tmp_path):
    textos = []
    for i in range(2):
        arquivo = tmp_path / f"n{i}.net"
        circuito.montar().generate_netlist(file_=str(arquivo))
        texto = arquivo.read_text(encoding="utf-8")
        textos.append(re.sub(r'\(date "[^"]*"\)', "", texto))
    assert textos[0] == textos[1]
