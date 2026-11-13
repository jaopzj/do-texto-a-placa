#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
round_trip_freerouting.py - Autorroteamento headless de uma placa KiCad
(issue M1-4 do Marco 1).

Fecha o segundo round-trip do spike: exporta a placa para Specctra DSN, roteia
no Freerouting SEM interface grafica e reimporta o SES, obtendo a placa com
trilhas. Roda dentro do container Docker do projeto. Exemplos:

    # via Makefile (recomendado) - depende de "make pcb" ter gerado a placa
    make rotear

    # direto no container
    docker run --rm --user $(id -u):$(id -g) -e HOME=/tmp \
        -v "$PWD":/projeto -w /projeto do-texto-a-placa \
        python scripts/spike/round_trip_freerouting.py

    # escolhendo entrada/saida
    python scripts/spike/round_trip_freerouting.py \
        -i placas/teste/teste/teste.kicad_pcb \
        -o placas/teste/teste/teste_roteada.kicad_pcb

FLUXO (conforme ADR-003; o kicad-cli 10 NAO exporta DSN/SES, so o pcbnew):
  1. pcbnew.ExportSpecctraDSN(board, teste.dsn)
  2. java -jar freerouting.jar  (headless)  -> teste.ses
  3. pcbnew.ImportSpecctraSES(board, teste.ses)  -> adiciona as trilhas
  4. pcbnew.SaveBoard(placa_roteada)

FREEROUTING 2.2.4 - FLAGS HEADLESS (confirmadas na imagem do projeto):
  java -Djava.awt.headless=true -jar /opt/freerouting/freerouting.jar \
       -de <input.dsn> -do <output.ses> -mp <passes>
  - -de : design input  (arquivo .dsn Specctra)
  - -do : design output (arquivo .ses Specctra)
  - -mp : numero maximo de passes do auto-router
  O proprio -de/-do coloca o Freerouting em modo CLI; a propriedade
  java.awt.headless=true evita qualquer tentativa de abrir janela. O aviso
  "Couldn't get screen resolution ... disable the GUI by setting gui.enabled
  to false" e inofensivo: o roteamento roda normalmente em modo CLI.

NENHUMA JANELA GRAFICA e aberta em nenhum passo.
"""

import argparse
import os
import subprocess
import sys

import pcbnew


# Padroes do spike.
PCB_ENTRADA_PADRAO = "placas/teste/teste/teste.kicad_pcb"
PCB_SAIDA_PADRAO = "placas/teste/teste/teste_roteada.kicad_pcb"
DIR_INTERMEDIARIO = "saida"  # .dsn/.ses sao intermediarios (saida/ e gitignored)
FREEROUTING_JAR = "/opt/freerouting/freerouting.jar"


def _contar(texto, marcador):
    return texto.count(marcador)


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Round-trip headless: KiCad .kicad_pcb -> Specctra DSN -> "
        "Freerouting -> SES -> placa roteada.",
    )
    parser.add_argument(
        "-i", "--input", default=PCB_ENTRADA_PADRAO,
        help="Placa de entrada (.kicad_pcb) sem trilhas (padrao: %(default)s).",
    )
    parser.add_argument(
        "-o", "--output", default=PCB_SAIDA_PADRAO,
        help="Placa de saida (.kicad_pcb) roteada (padrao: %(default)s).",
    )
    parser.add_argument(
        "--passes", type=int, default=10,
        help="Numero maximo de passes do auto-router (padrao: %(default)s).",
    )
    parser.add_argument(
        "--jar", default=FREEROUTING_JAR,
        help="Caminho do freerouting.jar (padrao: %(default)s).",
    )
    args = parser.parse_args(argv)

    if not os.path.isfile(args.input):
        raise SystemExit(
            "ERRO: placa de entrada nao encontrada: '{}'. Rode 'make pcb' "
            "antes (issue M1-2).".format(args.input)
        )
    if not os.path.isfile(args.jar):
        raise SystemExit("ERRO: freerouting.jar nao encontrado: '{}'".format(args.jar))

    os.makedirs(DIR_INTERMEDIARIO, exist_ok=True)
    base = os.path.splitext(os.path.basename(args.input))[0]
    dsn = os.path.join(DIR_INTERMEDIARIO, base + ".dsn")
    ses = os.path.join(DIR_INTERMEDIARIO, base + ".ses")

    # --- 1. Exportar Specctra DSN (pcbnew) -------------------------------
    print("[1/4] Exportando Specctra DSN: '{}' -> '{}'".format(args.input, dsn))
    board = pcbnew.LoadBoard(args.input)
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit("ERRO: ExportSpecctraDSN falhou.")

    # --- 2. Rotear no Freerouting (headless, sem GUI) --------------------
    print("[2/4] Roteando no Freerouting (headless): '{}' -> '{}'".format(dsn, ses))
    cmd = [
        "java", "-Djava.awt.headless=true", "-jar", args.jar,
        "-de", dsn, "-do", ses, "-mp", str(args.passes),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    # O Freerouting loga no stdout/stderr; repassamos para o log do spike.
    saida_fr = (proc.stdout or "") + (proc.stderr or "")
    for linha in saida_fr.splitlines():
        print("    freerouting| " + linha)
    if proc.returncode != 0:
        raise SystemExit(
            "ERRO: Freerouting retornou {}.".format(proc.returncode)
        )
    if not os.path.isfile(ses) or os.path.getsize(ses) == 0:
        raise SystemExit(
            "ERRO: Freerouting nao gerou um .ses valido em '{}'.".format(ses)
        )

    # --- 3. Importar SES de volta (pcbnew) -------------------------------
    print("[3/4] Importando Specctra SES: '{}'".format(ses))
    # Recarrega a placa limpa para aplicar o SES sobre ela.
    board = pcbnew.LoadBoard(args.input)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit("ERRO: ImportSpecctraSES falhou.")

    # --- 4. Salvar placa roteada ----------------------------------------
    destino = os.path.dirname(os.path.abspath(args.output))
    if destino and not os.path.isdir(destino):
        os.makedirs(destino, exist_ok=True)
    print("[4/4] Salvando placa roteada: '{}'".format(args.output))
    pcbnew.SaveBoard(args.output, board)

    # --- Validacao: a placa roteada precisa ter trilhas ------------------
    with open(args.output, "r", encoding="utf-8") as f:
        conteudo = f.read()
    segmentos = _contar(conteudo, "(segment")
    vias = _contar(conteudo, "(via ")
    if segmentos == 0:
        raise SystemExit(
            "ERRO: a placa roteada '{}' nao tem nenhum segmento de trilha. "
            "O roteamento nao produziu trilhas.".format(args.output)
        )

    print(
        "OK: '{}' gerada com {} segmento(s) de trilha e {} via(s).".format(
            args.output, segmentos, vias
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
