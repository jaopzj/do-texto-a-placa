"""Da netlist do agente ao DRC da placa roteada (Marco 5, Parte 4; ADR-018).

O laço de correção precisa do DRC depois de rotear. Este módulo leva o estado do agente pelo
mesmo caminho do ``make placa`` (Marco 2), passo a passo, e devolve as violações:

1. netlist pelo SKiDL (``gerar_netlist``);
2. placa a partir da placa-modelo (``scripts/gerar_placa.py``);
3. posições (``scripts/aplicar_posicoes.py``), com o posicionamento da placa de referência;
4. roteamento no Freerouting (``scripts/spike/round_trip_freerouting.py``);
5. DRC em JSON (``kicad-cli pcb drc``).

**Posições.** O ``posicoes.yaml`` da placa de referência é por referência (J1...J6), e as
referências do agente saem na ordem em que ele selecionou as peças. O que liga as duas é o
``value`` de cada conector, que é o mesmo nas duas netlists (``esp32-devkitc-v4 J2``,
``display-lcd-1602-i2c``...): a posição de um conector do agente é a do conector do
``gabarito.net`` com o mesmo ``value``. Um conector sem par no gabarito (uma peça que a
placa de referência não tem, ou duas do mesmo tipo) não tem posição, e a placa não é feita:
o código não inventa onde ela fica.

Só roda dentro do container (SKiDL, pcbnew, Freerouting e kicad-cli). Os comandos passam por
``executar``, para os testes trocarem por um falso.
"""
import json
import re
import subprocess
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import yaml

from .componentes.modelo import Componente
from .gerar_netlist import Plano, planejar

RAIZ = Path(__file__).resolve().parents[1]
REFERENCIA = RAIZ / "placas" / "monitor-umidade"
GABARITO = REFERENCIA / "gabarito.net"
POSICOES = REFERENCIA / "posicoes.yaml"
MODELO = REFERENCIA / "modelo" / "modelo.kicad_pcb"


class ErroPlaca(RuntimeError):
    """Um passo do caminho da placa falhou; não há DRC para mostrar."""

    def __init__(self, etapa: str, mensagem: str):
        self.etapa, self.mensagem = etapa, mensagem
        super().__init__(f"{etapa}: {mensagem}")


@dataclass(frozen=True)
class ItemDRC:
    """Uma violação do DRC, ou uma ligação que ficou sem trilha."""
    tipo: str                    # o "type" do kicad-cli (clearance, unconnected_items...)
    severidade: str
    descricao: str
    itens: tuple[str, ...] = ()  # as descrições dos itens envolvidos (pads, trilhas)


@dataclass(frozen=True)
class ResultadoPlaca:
    drc: tuple[ItemDRC, ...]
    placa: Path                  # a placa roteada
    relatorio: Path              # o JSON do DRC
    netlist: Path | None = None  # a netlist do agente, que a fábrica usa (BOM e conferência)
    posicoes: Path | None = None  # as posições aplicadas na placa


def ler_drc(dados: dict) -> list[ItemDRC]:
    """As violações e as ligações pendentes de um relatório JSON do ``kicad-cli pcb drc``."""
    itens = []
    for chave in ("violations", "unconnected_items"):
        lista = dados.get(chave)
        if not isinstance(lista, list):
            raise ErroPlaca("drc", f"o relatório não tem a lista {chave!r}")
        for v in lista:
            itens.append(ItemDRC(
                tipo=str(v.get("type", chave)), severidade=str(v.get("severity", "error")),
                descricao=str(v.get("description", "?")),
                itens=tuple(str(i.get("description", "?")) for i in v.get("items", []))))
    return itens


def _valores_do_gabarito(texto: str) -> dict[str, str]:
    """``value`` -> referência, de cada componente de uma netlist KiCad."""
    pares = re.findall(r'\(comp\s+\(ref\s+"([^"]+)"\)\s+\(value\s+"([^"]*)"\)', texto)
    valores: dict[str, str] = {}
    for ref, valor in pares:
        if valor in valores:
            raise ErroPlaca("posicoes", f"o gabarito tem dois conectores {valor!r}")
        valores[valor] = ref
    return valores


def posicoes_do_agente(plano: Plano, gabarito: str, posicoes: dict) -> dict[str, dict]:
    """As posições dos conectores do agente, pelas da placa de referência (pelo ``value``)."""
    por_valor = _valores_do_gabarito(gabarito)
    resultado, faltam, vistos = {}, [], set()
    for con in plano.conectores:
        if con.valor in vistos:
            faltam.append(f"{con.ref} ({con.valor}): a placa de referência tem um só")
            continue
        vistos.add(con.valor)
        ref_gabarito = por_valor.get(con.valor)
        if ref_gabarito is None or ref_gabarito not in posicoes:
            faltam.append(f"{con.ref} ({con.valor}): a placa de referência não tem esse "
                          "conector")
            continue
        resultado[con.ref] = dict(posicoes[ref_gabarito])
    if faltam:
        raise ErroPlaca("posicoes", "sem posição para " + "; ".join(faltam))
    return resultado


def caminho_legivel(caminho: Path) -> str:
    """O caminho a partir da raiz do repositório, quando ele está dentro dela."""
    try:
        return str(Path(caminho).resolve().relative_to(RAIZ))
    except ValueError:
        return str(caminho)


Executar = Callable[[list[str]], subprocess.CompletedProcess]


def executar_no_repositorio(comando: list[str]) -> subprocess.CompletedProcess:
    """Roda um comando na raiz do repositório, com a saída capturada."""
    return subprocess.run(comando, cwd=RAIZ, capture_output=True, text=True)


def resumo_da_falha(feito: subprocess.CompletedProcess) -> str:
    """As últimas linhas da saída de um comando que falhou, numa linha só."""
    saida = ((feito.stderr or "") + (feito.stdout or "")).strip().splitlines()
    return " / ".join(saida[-5:]) or f"saiu com {feito.returncode}"


def conferir_placa(estado: dict, pasta: Path, base: dict[str, Componente],
                   executar: Executar = executar_no_repositorio,
                   gerar: Callable[[dict, Path, dict], object] | None = None
                   ) -> ResultadoPlaca:
    """Netlist, placa, posições, roteamento e DRC do ``estado``, com os arquivos em ``pasta``.
    Levanta ``ErroPlaca`` se um passo falhar."""
    if gerar is None:
        from .gerar_netlist import gerar_netlist as gerar
    pasta = Path(pasta)
    pasta.mkdir(parents=True, exist_ok=True)
    plano = planejar(estado, base)
    posicoes = posicoes_do_agente(plano, GABARITO.read_text(encoding="utf-8"),
                                  yaml.safe_load(POSICOES.read_text(encoding="utf-8")))
    arquivo_posicoes = pasta / "posicoes.yaml"
    arquivo_posicoes.write_text(yaml.safe_dump(posicoes, sort_keys=True), encoding="utf-8")
    netlist, placa = pasta / "agente.net", pasta / "agente.kicad_pcb"
    roteada, relatorio = pasta / "agente_roteada.kicad_pcb", pasta / "drc.json"
    try:
        gerar(estado, netlist, base)
    except Exception as e:                      # o SKiDL falha com exceções próprias
        raise ErroPlaca("netlist", f"{type(e).__name__}: {e}") from None
    passos = [
        ("placa", [sys.executable, "scripts/gerar_placa.py", "-n", str(netlist), "-m",
                   str(MODELO), "-o", str(placa)]),
        ("posicoes", [sys.executable, "scripts/aplicar_posicoes.py", str(placa),
                      str(arquivo_posicoes), str(placa)]),
        ("roteamento", [sys.executable, "scripts/spike/round_trip_freerouting.py", "-i",
                        str(placa), "-o", str(roteada)]),
        ("drc", ["kicad-cli", "pcb", "drc", "--severity-all", "--format", "json", "-o",
                 str(relatorio), str(roteada)]),
    ]
    for etapa, comando in passos:
        feito = executar(comando)
        if feito.returncode != 0:
            raise ErroPlaca(etapa, resumo_da_falha(feito))
    try:
        dados = json.loads(relatorio.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise ErroPlaca("drc", f"não consegui ler {relatorio}: {e}") from None
    return ResultadoPlaca(tuple(ler_drc(dados)), roteada, relatorio, netlist,
                          arquivo_posicoes)
