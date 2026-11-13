#!/usr/bin/env python3
"""Move cada footprint para a posição declarada num YAML (Marco 2, Parte 6, passo 3).

O YAML tem uma entrada por referência, em milímetros e graus:

    J1: { x: 60.00, y: 60.00, rotacao: 90 }

A posição é a do pad 1 (a origem dos footprints PinSocket do KiCad). A rotação segue
a convenção do KiCad (graus, sentido anti-horário). O script recusa o YAML se faltar
ou sobrar alguma referência em relação à placa, ou se alguma entrada não tiver
exatamente x, y e rotacao numéricos.

Uso, dentro do container:
    python scripts/aplicar_posicoes.py <placa_entrada> <posicoes.yaml> <placa_saida>
"""

import sys

import pcbnew
import yaml

CAMPOS = {"x", "y", "rotacao"}


def ler_posicoes(caminho):
    with open(caminho, encoding="utf-8") as f:
        posicoes = yaml.safe_load(f)
    if not isinstance(posicoes, dict) or not posicoes:
        raise ValueError(f"'{caminho}' deve ter uma entrada por referência")
    problemas = []
    for ref, p in posicoes.items():
        if not isinstance(p, dict) or set(p) != CAMPOS:
            problemas.append(f"{ref}: precisa ter exatamente {sorted(CAMPOS)}, tem {p!r}")
        elif not all(isinstance(p[c], (int, float)) and not isinstance(p[c], bool) for c in CAMPOS):
            problemas.append(f"{ref}: x, y e rotacao precisam ser números, tem {p!r}")
    if problemas:
        raise ValueError("Posições inválidas:\n- " + "\n- ".join(problemas))
    return posicoes


def aplicar(placa, posicoes):
    """Aplica ``posicoes`` em ``placa`` (objeto BOARD). Levanta ValueError se as
    referências do YAML e da placa não forem as mesmas."""
    na_placa = {fp.GetReference() for fp in placa.GetFootprints()}
    faltando = sorted(na_placa - set(posicoes))
    sobrando = sorted(set(posicoes) - na_placa)
    if faltando or sobrando:
        raise ValueError(f"Referências sem posição: {faltando}; posições sem peça na placa: {sobrando}")

    for ref, p in posicoes.items():
        fp = placa.FindFootprintByReference(ref)
        fp.SetPosition(pcbnew.VECTOR2I(pcbnew.FromMM(p["x"]), pcbnew.FromMM(p["y"])))
        fp.SetOrientationDegrees(p["rotacao"])
    return len(posicoes)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        raise SystemExit(__doc__)
    entrada, arquivo_posicoes, saida = argv
    placa = pcbnew.LoadBoard(entrada)
    try:
        n = aplicar(placa, ler_posicoes(arquivo_posicoes))
    except ValueError as erro:
        raise SystemExit(f"ERRO: {erro}")
    placa.Save(saida)
    print(f"{n} peças posicionadas em '{saida}'")
    return 0


if __name__ == "__main__":
    sys.exit(main())
