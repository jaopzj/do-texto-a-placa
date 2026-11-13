# ADR-005: Os módulos entram na placa como conectores fêmea

Status: aceito · Data: 2026-11-13

## Contexto

A placa de referência usa quatro módulos prontos: o ESP32 DevKit, o LCD 16x2 com
adaptador I²C, o sensor de umidade e o conversor de nível. Eles chegam montados e
encaixam na placa pelos pinos. Há duas formas de representá-los no circuito:

1. com o símbolo e o footprint de cada módulo (quando existem nas bibliotecas oficiais do
   KiCad), o que traz o desenho e o nome de cada pino;
2. como conectores fêmea genéricos (`Connector_Generic:Conn_01xNN` com o footprint
   `Connector_PinSocket_2.54mm:PinSocket_1xNN_P2.54mm_Vertical`), um por fileira de pinos.

O guia do MVP (Marco 2, Parte 4) adota a segunda forma.

## Decisão

Cada fileira de pinos de cada módulo vira um conector fêmea genérico, com o número de
pinos medido na Parte 2 (`placas/monitor-umidade/pecas.md`):

| Ref | Módulo | Pinos |
|---|---|---|
| J1, J2 | ESP32, fileiras superior e inferior | 15 + 15 |
| J3 | LCD I²C | 4 |
| J4 | sensor de umidade | 4 |
| J5, J6 | conversor de nível, lados LV e HV | 6 + 6 |

O nome de cada pino fica no `circuito.py` (tabela `CONECTORES`), na ordem física do
`pecas.md`: o pino n do conector é o n-ésimo nome da pinagem.

## Consequências

- Só usamos footprints das bibliotecas oficiais do KiCad, sem desenhar nada à mão. A
  placa só precisa dos furos e das barras de pinos.
- A correção depende da pinagem medida: a ordem dos pinos e a distância entre fileiras
  vêm do `pecas.md`, e não de um footprint de fabricante. Por isso o `circuito.py` e o
  `posicoes.yaml` citam a origem de cada dado, e os testes conferem tudo contra o `pecas.md`.
- O símbolo genérico não diz que pino é entrada ou saída, então o ERC do SKiDL só confere
  pinos esquecidos e redes com um pino só, e não conflitos elétricos. As regras elétricas
  ficam para o motor de regras (a partir do Marco 3).
- Duas fileiras do mesmo módulo são peças separadas na placa. A distância entre elas está
  no `posicoes.yaml`, e não num footprint único.
- Os corpos dos módulos não aparecem na placa, então o DRC não confere colisão física entre
  módulos encaixados. Isso exige as medidas dos corpos, que ainda não estão no `pecas.md`.
