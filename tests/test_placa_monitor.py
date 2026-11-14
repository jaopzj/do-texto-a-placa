"""Testes da geração e do posicionamento da placa de referência (Marco 2, Parte 6).

Cada teste monta a cadeia inteira num diretório temporário: circuito.py -> netlist ->
placa-modelo + footprints -> posições do YAML. Precisam do pcbnew e do kicad-cli, então
rodam dentro do container (``make testes``).
"""

import copy
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pcbnew
import pytest
import yaml

RAIZ = Path(__file__).resolve().parents[1]
MONITOR = RAIZ / "placas" / "monitor-umidade"
MODELO = MONITOR / "modelo" / "modelo.kicad_pcb"
POSICOES = MONITOR / "posicoes.yaml"

sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "scripts" / "spike"))
import aplicar_posicoes  # noqa: E402
import gerar_placa  # noqa: E402
import verificar_placa  # noqa: E402
from netlist_para_pcb import montar_netlist  # noqa: E402


def _circuito():
    spec = importlib.util.spec_from_file_location("circuito_monitor", MONITOR / "circuito.py")
    modulo = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(modulo)
    return modulo


@pytest.fixture(scope="module")
def netlist(tmp_path_factory):
    caminho = tmp_path_factory.mktemp("netlist") / "monitor-umidade.net"
    _circuito().montar().generate_netlist(file_=str(caminho))
    return caminho


def _gerar(netlist, pasta, posicoes=None):
    """Gera a placa posicionada em ``pasta`` e devolve o caminho do .kicad_pcb."""
    placa = pasta / "monitor-umidade.kicad_pcb"
    gerar_placa.gerar(str(netlist), str(MODELO), str(placa))
    arquivo_posicoes = POSICOES
    if posicoes is not None:
        arquivo_posicoes = pasta / "posicoes.yaml"
        arquivo_posicoes.write_text(yaml.safe_dump(posicoes), encoding="utf-8")
    assert aplicar_posicoes.main([str(placa), str(arquivo_posicoes), str(placa)]) == 0
    return placa, arquivo_posicoes


def _problemas(placa, netlist, arquivo_posicoes):
    return verificar_placa.verificar(
        pcbnew.LoadBoard(str(placa)),
        montar_netlist(str(netlist)),
        aplicar_posicoes.ler_posicoes(str(arquivo_posicoes)),
    )


def _posicoes():
    return aplicar_posicoes.ler_posicoes(str(POSICOES))


def test_placa_atual_passa_em_todas_as_verificacoes(netlist, tmp_path):
    placa, arquivo_posicoes = _gerar(netlist, tmp_path)
    assert _problemas(placa, netlist, arquivo_posicoes) == []


def test_placa_tem_os_seis_conectores_da_netlist(netlist, tmp_path):
    placa, _ = _gerar(netlist, tmp_path)
    refs = sorted(fp.GetReference() for fp in pcbnew.LoadBoard(str(placa)).GetFootprints())
    assert refs == ["J1", "J2", "J3", "J4", "J5", "J6"]


def test_placa_herda_contorno_e_regras_do_modelo(netlist, tmp_path):
    import json

    placa, _ = _gerar(netlist, tmp_path)
    gerada = pcbnew.LoadBoard(str(placa))
    modelo = pcbnew.LoadBoard(str(MODELO))
    assert gerada.GetBoardEdgesBoundingBox() == modelo.GetBoardEdgesBoundingBox()
    pro_gerado = json.loads(placa.with_suffix(".kicad_pro").read_text(encoding="utf-8"))
    pro_modelo = json.loads(MODELO.with_suffix(".kicad_pro").read_text(encoding="utf-8"))
    assert pro_gerado["board"]["design_settings"] == pro_modelo["board"]["design_settings"]
    assert pro_gerado["net_settings"]["classes"] == pro_modelo["net_settings"]["classes"]


def test_esp32_fileiras_a_25_4_mm(netlist, tmp_path):
    # pecas.md, Parte 2: distância entre as fileiras do ESP32 (estimada), 25,4 mm.
    placa, _ = _gerar(netlist, tmp_path)
    b = pcbnew.LoadBoard(str(placa))
    j1 = b.FindFootprintByReference("J1").GetPosition()
    j2 = b.FindFootprintByReference("J2").GetPosition()
    assert j1.x == j2.x
    assert pcbnew.ToMM(j2.y - j1.y) == pytest.approx(25.4)


def test_geracao_reprodutivel(netlist, tmp_path):
    pastas = [tmp_path / "a", tmp_path / "b"]
    for pasta in pastas:
        pasta.mkdir()
    a, _ = _gerar(netlist, pastas[0])
    b, _ = _gerar(netlist, pastas[1])
    assert a.read_bytes() == b.read_bytes()


def test_drc_sem_violacoes(netlist, tmp_path):
    placa, _ = _gerar(netlist, tmp_path)
    relatorio = tmp_path / "drc.rpt"
    subprocess.run(
        ["kicad-cli", "pcb", "drc", "--severity-all", "-o", str(relatorio), str(placa)],
        check=True, capture_output=True,
    )
    texto = relatorio.read_text(encoding="utf-8")
    assert "** Found 0 DRC violations **" in texto
    assert "** Found 0 Footprint errors **" in texto
    # Antes do roteamento, as únicas pendências são as ligações ainda sem trilha:
    # 23 pads ligados em 8 redes = 23 - 8 = 15 ligações (desde o Marco 3, Parte 6: o
    # ESP32 de 38 pinos tem três GND, e o sensor HW-101 só três pinos).
    assert "** Found 15 unconnected pads **" in texto
    assert set(re.findall(r"^\[(\w+)\]", texto, flags=re.M)) == {"unconnected_items"}


def test_aplicar_recusa_referencia_sem_posicao(netlist, tmp_path):
    placa = tmp_path / "p.kicad_pcb"
    gerar_placa.gerar(str(netlist), str(MODELO), str(placa))
    posicoes = _posicoes()
    del posicoes["J6"]
    with pytest.raises(ValueError, match=r"sem posição: \['J6'\]"):
        aplicar_posicoes.aplicar(pcbnew.LoadBoard(str(placa)), posicoes)


def test_aplicar_recusa_posicao_sem_peca(netlist, tmp_path):
    placa = tmp_path / "p.kicad_pcb"
    gerar_placa.gerar(str(netlist), str(MODELO), str(placa))
    posicoes = dict(_posicoes(), J9={"x": 70, "y": 70, "rotacao": 0})
    with pytest.raises(ValueError, match=r"sem peça na placa: \['J9'\]"):
        aplicar_posicoes.aplicar(pcbnew.LoadBoard(str(placa)), posicoes)


def test_ler_posicoes_recusa_campo_errado(tmp_path):
    arquivo = tmp_path / "posicoes.yaml"
    arquivo.write_text("J1: { x: 60, y: 60, rot: 90 }\n", encoding="utf-8")
    with pytest.raises(ValueError, match="J1: precisa ter exatamente"):
        aplicar_posicoes.ler_posicoes(str(arquivo))


def test_verificar_detecta_peca_fora_do_contorno(netlist, tmp_path):
    posicoes = _posicoes()
    posicoes["J6"] = {"x": 152.0, "y": 60.0, "rotacao": 0}
    placa, arquivo = _gerar(netlist, tmp_path, posicoes)
    assert any("J6: courtyard" in p and "sai do contorno" in p for p in _problemas(placa, netlist, arquivo))


def test_verificar_detecta_sobreposicao(netlist, tmp_path):
    posicoes = _posicoes()
    posicoes["J4"] = copy.deepcopy(posicoes["J3"])
    placa, arquivo = _gerar(netlist, tmp_path, posicoes)
    assert "courtyards de J3 e J4 se sobrepõem" in _problemas(placa, netlist, arquivo)


def test_verificar_detecta_rede_trocada(netlist, tmp_path):
    placa, arquivo = _gerar(netlist, tmp_path)
    b = pcbnew.LoadBoard(str(placa))
    # Pad 3 do J4 é o AOUT do sensor HW-101, na rede SENSOR.
    pad = next(p for p in b.FindFootprintByReference("J4").Pads() if p.GetNumber() == "3")
    pad.SetNet(b.FindNet("GND"))
    problemas = verificar_placa.verificar(
        b, montar_netlist(str(netlist)), aplicar_posicoes.ler_posicoes(str(arquivo))
    )
    assert "pad ('J4', '3'): rede 'GND', netlist pede 'SENSOR'" in problemas
