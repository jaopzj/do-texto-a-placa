# Spike: da netlist à placa, sem interface

Data: 2026-11-13 · Marco 1 · Time-box: 8–12h
Relacionado: [ADR-003](../adr/0003-pcbnew-excecao-temporaria.md),
[ADR-001](../adr/0001-kicad-cli-base-do-pipeline.md),
[ADR-002](../adr/0002-python-e-docker.md), [issues do Marco 1](../issues/marco-1.md)

## Objetivo

Provar, de ponta a ponta e **sem interface gráfica**, o caminho
**netlist → placa com footprints → placa roteada**, dentro do container do projeto.
Dois round-trips a validar:

1. **netlist → `.kicad_pcb`** (colocar footprints).
2. **`.kicad_pcb` → DSN → Freerouting → SES → placa com trilhas** (autoroute).

## Resultado (resumo)

| Round-trip | Status | Evidência |
|---|---|---|
| netlist → placa (M1-2) | ✅ funciona | `teste.kicad_pcb` com 3 footprints posicionados; DRC sem erro de parse |
| DSN → Freerouting → SES (M1-4) | ✅ funciona | `teste_roteada.kicad_pcb` com 3 nets roteadas, **7 segmentos**, 0 vias, headless |

Ambos rodam headless no container. **Recomendação:** seguir com esta base; formalizada
no [ADR-003](../adr/0003-pcbnew-excecao-temporaria.md) (uso do `pcbnew` como exceção
temporária ao ADR-001).

## Entrada (fonte única de verdade)

`placas/teste/teste/teste.net`, exportada do KiCad (circuito R + LED + conector):

| Ref | Valor | Footprint |
|-----|-------|-----------|
| R1 | 330 Ω | `Resistor_SMD:R_0805_2012Metric` |
| D1 | LED vermelho | `LED_THT:LED_D5.0mm` |
| J1 | Conn_01x02 | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical` |

Validação headless da netlist: `scripts/spike/valida_netlist.sh` (sai 0 para netlist
válida, ≠0 com mensagem clara se faltar/incompleta). Ver `placas/teste/README.md`.

## Round-trip 1 — netlist → `.kicad_pcb` (M1-2)

**Caminho A (adotado): `kinet2pcb`.** O `kicad-cli` 10 não cria placa a partir da
netlist; `kinet2pcb` usa o `pcbnew` por baixo. Caminho B (`kiutils`) não foi preciso.

Script: `scripts/spike/netlist_para_pcb.py`.

```bash
# dentro da raiz do repo; roda headless no container
make pcb       # python scripts/spike/netlist_para_pcb.py -i <netlist> -o <placa>
make drc       # kicad-cli pcb drc -o saida/drc.rpt <placa>
```

Resultado:
- `placas/teste/teste/teste.kicad_pcb` com os **3 footprints posicionados**
  (`R_0805`, `LED_D5.0mm`, `PinHeader_1x02`).
- `make drc` roda **sem erro de parse**. As violações nesta etapa (itens não
  conectados) são **esperadas**: a placa tem footprints mas ainda **sem trilhas** —
  é o que o Round-trip 2 resolve.

## Round-trip 2 — DSN → Freerouting → SES (M1-4)

O `kicad-cli` não exporta DSN nem importa SES; usa-se `pcbnew.ExportSpecctraDSN` e
`pcbnew.ImportSpecctraSES`. Freerouting 2.2.4 roda **headless no Java 25** (ADR-002).

Script: `scripts/spike/round_trip_freerouting.py`
(1. ExportSpecctraDSN → 2. `freerouting.jar` headless gera `.ses` →
3. ImportSpecctraSES → salva a placa roteada).

```bash
make rotear    # python scripts/spike/round_trip_freerouting.py -i <placa> -o <roteada>
```

Resultado:
- `placas/teste/teste/teste_roteada.kicad_pcb` com **3 nets roteadas, 7 segmentos de
  trilha, 0 vias**.
- Round-trip **100% headless** — nenhuma janela gráfica é aberta
  (`gui.enabled=false` no Freerouting).

## Reprodução completa

```bash
make imagem    # build da imagem (KiCad 10 + Java 25 + Freerouting 2.2.4 + libs Python)
make versao    # confere kicad-cli, java 25 e o jar do Freerouting
make pcb       # netlist -> placa com footprints  (Round-trip 1)
make drc       # DRC (sem erro de parse)
make rotear    # placa -> DSN -> Freerouting -> SES -> placa roteada  (Round-trip 2)
```

## Riscos e dívidas

1. **Dependência do `pcbnew` (SWIG)**, marcado para remoção no KiCad 11. Mitigado por
   isolar o uso em `scripts/spike/` e registrar o gatilho de reavaliação no ADR-003.
2. **Caminho aninhado** `placas/teste/teste/` (em vez de `placas/teste/`): diverge do
   texto original das issues, mas Makefile e scripts já apontam para ele de forma
   consistente.
3. **Freerouting headless** depende de flags da versão 2.2.4; fixar a versão (ADR-002)
   evita surpresas em upgrades.

## Recomendação

Adotar esta base para o pipeline de roteamento, mantendo o `pcbnew` como exceção
**temporária e contida** (ADR-003) e revisitando a decisão no gatilho ali descrito
(KiCad 11 / API IPC madura). Os dois critérios técnicos do Marco 1 estão atendidos e
são reproduzíveis por `make pcb` + `make rotear`.
