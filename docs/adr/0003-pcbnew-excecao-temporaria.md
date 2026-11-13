# ADR-003: O módulo `pcbnew` como exceção temporária ao ADR-001

Status: aceito · Data: 2026-11-13

## Contexto

O [ADR-001](0001-kicad-cli-base-do-pipeline.md) decidiu que todo acesso ao KiCad
passa pelo `kicad-cli`, sem a API Python antiga (SWIG / `pcbnew`), que será removida
no KiCad 11. O Marco 1 (spike "da netlist à placa") mostrou que o `kicad-cli` 10 **não
cobre** duas operações centrais do pipeline:

- **Criar a placa a partir da netlist** (colocar footprints): o `kicad-cli` não tem
  esse comando.
- **Exportar/importar Specctra DSN/SES**: necessário para autorotear no Freerouting;
  o `kicad-cli` 10 não exporta `.dsn` nem importa `.ses`.

O único caminho headless que fecha os dois round-trips hoje é o módulo `pcbnew`:
- Para netlist → placa, a ferramenta `kinet2pcb` (que usa `pcbnew` por baixo).
- Para o roteamento, `pcbnew.ExportSpecctraDSN` / `pcbnew.ImportSpecctraSES`.

Isso conflita com o ADR-001, que bane o `pcbnew`. É preciso uma decisão explícita.

## Opções consideradas

1. **Usar `pcbnew` agora, como exceção temporária** (escolhida). Desbloqueia o
   pipeline imediatamente, de forma 100% headless. Custo: depende de uma API marcada
   para remoção no KiCad 11.
2. **Esperar a API IPC (`kicad-python`)**. É a API oficial do futuro, mas exige o
   KiCad **aberto** (contraria o modo headless do ADR-001) e ainda não cobre
   netlist→placa nem DSN/SES de forma madura. Adia o Marco 1 por tempo indefinido.
3. **Trocar de roteador / gerar a placa por outra via** (ex.: montar o `.kicad_pcb`
   "na mão" via `kiutils`, outro autoroteador). Maior esforço, reimplementa o que o
   `pcbnew` já faz, sem eliminar a dependência de alguma API instável.
4. **Adiar o autoroute** para um marco futuro. Deixaria o critério central do spike
   (placa com trilhas) sem resposta e não validaria a viabilidade técnica agora.

## Decisão

Adotar o **`pcbnew` como exceção temporária e localizada ao ADR-001**, restrita a
criar/rotear a placa de forma headless no Marco 1:

- **Caminho A (adotado): `kinet2pcb`** para netlist → `.kicad_pcb`.
- **Caminho B (reserva): `kiutils`**, só se o Caminho A se mostrar inviável.
- **Roteamento:** `pcbnew.ExportSpecctraDSN` → Freerouting (headless) →
  `pcbnew.ImportSpecctraSES`.

Toda chamada a `pcbnew` fica isolada em `scripts/spike/` (`netlist_para_pcb.py` e
`round_trip_freerouting.py`), para ser fácil de localizar e substituir. O restante do
sistema continua usando só o `kicad-cli`, conforme o ADR-001; o Java/Docker seguem o
[ADR-002](0002-python-e-docker.md) (Freerouting roda no Java 25).

## Consequências

- O pipeline netlist → placa → placa roteada funciona **hoje**, headless, no
  container (`make pcb`, `make rotear`).
- Cria-se uma dívida técnica consciente: duas operações dependem de uma API (SWIG)
  com remoção anunciada.
- A exceção é **contida**: só os dois scripts do spike tocam `pcbnew`. Migrar depois
  significa trocar esses dois pontos, não o pipeline inteiro.
- O ADR-001 continua valendo como regra geral; este ADR é a única exceção registrada.

## Gatilho de reavaliação

Reabrir esta decisão quando **qualquer** um ocorrer:

- Chegada do **KiCad 11** / remoção efetiva da API SWIG `pcbnew` (já ausente nas
  builds de desenvolvimento do KiCad 11, conforme o ADR-001).
- A **API IPC (`kicad-python`)** passar a cobrir netlist→placa e DSN/SES de forma
  headless e estável.
- Surgir um autoroteador/toolchain que feche o round-trip sem `pcbnew`.

Na reavaliação, migrar os dois scripts do spike para a alternativa madura e remover
esta exceção, restaurando o ADR-001 sem ressalvas.
