# ADR-019: Fluxo completo, relatório de projeto, segunda aprovação e evals do fluxo

Status: aceito · Data: 2026-11-16

## Contexto

As Partes 1 a 4 do Marco 5 ficaram prontas em comandos separados: `make briefing`, `make
regras` e `make correcao`. Ainda faltavam três coisas.

- **A Parte 5.** Gerar o relatório de projeto (decisões e fontes, regras verificadas,
  resultado do DRC, BOM e pendências) e pedir a segunda confirmação antes dos arquivos da
  fábrica.
- **A Parte 6.** Escrever de três a cinco pedidos em `src/evals/pedidos/`: a mesma placa com
  outras palavras, uma peça fora da base e um pedido impossível. Injetar um erro depois que
  o agente termina, conferir que o laço o corrige e registrar tudo em `docs/evals.md`.
- **O caminho do Marco 4, Parte 7.** A netlist do agente precisa passar pelo pipeline até os
  Gerbers.

O critério do marco é que a frase do usuário vire os arquivos da fábrica, com as duas
aprovações e sem edição manual. O john pediu um fluxo que um usuário comum consiga usar sem
rodar ferramentas internas à mão. Ele também pediu que uma peça ou um dado em falta vire
pendência, nunca uma placa inconsistente.

A análise do repositório achou dois buracos que o fluxo completo deixaria passar:

- **Tirar uma ligação podia passar despercebido.** Sem a ligação do VCC ou do GND do sensor,
  a netlist continuava válida e nenhuma regra da base olhava para isso. O DRC também não
  acusava, porque um pad sem rede não tem o que ligar. Esse é justamente o erro que o guia
  sugere injetar.
- **A placa saía sempre do mesmo modelo.** O pipeline usa a placa-modelo, as posições e o
  contorno da placa de referência. Uma especificação com outro contorno, outro número de
  camadas ou outra montagem viraria Gerbers da placa de 100 x 100 mm, diferentes do que foi
  aprovado.

## Decisão

**Um comando para o fluxo inteiro.** `python -m src.projeto "pedido"` (ou `make projeto
PEDIDO=...`) faz quatro etapas, cada uma anunciada no terminal:

1. **Briefing e primeira aprovação.** Usa `src/briefing.py` sem mudança de comportamento:
   `no_terminal` só tirou do `main` as perguntas e a aprovação pelo terminal, para os dois
   usarem. A especificação aprovada vai para `saida/projetos/<projeto>/spec.yaml`. Quando
   há pendências, o usuário é avisado antes do resumo de que, com elas, a placa não será
   feita.
2. **Circuito e laço de correção** (ADR-018). O laço virou a classe `Laco`, que mantém a
   conversa com o agente. `corrigir` continua com a mesma assinatura e o mesmo resultado. O
   andamento do agente aparece no terminal, ferramenta por ferramenta.
3. **Relatório e segunda aprovação.** O `relatorio.md` é gravado antes da pergunta. O usuário
   vê:
   - netlist e alimentação;
   - a contagem das regras, com as que ficam para conferir à mão;
   - os itens do DRC;
   - o caminho do relatório.

   Ele responde `s` para gerar os arquivos ou `n` para parar sem eles, ou escreve uma mudança
   no circuito. A mudança volta ao agente na mesma conversa (`Laco.pedido_do_usuario`) e passa
   de novo por todas as conferências, com o mesmo limite de três correções, antes de uma nova
   segunda aprovação.
4. **Fábrica** (`src/fabrica.py`). São os mesmos passos do fim do `make placa`, sobre a placa
   roteada da última conferência:
   - os Gerbers das sete camadas;
   - a furação;
   - as posições;
   - a BOM pela netlist do agente;
   - `scripts/verificar_saidas.py`, que confere tudo.

   A pasta é apagada antes. Se um passo falhar, o fluxo diz em qual etapa e não apresenta os
   arquivos como prontos.

Quem decide continua sendo o código. O usuário só aprova o que já passou nas conferências, e
nenhuma resposta dele aprova um circuito reprovado.

**Paradas, sempre com relatório.** O fluxo para sem placa em cinco casos:

| Situação | Quando |
|---|---|
| `pendencias` | o briefing ou o agente registrou uma pendência (falta peça ou dado na base), ou a especificação pede o que o pipeline não faz |
| `reprovado` | o laço não aprovou o circuito |
| `recusado` | o usuário respondeu `n` na segunda aprovação |
| `falha_da_fabrica` | a geração ou a conferência dos arquivos falhou |
| `sem_placa` | a execução foi feita com `--sem-placa` |

Em todos eles, o `relatorio.md` diz o que foi feito, o que faltou e quais arquivos saíram, e
o terminal lista os arquivos que a execução produziu. Pendências bloqueiam a placa porque a
ferramenta `registrar_pendencia` existe justamente para o que um humano precisa resolver: um
circuito sem a peça que falta seria inconsistente com o pedido.

**O que o pipeline faz.** `restricoes_incompativeis` compara camadas, contorno e montagem com
os do `placas/monitor-umidade/spec.yaml`, a especificação da placa-modelo. O que não bate vira
pendência de origem `pipeline`, e o fluxo para antes de montar o circuito.

**Alimentação de cada peça.** O laço ganhou uma conferência entre a netlist e as regras,
`sem_alimentacao`. Toda peça cujos pinos na base têm tipo `alimentacao` ou `terra` precisa de
pelo menos um pino de cada tipo ligado. Um basta, porque os três GND do ESP32 são o mesmo
terra na placa de desenvolvimento. Ela usa só o `tipo` dos pinos, que já está na base, e
nenhuma regra nova foi escrita na base. Só o terceiro GND do ESP32, redundante, continua sem
ser detectado.

**O relatório de projeto (`src/relatorio.py`).** Ele só formata objetos que o código já
conferiu e não decide nada. As seções são:

- o resultado;
- as decisões da especificação, com quem decidiu, o motivo e a fonte, e as decisões
  registradas pelo agente;
- cada regra do motor, com a situação e o detalhe;
- cada conferência e correção;
- o DRC;
- a BOM, pela mesma netlist da `bom.csv`;
- as pendências;
- os arquivos da fábrica com o tamanho e a conferência;
- os custos por etapa.

O guia sugeria `saida/relatorio.md`. O relatório fica em `saida/projetos/<projeto>/`, junto
dos arquivos que descreve, porque `saida/monitor-umidade/` é do `make placa`, e um projeto
não pode sobrescrever o de outro.

**Ambiente.** Antes de chamar o modelo, o fluxo confere se o `kicad-cli` existe e se o `make
configurar` já foi feito (`fp-lib-table` e `sym-lib-table`). Se faltar algo, ele para sem
gastar nada.

**Evals do fluxo (`src/evals/fluxo.py`, `make eval-fluxo`).** São cinco pedidos em
`src/evals/pedidos/`:

- três da mesma placa: a frase do guia, outras palavras e com Wi-Fi;
- um com relé e bomba, que a base não tem;
- um impossível.

Um usuário de roteiro responde com as respostas do arquivo, depois "não sei", e `s` nas duas
aprovações. Há também dois erros injetados no circuito de referência depois do agente:

- `tira-vcc-do-sensor`, o exemplo do guia;
- `sensor-no-adc2`.

Um caso passa quando a situação final é a esperada. O pedido impossível nunca pode esperar
uma placa. A tabela nova de `docs/evals.md` recebe uma linha por caso.

## Consequências

- Um usuário vai do pedido aos Gerbers com um comando e duas respostas `s`. Cada parada tem
  explicação e relatório.
- O caminho de verdade (SKiDL, pcbnew, Freerouting, kicad-cli e a conferência dos arquivos)
  só roda dentro do container. O teste de ponta a ponta de `tests/test_projeto.py` usa um
  agente de roteiro com a placa e a fábrica reais, e é pulado fora dele.
- Os evals do fluxo e o `make projeto` chamam a API. Até o john rodar com a chave dele, as
  tabelas de `docs/evals.md` ficam vazias, e a checagem do marco com o modelo de verdade
  continua pendente.
- O fluxo só faz placas que caibam na placa de referência: o mesmo contorno e as mesmas
  peças, com as posições dela. Uma peça nova na base precisa de posição antes de virar placa,
  e outro contorno precisa de outra placa-modelo. Isso fica para quando houver uma segunda
  placa, fora do Marco 5.
- `VERSAO_DO_PROMPT` do laço subiu para 2 por causa do `PEDIDO_DO_USUARIO`. O prompt de
  sistema e o pedido de correção não mudaram.
