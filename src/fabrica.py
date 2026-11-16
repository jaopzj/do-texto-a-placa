"""Os arquivos da fábrica a partir da placa roteada do agente (Marco 5, Parte 5; ADR-019).

É o fim do ``make placa`` (Marco 2, Partes 7 e 8), aplicado à placa que o laço de correção
aprovou (``src/drc.py``), em vez da placa de referência:

1. Gerbers das sete camadas de fabricação e o arquivo de job;
2. furação (``.drl``);
3. posições das peças (``posicoes.csv``);
4. BOM (``bom.csv``), pela netlist do agente (``scripts/bom.py``);
5. conferência de tudo (``scripts/verificar_saidas.py``): DRC sem itens, um Gerber por
   camada, um furo por pad e por via, posições e BOM iguais às da netlist.

Se a conferência falhar, os arquivos ficam na pasta para o usuário ver o que saiu, mas o
resultado diz que falhou: nada é apresentado como pronto para a fábrica.

Só roda dentro do container (kicad-cli e pcbnew). Os comandos passam por ``executar``, para
os testes trocarem por um falso.
"""
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .drc import Executar, ResultadoPlaca, executar_no_repositorio, resumo_da_falha

# As mesmas camadas do alvo "placa" do Makefile.
CAMADAS = "F.Cu,B.Cu,F.Mask,B.Mask,F.Silkscreen,B.Silkscreen,Edge.Cuts"


class ErroFabrica(RuntimeError):
    """Um passo da geração dos arquivos da fábrica falhou."""

    def __init__(self, etapa: str, mensagem: str):
        self.etapa, self.mensagem = etapa, mensagem
        super().__init__(f"{etapa}: {mensagem}")


@dataclass(frozen=True)
class ResultadoFabrica:
    pasta: Path
    arquivos: tuple[Path, ...]        # tudo que ficou na pasta, em ordem
    conferencia: str                  # a linha "OK: ..." do verificar_saidas


def comandos(placa: ResultadoPlaca, pasta: Path) -> list[tuple[str, list[str]]]:
    """Os passos, na ordem, cada um com o nome que aparece num erro."""
    if placa.netlist is None or placa.posicoes is None:
        raise ErroFabrica("entrada", "a placa não tem a netlist e as posições do agente")
    roteada, destino = str(placa.placa), str(pasta)
    return [
        ("gerbers", ["kicad-cli", "pcb", "export", "gerbers", "--layers", CAMADAS, "-o",
                     destino + "/", roteada]),
        ("furacao", ["kicad-cli", "pcb", "export", "drill", "-o", destino + "/", roteada]),
        ("posicoes", ["kicad-cli", "pcb", "export", "pos", "--format", "csv", "--units", "mm",
                      "-o", str(pasta / "posicoes.csv"), roteada]),
        ("bom", [sys.executable, "scripts/bom.py", str(placa.netlist),
                 str(pasta / "bom.csv")]),
        ("conferencia", [sys.executable, "scripts/verificar_saidas.py", roteada,
                         str(placa.netlist), str(placa.posicoes), str(placa.relatorio),
                         destino]),
    ]


def gerar_fabrica(placa: ResultadoPlaca, pasta: Path,
                  executar: Executar = executar_no_repositorio) -> ResultadoFabrica:
    """Gera e confere os arquivos da fábrica em ``pasta`` (apagada antes, para nada ficar
    desatualizado). Levanta ``ErroFabrica`` no primeiro passo que falhar."""
    pasta = Path(pasta)
    passos = comandos(placa, pasta)
    if pasta.exists():
        shutil.rmtree(pasta)
    pasta.mkdir(parents=True)
    conferencia = ""
    for etapa, comando in passos:
        feito = executar(comando)
        if feito.returncode != 0:
            raise ErroFabrica(etapa, resumo_da_falha(feito))
        if etapa == "conferencia":
            linhas = (feito.stdout or "").strip().splitlines()
            conferencia = linhas[-1] if linhas else "conferido"
    arquivos = tuple(sorted(p for p in pasta.iterdir() if p.is_file()))
    return ResultadoFabrica(pasta, arquivos, conferencia)
