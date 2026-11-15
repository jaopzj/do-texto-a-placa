# ADR-016: Briefing e primeira aprovação

Status: aceito · Data: 2026-11-15

Número: o ADR-015 (eval com pinos equivalentes) está no PR #32, ainda aberto; este fica com
o 016 para os dois não colidirem.

## Contexto

As Partes 1 e 2 do Marco 5 pedem que o agente transforme um pedido em texto livre na
especificação da placa, no lugar do `spec.yaml` escrito à mão:

- `src/briefing.py`, com um prompt que explica o formato da especificação e as perguntas
  típicas (montagem do microcontrolador, alimentação, display, tamanho);
- um limite de perguntas (o guia sugere seis);
- para cada "não sei", o agente escolhe um padrão sensato e marca `decidido_por: agente`;
- a especificação passa pelo modelo Pydantic e, se for inválida, o erro volta ao agente;
- depois do briefing, um resumo no terminal (componentes, decisões do agente, custo
  estimado se houver preços), e o usuário responde `s` ou escreve uma correção, que volta
  para o agente.

O guia deixa em aberto como o agente conversa com o usuário, como o código sabe que uma
resposta foi "não sei", o que vale como fonte de uma decisão tomada no briefing, como a
correção volta ao agente e onde a especificação aprovada fica.

## Decisão

**O mesmo laço, outras ferramentas.** O laço do Marco 4 (`laco.py`) virou `conversar`, que
recebe prompt, contratos e quem executa as ferramentas, e pode parar por uma condição
(`encerrar`). `rodar_agente` continua igual por fora e usa `conversar`. O briefing usa o
mesmo laço e o mesmo adaptador (`provedores/claude.py`), sem mudar o `Provedor`: o usuário
chega ao agente só por ferramentas. São cinco:

- `buscar_componente`, `ler_dados_componente` e `registrar_pendencia`, as do agente do
  Marco 4, com os mesmos contratos (o objeto é o mesmo, não uma cópia). O briefing não
  seleciona nem liga peças;
- `perguntar_usuario(pergunta, sobre)`: uma pergunta por chamada. `sobre` diz de que parte
  da especificação ela trata: `projeto`, `alimentacao`, `restricoes.camadas`,
  `restricoes.contorno`, `restricoes.montagem` ou `modulo:<papel>`;
- `entregar_especificacao(especificacao)`: a especificação em YAML.

**Limite de perguntas no código.** `MAX_PERGUNTAS = 6`. Da sétima em diante, a ferramenta
recusa (`limite_de_perguntas`) sem chegar ao usuário e manda decidir com padrões.

**"Não sei" conferido pelo código.** Uma resposta vazia, ou que começa por "não sei", "sei
lá", "tanto faz", "você decide" e semelhantes (sem maiúsculas, acentos e pontuação), é "não
sei". O resultado da pergunta avisa o agente, e, na entrega, toda decisão sobre o assunto
da pergunta precisa estar com `decidido_por: agente` (e, pelo ADR-009, com motivo e fonte).
Um `modulo:<papel>` sem módulo com esse papel também é recusado. Os padrões do projeto para
montagem, camadas e contorno (`PADROES`: barra macho, 2 camadas, 100 x 100 mm) vão no
prompt, cada um com o documento que o sustenta.

**Validação da entrega.** O YAML passa por `especificacao_de_texto`, separada de
`ler_especificacao`, o mesmo caminho do `spec.yaml` escrito à mão: carregador que recusa
chave repetida, modelo estrito e referências à base. Por cima disso, só no briefing:

- toda decisão do agente cita em `fonte.documento` um documento que existe: um arquivo do
  repositório (caminho relativo, dentro do repositório) ou um documento que a base cita nas
  fontes dos pinos. É a mesma ideia do `registrar_decisao` (ADR-010): o que o código não
  confere, não vale. O `spec.yaml` escrito à mão não passa por essa regra, porque cita a
  proposta, que não está no repositório;
- as respostas "não sei", como acima.

Todos os problemas voltam juntos ao agente (`especificacao_invalida`), e ele entrega de
novo. O formato da especificação no prompt é o JSON Schema do próprio modelo Pydantic, para
nunca ficar desatualizado.

**Primeira aprovação dentro da entrega.** Com a entrega válida, o código chama a aprovação
(`src/aprovacao.py`), que mostra o resumo e lê a resposta. `s` ou `sim` aprova, e o laço para
ali (`encerrar`), sem mais uma chamada ao modelo. Qualquer outro texto é correção e volta ao
agente como resultado da mesma entrega (`correcao_do_usuario`), com a conversa inteira no
histórico; ele ajusta e entrega de novo, e a aprovação aparece outra vez. Resposta vazia
pergunta de novo. O resumo mostra os componentes (com aviso para os que estão em
`rascunho`), alimentação e placa, as decisões do agente com motivo, fonte e regras, as
pendências e o custo. A base ainda não tem preços, então o custo aparece como não
estimado; nenhum valor é chutado.

**Gravação.** A especificação aprovada é reescrita pelo código a partir do modelo validado
(não é o texto do modelo) em `saida/briefing/<projeto.id>/spec.yaml`, com um cabeçalho que
diz que veio do briefing. Ao lado, `briefing.yaml` guarda o pedido, a versão do prompt, as
perguntas e respostas, as entregas recusadas, as correções, as pendências, os tokens e o
custo. A pasta não é `saida/<projeto>/`, que o `make placa` apaga. Nada é gravado sem
aprovação, nem num cancelamento (fim da entrada ou Ctrl+C).

**Comandos.** `python -m src.briefing "pedido"` (com `--modelo`, `--esforco`, `--saida` e
`--andamento`) e `make briefing PEDIDO="..."`, que roda o container com `-it` e repassa só a
`ANTHROPIC_API_KEY`, como o `make eval`. Saída 0 com a especificação gravada, 1 sem
aprovação, 130 cancelado.

## Consequências

- O agente do Marco 4 lê a especificação do briefing como lê o `spec.yaml`:
  `python -m src.agente saida/briefing/<projeto>/spec.yaml`.
- Os testes (`tests/test_briefing.py`, `tests/test_aprovacao.py`) usam um provedor falso e
  um usuário de roteiro, sem chamar o modelo, e rodam no GitHub Actions.
- O código não consegue conferir se uma decisão marcada `usuario` veio mesmo do usuário
  (fora das respostas "não sei"). O resumo lista quem decidiu cada módulo, para o usuário
  pegar isso na aprovação.
- Se o modelo perguntar em texto solto em vez de usar `perguntar_usuario`, o laço termina
  sem especificação e o programa diz isso. Responder a ele exigiria mudar o `Provedor`; fica
  para quando aparecer nas execuções reais.
- Uma peça que a base não tem vira pendência, aparece na aprovação e fica fora da
  especificação. A especificação não guarda pendências: elas ficam no `briefing.yaml`.
- O motor de regras, o laço de correção e a segunda aprovação (Partes 3 a 5) não fazem parte
  desta decisão. As regras da base entram no briefing só como conhecimento do agente,
  citadas em `regras`; quem as confere é o motor de regras, na Parte 3.
