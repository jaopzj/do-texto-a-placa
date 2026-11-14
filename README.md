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

## Integração contínua

O GitHub Actions (`.github/workflows/testes.yml`) roda a cada push e pull request:
carrega a base e roda `tests/test_componentes.py`, `tests/test_especificacao.py` e
`tests/test_ferramentas.py`. Um YAML com erro deixa o pull request com X vermelho. O runner do GitHub não tem o KiCad, então os testes da netlist e da placa
(e a conferência das bibliotecas do KiCad) rodam só no `make testes`, dentro do container.

## Estrutura

- `docker/`: Dockerfile e dependências Python
- `.github/workflows/`: integração contínua (GitHub Actions)
- `docs/adr/`: decisões de arquitetura registradas
- `docs/diario.md`: diário de bordo
- `componentes/`: base de componentes
- `placas/`: placas do projeto (a de referência é `monitor-umidade`)
- `src/`: código da plataforma
- `tests/`: testes automáticos
