# ADR-007: Conectores por peça na base de componentes

Status: aceito · Data: 2026-11-14

## Contexto

O modelo da base (Marco 3, Parte 2; ADR-006) guarda um único `kicad_simbolo` e um único
`kicad_footprint` por peça. Isso serve para o sensor de umidade, que tem um conector só.

Já o ESP32 DevKitC V4 tem 38 pinos em duas fileiras de 19, separadas por 25,4 mm. O
conversor de nível tem um lado HV e um lado LV. O guia pede o ESP32 como um componente só,
com todos os pinos. Pelo ADR-005, porém, cada fileira de cada módulo entra na placa como um
conector fêmea genérico. Um único footprint 2x19 de passo 2,54 mm não encaixa nesse ESP32,
e a Parte 6 manda o `circuito.py` buscar símbolo e footprint na base.

As opções eram: uma lista de conectores por peça; um footprint de módulo inteiro por peça;
ou uma peça na base por fileira. O john escolheu a lista de conectores.

## Decisão

O modelo ganha o campo opcional `conectores`. Cada conector tem:

- `nome`, por exemplo `esquerda` ou `HV`;
- `kicad_simbolo` e `kicad_footprint`, no formato `Biblioteca:Nome`;
- `pinos`: os números dos pinos da peça que ele leva, na ordem física, do pino 1 do
  conector em diante.

Regras:

- a peça usa `kicad_simbolo` e `kicad_footprint` **ou** `conectores`, nunca os dois. Sem
  `conectores`, os dois campos continuam obrigatórios, como antes;
- cada pino da peça fica em exatamente um conector, e um conector só cita pinos que a peça
  tem;
- nomes de conector não se repetem dentro da peça.

`Componente.conectores_fisicos()` devolve a lista de conectores nos dois casos. Uma peça
sem `conectores` vira um conector único, com todos os pinos na ordem do YAML. A conferência
das bibliotecas do KiCad (`src/componentes/kicad.py`) passa a olhar cada conector.

Exemplo (o ESP32 dividido nas duas fileiras):

```yaml
conectores:
  - nome: J2
    kicad_simbolo: Connector_Generic:Conn_01x19
    kicad_footprint: Connector_PinHeader_2.54mm:PinHeader_1x19_P2.54mm_Vertical
    pinos: [1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19]
  - nome: J3
    kicad_simbolo: Connector_Generic:Conn_01x19
    kicad_footprint: Connector_PinHeader_2.54mm:PinHeader_1x19_P2.54mm_Vertical
    pinos: [20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 34, 35, 36, 37, 38]
```

A distribuição real dos pinos em cada fileira sai do datasheet, e não deste exemplo.

## Consequências

- O ESP32 e o conversor continuam sendo uma peça cada na base, e as regras de uso (ADR-006,
  lista `regras`) ficam na peça inteira.
- O `circuito.py` monta um conector na placa (J1, J2...) para cada item de
  `conectores_fisicos()`.
- O modelo não confere se o número de pinos do símbolo bate com o tamanho da lista
  `pinos`. Essa conferência pode ser acrescentada ao `kicad.py` quando for necessária.
