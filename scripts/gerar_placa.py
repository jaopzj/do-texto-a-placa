#!/usr/bin/env python3
"""Gera a placa a partir da netlist e da placa-modelo (Marco 2, Parte 6, passo 1).

1. Lê a netlist com o parser do spike (``scripts/spike/netlist_para_pcb.py``) e gera
   uma placa intermediária com o kinet2pcb (Caminho A do ADR-003).
2. Copia os footprints dessa placa, com as redes de cada pad, para dentro de uma cópia
   da placa-modelo. O resultado herda o contorno, as camadas e as regras do modelo
   (o ``.kicad_pro`` do modelo é gravado ao lado da placa gerada).

As posições que o kinet2pcb escolhe são provisórias: quem decide é o
``scripts/aplicar_posicoes.py``.

Uso, dentro do container:
    python scripts/gerar_placa.py -n <netlist> -m <modelo.kicad_pcb> -o <placa.kicad_pcb>
"""

import argparse
import os
import sys
import tempfile
import uuid

import pcbnew

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "spike"))
import kinet2pcb as _k2p  # noqa: E402
from netlist_para_pcb import LIBS_PADRAO, montar_netlist  # noqa: E402


# Espaço de nomes dos UUIDs da placa: com ele, os UUIDs dependem só da referência e da
# posição de cada item no footprint, e a placa gerada sai igual a cada execução.
ESPACO_UUID = uuid.UUID("6c1f4a52-6f2e-5d0a-9a51-646f2d746578")


def fixar_uuids(fp):
    """Troca os UUIDs aleatórios do footprint e dos seus itens por UUIDs derivados da
    referência. O KiCad ordena os itens pelo UUID ao salvar, então sem isso a ordem dos
    footprints no arquivo muda a cada execução."""
    ref = fp.GetReference()

    def kiid(sufixo):
        return pcbnew.KIID(str(uuid.uuid5(ESPACO_UUID, f"{ref}/{sufixo}")))

    fp.SetUuid(kiid("footprint"))
    for i, item in enumerate(fp.GetFields()):
        item.SetUuid(kiid(f"campo/{i}"))
    for i, item in enumerate(fp.GraphicalItems()):
        item.SetUuid(kiid(f"grafico/{i}"))
    for item in fp.Pads():
        item.SetUuid(kiid(f"pad/{item.GetNumber()}"))


def copiar_footprints(origem, destino):
    """Copia os footprints de ``origem`` para ``destino``, religando cada pad à rede
    de mesmo nome em ``destino`` (criada se ainda não existir)."""
    for fp in sorted(origem.GetFootprints(), key=lambda f: f.GetReference()):
        novo = pcbnew.FOOTPRINT(fp)
        for pad in novo.Pads():
            nome = pad.GetNetname()
            if not nome:
                pad.SetNetCode(0)
                continue
            net = destino.FindNet(nome)
            if net is None:
                net = pcbnew.NETINFO_ITEM(destino, nome)
                destino.Add(net)
            pad.SetNet(net)
        fixar_uuids(novo)
        destino.Add(novo)


def gerar(netlist, modelo, saida, libs=LIBS_PADRAO):
    """Gera ``saida`` (com o ``.kicad_pro`` do modelo ao lado) e devolve o número de
    footprints copiados."""
    dados = montar_netlist(netlist)
    os.makedirs(os.path.dirname(os.path.abspath(saida)), exist_ok=True)

    with tempfile.TemporaryDirectory() as tmp:
        intermediaria = os.path.join(tmp, "intermediaria.kicad_pcb")
        _k2p.kinet2pcb(dados, intermediaria, [libs])
        origem = pcbnew.LoadBoard(intermediaria)

        refs = sorted(fp.GetReference() for fp in origem.GetFootprints())
        esperadas = sorted(p.ref for p in dados.parts)
        if refs != esperadas:
            raise SystemExit(f"ERRO: a netlist tem {esperadas}, mas o kinet2pcb gerou {refs}")

        placa = pcbnew.LoadBoard(modelo)  # carrega também o .kicad_pro do modelo
        if len(placa.GetFootprints()) != 0:
            raise SystemExit(f"ERRO: a placa-modelo '{modelo}' já tem footprints")
        copiar_footprints(origem, placa)
        placa.Save(saida)
    return len(refs)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("-n", "--netlist", required=True)
    parser.add_argument("-m", "--modelo", required=True)
    parser.add_argument("-o", "--saida", required=True)
    args = parser.parse_args(argv)

    for caminho in (args.netlist, args.modelo):
        if not os.path.isfile(caminho):
            raise SystemExit(f"ERRO: arquivo não encontrado: '{caminho}'")

    n = gerar(args.netlist, args.modelo, args.saida)
    print(f"OK: '{args.saida}' gerada a partir de '{args.modelo}' com {n} footprint(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
