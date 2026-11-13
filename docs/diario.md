# Diário de bordo

## 2026-11-12
- Criei o repositório e a estrutura de pastas.
- Próximo passo: quadro de tarefas no GitHub.

## 2026-11-13 — Marco 1 fechado (spike da netlist à placa)
- M1-1: netlist `teste.net` fixada como fonte única de verdade + `valida_netlist.sh`.
- M1-3: Freerouting 2.2.4 rodando no Java 25 (Dockerfile + nota no ADR-002).
- M1-2: netlist → `.kicad_pcb` via `kinet2pcb` (Caminho A); 3 footprints, DRC ok.
- M1-4: round-trip DSN → Freerouting → SES headless; placa roteada com 7 trilhas.
- M1-5: ADR-003 (`pcbnew` como exceção temporária ao ADR-001).
- M1-6: relatório do spike em `docs/spikes/netlist-ate-placa.md`.
- Reproduzível por `make pcb` + `make rotear`. Orquestração via time de agentes
  (Planejador, Desenvolvedor, Pesquisador); docs finais consolidados pelo Orquestrador.

## 2026-11-13 — Marco 2, Parte 1 (bibliotecas do container, issue #12)
- Fiz: `.home/` como HOME do container (ignorada pelo Git), variáveis de bibliotecas no `Makefile` e o alvo `make configurar`; os 3 avisos `lib_footprint_issues` do DRC da placa de teste sumiram.
- Aprendi: o SKiDL 3.0.0 (ferramenta `kicad10`) lê `KICAD10_SYMBOL_DIR`, e não `KICAD_SYMBOL_DIR`; as tabelas do KiCad 10 usam `${KICAD10_FOOTPRINT_DIR}` e `${KICAD10_SYMBOL_DIR}`, que o kicad-cli resolve sozinho, mas o SKiDL não.
- Travou: o SKiDL 3.0.0 acha a `fp-lib-table`, mas não indexa nenhuma biblioteca dela, porque compara o tipo `"KiCad"` com as aspas. Não afeta a netlist (o footprint vai como texto), mas a busca de footprints do SKiDL não funciona. Rever na Parte 4.
