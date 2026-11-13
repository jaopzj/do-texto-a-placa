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