# ADR-004: A exceção do `pcbnew` vale também para os scripts da placa

Status: aceito · Data: 2026-11-13 · Complementa o [ADR-003](0003-pcbnew-excecao-temporaria.md)

## Contexto

O ADR-003 abriu uma exceção ao [ADR-001](0001-kicad-cli-base-do-pipeline.md): o módulo
`pcbnew` pode ser usado para criar e rotear a placa, mas só nos dois scripts de
`scripts/spike/`. No Marco 2, Parte 6, o guia do MVP pede a placa real da placa de
referência: juntar a netlist à placa-modelo e mover cada peça para uma posição
declarada num YAML (`scripts/aplicar_posicoes.py`). O `kicad-cli` 10 também não faz
nenhuma dessas operações, então elas precisam do `pcbnew`, fora de `scripts/spike/`.

## Decisão

A exceção do ADR-003 passa a cobrir também estes scripts, e só eles:

- `scripts/gerar_placa.py`: netlist + placa-modelo -> placa com os footprints e as redes;
- `scripts/aplicar_posicoes.py`: aplica as posições do YAML;
- `scripts/verificar_placa.py`: confere a placa contra a netlist e o YAML.
- `scripts/verificar_saidas.py`: confere a furação contra os pads e vias da placa roteada
  (Parte 7).

Eles reaproveitam o parser de netlist do `scripts/spike/netlist_para_pcb.py`. As
verificações de fabricação continuam no `kicad-cli` (DRC).

## Consequências

- A Parte 6 roda headless no container (`make posicionar`).
- A dívida técnica do ADR-003 cresce de dois para seis scripts, todos em `scripts/`.
  Nenhum código de `src/` usa o `pcbnew`.
- O gatilho de reavaliação é o mesmo do ADR-003 (KiCad 11 ou API IPC madura). Na
  migração, estes quatro scripts entram na lista.
