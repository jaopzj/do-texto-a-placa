# Placa de teste (`teste`) — fixture do spike

Esta pasta contém o circuito mínimo usado como **fonte única de verdade** da
entrada do spike "do-texto-a-placa" (issue **M1-1** do Marco 1).

O arquivo canônico desta issue é a netlist [`teste/teste.net`](teste/teste.net),
versionada no git. Não gere outra netlist por conta própria: duas fontes de
verdade divergem e quebram o pipeline. SKiDL fica fora deste marco.

## 1. Como a netlist foi gerada

A netlist foi exportada manualmente pela GUI do KiCad:

1. Abrir o esquemático `teste/teste.kicad_sch` no **Eeschema** (KiCad 10.x).
2. Menu **Arquivo → Exportar → Netlist** (ou **Ferramentas → Gerar Netlist**).
3. Escolher o formato **KiCad** (netlist nativa, s-expression — o arquivo começa
   com `(export (version "E") ...`).
4. Salvar como `teste/teste.net`.

A ferramenta que gerou o arquivo foi o `Eeschema 10.0.8` (ver campo `(tool ...)`
no topo da netlist).

## 2. Mapa componente → footprint

A netlist descreve três componentes:

| Ref | Value          | Footprint                                                        |
|-----|----------------|-----------------------------------------------------------------|
| D1  | LED VERMELHO   | `LED_THT:LED_D5.0mm`                                             |
| J1  | Conn_01x02     | `Connector_PinHeader_2.54mm:PinHeader_1x02_P2.54mm_Vertical`    |
| R1  | 330 Ω          | `Resistor_SMD:R_0805_2012Metric`                                |

Ligações (nets): R1 e o anodo (A) do D1 ligados; catodo (K) do D1 ao pino 2 do
J1; pino 1 do J1 ao outro terminal do R1. É um LED com resistor de 330 Ω levado
a um conector de duas vias.

## 3. Aviso sobre `KICAD*_SYMBOL_DIR` / `fp-lib-table`

Ao rodar ferramentas baseadas em SKiDL/KiCad dentro do container (ver
`skidl_REPL.log` na raiz do repositório) aparecem avisos como:

```
WARNING: KICAD9_SYMBOL_DIR environment variable is missing, so the default
         KiCad symbol libraries won't be searched.
WARNING: KICAD8_SYMBOL_DIR environment variable is missing ...
WARNING: KICAD_SYMBOL_DIR  ... / KICAD6_SYMBOL_DIR ... / KICAD10_SYMBOL_DIR ...
WARNING: fp-lib-table file was not found. Component footprints are not available.
```

### Por que acontece

O container não define as variáveis de ambiente `KICAD*_SYMBOL_DIR` que apontam
para as bibliotecas de símbolos do KiCad, nem possui uma `fp-lib-table` (tabela
de bibliotecas de footprints) no `HOME` do usuário. Sem elas, uma ferramenta que
resolve símbolos/footprints "do zero" não encontra as bibliotecas padrão.

### Por que NÃO bloqueia esta issue

A netlist `teste.net` **já traz o footprint embutido** em cada componente
(campo `(footprint "...")`). Portanto a validação da M1-1 não depende das
bibliotecas do KiCad — ela lê o footprint direto do arquivo. Os avisos são
inofensivos para este marco.

### Como contornar dentro do container

Se/quando uma etapa futura realmente precisar resolver símbolos/footprints pelas
bibliotecas do KiCad, aponte as variáveis para as libs instaladas na imagem e,
se necessário, exporte uma `fp-lib-table`. Dentro do container:

```bash
# Descobrir onde as libs do KiCad foram instaladas (ajuste a versão conforme a imagem):
export KICAD_SYMBOL_DIR=/usr/share/kicad/symbols
export KICAD10_SYMBOL_DIR=/usr/share/kicad/symbols
# (defina também KICAD6/7/8/9_SYMBOL_DIR para o mesmo caminho se a ferramenta reclamar)

# fp-lib-table global no HOME do usuário do container (HOME=/tmp no Makefile):
mkdir -p "$HOME/.config/kicad"
cp /usr/share/kicad/template/fp-lib-table "$HOME/.config/kicad/fp-lib-table" 2>/dev/null || true
```

Confirme o caminho real das libs com `kicad-cli version` e
`ls /usr/share/kicad/` na imagem antes de fixar os valores.

## 4. Validação

O script [`scripts/spike/valida_netlist.sh`](../../scripts/spike/valida_netlist.sh)
valida esta netlist de forma headless (parse de estrutura, >= 2 componentes,
footprint por componente). Rodar dentro do container:

```bash
docker run --rm -v "$PWD":/projeto -w /projeto do-texto-a-placa \
    bash scripts/spike/valida_netlist.sh
```

Sai `0` quando válida; sai `!=0` com mensagem clara se o arquivo faltar ou
estiver incompleto.
