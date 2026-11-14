"""Testes da netlist em SKiDL da placa de referência (Marco 2, Parte 4; Marco 3, Parte 6).

A tabela esperada abaixo foi transcrita à mão do ``pecas.md`` (Parte 3), de forma
independente do ``circuito.py``. A pinagem física é lida direto do ``pecas.md`` e conferida
contra a base de componentes, de onde o ``circuito.py`` tira símbolo, footprint e nomes dos
pinos. Assim, os testes conferem a cadeia inteira: base e pecas.md -> circuito.py -> netlist
gerada.
"""

import importlib.util
import re
from pathlib import Path

import pytest
from skidl.logger import erc_logger

PASTA = Path(__file__).resolve().parents[1] / "placas" / "monitor-umidade"
BASE = Path(__file__).resolve().parents[1] / "componentes"


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
    # Ordem dos blocos no pecas.md: ESP32 fileira J2, ESP32 fileira J3, LCD, sensor,
    # conversor HV, conversor LV.
    assert len(linhas) == 6, linhas
    return dict(zip(("J1", "J2", "J3", "J4", "J6", "J5"), linhas))


# Transcrição da tabela 1 da Parte 3 (pecas.md).
LIGACOES_ESPERADAS = {
    "+5V": {("J1", "5V"), ("J3", "VCC"), ("J6", "HV")},
    "+3V3": {("J1", "3V3"), ("J4", "VCC"), ("J5", "LV")},
    "GND": {("J1", "GND"), ("J2", "GND"), ("J3", "GND"), ("J4", "GND"),
            ("J5", "GND"), ("J6", "GND")},
    "SENSOR": {("J4", "AOUT"), ("J1", "IO34")},
    "SDA_3V3": {("J2", "IO21"), ("J5", "LV1")},
    "SCL_3V3": {("J2", "IO22"), ("J5", "LV2")},
    "SDA_5V": {("J6", "HV1"), ("J3", "SDA")},
    "SCL_5V": {("J6", "HV2"), ("J3", "SCL")},
}

# Transcrição da tabela 2 da Parte 3 (pecas.md).
NAO_USADOS_ESPERADOS = {
    ("J1", p) for p in ("EN", "VP", "VN", "IO35", "IO32", "IO33", "IO25", "IO26", "IO27",
                        "IO14", "IO12", "IO13", "D2", "D3", "CMD")
} | {
    ("J2", p) for p in ("IO23", "TX", "RX", "IO19", "IO18", "IO5", "IO17", "IO16", "IO4",
                        "IO0", "IO2", "IO15", "D1", "D0", "CLK")
} | {("J5", "LV3"), ("J5", "LV4"), ("J6", "HV3"), ("J6", "HV4")}

# Contagens da tabela 3 da Parte 3 (pecas.md): pinos ligados por módulo.
LIGADOS_POR_MODULO = {"ESP32": 8, "LCD": 4, "sensor": 3, "conversor": 8}
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
    assert {ref: c[3] for ref, c in circuito.CONECTORES.items()} == pinagens


def _yaml_da_base(id_peca):
    import yaml
    return yaml.safe_load((BASE / f"{id_peca}.yaml").read_text(encoding="utf-8"))


def test_simbolo_footprint_e_pinos_vem_da_base():
    # Lido direto dos YAMLs, sem passar pelo carregador nem pelo circuito.py.
    for ref, (id_peca, nome_conector) in circuito.PECAS.items():
        dados = _yaml_da_base(id_peca)
        nomes = {p["numero"]: p["nome"] for p in dados["pinos"]}
        if nome_conector is None:
            esperado = (dados["kicad_simbolo"], dados["kicad_footprint"],
                        tuple(nomes[p["numero"]] for p in dados["pinos"]))
        else:
            [con] = [c for c in dados["conectores"] if c["nome"] == nome_conector]
            esperado = (con["kicad_simbolo"], con["kicad_footprint"],
                        tuple(nomes[n] for n in con["pinos"]))
        assert circuito.CONECTORES[ref][1:] == esperado, ref


def test_circuito_nao_tem_simbolo_nem_footprint_escrito_no_codigo():
    codigo = (PASTA / "circuito.py").read_text(encoding="utf-8")
    assert "Connector_" not in codigo and "PinSocket" not in codigo and "PinHeader" not in codigo


def test_peca_ausente_da_base_e_apontada(monkeypatch):
    monkeypatch.setitem(circuito.PECAS, "J9", ("peca-que-nao-existe", None))
    with pytest.raises(ValueError, match=r"J9: a peça 'peca-que-nao-existe' não está na base"):
        circuito.conectores_da_base()


def test_conector_inexistente_e_apontado(monkeypatch):
    monkeypatch.setitem(circuito.PECAS, "J1", ("esp32-devkitc-v4", "J9"))
    with pytest.raises(ValueError, match=r"J1: esp32-devkitc-v4 não tem o conector 'J9'"):
        circuito.conectores_da_base()


def test_peca_de_varios_conectores_exige_o_nome(monkeypatch):
    monkeypatch.setitem(circuito.PECAS, "J1", ("esp32-devkitc-v4", None))
    with pytest.raises(ValueError, match=r"J1: esp32-devkitc-v4 tem conectores \['J2', 'J3'\]"):
        circuito.conectores_da_base()


def test_tabelas_do_circuito_batem_com_a_parte_3():
    ligacoes = {rede: set(p) for rede, p in circuito.LIGACOES.items()}
    assert ligacoes == LIGACOES_ESPERADAS
    nao_usados = {(ref, p) for ref, ps in circuito.NAO_USADOS.items() for p in ps}
    assert nao_usados == NAO_USADOS_ESPERADOS


def test_validar_aceita_a_tabela_atual():
    circuito.validar()


def test_validar_recusa_pino_esquecido(monkeypatch):
    sem_lv4 = dict(circuito.NAO_USADOS, J5=("LV3",))
    monkeypatch.setattr(circuito, "NAO_USADOS", sem_lv4)
    with pytest.raises(ValueError, match=r"\('J5', 'LV4'\) \(nº 6\) aparece 0 vez"):
        circuito.validar()


def test_validar_recusa_pino_em_duas_redes(monkeypatch):
    ligacoes = dict(circuito.LIGACOES, SENSOR=(("J4", "AOUT"), ("J1", "5V")))
    monkeypatch.setattr(circuito, "LIGACOES", ligacoes)
    with pytest.raises(ValueError, match=r"\('J1', '5V'\) \(nº 19\) aparece 2 vez"):
        circuito.validar()


def test_validar_recusa_pino_inexistente(monkeypatch):
    ligacoes = dict(circuito.LIGACOES, SENSOR=(("J4", "A0"), ("J1", "IO34")))
    monkeypatch.setattr(circuito, "LIGACOES", ligacoes)
    with pytest.raises(ValueError, match="pino inexistente"):
        circuito.validar()


def test_erc_sem_erros_nem_avisos():
    circuito.montar().ERC()
    assert erc_logger.error.count == 0
    assert erc_logger.warning.count == 0


def test_componentes_e_footprints(netlist):
    _, componentes, _ = netlist
    esperado = {ref: c[2] for ref, c in circuito.CONECTORES.items()}
    assert componentes == esperado
    assert componentes["J1"] == componentes["J2"] == (
        "Connector_PinHeader_2.54mm:PinHeader_1x19_P2.54mm_Vertical")


def test_redes_da_netlist_batem_com_a_parte_3(netlist):
    _, _, redes = netlist
    pinagens = pinagens_do_pecas_md()
    por_nome = {
        rede: {(ref, pinagens[ref][int(num) - 1]) for ref, num in pinos}
        for rede, pinos in redes.items()
    }
    assert por_nome == LIGACOES_ESPERADAS


def test_todo_pino_esta_numa_rede_ou_nao_usado(netlist):
    # Por número de pino, porque um conector pode ter dois pinos com o mesmo nome (GND).
    _, _, redes = netlist
    pinagens = pinagens_do_pecas_md()
    ligados = [(ref, int(n)) for pinos in redes.values() for ref, n in pinos]
    assert len(ligados) == len(set(ligados)), "pino ligado a mais de uma rede"
    nao_usados = {(ref, i + 1) for ref, ps in pinagens.items() for i, p in enumerate(ps)
                  if (ref, p) in NAO_USADOS_ESPERADOS}
    todos = {(ref, i + 1) for ref, ps in pinagens.items() for i in range(len(ps))}
    assert set(ligados) | nao_usados == todos
    assert not set(ligados) & nao_usados
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


def _estrutura(redes):
    """Quais pinos estão ligados entre si, sem olhar os nomes das redes."""
    return {frozenset(pinos) for pinos in redes.values()}


def test_netlist_tem_a_estrutura_do_gabarito(netlist):
    # O gabarito.net é a resposta certa usada nos evals (Marco 4). Nunca alterá-lo
    # para fazer este teste passar: se ele falhar, o circuito.py mudou.
    _, componentes, redes = netlist
    _, componentes_gabarito, redes_gabarito = ler_netlist(PASTA / "gabarito.net")
    assert componentes == componentes_gabarito
    assert _estrutura(redes) == _estrutura(redes_gabarito)
