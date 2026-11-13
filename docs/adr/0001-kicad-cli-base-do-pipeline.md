# ADR-001: O kicad-cli é a base do pipeline

Status: aceito · Data: 2026-11-13

## Contexto

A plataforma precisa operar o KiCad de forma automática, sem ninguém clicando na
interface: rodar verificações (ERC e DRC) e gerar arquivos de fabricação. Existem
três formas de um programa operar o KiCad:

- `kicad-cli`: linha de comando, funciona sem abrir a interface.
- API IPC (`kicad-python`): a API oficial nova, mas exige o KiCad aberto.
- API antiga em Python (SWIG / `pcbnew`): removida das versões de desenvolvimento
  do KiCad 11.

## Decisão

Usar o `kicad-cli` para todas as verificações e exportações. Nenhuma parte do
sistema chama o KiCad diretamente: todo acesso passa por um módulo adaptador nosso.
A API IPC fica reservada para um futuro modo em que o usuário assiste ao agente
trabalhando.

## Consequências

- O pipeline roda em qualquer máquina ou servidor, sem interface gráfica.
- Mudanças no KiCad afetam só o módulo adaptador.
- Algumas operações talvez não existam no `kicad-cli` (por exemplo, criar a placa a
  partir da netlist). Isso será investigado no Marco 1 e registrado num novo ADR.
