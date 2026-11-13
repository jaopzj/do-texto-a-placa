# Marco 1 — Spike: da netlist à placa, sem interface

Time-box: 8–12h. Entregáveis: scripts headless, `docs/spikes/netlist-ate-placa.md` e ADR-003.

**Decisão ratificada (owner):** ADR-003 = usar o módulo `pcbnew` agora como **exceção
temporária** ao ADR-001 (o `kicad-cli` 10 não exporta DSN/SES; o `pcbnew` tem
`ExportSpecctraDSN`/`ImportSpecctraSES`). Para netlist→placa: **Caminho A = `kinet2pcb`**
primeiro; **Caminho B = `kiutils`** só se sobrar tempo no time-box.

## Grafo de dependências / ordem

```
(M1-1 fixture) ─┐
(M1-3 fix Java) ─┼─> M1-2 netlist→pcb ─> M1-4 round-trip ─┬─> M1-5 ADR-003
                │                                          └─> M1-6 relatório
                └ M1-3 bloqueia M1-4
```
Ordem prática: **M1-1 ∥ M1-3** → **M1-2** → **M1-4** → **M1-5 ∥ M1-6**.

| ID | Título | Depende de | Branch |
|----|--------|-----------|--------|
| M1-1 | Fixture: versionar `teste.net` + doc + script de validação | — | `m1/fixture-netlist` |
| M1-2 | Script netlist → `.kicad_pcb` com footprints (headless) | M1-1 | `m1/netlist-para-pcb` |
| M1-3 | Fix Java/Freerouting (Dockerfile 21→25-jre) | — (bloqueia M1-4) | `m1/fix-java-freerouting` |
| M1-4 | Round-trip DSN → Freerouting → SES (headless) | M1-2, M1-3 | `m1/round-trip-freerouting` |
| M1-5 | ADR-003: `pcbnew` como exceção temporária ao ADR-001 | M1-2, M1-4 | `m1/adr-003` |
| M1-6 | Relatório do spike `docs/spikes/netlist-ate-placa.md` | M1-2, M1-4, M1-5 | `m1/relatorio-spike` |

---

## M1-1 — Fixture: `teste.net` como fonte única de verdade
**Branch:** `m1/fixture-netlist` · **Depende de:** —

**Objetivo:** fixar a ENTRADA do spike (circuito R + LED) como fonte única de verdade,
versionada, para todas as issues seguintes partirem do mesmo insumo.

**Contexto:** hoje não há netlist versionada no repo; o `saida/drc.rpt` mostra que o
circuito de referência é R + LED (footprints `Resistor_SMD`, `LED_SMD`). O **usuário vai
exportar** a netlist do KiCad (GUI) para `placas/teste/teste.net`. NÃO gerar outra netlist
por conta própria (evita duas fontes de verdade); o SKiDL fica fora deste marco.

**Escopo:**
- Versionar `placas/teste/teste.net` (a exportada pelo usuário).
- Documentar em `placas/teste/README.md` como ela foi gerada (KiCad → Exportar netlist) e
  o mapa componente→footprint; registrar o aviso de `KICAD*_SYMBOL_DIR`/`fp-lib-table`
  visto no `skidl_REPL.log` e como contorná-lo no container.
- Script headless no container (ex.: `scripts/spike/valida_netlist.sh`) que **valida** a
  `teste.net` (parse/estrutura + presença de footprints) e falha com mensagem clara se o
  arquivo estiver ausente ou incompleto.

**Pronto quando:**
- `placas/teste/teste.net` existe no git, com ≥2 componentes e footprint por componente.
- `scripts/spike/valida_netlist.sh` roda sem interface no container e sai 0 para a netlist
  válida, ≠0 com mensagem clara se faltar/estiver incompleta.
- `placas/teste/README.md` descreve origem, mapa de footprints e o contorno do symbol-dir.

---

## M1-2 — Script netlist → `.kicad_pcb` com footprints (headless)
**Branch:** `m1/netlist-para-pcb` · **Depende de:** M1-1 · **(Critério de pronto do marco #1)**

**Objetivo:** um comando, sem interface, lê `placas/teste/teste.net` e produz um
`.kicad_pcb` com os footprints de cada componente colocados.

**Contexto:** o `kicad-cli` 10 NÃO cria placa a partir da netlist. Caminho ratificado:
**A = `kinet2pcb`** primeiro; **B = `kiutils`** só se sobrar tempo.

**Escopo:**
- Script em `scripts/spike/` (ex.: `netlist_para_pcb.py`/`.sh`) que recebe a netlist e
  gera `placas/teste/teste.kicad_pcb` com footprints, rodando headless no container.
- Tentar Caminho A (`kinet2pcb`); registrar no código/README se caiu para B (`kiutils`).
- Garantir resolução de footprints no container (fp-lib-table / variáveis de ambiente).

**Pronto quando:**
- Um comando headless gera `placas/teste/teste.kicad_pcb` a partir da netlist.
- Abrindo no KiCad, os footprints (R e LED) aparecem posicionados.
- `kicad-cli pcb drc placas/teste/teste.kicad_pcb` roda sem erro de parse.
- Está registrado qual caminho funcionou (A `kinet2pcb` ou B `kiutils`).

---

## M1-3 — Fix Java/Freerouting (Dockerfile 21→25-jre)
**Branch:** `m1/fix-java-freerouting` · **Depende de:** — · **BLOQUEIA:** M1-4
> Já iniciada pelo Desenvolvedor.

**Objetivo:** fazer o Freerouting 2.2.4 rodar no container, pré-requisito do round-trip.

**Contexto:** o Freerouting 2.2.4 foi compilado para **Java 25** e NÃO roda no Java 21. O
`docker/Dockerfile` hoje copia o Java do estágio `eclipse-temurin:21-jre`.

**Escopo:**
- Subir o estágio java do `docker/Dockerfile` de `eclipse-temurin:21-jre` para
  `eclipse-temurin:25-jre`.
- Rebuild da imagem `do-texto-a-placa`.
- Consequência de ADR (ADR-002 fixa versões conscientemente): registrar a troca — nota no
  ADR-002 ou menção no ADR-003/relatório.

**Pronto quando:**
- `make imagem` builda com Java 25.
- `make versao` mostra Java 25 e lista o jar do Freerouting.
- `java -jar /opt/freerouting/freerouting.jar --version` (ou equivalente headless) roda
  sem erro de versão de classe no container.

---

## M1-4 — Round-trip DSN → Freerouting → SES (headless)
**Branch:** `m1/round-trip-freerouting` · **Depende de:** M1-2, M1-3 · **(Critério de pronto do marco #2)**

**Objetivo:** exportar a placa para Specctra DSN, autorotear no Freerouting sem GUI e
reimportar o SES, obtendo a placa com trilhas.

**Contexto:** `kicad-cli` não exporta DSN/SES; usar `pcbnew` (`ExportSpecctraDSN` /
`ImportSpecctraSES`), conforme ADR-003. Freerouting 2.2.4 + Java 25 (depende de M1-3).

**Escopo:**
- Script headless em `scripts/spike/`: `ExportSpecctraDSN` (pcbnew) → `freerouting.jar`
  em modo headless/CLI gerando `.ses` → `ImportSpecctraSES` (pcbnew) → salvar a placa.
- Se algum passo for impossível no time-box, DOCUMENTAR o bloqueio + alternativa concreta.

**Pronto quando:**
- Um comando headless gera `.ses` a partir do `.kicad_pcb` e produz uma placa com trilhas
  roteadas; OU, se inviável, há bloqueio documentado + alternativa concreta.
- O round-trip não abre nenhuma janela gráfica.

---

## M1-5 — ADR-003: `pcbnew` como exceção temporária ao ADR-001
**Branch:** `m1/adr-003` · **Depende de:** M1-2, M1-4 · **(Critério de pronto do marco #3)**

**Objetivo:** registrar formalmente a decisão (já ratificada) de usar `pcbnew` como
exceção temporária ao ADR-001 para criar/rotear a placa headless.

**Contexto:** `kicad-cli` não faz netlist→pcb nem exporta DSN/SES; só o `pcbnew` (API SWIG,
prevista para remoção no KiCad 11) fecha o round-trip. Decisão do owner: aceitar como
exceção **temporária**, com plano B.

**Escopo:**
- Criar `docs/adr/0003-pcbnew-excecao-temporaria.md`, status aceito, referenciando ADR-001
  e ADR-002.
- Descrever: problema, opções (pcbnew agora / IPC API / roteador alternativo / adiar), a
  decisão (pcbnew agora; A=kinet2pcb, B=kiutils), consequências e gatilho de reavaliação
  (chegada do KiCad 11 / remoção do SWIG).

**Pronto quando:**
- `docs/adr/0003-*.md` existe, status definido, referencia ADR-001/ADR-002.
- Descreve a exceção do `pcbnew`, o plano B e o gatilho de reavaliação.

---

## M1-6 — Relatório do spike
**Branch:** `m1/relatorio-spike` · **Depende de:** M1-2, M1-4, M1-5 · **(Critério de pronto do marco #3)**

**Objetivo:** consolidar os achados do spike: o que foi tentado, o que funcionou, comandos
reproduzíveis, tempo gasto, riscos e recomendação.

**Escopo:**
- Escrever `docs/spikes/netlist-ate-placa.md` cobrindo os dois round-trips (netlist→pcb e
  DSN→SES), referenciando os scripts (M1-2, M1-4) e o ADR-003 (M1-5).
- Incluir passos de reprodução e os comandos headless exatos.

**Pronto quando:**
- `docs/spikes/netlist-ate-placa.md` existe.
- Cobre os dois round-trips, lista comandos headless reproduzíveis, aponta riscos e
  recomendação, e linka o ADR-003.
