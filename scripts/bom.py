#!/usr/bin/env python3
"""Lista de materiais (BOM) a partir da netlist (Marco 2, Parte 7, passo 4).

O KiCad tira a BOM do esquemático, que este projeto não tem (o circuito está em
código). Este script lê a netlist e escreve um CSV com uma linha por tipo de conector:
referências, tipo de conector (footprint), quantidade e o módulo que encaixa em cada
referência.

Uso, dentro do container:
    python scripts/bom.py <netlist.net> <bom.csv>
"""

import csv
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "spike"))
from netlist_para_pcb import montar_netlist  # noqa: E402

COLUNAS = ["Referencias", "Tipo de conector", "Quantidade", "Modulos"]


def _chave_ref(ref):
    """Ordena J2 antes de J10."""
    letras = ref.rstrip("0123456789")
    return (letras, int(ref[len(letras):] or 0))


def linhas_bom(netlist):
    """Agrupa as peças da netlist por footprint e devolve as linhas da BOM."""
    grupos = defaultdict(list)
    for parte in netlist.parts:
        grupos[parte.footprint].append(parte)
    linhas = []
    for footprint, partes in grupos.items():
        partes.sort(key=lambda p: _chave_ref(p.ref))
        linhas.append({
            "Referencias": " ".join(p.ref for p in partes),
            "Tipo de conector": footprint,
            "Quantidade": len(partes),
            "Modulos": "; ".join(f"{p.ref}: {p.value}" for p in partes),
        })
    linhas.sort(key=lambda l: _chave_ref(l["Referencias"].split()[0]))
    return linhas


def escrever_bom(netlist, caminho):
    linhas = linhas_bom(netlist)
    with open(caminho, "w", encoding="utf-8", newline="") as f:
        escritor = csv.DictWriter(f, fieldnames=COLUNAS)
        escritor.writeheader()
        escritor.writerows(linhas)
    return linhas


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 2:
        raise SystemExit(__doc__)
    linhas = escrever_bom(montar_netlist(argv[0]), argv[1])
    total = sum(l["Quantidade"] for l in linhas)
    print(f"BOM em '{argv[1]}': {len(linhas)} tipo(s) de conector, {total} peça(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
