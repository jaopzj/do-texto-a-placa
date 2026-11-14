# ADR-013: Eval do gabarito e versões fixas da imagem

Status: aceito · Data: 2026-11-14

## Contexto

A Parte 6 do Marco 4 pede `src/evals/rodar.py`, que roda o agente N vezes sobre o
`spec.yaml` e registra, para cada execução, se a netlist bateu com o gabarito, quantas
tentativas de peça inexistente houve, quantas chamadas e quanto custou. Os números vão para
uma tabela em `docs/evals.md`, com a data e a versão do prompt, e a meta sugerida é 4 de 5
execuções equivalentes. A chave da API fica numa variável de ambiente, nunca no código.

Para isso o agente precisa rodar dentro do container, onde estão o SKiDL e as bibliotecas do
KiCad que o `gerar_netlist.py` usa. A biblioteca `anthropic` não estava na imagem (ADR-010 e
ADR-011 deixaram a entrada dela para esta parte, com a aprovação do john). O
`docker/requirements.txt` não fixava nenhuma versão: reconstruir a imagem para somar a
`anthropic` reinstalaria o SKiDL e o resto na versão mais nova do PyPI, e a netlist poderia
mudar sem ninguém ter pedido.

O custo também não saía certo: o laço somava toda a entrada num número só, mas a leitura e a
gravação do cache têm preços diferentes da entrada comum.

## Decisão

**Imagem.** O `docker/requirements.txt` passa a fixar, com `==`, as versões que estavam na
imagem que passou nos testes, e ganha `anthropic==2.8.0`. O john escolheu essa opção num
cartão de decisão (2026-11-14). Para mudar uma versão, altere o arquivo e registre num ADR,
como o Dockerfile já pede.

**Custo.** A `Resposta` do laço ganha `tokens_cache_leitura`, `tokens_cache_escrita` e
`custo_usd`, e a `Execucao` soma os três. O adaptador da Anthropic calcula o custo de cada
resposta pela tabela `PRECOS` (US$ por milhão de tokens: entrada, saída, leitura e gravação
do cache com TTL de 5 minutos), usando o modelo que de fato respondeu, que pode ser o
reserva. Modelo fora da tabela dá custo `None`, e a rodada mostra `?`: preço chutado não
entra no registro.

**Eval (`src/evals/rodar.py`).** Cada execução usa ferramentas novas e um provedor novo, para
nenhuma conversa vazar para a seguinte. Ao fim do laço, o estado vira netlist
(`gerar_netlist`) e é comparado com o gabarito (`comparar`, ADR-012). Erro da API, estado
que não vira netlist e netlist que não dá para ler contam como execução não equivalente, com
o motivo, e o eval segue. Cada execução grava em `saida/evals/<data>_<hora>/<n>/` o registro
do laço, o estado, a netlist e o resultado em JSON; a rodada grava `rodada.md`. A meta é
4 de 5, ou a mesma proporção para outro N.

**Registro.** `--registrar` acrescenta a linha da rodada à tabela de `docs/evals.md`, depois
do marcador da tabela, com data, versão do prompt, modelo, esforço, acertos, meta, peças
inexistentes, média de chamadas, custo médio e total e uma observação. O modelo e o esforço
podem ser trocados (`--modelo`, `--esforco`), para medir o custo de cada combinação, e o
padrão continua o do ADR-011 (Claude Opus 5.5, esforço `high`).

**Comando.** `make eval` repassa ao container só a variável `ANTHROPIC_API_KEY` do terminal,
e só neste alvo, e para antes de chamar o Docker se ela não estiver definida.

O texto do pedido ao agente (`PEDIDO` e `montar_pedido`) foi de `src/agente/__main__.py`
para `src/agente/laco.py`, junto do prompt de sistema, porque o eval também usa e porque ele
também é prompt: muda junto com `VERSAO_DO_PROMPT`. O texto não mudou, e a versão continua
"1".

## Consequências

- Os testes do eval rodam sem a API: um provedor de roteiro pede as ligações do
  `circuito.py`, e o eval tem de achar a netlist equivalente; outro troca SDA e SCL, outro
  tenta uma peça inexistente, outro falha na rede, e cada um tem de sair medido certo.
- Rodar o eval de verdade custa dinheiro (cerca de US$ 0,35 por execução no Opus 5.5 com
  esforço `high`, pela primeira medida do john) e só acontece quando alguém roda
  `make eval` com a chave. A tabela de `docs/evals.md` só ganha linhas assim.
- Se o resultado for ruim, o guia manda melhorar as descrições das ferramentas e o prompt,
  subir `VERSAO_DO_PROMPT` e rodar de novo: cada rodada vira uma linha nova.
- Uma versão nova de qualquer biblioteca só entra na imagem por mudança explícita no
  `requirements.txt`.
- A tabela `PRECOS` precisa ser atualizada, com a data, se a Anthropic mudar os preços.
