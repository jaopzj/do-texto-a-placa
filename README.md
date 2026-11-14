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

## Integração contínua

O GitHub Actions (`.github/workflows/testes.yml`) roda a cada push e pull request:
carrega a base e roda `tests/test_componentes.py`. Um YAML com erro deixa o pull request
com X vermelho. O runner do GitHub não tem o KiCad, então os testes da netlist e da placa
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
