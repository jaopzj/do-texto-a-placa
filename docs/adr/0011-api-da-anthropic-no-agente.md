# ADR-011: O agente usa a API da Anthropic

Status: aceito · Data: 2026-11-14 · Substitui a parte do provedor no ADR-010

## Contexto

O ADR-010 trouxe o laço do `agente_minimo.py` com o adaptador do Gemini
(`src/agente/provedores/gemini.py`), que era o provedor usado no protótipo. Em 2026-11-14 o
john decidiu que o agente passa a usar a API da Anthropic.

Como o laço só conversa com um objeto `Provedor` (`iniciar` e `continuar`), a troca fica
toda no adaptador: o laço, os contratos e as ferramentas não mudam.

## Decisão

- `src/agente/provedores/claude.py` (`ProvedorClaude`) é o adaptador do agente e o único
  módulo que importa a biblioteca `anthropic` (versão 2.8.0). O arquivo não se chama
  `anthropic.py` para não confundir com a biblioteca.
- Modelo `claude-opus-5-5`, com raciocínio adaptativo (`thinking: {type: "adaptive"}`) e
  esforço `high`, porque o trabalho é um laço com muitas chamadas de ferramenta (o padrão do
  modelo é `medium`). `max_tokens` de 16000 por resposta, sem streaming.
- Os contratos de `contratos.py` viram ferramentas da API (`input_schema` = o JSON Schema do
  contrato). Os argumentos continuam validados pelas ferramentas, que são a garantia.
- O conteúdo inteiro de cada resposta volta para o histórico, inclusive os blocos de
  raciocínio, e o histórico só cresce no fim (nada é editado). Os resultados de todas as
  ferramentas de um passo voltam numa só mensagem, com `is_error` quando `ok` é falso.
- Cache automático de prompt (`cache_control` no pedido), porque o prompt de sistema e os
  contratos são iguais em todos os passos.
- Recusa de segurança: o pedido vai com `fallbacks: "default"` (beta
  `server-side-fallback-2026-07-01`), e a própria API tenta num modelo reserva. Se a resposta
  final ainda for uma recusa, ou se ela for cortada no limite de tokens, o adaptador não
  devolve nenhum pedido de ferramenta e o laço termina com o motivo no texto.
- A chave vem de `ANTHROPIC_API_KEY` (ou de um login com `ant auth login`), lida pela
  biblioteca.
- O adaptador do Gemini sai do código (fica no histórico do Git, commit 3f2b5ff).

## Consequências

- `python -m src.agente` roda com o Claude. O custo de cada execução aparece nos tokens que
  a `Execucao` soma (a entrada inclui os tokens lidos e gravados no cache).
- `anthropic` ainda não está em `docker/requirements.txt`: entra, com a versão fixada,
  quando o agente for rodar no container (Parte 6), com a aprovação do john.
- Os testes do adaptador usam um cliente falso e são pulados onde a biblioteca não existe.
- Voltar ao Gemini, ou trocar de provedor de novo, é escrever outro adaptador e um ADR novo.
