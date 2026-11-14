"""Confere se o símbolo e o footprint de um componente existem nas bibliotecas do KiCad.

A base aponta para as bibliotecas oficiais do KiCad, sem copiá-las (CLAUDE.md, seção
"Base de componentes"). Este módulo só lê as pastas das bibliotecas; ele não chama o
KiCad. As pastas vêm das mesmas variáveis de ambiente que o Makefile passa ao container
(``KICAD10_SYMBOL_DIR`` e ``KICAD10_FOOTPRINT_DIR``).
"""
import os
import re
from pathlib import Path

from .modelo import Componente


def pastas_do_ambiente() -> tuple[Path, Path] | None:
    """(símbolos, footprints) do ambiente, ou ``None`` se as bibliotecas não estiverem lá."""
    simbolos = os.environ.get("KICAD10_SYMBOL_DIR")
    footprints = os.environ.get("KICAD10_FOOTPRINT_DIR")
    if not simbolos or not footprints:
        return None
    simbolos, footprints = Path(simbolos), Path(footprints)
    if not simbolos.is_dir() or not footprints.is_dir():
        return None
    return simbolos, footprints


def simbolo_existe(referencia: str, pasta_simbolos: Path) -> bool:
    biblioteca, nome = referencia.split(":", 1)
    arquivo = pasta_simbolos / f"{biblioteca}.kicad_sym"
    if arquivo.is_file():
        texto = arquivo.read_text(encoding="utf-8")
        return re.search(rf'\(symbol\s+"{re.escape(nome)}"', texto) is not None
    # Formato de biblioteca em pasta (um arquivo por símbolo)
    return (pasta_simbolos / f"{biblioteca}.kicad_symdir" / f"{nome}.kicad_sym").is_file()


def footprint_existe(referencia: str, pasta_footprints: Path) -> bool:
    biblioteca, nome = referencia.split(":", 1)
    return (pasta_footprints / f"{biblioteca}.pretty" / f"{nome}.kicad_mod").is_file()


def referencias_ausentes(comp: Componente, pasta_simbolos: Path,
                         pasta_footprints: Path) -> list[str]:
    """Lista legível das referências do componente que não existem nas bibliotecas."""
    ausentes = []
    if not simbolo_existe(comp.kicad_simbolo, pasta_simbolos):
        ausentes.append(f"{comp.id}: símbolo {comp.kicad_simbolo!r} não existe em {pasta_simbolos}")
    if not footprint_existe(comp.kicad_footprint, pasta_footprints):
        ausentes.append(
            f"{comp.id}: footprint {comp.kicad_footprint!r} não existe em {pasta_footprints}")
    return ausentes
