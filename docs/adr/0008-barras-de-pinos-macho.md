# ADR-008: Os módulos entram na placa com barras de pinos macho

Status: aceito · Data: 2026-11-14 · Substitui em parte o ADR-005

## Contexto

O ADR-005 decidiu que cada fileira de pinos de cada módulo entra na placa como um conector
genérico, e escolheu o footprint fêmea (`Connector_PinSocket_2.54mm`), para os módulos
encaixarem direto na placa.

Ao preencher a base de componentes (Marco 3, Parte 6), o john registrou o LCD e o conversor
de nível com barra de pinos macho (`Connector_PinHeader_2.54mm`). Perguntado sobre qual dos
dois vale, ele escolheu o macho.

## Decisão

Na base de componentes, os footprints dos módulos são barras de pinos macho
(`Connector_PinHeader_2.54mm:PinHeader_1xNN_P2.54mm_Vertical`), com o símbolo genérico
`Connector_Generic:Conn_01xNN`. Continua valendo do ADR-005 a ideia de um conector genérico
por fileira, agora descrita na base pelo campo `conectores` (ADR-007).

O ESP32 DevKitC passa a ter duas barras 1x19 macho (J2 e J3 da documentação da Espressif).

## Consequências

- Como o `circuito.py` busca o footprint na base, a placa de referência passa a ter barras
  macho, e o `gabarito.net` muda junto.
- Os módulos também têm pinos macho, então a ligação entre módulo e placa deixa de ser por
  encaixe direto. Ela passa a depender de cabos ou de barras fêmea montadas à parte. Quem
  monta a placa precisa saber disso.
- O sensor de umidade ainda está com footprint fêmea na base (`PinSocket_1x03`). Ele fica
  assim até o john decidir.
