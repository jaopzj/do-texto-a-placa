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

## 3. Bibliotecas do KiCad no container (`KICAD*_SYMBOL_DIR` / `fp-lib-table`)

No Marco 1, o container rodava com `HOME=/tmp` e sem variáveis de bibliotecas, então o
SKiDL avisava `KICAD10_SYMBOL_DIR environment variable is missing` e
`fp-lib-table file was not found`, e o DRC desta placa avisava `lib_footprint_issues`.
A netlist `teste.net` traz o footprint embutido em cada componente, por isso a validação
da M1-1 não dependia das bibliotecas.

Desde o Marco 2 (Parte 1, issue #12) isso está resolvido no `Makefile`:

- o container usa `HOME=/projeto/.home` (pasta `.home/` do repositório, ignorada pelo Git);
- `KICAD_SYMBOL_DIR`, `KICAD10_SYMBOL_DIR` e `KICAD10_FOOTPRINT_DIR` apontam para
  `/usr/share/kicad/symbols` e `/usr/share/kicad/footprints`;
- `make configurar` copia `fp-lib-table` e `sym-lib-table` de `/usr/share/kicad/template`
  para `.home/.config/kicad/10.0/`. Basta rodar uma vez.

Os avisos que ainda aparecem ao importar o SKiDL (`KICAD6_SYMBOL_DIR` a `KICAD9_SYMBOL_DIR`
e quatro `fp-lib-table file was not found`) vêm das ferramentas do KiCad 6 a 9 que o SKiDL
carrega junto. O projeto usa só a ferramenta `kicad10`, que não avisa mais nada.

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
