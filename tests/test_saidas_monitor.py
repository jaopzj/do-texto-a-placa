"""Testes do roteamento e dos arquivos da fábrica da placa de referência (Marco 2, Parte 7).

Um fixture monta a cadeia inteira uma vez num diretório temporário (netlist, placa
posicionada, roteamento no Freerouting, DRC e exportações do kicad-cli), e os testes
conferem o resultado com ``scripts/verificar_saidas.py``. Os testes negativos estragam
uma cópia das saídas e conferem que o verificador acusa o problema. Rodam dentro do
container (``make testes``).
"""

import csv
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path

import pcbnew
import pytest

RAIZ = Path(__file__).resolve().parents[1]
MONITOR = RAIZ / "placas" / "monitor-umidade"
MODELO = MONITOR / "modelo" / "modelo.kicad_pcb"
POSICOES = MONITOR / "posicoes.yaml"
CAMADAS = "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts"

sys.path.insert(0, str(RAIZ / "scripts"))
sys.path.insert(0, str(RAIZ / "scripts" / "spike"))
import aplicar_posicoes  # noqa: E402
import bom  # noqa: E402
import gerar_placa  # noqa: E402
import round_trip_freerouting  # noqa: E402
import verificar_placa  # noqa: E402
import verificar_saidas  # noqa: E402
from netlist_para_pcb import montar_netlist  # noqa: E402


def _kicad_cli(*args):
    return subprocess.run(["kicad-cli", *args], capture_output=True, text=True)


@pytest.fixture(scope="module")
def saidas(tmp_path_factory):
    pasta = tmp_path_factory.mktemp("placa")
    spec = importlib.util.spec_from_file_location("circuito_monitor", MONITOR / "circuito.py")
    circuito = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(circuito)
    netlist = pasta / "monitor-umidade.net"
    circuito.montar().generate_netlist(file_=str(netlist))

    posicionada = pasta / "monitor-umidade.kicad_pcb"
    roteada = pasta / "monitor-umidade_roteada.kicad_pcb"
    gerar_placa.gerar(str(netlist), str(MODELO), str(posicionada))
    assert aplicar_posicoes.main([str(posicionada), str(POSICOES), str(posicionada)]) == 0
    assert round_trip_freerouting.main(["-i", str(posicionada), "-o", str(roteada)]) == 0

    drc = pasta / "drc.json"
    resultado = _kicad_cli("pcb", "drc", "--severity-all", "--exit-code-violations",
                           "--format", "json", "-o", str(drc), str(roteada))
    fabrica = pasta / "fabrica"
    fabrica.mkdir()
    for args in (
        ("pcb", "export", "gerbers", "--layers", CAMADAS, "-o", f"{fabrica}/", str(roteada)),
        ("pcb", "export", "drill", "-o", f"{fabrica}/", str(roteada)),
        ("pcb", "export", "pos", "--format", "csv", "--units", "mm",
         "-o", str(fabrica / "posicoes.csv"), str(roteada)),
    ):
        assert _kicad_cli(*args).returncode == 0, args
    assert bom.main([str(netlist), str(fabrica / "bom.csv")]) == 0
    return {"pasta": pasta, "netlist": netlist, "roteada": roteada, "drc": drc,
            "drc_saida": resultado.returncode, "fabrica": fabrica}


def _problemas(saidas, drc=None, fabrica=None):
    return verificar_saidas.verificar(
        pcbnew.LoadBoard(str(saidas["roteada"])),
        montar_netlist(str(saidas["netlist"])),
        aplicar_posicoes.ler_posicoes(str(POSICOES)),
        str(drc or saidas["drc"]),
        str(fabrica or saidas["fabrica"]),
    )


def _copia_da_fabrica(saidas, tmp_path):
    destino = tmp_path / "fabrica"
    shutil.copytree(saidas["fabrica"], destino)
    return destino


def test_drc_da_placa_roteada_sem_violacoes_nem_pendencias(saidas):
    assert saidas["drc_saida"] == 0
    drc = json.loads(saidas["drc"].read_text(encoding="utf-8"))
    assert drc["violations"] == []
    assert drc["unconnected_items"] == []


def test_placa_roteada_tem_trilhas_e_preserva_netlist_e_posicoes(saidas):
    placa = pcbnew.LoadBoard(str(saidas["roteada"]))
    assert sum(1 for t in placa.GetTracks() if t.GetClass() == "PCB_TRACK") > 0
    problemas = verificar_placa.verificar(
        placa, montar_netlist(str(saidas["netlist"])), aplicar_posicoes.ler_posicoes(str(POSICOES))
    )
    assert problemas == []


def test_trilhas_so_ligam_pads_da_mesma_rede(saidas):
    placa = pcbnew.LoadBoard(str(saidas["roteada"]))
    redes_com_pads = {p.GetNetname() for fp in placa.GetFootprints() for p in fp.Pads() if p.GetNetname()}
    redes_das_trilhas = {t.GetNetname() for t in placa.GetTracks()}
    assert "" not in redes_das_trilhas
    assert redes_das_trilhas == redes_com_pads


def test_saidas_completas_e_coerentes(saidas):
    assert _problemas(saidas) == []


def test_bom_agrupa_os_conectores_por_tipo(saidas):
    with open(saidas["fabrica"] / "bom.csv", encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    assert [(l["Referencias"], l["Quantidade"]) for l in linhas] == [
        ("J1 J2", "2"), ("J3 J4", "2"), ("J5 J6", "2")
    ]
    assert linhas[0]["Tipo de conector"].endswith("PinSocket_1x15_P2.54mm_Vertical")


def test_verificador_acusa_violacao_no_drc(saidas, tmp_path):
    drc = json.loads(saidas["drc"].read_text(encoding="utf-8"))
    drc["unconnected_items"] = [{"description": "Missing connection between items"}]
    arquivo = tmp_path / "drc.json"
    arquivo.write_text(json.dumps(drc), encoding="utf-8")
    assert any("unconnected_items" in p for p in _problemas(saidas, drc=arquivo))


def test_verificador_acusa_gerber_faltando(saidas, tmp_path):
    fabrica = _copia_da_fabrica(saidas, tmp_path)
    next(fabrica.glob("*-B_Cu.gbl")).unlink()
    assert "Gerber de B.Cu (Copper,L2,Bot): 0 arquivo(s), esperado 1" in _problemas(saidas, fabrica=fabrica)


def test_verificador_acusa_furo_faltando(saidas, tmp_path):
    fabrica = _copia_da_fabrica(saidas, tmp_path)
    drl = next(fabrica.glob("*.drl"))
    linhas = drl.read_text(encoding="utf-8").splitlines()
    primeiro_furo = next(i for i, l in enumerate(linhas) if l.startswith("X60.0Y-60.0"))
    del linhas[primeiro_furo]
    drl.write_text("\n".join(linhas) + "\n", encoding="utf-8")
    assert any("furo(s) de componente" in p for p in _problemas(saidas, fabrica=fabrica))


def test_verificador_acusa_bom_incompleta(saidas, tmp_path):
    fabrica = _copia_da_fabrica(saidas, tmp_path)
    arquivo = fabrica / "bom.csv"
    linhas = arquivo.read_text(encoding="utf-8").splitlines()
    arquivo.write_text("\n".join(linhas[:-1]) + "\n", encoding="utf-8")
    assert any(p.startswith("BOM: referências") for p in _problemas(saidas, fabrica=fabrica))
