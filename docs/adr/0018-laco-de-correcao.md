# ADR-018: Laço de correção com motor de regras e DRC

Status: aceito · Data: 2026-11-16

## Contexto

A Parte 4 do Marco 5 pede o laço de correção:

- depois de gerar a netlist, rodar o motor de regras; depois de rotear, rodar o DRC;
- se houver problema, montar um relatório curto e estruturado (qual regra, onde, por quê)
  e devolver ao agente, pedindo a correção;
- no máximo três tentativas. Se o agente não resolver, o programa para e explica o problema
  ao usuário, em português, em vez de entregar uma placa errada.

O guia deixa em aberto como o agente desfaz uma ligação (o Marco 4 não tinha ferramenta para
isso), como a netlist do agente chega ao roteamento (o `posicoes.yaml` é por referência, e
as referências do agente não são as do gabarito) e o que conta como uma tentativa.

## Decisão

**Ordem das conferências (`src/correcao.py`).** A cada rodada, o código confere três coisas,
nesta ordem:

1. a netlist: `planejar`, a mesma conferência da netlist;
2. o motor de regras (ADR-017). Toda regra de `erro` violada ou não verificável vira um
   problema;
3. a placa: netlist, placa, posições, roteamento e DRC (`src/drc.py`). Ela só roda se 1 e 2
   não acharam nada, porque não adianta rotear um circuito que viola uma regra.

**Relatório ao agente.** O relatório é um JSON com um item por problema, com os campos
`etapa`, `regra`, `onde`, `porque` e `correcao`. Ele volta ao agente na mesma conversa: o
laço genérico ganhou `retomar`, que manda o texto por `Provedor.responder` em vez de iniciar
de novo. O relatório não tem nenhum campo para ignorar uma regra, e o agente não chega ao
motor. Ele só corrige o circuito.

**Tentativas.** `MAX_CORRECOES = 3` pedidos de correção depois do circuito entregue. O laço
para sem aprovar em quatro casos:

- `limite`: acabaram as três correções;
- `sem_mudanca`: o agente não mudou o circuito numa correção, então repetir o pedido não
  adiantaria. Isso economiza chamadas quando o problema não tem solução por ligação, como um
  dado que falta na base;
- `sem_circuito`: o agente não selecionou nenhuma peça;
- `placa`: um passo do caminho da placa falhou (por exemplo, uma peça sem posição), e o
  agente não tem como resolver isso.

`explicar` diz em português o motivo, cada problema que ficou, com onde e como corrigir, e as
pendências que o agente registrou. Nenhuma placa é entregue.

**`desconectar`, só no laço de correção.** É a sétima ferramenta: ela tira um pino da rede
em que está. `Ferramentas(..., correcao=True)` a liga, e `CONTRATOS_DE_CORRECAO` traz o
contrato. O agente do Marco 4 e o eval continuam com as seis ferramentas e o mesmo prompt,
então a medição do eval (ADR-013) não muda. O prompt do laço é o do agente com um parágrafo
sobre o relatório (`SISTEMA_DE_CORRECAO`, `VERSAO_DO_PROMPT = "1"`).

**Posições pela placa de referência.** O `value` de cada conector é o mesmo na netlist do
agente e no `gabarito.net` (por exemplo, `esp32-devkitc-v4 J2`). A posição de um conector do
agente é a do conector do gabarito com o mesmo `value`. Uma peça que a referência não tem, ou
duas da mesma, não ganha posição, e a placa não é feita: o código não inventa um lugar. Os
passos são os do `make placa`, com os mesmos scripts, e o DRC roda em JSON
(`kicad-cli pcb drc --severity-all --format json`). Itens com severidade `ignore` não contam.

**Comando.** `python -m src.correcao [spec] [--sem-placa]` e `make correcao`, que precisa da
`ANTHROPIC_API_KEY`, como o `make eval`. Saídas:

- `saida/correcao/<projeto>/estado.json` e `correcao.json`, com as rodadas e os problemas de
  cada uma;
- `rodada-N/`, com a placa roteada e o `drc.json` de cada rodada que chegou ao DRC;
- o custo, no registro de custos (ADR-017): `agente` para o circuito entregue, `correcao`
  para as correções, e `motor_de_regras` e `drc` para as operações.

## Consequências

- Enquanto a base não tiver a tensão da saída AOUT do sensor (ADR-017), o circuito de
  referência não é aprovado: a regra `gpio-not-5v-tolerant` volta como não verificável. O
  agente não tem como resolver isso por ligação, e o laço para com `sem_mudanca` ou
  `limite`, explicando o que falta. É o comportamento pedido: parar e explicar, em vez de
  entregar uma placa sem a conferência.
- O DRC só aponta o que a placa mostra: folga, ligação sem trilha, peça fora do contorno. O
  agente controla as ligações, não o posicionamento, então um problema de posição (que é o
  da placa de referência) tende a terminar no limite, com a explicação.
- O caminho de verdade até o DRC só roda dentro do container (`make testes`). No GitHub
  Actions, os testes usam um provedor de roteiro e uma placa falsa.
- O erro injetado da Parte 6 do guia já tem a porta: `corrigir(..., depois_do_agente=...)`
  roda depois do agente e antes da primeira conferência. Os testes usam isso para tirar o
  sensor do IO34 e pôr no IO25, e o laço detecta e corrige. Os pedidos de eval da Parte 6
  ficam para a Parte 6.
- O relatório de projeto e a segunda aprovação (Parte 5) não fazem parte desta decisão.
