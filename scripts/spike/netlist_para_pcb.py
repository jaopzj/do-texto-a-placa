#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
netlist_para_pcb.py - Converte uma netlist KiCad em um .kicad_pcb com os
footprints de cada componente colocados (issue M1-2 do Marco 1).

Roda HEADLESS (sem GUI), dentro do container Docker do projeto. Exemplos:

    # via Makefile (recomendado)
    make pcb

    # direto no container
    docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp \
        -v "$PWD":/projeto -w /projeto do-texto-a-placa \
        python scripts/spike/netlist_para_pcb.py

    # escolhendo entrada/saida
    python scripts/spike/netlist_para_pcb.py \
        -i placas/teste/teste/teste.net -o placas/teste/teste/teste.kicad_pcb

CAMINHO USADO: **A = kinet2pcb** (ratificado no ADR-003; ver docs/issues/marco-1.md).
O `kicad-cli` 10 NAO cria placa a partir de netlist, entao usamos a engine do
kinet2pcb (que por baixo usa `pcbnew` para montar a BOARD e `hierplace` para
posicionar os footprints sem sobreposicao). O Caminho B (`kiutils`) nao foi
necessario.

POR QUE NAO CHAMAMOS O CLI `kinet2pcb` DIRETO:
O parser de netlist embutido no kinet2pcb 1.1.4 (`parse_netlist`, que usa
`simp_sexp.search('value')`) quebra na netlist exportada pelo KiCad 10 porque
o `search` casa TODOS os `(value ...)` aninhados (dos blocos `(property ...)` e
`(field ...)`), e `.value` entao falha com:

    ValueError: Sexp isn't in a form that permits extracting a single value.

A funcao `kinet2pcb.kinet2pcb()`, porem, aceita um objeto netlist ja montado.
Este script faz um parse ROBUSTO (apenas os filhos diretos de cada `(comp ...)`
e de cada `(net ...)`) e entrega o objeto pronto para a engine. Assim mantemos
o Caminho A, apenas contornando o bug do parser embutido.

RESOLUCAO DE FOOTPRINTS NO CONTAINER:
Passamos `--libraries /usr/share/kicad/footprints` (todas as libs `.pretty` da
imagem). O kinet2pcb registra cada `.pretty` usando o nome do diretorio como
"nickname" (ex.: `LED_THT`, `Resistor_SMD`), que e exatamente o prefixo usado no
campo `(footprint "LibNick:Nome")` da netlist. Isso dispensa configurar
`fp-lib-table`/`KICAD*_SYMBOL_DIR` (ver placas/teste/README.md, secao 3).
"""

import argparse
import os
import sys

import simp_sexp

# A engine (pcbnew + hierplace) e os containers de dados vem do proprio kinet2pcb.
# O pacote reexporta tudo via `from .kinet2pcb import *`, entao a FUNCAO
# k2p.kinet2pcb() e as classes k2p.NetlistPart/Pin/Net ficam no mesmo namespace.
import kinet2pcb as _k2p


# Padroes do spike. A netlist e a fonte unica de verdade fixada na M1-1; a placa
# e gerada ao lado dela, dentro do projeto KiCad `teste/teste/`.
NETLIST_PADRAO = "placas/teste/teste/teste.net"
PCB_PADRAO = "placas/teste/teste/teste.kicad_pcb"
LIBS_PADRAO = "/usr/share/kicad/footprints"


def _filhos(node):
    """Itera os filhos diretos de um no s-expression (listas cujo [0] e a tag)."""
    for el in node:
        if isinstance(el, list) and el:
            yield el


def _valor_direto(node, tag):
    """Retorna o escalar do PRIMEIRO filho direto `(tag valor)`, ou None.

    Diferente de `simp_sexp.search(tag)`, olha SO os filhos diretos - e por isso
    nao confunde o `(value ...)` do componente com os `(value ...)` aninhados em
    `(property ...)`/`(field ...)`, que e o bug que derruba o CLI do kinet2pcb.
    """
    for filho in _filhos(node):
        if filho[0] == tag and len(filho) > 1 and not isinstance(filho[1], list):
            return filho[1]
    return None


def montar_netlist(caminho_netlist):
    """Le a netlist KiCad e devolve um objeto no formato esperado por kinet2pcb().

    O objeto tem `.parts` (cada um com .ref/.value/.footprint/.sheetpath) e
    `.nets` (cada um com .name/.pins, e cada pin com .ref/.num).
    """
    with open(caminho_netlist, "r", encoding="utf-8") as f:
        sexp = simp_sexp.Sexp(f.read())

    class _Netlist:
        def __init__(self):
            self.parts = []
            self.nets = []

    netlist = _Netlist()

    # --- Componentes -----------------------------------------------------
    for comp in sexp.search("export/components/comp"):
        ref = _valor_direto(comp, "ref")
        footprint = _valor_direto(comp, "footprint")
        value = _valor_direto(comp, "value")

        # Sem ref ou footprint nao da para colocar o componente na placa.
        if not ref or not footprint:
            continue
        if ":" not in footprint:
            raise SystemExit(
                "ERRO: componente '{}' tem footprint '{}' sem o formato "
                "'Biblioteca:Nome'.".format(ref, footprint)
            )

        netlist.parts.append(_k2p.NetlistPart(ref, value or "", footprint))

    if not netlist.parts:
        raise SystemExit(
            "ERRO: nenhum componente com footprint encontrado em "
            "'{}'.".format(caminho_netlist)
        )

    # --- Nets ------------------------------------------------------------
    for net in sexp.search("export/nets/net"):
        nome = _valor_direto(net, "name")
        if not nome:
            continue
        pinos = []
        for node in _filhos(net):
            if node[0] != "node":
                continue
            pino_ref = _valor_direto(node, "ref")
            pino_num = _valor_direto(node, "pin")
            if pino_ref and pino_num is not None:
                pinos.append(_k2p.NetlistPin(pino_ref, str(pino_num)))
        netlist.nets.append(_k2p.NetlistNet(nome, pinos))

    return netlist


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Gera um .kicad_pcb (footprints colocados) a partir de uma "
        "netlist KiCad, headless, via engine do kinet2pcb (Caminho A).",
    )
    parser.add_argument(
        "-i", "--input", default=NETLIST_PADRAO,
        help="Netlist KiCad de entrada (padrao: %(default)s).",
    )
    parser.add_argument(
        "-o", "--output", default=PCB_PADRAO,
        help="Arquivo .kicad_pcb de saida (padrao: %(default)s).",
    )
    parser.add_argument(
        "-l", "--libraries", default=LIBS_PADRAO,
        help="Diretorio com bibliotecas .pretty de footprints "
        "(padrao: %(default)s).",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input):
        raise SystemExit("ERRO: netlist nao encontrada: '{}'".format(args.input))
    if not os.path.isdir(args.libraries):
        raise SystemExit(
            "ERRO: diretorio de bibliotecas nao encontrado: "
            "'{}'".format(args.libraries)
        )

    netlist = montar_netlist(args.input)
    esperado = len(netlist.parts)
    print(
        "Convertendo '{}' -> '{}' ({} componentes) [Caminho A: kinet2pcb]".format(
            args.input, args.output, esperado
        )
    )

    # Garante que a pasta de saida existe.
    destino = os.path.dirname(os.path.abspath(args.output))
    if destino and not os.path.isdir(destino):
        os.makedirs(destino, exist_ok=True)

    # A engine do kinet2pcb aceita o objeto netlist ja montado, o nome do arquivo
    # de saida e a lista de diretorios de bibliotecas.
    _k2p.kinet2pcb(netlist, args.output, [args.libraries])

    # Validacao minima: a placa deve existir e conter um footprint por componente.
    if not os.path.isfile(args.output):
        raise SystemExit(
            "ERRO: a engine nao gerou o arquivo '{}'.".format(args.output)
        )
    with open(args.output, "r", encoding="utf-8") as f:
        conteudo = f.read()
    colocados = conteudo.count("(footprint ")
    if colocados < esperado:
        raise SystemExit(
            "ERRO: esperava {} footprint(s) na placa, mas encontrei {}. "
            "Verifique se as bibliotecas em '{}' contem os footprints da "
            "netlist.".format(esperado, colocados, args.libraries)
        )

    print(
        "OK: '{}' gerado com {} footprint(s) posicionado(s).".format(
            args.output, colocados
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
