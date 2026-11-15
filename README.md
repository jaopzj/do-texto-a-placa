# Do texto à placa

Plataforma de projeto de placas de circuito impresso conduzida por um agente de IA:
o usuário descreve o hardware em português e o agente entrega a placa pronta para
fabricação, usando o KiCad e verificações reais. A IA propõe, o código decide.

Status: em estruturação (Marco 3, base de componentes).

## Requisitos

- Windows com WSL2 (Ubuntu) ou Linux
- Docker Desktop, com a integração WSL ativada para o Ubuntu
- `make` e `git` instalados no Ubuntu

## Como rodar

```bash
make imagem      # constrói a imagem Docker (a primeira vez demora)
make configurar  # copia as tabelas de bibliotecas do KiCad para .home/ (uma vez só)
make versao      # confere KiCad, Java, Python e Freerouting dentro do container
make drc         # roda o DRC na placa de teste e salva o relatório em saida/
make netlist     # gera a netlist da placa de referência (SKiDL)
make posicionar  # gera a placa de referência com as peças nas posições de posicoes.yaml
make placa       # pipeline completo: netlist, placa, roteamento, DRC e arquivos da fábrica
make testes      # roda os testes automáticos (pytest)
make briefing PEDIDO="..."  # o agente transforma o pedido na especificação (Marco 5)
make shell       # abre um terminal dentro do container
```

O container usa como pasta pessoal (`HOME`) a pasta `.home/` do repositório, ignorada
pelo Git. É lá que o `make configurar` guarda a configuração do KiCad, para ela não
sumir entre um comando e outro. Se apagar a `.home/`, rode `make configurar` de novo.

## Pipeline (`make placa`)

Num clone novo: `make imagem`, `make configurar` e `make placa`. O `make placa` apaga as
saídas anteriores e, em ordem, para no primeiro passo que falhar:

1. `make netlist`: `placas/monitor-umidade/circuito.py` (SKiDL) gera a netlist;
2. `make posicionar`: a netlist entra na placa-modelo, as peças vão para as posições do
   `posicoes.yaml` e `scripts/verificar_placa.py` confere tudo contra a netlist;
3. roteamento no Freerouting (`scripts/spike/round_trip_freerouting.py`);
4. `scripts/verificar_placa.py` de novo, na placa roteada, e o DRC, que precisa terminar
   sem nenhuma violação e sem ligação pendente;
5. Gerbers, furação e posições pelo `kicad-cli`, e a BOM por `scripts/bom.py`, em
   `saida/fabrica/`;
6. `scripts/verificar_saidas.py` confere o DRC, os Gerbers, a furação, as posições e a BOM.

As entradas feitas à mão ficam no Git, e o pipeline só as lê:

| Entrada | Feita na | O que traz |
|---|---|---|
| `placas/monitor-umidade/pecas.md` | Partes 2 e 3 | pinagem medida e tabela de ligações |
| `placas/monitor-umidade/circuito.py` | Parte 4 | a tabela de ligações em SKiDL |
| `placas/monitor-umidade/modelo/` | Parte 5 | contorno e regras da placa |
| `placas/monitor-umidade/posicoes.yaml` | Parte 6 | posição e rotação de cada conector |

O `placas/monitor-umidade/gabarito.net` é a netlist de referência para os evals do
Marco 4. Ele não é gerado pelo pipeline, e um teste confere que a netlist gerada tem a
mesma estrutura.

## Base de componentes

Cada peça é um YAML em `componentes/`, no formato do modelo `src/componentes/modelo.py`.
Para usar a base no código:

```python
from src.componentes.carregar import carregar_todos
base = carregar_todos()   # {id: Componente}
```

Se qualquer arquivo tiver problema (campo faltando, campo desconhecido, tipo errado,
valor inconsistente, YAML quebrado ou `id` repetido), `carregar_todos()` não devolve nada e
levanta `ErroBase`, com o arquivo e o campo de cada erro. As regras estão no ADR-006. Uma peça com várias
fileiras de pinos (o ESP32, o conversor de nível) descreve cada fileira em `conectores`, com
seu símbolo e footprint (ADR-007). O
`make testes` também confere se o símbolo e o footprint de cada peça existem nas
bibliotecas do KiCad do container.

## Especificação da placa

A entrada do agente (Marco 4) é a especificação da placa, um YAML no formato do modelo
`src/especificacao.py`. A da placa de referência é `placas/monitor-umidade/spec.yaml`:
projeto, módulos (cada um com o id de um componente da base), alimentação e restrições.
Cada decisão diz quem a tomou em `decidido_por` (`usuario` ou `agente`), e uma decisão do
agente sempre traz motivo e fonte.

```python
from pathlib import Path
from src.especificacao import ler_especificacao
spec = ler_especificacao(Path("placas/monitor-umidade/spec.yaml"))
```

Com qualquer problema (campo errado, `decidido_por` fora dos dois valores, componente ou
regra que não está na base), `ler_especificacao()` levanta `ErroEspecificacao`, com o campo
de cada erro. As regras estão no ADR-009.

## Ferramentas do agente

O agente não escreve a netlist: ele chama seis ferramentas de `src/agente/ferramentas.py`,
e o código confere cada pedido contra a base antes de mudar o projeto.

| Ferramenta | O que faz |
|---|---|
| `buscar_componente(termo)` | procura na base, sem diferença de maiúsculas, acentos, espaços, `_` e `-` |
| `ler_dados_componente(id)` | devolve o componente como está no YAML |
| `selecionar_componente(id, ref)` | põe uma peça da base no projeto; id inexistente ou referência repetida são recusados |
| `conectar(ref, pino, rede)` | liga um pino (número ou nome da base) de uma peça selecionada a uma rede |
| `registrar_decisao(decisao, motivo, fonte)` | guarda uma decisão cuja fonte aponta para a base ou para a especificação |
| `registrar_pendencia(necessidade, motivo)` | guarda o que falta na base, para um humano resolver |

```python
from src.agente.ferramentas import Ferramentas
f = Ferramentas()                      # lê a base com carregar_todos()
f.selecionar_componente("sensor-umidade-capacitivo", "U3")
f.conectar("U3", "AOUT", "SENSOR")     # {"ok": True, ...}
f.selecionar_componente("nao-existe", "J9")  # {"ok": False, "erro": "componente_inexistente", ...}
```

Toda ferramenta devolve um dicionário com `ok`; na recusa, vêm também o código do erro, a
mensagem e o próximo passo, e o estado do projeto não muda. O contrato está no ADR-010.

O laço do agente (`src/agente/laco.py`, vindo do `agente_minimo.py` do protótipo) manda o
prompt e os contratos das ferramentas (`src/agente/contratos.py`) ao modelo e executa cada
pedido pelas ferramentas. O modelo fica atrás de um adaptador; o da API da Anthropic
(Claude Haiku 5.5 por padrão, ADR-014) está em `src/agente/provedores/claude.py` (ADR-011). Para rodar uma vez
sobre a placa de referência (a biblioteca `anthropic` já está na imagem; a chave vai na
variável `ANTHROPIC_API_KEY`, nunca no código):

```bash
python -m src.agente placas/monitor-umidade/spec.yaml --esforco medium
```

## Netlist do agente e eval do gabarito

`src/gerar_netlist.py` transforma o estado das ferramentas (`Ferramentas.estado()`) numa
netlist KiCad, pelo SKiDL, do mesmo jeito que o `circuito.py`: um conector por fileira de
pinos, símbolo e footprint da base, e os pinos que o agente não ligou na rede NC (ADR-012).
Antes de montar, confere o estado de novo contra a base e recusa o que não confere.

`src/evals/comparar.py` diz se duas netlists são o mesmo circuito. Ele compara os grupos de
pinos ligados, com cada pino identificado pela peça e pelo nome na base
(`"display-lcd-1602-i2c: SDA"`, ou `"esp32-devkitc-v4: GND#14"` quando o nome se repete), e
ignora o nome das redes, as referências e a ordem. Dentro do container:

```bash
python -m src.evals.comparar placas/monitor-umidade/gabarito.net outra.net
```

O comando sai com 0 se as netlists forem equivalentes e com 1 se não forem, mostrando o que
faltou ou sobrou e com quem cada pino divergente ficou ligado.

## Eval do gabarito (`make eval`)

`src/evals/rodar.py` roda o agente N vezes sobre o `spec.yaml` e, para cada execução, gera a
netlist, compara com o `gabarito.net` e registra se bateu, quantas tentativas de peça
inexistente houve, quantas chamadas e quanto custou (ADR-013). A meta é 4 de 5 execuções
equivalentes. Chama a API da Anthropic, então custa dinheiro:

```bash
export ANTHROPIC_API_KEY=...      # só no terminal; nunca em arquivo ou commit
make eval N=5 OBS="primeira rodada"
```

`MODELO` e `ESFORCO` trocam o modelo e o esforço (padrão: `claude-haiku-5-5` e `high`).
Os modelos com preço conhecido são `claude-opus-5-5`, `claude-sonnet-5-5` e
`claude-haiku-5-5` (ADR-014); o esforço vai de `low` a `max`. Por exemplo:

```bash
make eval N=1 MODELO=claude-opus-5-5 ESFORCO=medium OBS="opus medium"
```

Enquanto roda, o terminal mostra cada passo do agente (tempo, tokens, custo até agora e o
que ele pensou) e cada ferramenta (`ok` ou `ERRO` com o motivo). A rodada entra na tabela
de `docs/evals.md`, e o registro completo de cada execução fica em `saida/evals/`.

## Briefing e primeira aprovação (`make briefing`)

O briefing (Marco 5, Partes 1 e 2; ADR-016) substitui o `spec.yaml` escrito à mão. O agente
recebe o pedido em português, consulta a base de componentes, faz no máximo seis perguntas
e entrega a especificação, que o código valida pelo mesmo caminho do `spec.yaml`
(`src/especificacao.py`). Se ela tiver problema, a lista volta ao agente, que corrige. O
código também confere que toda decisão do agente cita um documento que existe (um arquivo
do repositório, como `componentes/<id>.yaml`, ou um documento citado pela base) e que toda
pergunta respondida com "não sei" virou decisão do agente (`decidido_por: agente`).

Com a especificação válida, o terminal mostra o resumo da primeira aprovação: componentes
escolhidos (com aviso para os que estão em `rascunho`), decisões tomadas pelo agente, com
motivo e fonte, pendências e custo estimado (a base ainda não tem preços, então o custo não
é estimado). Responda `s` para seguir ou escreva a correção em português, que volta para o
agente. Chama a API da Anthropic, como o `make eval`:

```bash
export ANTHROPIC_API_KEY=...      # só no terminal; nunca em arquivo ou commit
make briefing PEDIDO="quero um monitor de umidade do solo com ESP32 e um LCD"
```

A especificação aprovada vai para `saida/briefing/<projeto>/spec.yaml`, com a conversa
(perguntas, respostas, entregas recusadas, correções, tokens e custo) em `briefing.yaml` ao
lado. Ela é a entrada do agente do Marco 4: `python -m src.agente saida/briefing/<projeto>/spec.yaml`.
Se o agente escrever uma pergunta em texto, em vez de usar a ferramenta, o código o lembra
de usar a ferramenta (até três vezes seguidas), em vez de encerrar o briefing. O registro
completo do último briefing fica em `saida/briefing/registro.txt`.
`MODELO` e `ESFORCO` funcionam como no `make eval`. Fora do container:
`python -m src.briefing "pedido" [--andamento]`, onde `--andamento` mostra cada passo do
agente.

## Integração contínua

O GitHub Actions (`.github/workflows/testes.yml`) roda a cada push e pull request:
carrega a base e roda `tests/test_componentes.py`, `tests/test_especificacao.py`,
`tests/test_ferramentas.py`, `tests/test_agente.py`, `tests/test_comparar.py`,
`tests/test_gerar_netlist.py`, `tests/test_rodar.py`, `tests/test_terminal.py`,
`tests/test_briefing.py` e `tests/test_aprovacao.py` (a parte que não precisa do SKiDL). Um YAML com erro deixa o pull request com X vermelho. O runner do GitHub não tem o KiCad, então os testes da netlist e da placa
(e a conferência das bibliotecas do KiCad) rodam só no `make testes`, dentro do container.

## Estrutura

- `docker/`: Dockerfile e dependências Python
- `.github/workflows/`: integração contínua (GitHub Actions)
- `docs/adr/`: decisões de arquitetura registradas
- `docs/diario.md`: diário de bordo
- `componentes/`: base de componentes
- `placas/`: placas do projeto (a de referência é `monitor-umidade`)
- `src/`: código da plataforma (`src/evals/`: os evals do agente)
- `tests/`: testes automáticos
