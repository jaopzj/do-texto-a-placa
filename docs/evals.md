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
