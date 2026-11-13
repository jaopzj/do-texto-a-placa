#!/usr/bin/env python3
"""Confere uma placa gerada contra a netlist e o YAML de posições (Marco 2, Parte 6).

Verificações (todas determinísticas):
1. as referências da placa são exatamente as da netlist e as do YAML;
2. cada footprint é o da netlist;
3. cada pad está na rede da netlist, e os pads fora da netlist não têm rede;
4. cada peça está na posição e na rotação do YAML;
5. o courtyard (F.CrtYd) de cada peça está dentro do contorno (Edge.Cuts);
6. nenhum par de courtyards se sobrepõe.

Sai com código 0 se tudo passar e 1 se algo falhar, listando os problemas.

Uso, dentro do container:
    python scripts/verificar_placa.py <placa.kicad_pcb> <netlist.net> <posicoes.yaml>
"""

import os
import sys
from itertools import combinations

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "spike"))
from aplicar_posicoes import ler_posicoes  # noqa: E402
from netlist_para_pcb import montar_netlist  # noqa: E402

TOLERANCIA_NM = 1  # posições e ângulos são gravados exatamente; 1 nm cobre arredondamento


def _mm(valor):
    return round(pcbnew.ToMM(valor), 4)


def _caixa(fp):
    return fp.GetCourtyard(pcbnew.F_CrtYd).BBox()


def verificar(placa, netlist, posicoes):
    """Devolve a lista de problemas (vazia se a placa estiver correta)."""
    problemas = []
    fps = {fp.GetReference(): fp for fp in placa.GetFootprints()}
    partes = {p.ref: p for p in netlist.parts}

    # 1. Referências
    if set(fps) != set(partes) or set(fps) != set(posicoes):
        problemas.append(
            f"referências diferentes: placa {sorted(fps)}, netlist {sorted(partes)}, "
            f"posições {sorted(posicoes)}"
        )

    # 2. Footprints
    for ref in sorted(set(fps) & set(partes)):
        if fps[ref].GetFPIDAsString() != partes[ref].footprint:
            problemas.append(
                f"{ref}: footprint {fps[ref].GetFPIDAsString()}, netlist pede {partes[ref].footprint}"
            )

    # 3. Redes de cada pad
    esperado = {(pino.ref, str(pino.num)): net.name for net in netlist.nets for pino in net.pins}
    encontrado = {
        (ref, pad.GetNumber()): pad.GetNetname()
        for ref, fp in fps.items()
        for pad in fp.Pads()
    }
    for chave in sorted(set(esperado) | set(encontrado)):
        if chave not in encontrado:
            problemas.append(f"pad {chave} da netlist não existe na placa")
        elif esperado.get(chave, "") != encontrado[chave]:
            problemas.append(
                f"pad {chave}: rede '{encontrado[chave]}', netlist pede '{esperado.get(chave, '')}'"
            )

    # 4. Posição e rotação
    for ref in sorted(set(fps) & set(posicoes)):
        fp, p = fps[ref], posicoes[ref]
        pos = fp.GetPosition()
        alvo = pcbnew.VECTOR2I(pcbnew.FromMM(p["x"]), pcbnew.FromMM(p["y"]))
        if abs(pos.x - alvo.x) > TOLERANCIA_NM or abs(pos.y - alvo.y) > TOLERANCIA_NM:
            problemas.append(f"{ref}: em ({_mm(pos.x)}, {_mm(pos.y)}), YAML pede ({p['x']}, {p['y']})")
        if abs(fp.GetOrientationDegrees() - (p["rotacao"] % 360)) > 1e-6:
            problemas.append(f"{ref}: rotação {fp.GetOrientationDegrees()}, YAML pede {p['rotacao']}")

    # 5. Dentro do contorno
    contorno = pcbnew.SHAPE_POLY_SET()
    if not placa.GetBoardPolygonOutlines(contorno, False) or contorno.OutlineCount() != 1:
        problemas.append("a placa não tem um contorno fechado único em Edge.Cuts")
    else:
        for ref, fp in sorted(fps.items()):
            caixa = _caixa(fp)
            cantos = [
                pcbnew.VECTOR2I(caixa.GetX(), caixa.GetY()),
                pcbnew.VECTOR2I(caixa.GetRight(), caixa.GetY()),
                pcbnew.VECTOR2I(caixa.GetX(), caixa.GetBottom()),
                pcbnew.VECTOR2I(caixa.GetRight(), caixa.GetBottom()),
            ]
            if not all(contorno.Contains(c) for c in cantos):
                problemas.append(
                    f"{ref}: courtyard ({_mm(caixa.GetX())}, {_mm(caixa.GetY())})-"
                    f"({_mm(caixa.GetRight())}, {_mm(caixa.GetBottom())}) sai do contorno"
                )

    # 6. Sobreposição
    for (ra, a), (rb, b) in combinations(sorted(fps.items()), 2):
        if _caixa(a).Intersects(_caixa(b)):
            problemas.append(f"courtyards de {ra} e {rb} se sobrepõem")

    return problemas


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 3:
        raise SystemExit(__doc__)
    arquivo_placa, arquivo_netlist, arquivo_posicoes = argv
    placa = pcbnew.LoadBoard(arquivo_placa)
    problemas = verificar(placa, montar_netlist(arquivo_netlist), ler_posicoes(arquivo_posicoes))
    if problemas:
        print("FALHOU:\n- " + "\n- ".join(problemas))
        return 1
    n = len(placa.GetFootprints())
    print(f"OK: {n} peças conferidas (referências, footprints, redes, posições, contorno, sobreposição)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
