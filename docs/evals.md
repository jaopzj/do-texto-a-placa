# Evals do agente

Cada linha é uma rodada do eval do gabarito (`src/evals/rodar.py`, ADR-013): o agente roda
N vezes sobre `placas/monitor-umidade/spec.yaml`, a netlist de cada execução é gerada pelo
`src/gerar_netlist.py` e comparada com o `gabarito.net` pela estrutura
(`src/evals/comparar.py`, ADR-012).

- **Equivalentes:** execuções cuja netlist tem os mesmos componentes e os mesmos grupos de
  pinos ligados do gabarito. Erro da API, da geração ou da leitura conta como não equivalente.
- **Meta:** 4 de 5 execuções equivalentes (guia do MVP, Parte 6), ou a mesma proporção
  para outro N.
- **Peças inexistentes:** soma, na rodada, das tentativas de selecionar um id que não está
  na base.
- **Custo:** em dólares, pelos tokens que a API informou e pela tabela `PRECOS` de
  `src/agente/provedores/claude.py`. `?` quando algum modelo não estava na tabela.
- **Prompt:** `VERSAO_DO_PROMPT` de `src/agente/laco.py`. Toda mudança no prompt de sistema,
  no pedido ou nos contratos sobe a versão e vira uma rodada nova.

Os detalhes de cada execução (registro do laço, estado, netlist e diferenças) ficam em
`saida/evals/<data>_<hora>/`, fora do Git.

## Rodadas

<!-- rodadas: rodar.py --registrar acrescenta as linhas abaixo -->
| Data | Prompt | Modelo | Esforço | Equivalentes | Meta | Peças inexistentes | Chamadas (média) | Custo médio (US$) | Custo total (US$) | Observação |
|---|---|---|---|---|---|---|---|---|---|---|
| (nenhuma rodada registrada ainda) | | | | | | | | | | |

## Fluxo completo (Marco 5, Parte 6)

Cada linha é um caso do eval do fluxo (`src/evals/fluxo.py`, ADR-019), registrado com
`make eval-fluxo REGISTRAR=--registrar`.

- **Pedidos** (`src/evals/pedidos/*.yaml`): o fluxo inteiro, do briefing aos arquivos da
  fábrica, com um usuário de roteiro (as respostas do arquivo, depois "não sei", e `s` nas
  duas aprovações). Passa quando a situação final está entre as esperadas:
  - `1-frase-do-guia`, `2-outras-palavras` e `3-com-wifi` (a mesma placa): `fabrica` (ou
    `sem_placa`, numa rodada com `--sem-placa`);
  - `4-peca-fora-da-base` (relé e bomba, que a base não tem): `pendencias`;
  - `5-impossivel` (2 x 2 cm, pilha de 1,5 V, motor de 220 V): `pendencias`, `reprovado` ou
    `sem_especificacao`, sempre sem placa e com a explicação no relatório.
- **Erros injetados**: o agente monta a placa de referência e, depois que ele termina, o
  código estraga o circuito. Passa quando a primeira conferência aponta o erro e o laço
  termina aprovado:
  - `tira-vcc-do-sensor`: tira a ligação do VCC do sensor (o exemplo do guia);
  - `sensor-no-adc2`: leva o sinal do sensor para o IO25, do ADC2.
- **Prompt:** `b<briefing>+c<correção>`, as versões de `src/briefing.py` e `src/correcao.py`.
- **Custo:** em dólares, calculado pela tabela de preços; `?` quando algum modelo não tinha
  preço ou a API falhou.

Os detalhes de cada caso (terminal, relatório, especificação, placa, arquivos da fábrica e
custos) ficam em `saida/evals/fluxo/<data>_<hora>/<caso>/`, fora do Git.

<!-- fluxo: fluxo.py --registrar acrescenta as linhas abaixo -->
| Data | Prompt | Modelo | Esforço | Placa | Caso | Tipo | Esperado | Obtido | Passou | Custo (US$) | Detalhe |
|---|---|---|---|---|---|---|---|---|---|---|---|
| (nenhuma rodada registrada ainda) | | | | | | | | | | | |
