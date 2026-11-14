# PEÇAS USADAS NO PROJETO

## ESP-32 Dev-Kit

> Atualizado em 2026-11-14 (Marco 3, Parte 6): a placa usada é o ESP32-DevKitC V4, de 38
> pinos, e não o DevKit V1 de 30 pinos anotado antes. A pinagem abaixo é a da base de
> componentes (`componentes/esp32-devkitc-v4.yaml`), tirada da tabela "1.1.5 Header
> Block" do guia da Espressif (esp-dev-kits-en-master-esp32.pdf, página 5).

-   **Modelo:** ESP32-DevKitC V4
-   **Módulo:** ESP32-WROOM-32E
-   **Quantidade de pinos:** 38 pinos
-   **Distribuição:** 19 pinos por fileira (cabeçalhos J2 e J3 da Espressif)

### Dimensões

-   **Distância entre as fileiras:** aproximadamente 25,4 mm (centro a
    centro).
-   **Observação:** medida estimada visualmente. O guia da Espressif não traz a medida;
    ela está no documento de dimensões do DevKitC V4, que não está no repositório.

### Pinagem

#### Fileira J2 (pino 1 na ponta oposta ao USB)

``` text
3V3 | EN | VP | VN | IO34 | IO35 | IO32 | IO33 | IO25 | IO26 | IO27 | IO14 | IO12 | GND | IO13 | D2 | D3 | CMD | 5V
```

#### Fileira J3 (pino 1 na ponta oposta ao USB)

``` text
GND | IO23 | IO22 | TX | RX | IO21 | GND | IO19 | IO18 | IO5 | IO17 | IO16 | IO4 | IO0 | IO2 | IO15 | D1 | D0 | CLK
```

### Resumo

  Característica               Valor
  ---------------------------- -------------------------
  Fileira J2                   19 pinos
  Fileira J3                   19 pinos
  Total                        38 pinos
  Espaçamento entre fileiras   Aproximadamente 25,4 mm
  Módulo                       ESP32-WROOM-32E

------------------------------------------------------------------------

## LCD 16x2 com adaptador I²C

-   **Tipo:** Display LCD alfanumérico 16x2 com módulo adaptador I²C.
-   **Controlador do adaptador:** PCF8574 (provável).
-   **Quantidade de pinos na interface I²C:** 4 pinos.

### Pinagem

#### Conector I²C (ordem usual, da esquerda para a direita, olhando o adaptador com as inscrições voltadas para cima)

``` text
GND | VCC | SDA | SCL
```

### Resumo

  Característica             Valor
  -------------------------- --------------------
  Display                    LCD 16x2
  Interface                  I²C
  Pinos de conexão           4
  Sinais                     GND, VCC, SDA, SCL
  Controlador do adaptador   PCF8574 (provável)

------------------------------------------------------------------------

## Sensor de umidade do solo

> Atualizado em 2026-11-14 (Marco 3, Parte 6): a placa usa o sensor capacitivo HW-101
> (decisão do john), e não o resistivo FC-28 anotado antes. Pinagem da base de componentes
> (`componentes/sensor-umidade-capacitivo.yaml`, datasheet HW-101, página 2).

-   **Tipo:** Sensor capacitivo de umidade do solo, saída analógica.
-   **Modelo:** HW-101 (HW-moisture sensor V1.2).
-   **Quantidade de pinos na interface do módulo:** 3 pinos.
-   **Alimentação:** 3,3 a 5,5 V (datasheet, página 2).

### Pinagem

#### Conector do módulo

``` text
GND | VCC | AOUT
```

-   **GND:** terra.
-   **VCC:** alimentação.
-   **AOUT:** saída analógica.

### Resumo

  Característica          Valor
  ----------------------- -------------------------------------
  Tipo                    Sensor capacitivo de umidade do solo
  Pinos do módulo         3
  Saída                   Analógica (AOUT)
  Alimentação             VCC e GND

------------------------------------------------------------------------

## Conversor de nível lógico bidirecional

-   **Tipo:** Conversor de nível lógico bidirecional.
-   **Canais:** 4 canais (identificação provável).
-   **Quantidade de pinos:** 12 pinos, distribuídos em 2 fileiras de 6.
-   **Função:** adaptação de sinais entre dois níveis de tensão,
    normalmente 3,3 V e 5 V.

### Pinagem

> Atualizado em 2026-11-14 (Marco 3, Parte 6): pinagem da base de componentes
> (`componentes/conversor-nivel-logico-4-canais.yaml`, manual 010-0061, página 1).

#### Lado de alta tensão (HV), pinos 1 a 6

``` text
HV1 | HV2 | HV | GND | HV3 | HV4
```

#### Lado de baixa tensão (LV), pinos 7 a 12

``` text
LV1 | LV2 | LV | GND | LV3 | LV4
```

### Resumo

  Característica         Valor
  ---------------------- ----------------------------------------
  Tipo                   Conversor de nível lógico bidirecional
  Canais de sinal        4
  Pinos por lado         6
  Total                  12 pinos
  Lado de alta tensão    HV1, HV2, HV, GND, HV3, HV4
  Lado de baixa tensão   LV1, LV2, LV, GND, LV3, LV4
  Níveis usuais          3,3 V e 5 V

------------------------------------------------------------------------

# LIGAÇÕES DO CIRCUITO (NETLIST EM PORTUGUÊS)

A tabela abaixo descreve as conexões planejadas entre os componentes.
Cada pino deve aparecer associado a uma rede elétrica ou ser
explicitamente marcado como **não usado**.

## 1. Tabela de ligações

  -----------------------------------------------------------------------
  Rede (net)              Ligações                Por quê
  ----------------------- ----------------------- -----------------------
  **+5V**                 ESP32 (5V), LCD (VCC),  O LCD e o lado de alta
                          conversor de nível (HV) tensão do conversor
                                                  recebem 5 V. A
                                                  alimentação de 5 V vem
                                                  do USB conectado ao
                                                  ESP32.

  **+3V3**                ESP32 (3V3), sensor     O sensor e o lado de
                          (VCC), conversor de     baixa tensão do
                          nível (LV)              conversor operam em 3,3
                                                  V.

  **GND**                 ESP32 (os três GND),    Todos os componentes
                          LCD (GND),
                          sensor (GND), conversor precisam compartilhar a
                          (GND do lado HV e GND   mesma referência
                          do lado LV)             elétrica.

  **SENSOR**              Sensor (AOUT), ESP32    A saída analógica do
                          (IO34 / GPIO34)         sensor é lida pelo ADC1
                                                  do ESP32. O GPIO34
                                                  pertence ao ADC1, que
                                                  pode ser usado com
                                                  Wi-Fi ativo.

  **SDA_3V3**             ESP32 (IO21 / GPIO21),  GPIO21 é o pino SDA
                          conversor (LV1)         padrão do ESP32. O
                                                  sinal entra no lado de
                                                  3,3 V do conversor.

  **SCL_3V3**             ESP32 (IO22 / GPIO22),  GPIO22 é o pino SCL
                          conversor (LV2)         padrão do ESP32. O
                                                  sinal entra no lado de
                                                  3,3 V do conversor.

  **SDA_5V**              Conversor (HV1),        O sinal SDA convertido
                          LCD (SDA)               para o lado de 5 V
                                                  chega ao LCD.

  **SCL_5V**              Conversor (HV2),        O sinal SCL convertido
                          LCD (SCL)               para o lado de 5 V
                                                  chega ao LCD.
  -----------------------------------------------------------------------

**Nota sobre a nomenclatura do conversor:** desde 2026-11-14 os nomes são os
da base de componentes (LV1 a LV4 e HV1 a HV4). Antes, esta documentação usava
A1 a A4 e B1 a B4. Confirme a serigrafia do módulo físico antes de montar o
circuito.

## 2. Pinos não utilizados

Os pinos abaixo não participam das ligações desta versão do circuito e
devem permanecer sem conexão.

  -----------------------------------------------------------------------
  Componente                          Pinos não utilizados
  ----------------------------------- -----------------------------------
  ESP32 --- fileira J2                EN, VP, VN, IO35, IO32, IO33, IO25,
                                      IO26, IO27, IO14, IO12, IO13, D2,
                                      D3, CMD

  ESP32 --- fileira J3                IO23, TX, RX, IO19, IO18, IO5,
                                      IO17, IO16, IO4, IO0, IO2, IO15,
                                      D1, D0, CLK

  LCD I²C                             Nenhum

  Sensor de umidade                   Nenhum

  Conversor --- lado LV               LV3, LV4

  Conversor --- lado HV               HV3, HV4
  -----------------------------------------------------------------------

## 3. Conferência de todos os pinos

  -----------------------------------------------------------------------
  Componente       Pinos conectados   Pinos não usados              Total
                                                            contabilizado
  -------------- ------------------ ------------------ ------------------
  ESP32 DevKit   8 posições de pino                 30                 38
                     (5V, 3V3, três                    
                    GND, IO34, IO21,                   
                              IO22)                    

  LCD I²C                         4                  0                  4

  Sensor de      3 (AOUT, GND, VCC)                  0                  3
  umidade                                              

  Conversor de      8 (HV, LV, dois                  4                 12
  nível lógico        GND, LV1, LV2,                   
                          HV1, HV2)                    
  -----------------------------------------------------------------------

**Observação:** os três pinos GND do ESP32 (um na fileira J2 e dois na
J3) são posições físicas distintas, todas ligadas à rede GND. Da mesma forma, os dois pinos GND
do conversor são posições distintas e ambos devem ser conectados à
referência comum.

## 4. Verificações antes de transformar a tabela em netlist

-   [ ] Confirmar que o pino 5V do ESP32 fornece 5 V quando alimentado
    pelo USB.
-   [ ] Confirmar a ordem física e a serigrafia dos pinos do LCD I²C.
-   [ ] Confirmar a ordem física e a serigrafia dos pinos do módulo do
    sensor.
-   [ ] Confirmar no conversor quais terminais correspondem aos canais
    LV1/HV1 e LV2/HV2.
-   [ ] Confirmar que HV está ligado a 5 V e LV a 3,3 V.
-   [ ] Confirmar que todos os GND estão interligados.
-   [ ] Confirmar que cada pino está conectado a uma rede ou marcado
    como não usado.
