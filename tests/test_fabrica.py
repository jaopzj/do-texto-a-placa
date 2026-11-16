"""Testes da geração dos arquivos da fábrica (ADR-019), com os comandos falsos.

O caminho de verdade (kicad-cli e pcbnew) está no teste de ponta a ponta de
``test_projeto.py``, que só roda dentro do container.
"""
import subprocess
from pathlib import Path

import pytest

from src.drc import ResultadoPlaca
from src.fabrica import CAMADAS, ErroFabrica, comandos, gerar_fabrica


def _placa(tmp_path) -> ResultadoPlaca:
    pasta = tmp_path / "placa"
    return ResultadoPlaca((), pasta / "agente_roteada.kicad_pcb", pasta / "drc.json",
                          pasta / "agente.net", pasta / "posicoes.yaml")


class Comandos:
    """Grava cada comando; o de um passo escolhido falha."""

    def __init__(self, falha: str | None = None, pasta: Path | None = None):
        self.falha, self.pasta, self.feitos = falha, pasta, []

    def __call__(self, comando):
        self.feitos.append(comando)
        if self.falha and self.falha in " ".join(comando):
            return subprocess.CompletedProcess(comando, 1, "", "linha 1\nERRO: deu ruim")
        if "export" in comando and "gerbers" in comando:
            (self.pasta / "placa-F_Cu.gbr").write_text("G04*\nM02*\n", encoding="utf-8")
        saida = "OK: DRC sem violações\n" if "verificar_saidas.py" in " ".join(comando) else ""
        return subprocess.CompletedProcess(comando, 0, saida, "")


def test_passos_na_ordem_do_make_placa(tmp_path):
    passos = comandos(_placa(tmp_path), tmp_path / "fabrica")
    assert [e for e, _ in passos] == ["gerbers", "furacao", "posicoes", "bom", "conferencia"]
    gerbers = dict(passos)["gerbers"]
    assert gerbers[:4] == ["kicad-cli", "pcb", "export", "gerbers"] and CAMADAS in gerbers
    conferencia = dict(passos)["conferencia"]
    assert conferencia[1] == "scripts/verificar_saidas.py"
    # placa roteada, netlist, posições, DRC e pasta, na ordem do script.
    assert [Path(a).name for a in conferencia[2:]] == [
        "agente_roteada.kicad_pcb", "agente.net", "posicoes.yaml", "drc.json", "fabrica"]


def test_gera_e_devolve_os_arquivos_e_a_conferencia(tmp_path):
    destino = tmp_path / "fabrica"
    executar = Comandos(pasta=destino)
    r = gerar_fabrica(_placa(tmp_path), destino, executar)
    assert len(executar.feitos) == 5
    assert [a.name for a in r.arquivos] == ["placa-F_Cu.gbr"]
    assert r.conferencia == "OK: DRC sem violações"


def test_apaga_arquivos_de_uma_execucao_anterior(tmp_path):
    destino = tmp_path / "fabrica"
    destino.mkdir()
    (destino / "velho.gbr").write_text("x", encoding="utf-8")
    r = gerar_fabrica(_placa(tmp_path), destino, Comandos(pasta=destino))
    assert not (destino / "velho.gbr").exists()
    assert [a.name for a in r.arquivos] == ["placa-F_Cu.gbr"]


@pytest.mark.parametrize("falha,etapa", [("gerbers", "gerbers"), ("drill", "furacao"),
                                         ("bom.py", "bom"), ("verificar_saidas", "conferencia")])
def test_passo_que_falha_para_com_o_erro(tmp_path, falha, etapa):
    destino = tmp_path / "fabrica"
    with pytest.raises(ErroFabrica) as erro:
        gerar_fabrica(_placa(tmp_path), destino, Comandos(falha, destino))
    assert erro.value.etapa == etapa and "ERRO: deu ruim" in erro.value.mensagem


def test_placa_sem_netlist_nao_vai_para_a_fabrica(tmp_path):
    placa = ResultadoPlaca((), tmp_path / "p.kicad_pcb", tmp_path / "drc.json")
    with pytest.raises(ErroFabrica, match="netlist"):
        gerar_fabrica(placa, tmp_path / "fabrica", Comandos())
    assert not (tmp_path / "fabrica").exists()
