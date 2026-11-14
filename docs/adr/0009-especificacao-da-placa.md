# ADR-009: Modelo da especificação da placa

Status: aceito · Data: 2026-11-14

## Contexto

O Marco 4 (guia do MVP, Parte 2) pede um modelo Pydantic para a especificação da placa,
"no mesmo estilo do modelo de componentes": projeto, módulos (com o id do componente na
base), alimentação e restrições, com `decidido_por` (`usuario` ou `agente`) em cada decisão.
A proposta (página 9) mostra um exemplo, com um comentário por linha dizendo quem decidiu.

Do jeito mínimo, alguns erros passariam sem aviso: um id de componente com erro de
digitação, uma decisão do agente sem justificativa, um `decidido_por: usuário` com acento
que ninguém confere, ou uma regra da base citada que não existe.

## Decisão

`src/especificacao.py` segue as regras do ADR-006 (campo desconhecido é erro, nenhum tipo é
convertido, texto obrigatório não pode ser vazio, tensões e medidas positivas) e define:

- `projeto` (id no formato dos ids da base, nome e descrição), que descreve o pedido e não é
  uma decisão;
- `modulos`: pelo menos um; cada módulo é uma decisão com `papel` (único na placa),
  `componente` (id da base) e `requisitos` opcionais, cada requisito também uma decisão;
- `alimentacao`: decisão com `origem` (hoje só `usb_do_devkit`) e `tensao` em volts;
- `restricoes`: `camadas`, `contorno` (largura e altura em milímetros) e `montagem`
  (`barra_pinos_macho` ou `barra_pinos_femea`, os termos do ADR-005 e do ADR-008), cada uma
  uma decisão.

Toda decisão herda de `Decisao`: `decidido_por` obrigatório, só `usuario` ou `agente`, e
`motivo`, `fonte` (o mesmo `Fonte` da base: documento e página) e `regras` (regras da base,
por id do componente e id da regra) opcionais. Uma decisão do agente exige `motivo` e
`fonte`, como a ferramenta `registrar_decisao(decisao, motivo, fonte)` da Parte 3 do guia.
Uma decisão do usuário não exige motivo, porque a fonte é o próprio pedido.

As listas fechadas (`origem`, `montagem`) só têm os valores que o projeto já usa. Um valor
novo entra no modelo junto com a placa que precisar dele.

`ler_especificacao(arquivo, base)` lê o YAML com o mesmo carregador da base (recusa chave
repetida), valida pelo modelo e cruza as referências com `carregar_todos()`: todo
`componente` existe na base, e toda regra citada existe e é de um módulo da placa. Ele
junta todos os problemas num único `ErroEspecificacao`, com o arquivo e o campo, e não
devolve nada se houver algum.

O modelo não confere dados elétricos (tensão da alimentação contra a dos módulos, níveis
lógicos). Isso é trabalho do motor de regras, que lê a base.

No `placas/monitor-umidade/spec.yaml`, `decidido_por` segue a página 9 da proposta. O que
a proposta não cobre ou o que o john decidiu depois cita o documento da decisão: o modelo
do ESP32 e do sensor (`pecas.md`, Marco 3, Parte 6), o contorno (placa-modelo, Marco 2,
Parte 5) e a montagem com barra macho (ADR-008, que substitui a barra fêmea da proposta).

## Consequências

- O agente do Marco 4 recebe uma entrada validada, e um id inventado é recusado antes de
  qualquer ligação.
- Toda decisão do agente fica com motivo e fonte, e o eval pode separar erro de
  entendimento (especificação errada) de erro de execução (netlist errada).
- `tests/test_especificacao.py` só precisa do Pydantic e do PyYAML e roda também no GitHub
  Actions.
- Mudar o formato da especificação passa por este modelo e pelos testes.
