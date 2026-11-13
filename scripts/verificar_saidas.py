#!/usr/bin/env python3
"""Confere a placa roteada e os arquivos da fábrica (Marco 2, Parte 7).

Verificações (todas determinísticas):
1. o relatório JSON do DRC da placa roteada tem zero violações e zero ligações pendentes;
2. existe um Gerber para cada camada de fabricação (cobre, máscara e serigrafia dos dois
   lados e contorno), identificado pelo atributo TF.FileFunction, e cada um termina com M02*;
3. existe o arquivo de job dos Gerbers;
4. a furação tem exatamente um furo por pad e por via da placa, nas mesmas posições;
5. o arquivo de posições tem as peças da netlist, nas posições e rotações do YAML;
6. a BOM tem cada peça da netlist uma vez, com o footprint certo.

Sai com código 0 se tudo passar e 1 se algo falhar, listando os problemas.

Uso, dentro do container:
    python scripts/verificar_saidas.py <placa_roteada> <netlist.net> <posicoes.yaml> \
        <drc.json> <pasta_fabrica>
"""

import csv
import glob
import json
import os
import re
import sys

import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "spike"))
from aplicar_posicoes import ler_posicoes  # noqa: E402
from netlist_para_pcb import montar_netlist  # noqa: E402

# Camadas que a fábrica precisa, pelo atributo TF.FileFunction de cada Gerber.
CAMADAS = {
    "Copper,L1,Top": "F.Cu",
    "Copper,L2,Bot": "B.Cu",
    "Soldermask,Top": "F.Mask",
    "Soldermask,Bot": "B.Mask",
    "Legend,Top": "F.Silkscreen",
    "Legend,Bot": "B.Silkscreen",
    "Profile,NP": "Edge.Cuts",
}
CASAS = 3  # milímetros com 3 casas (1 µm): a precisão do arquivo de furação


def _ponto(x, y):
    return (round(x, CASAS), round(y, CASAS))


def verificar_drc(caminho):
    with open(caminho, encoding="utf-8") as f:
        drc = json.load(f)
    problemas = []
    for chave in ("violations", "unconnected_items"):
        itens = drc.get(chave)
        if not isinstance(itens, list):
            problemas.append(f"DRC: o relatório não tem a lista '{chave}'")
        elif itens:
            descricoes = sorted({i.get("description", "?") for i in itens})
            problemas.append(f"DRC: {len(itens)} item(ns) em '{chave}': {descricoes}")
    return problemas


def verificar_gerbers(pasta):
    problemas = []
    encontrados = {}
    for arquivo in sorted(glob.glob(os.path.join(pasta, "*"))):
        if arquivo.endswith((".drl", ".csv", ".gbrjob", ".json")):
            continue
        with open(arquivo, encoding="utf-8", errors="replace") as f:
            texto = f.read()
        funcao = re.search(r"%TF\.FileFunction,([^*]*)\*%", texto)
        if not funcao:
            continue
        nome = re.sub(r",(Signal|Mixed|Plane)$", "", funcao.group(1))
        if nome in CAMADAS:
            encontrados.setdefault(nome, []).append(arquivo)
            if not texto.rstrip().endswith("M02*"):
                problemas.append(f"Gerber {os.path.basename(arquivo)} não termina com M02*")
    for funcao, camada in CAMADAS.items():
        quantos = len(encontrados.get(funcao, []))
        if quantos != 1:
            problemas.append(f"Gerber de {camada} ({funcao}): {quantos} arquivo(s), esperado 1")
    if len(glob.glob(os.path.join(pasta, "*.gbrjob"))) != 1:
        problemas.append("falta o arquivo de job dos Gerbers (.gbrjob)")
    return problemas


def ler_furos(caminho):
    """Devolve {'ViaDrill': [...], 'ComponentDrill': [...]} com os furos (x, y) em mm,
    no sistema do arquivo (y para cima)."""
    funcao_da_ferramenta, furos, funcao, atual = {}, {}, None, None
    with open(caminho, encoding="utf-8") as f:
        for linha in f:
            linha = linha.strip()
            m = re.match(r"; #@! TA\.AperFunction,.*,(\w+)$", linha)
            if m:
                funcao = m.group(1)
                continue
            m = re.match(r"(T\d+)C[\d.]+$", linha)
            if m:
                funcao_da_ferramenta[m.group(1)] = funcao
                continue
            if re.match(r"T\d+$", linha):
                atual = funcao_da_ferramenta.get(linha)
                continue
            m = re.match(r"X(-?[\d.]+)Y(-?[\d.]+)$", linha)
            if m:
                furos.setdefault(atual, []).append(_ponto(float(m.group(1)), float(m.group(2))))
    return furos


def verificar_furacao(pasta, placa):
    arquivos = glob.glob(os.path.join(pasta, "*.drl"))
    if len(arquivos) != 1:
        return [f"furação: {len(arquivos)} arquivo(s) .drl, esperado 1"]
    furos = ler_furos(arquivos[0])
    # O arquivo de furação usa y para cima; a placa, y para baixo.
    pads = sorted(
        _ponto(pcbnew.ToMM(p.GetPosition().x), -pcbnew.ToMM(p.GetPosition().y))
        for fp in placa.GetFootprints() for p in fp.Pads()
    )
    vias = sorted(
        _ponto(pcbnew.ToMM(t.GetPosition().x), -pcbnew.ToMM(t.GetPosition().y))
        for t in placa.GetTracks() if t.GetClass() == "PCB_VIA"
    )
    problemas = []
    if sorted(furos.get("ComponentDrill", [])) != pads:
        problemas.append(
            f"furação: {len(furos.get('ComponentDrill', []))} furo(s) de componente, a placa tem {len(pads)} pad(s) nessas posições"
        )
    if sorted(furos.get("ViaDrill", [])) != vias:
        problemas.append(f"furação: {len(furos.get('ViaDrill', []))} furo(s) de via, a placa tem {len(vias)} via(s)")
    outros = set(furos) - {"ComponentDrill", "ViaDrill"}
    if outros:
        problemas.append(f"furação: furos de tipo inesperado {sorted(map(str, outros))}")
    return problemas


def verificar_posicoes(caminho, netlist, posicoes):
    with open(caminho, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    problemas = []
    refs = [l["Ref"] for l in linhas]
    if sorted(refs) != sorted(p.ref for p in netlist.parts):
        problemas.append(f"posições: referências {sorted(refs)}, netlist tem {sorted(p.ref for p in netlist.parts)}")
    for l in linhas:
        p = posicoes.get(l["Ref"])
        if p is None:
            continue
        # O arquivo de posições usa y para cima.
        obtido = (float(l["PosX"]), -float(l["PosY"]), float(l["Rot"]) % 360)
        esperado = (p["x"], p["y"], p["rotacao"] % 360)
        if any(abs(a - b) > 1e-3 for a, b in zip(obtido, esperado)):
            problemas.append(f"posições: {l['Ref']} em {obtido}, YAML pede {esperado}")
        if l["Side"] != "top":
            problemas.append(f"posições: {l['Ref']} no lado {l['Side']}, esperado top")
    return problemas


def verificar_bom(caminho, netlist):
    with open(caminho, encoding="utf-8") as f:
        linhas = list(csv.DictReader(f))
    problemas = []
    footprints = {p.ref: p.footprint for p in netlist.parts}
    vistos = []
    for l in linhas:
        refs = l["Referencias"].split()
        vistos.extend(refs)
        if int(l["Quantidade"]) != len(refs):
            problemas.append(f"BOM: quantidade {l['Quantidade']} para {refs}")
        for ref in refs:
            if footprints.get(ref) != l["Tipo de conector"]:
                problemas.append(f"BOM: {ref} com {l['Tipo de conector']}, netlist pede {footprints.get(ref)}")
    if sorted(vistos) != sorted(footprints):
        problemas.append(f"BOM: referências {sorted(vistos)}, netlist tem {sorted(footprints)}")
    return problemas


def verificar(placa, netlist, posicoes, arquivo_drc, pasta):
    problemas = verificar_drc(arquivo_drc)
    problemas += verificar_gerbers(pasta)
    problemas += verificar_furacao(pasta, placa)
    arquivo_pos = os.path.join(pasta, "posicoes.csv")
    arquivo_bom = os.path.join(pasta, "bom.csv")
    for arquivo in (arquivo_pos, arquivo_bom):
        if not os.path.isfile(arquivo):
            problemas.append(f"falta '{arquivo}'")
    if os.path.isfile(arquivo_pos):
        problemas += verificar_posicoes(arquivo_pos, netlist, posicoes)
    if os.path.isfile(arquivo_bom):
        problemas += verificar_bom(arquivo_bom, netlist)
    return problemas


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    if len(argv) != 5:
        raise SystemExit(__doc__)
    arquivo_placa, arquivo_netlist, arquivo_posicoes, arquivo_drc, pasta = argv
    placa = pcbnew.LoadBoard(arquivo_placa)
    problemas = verificar(
        placa, montar_netlist(arquivo_netlist), ler_posicoes(arquivo_posicoes), arquivo_drc, pasta
    )
    if problemas:
        print("FALHOU:\n- " + "\n- ".join(problemas))
        return 1
    vias = sum(1 for t in placa.GetTracks() if t.GetClass() == "PCB_VIA")
    trilhas = sum(1 for t in placa.GetTracks() if t.GetClass() == "PCB_TRACK")
    print(
        f"OK: DRC sem violações nem pendências; {len(CAMADAS)} Gerbers, furação, posições e BOM "
        f"conferidos ({trilhas} trilhas, {vias} via(s))"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
