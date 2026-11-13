# PEÇAS USADAS NO PROJETO

## ESP-32 Dev-Kit

-   **Modelo:** ESP32 DevKit V1 (identificação provável)
-   **Módulo:** ESP32-WROOM-32 (identificação provável)
-   **Conector USB:** USB Type-C
-   **Quantidade de pinos:** 30 pinos
-   **Distribuição:** 15 pinos por fileira

### Dimensões

-   **Distância entre as fileiras:** aproximadamente 25,4 mm (centro a
    centro).
-   **Observação:** medida estimada visualmente.

### Pinagem

#### Fileira superior (esquerda para a direita)

``` text
VIN | GND | D13 | D12 | D14 | D27 | D26 | D25 | D33 | D32 | D35 | D34 | VN | VP | EN
```

#### Fileira inferior (esquerda para a direita)

``` text
3V3 | GND | D15 | D2 | D4 | RX2 | TX2 | D5 | D18 | D19 | D21 | RX0 | TX0 | D22 | D23
```

### Resumo

  Característica               Valor
  ---------------------------- -------------------------
  Fileira superior             15 pinos
  Fileira inferior             15 pinos
  Total                        30 pinos
  Espaçamento entre fileiras   Aproximadamente 25,4 mm
  Conector USB                 USB Type-C
  Módulo                       ESP32-WROOM-32

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

-   **Tipo:** Sensor resistivo de umidade do solo com módulo comparador.
-   **Modelo/família:** FC-28 com módulo LM393 (identificação provável).
-   **Conjunto:** sonda resistiva de duas trilhas e placa eletrônica
    comparadora.
-   **Quantidade de pinos na interface do módulo:** 4 pinos.
-   **Conexão entre a sonda e o módulo:** 2 fios.

### Pinagem

#### Conector do módulo (ordem usual, com o ajuste azul voltado para cima; confirmar as inscrições da placa física)

``` text
A0 | D0 | GND | VCC
```

-   **A0:** saída analógica.
-   **D0:** saída digital do comparador.
-   **GND:** terra.
-   **VCC:** alimentação.

### Resumo

  Característica          Valor
  ----------------------- -------------------------------------
  Tipo                    Sensor resistivo de umidade do solo
  Pinos do módulo         4
  Conexão da sonda        2 fios
  Saídas                  Analógica (A0) e digital (D0)
  Alimentação             VCC e GND
  Controlador do módulo   LM393 (provável)

------------------------------------------------------------------------

## Conversor de nível lógico bidirecional

-   **Tipo:** Conversor de nível lógico bidirecional.
-   **Canais:** 4 canais (identificação provável).
-   **Quantidade de pinos:** 12 pinos, distribuídos em 2 fileiras de 6.
-   **Função:** adaptação de sinais entre dois níveis de tensão,
    normalmente 3,3 V e 5 V.

### Pinagem

#### Lado de alta tensão (HV) --- ordem física de cima para baixo, conforme a orientação da inscrição na placa

``` text
HV | B1 | B2 | B3 | B4 | GND
```

#### Lado de baixa tensão (LV) --- ordem física de cima para baixo, conforme a orientação da inscrição na placa

``` text
LV | A1 | A2 | A3 | A4 | GND
```

### Resumo

  Característica         Valor
  ---------------------- ----------------------------------------
  Tipo                   Conversor de nível lógico bidirecional
  Canais de sinal        4
  Pinos por lado         6
  Total                  12 pinos
  Lado de alta tensão    HV, B1, B2, B3, B4, GND
  Lado de baixa tensão   LV, A1, A2, A3, A4, GND
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
  **+5V**                 ESP32 (VIN), LCD (VCC), O LCD e o lado de alta
                          conversor de nível (HV) tensão do conversor
                                                  recebem 5 V. A
                                                  alimentação de 5 V vem
                                                  do USB conectado ao
                                                  ESP32.

  **+3V3**                ESP32 (3V3), sensor     O sensor e o lado de
                          (VCC), conversor de     baixa tensão do
                          nível (LV)              conversor operam em 3,3
                                                  V.

  **GND**                 ESP32 (GND), LCD (GND), Todos os componentes
                          sensor (GND), conversor precisam compartilhar a
                          (GND do lado HV e GND   mesma referência
                          do lado LV)             elétrica.

  **SENSOR**              Sensor (A0), ESP32 (D34 A saída analógica do
                          / GPIO34)               sensor é lida pelo ADC1
                                                  do ESP32. O GPIO34
                                                  pertence ao ADC1, que
                                                  pode ser usado com
                                                  Wi-Fi ativo.

  **SDA_3V3**             ESP32 (D21 / GPIO21),   GPIO21 é o pino SDA
                          conversor (A1 / LV1)    padrão do ESP32. O
                                                  sinal entra no lado de
                                                  3,3 V do conversor.

  **SCL_3V3**             ESP32 (D22 / GPIO22),   GPIO22 é o pino SCL
                          conversor (A2 / LV2)    padrão do ESP32. O
                                                  sinal entra no lado de
                                                  3,3 V do conversor.

  **SDA_5V**              Conversor (B1 / HV1),   O sinal SDA convertido
                          LCD (SDA)               para o lado de 5 V
                                                  chega ao LCD.

  **SCL_5V**              Conversor (B2 / HV2),   O sinal SCL convertido
                          LCD (SCL)               para o lado de 5 V
                                                  chega ao LCD.
  -----------------------------------------------------------------------

**Nota sobre a nomenclatura do conversor:** nesta documentação, A1/A2
representam os canais do lado LV e B1/B2 os canais correspondentes do
lado HV. Alguns módulos imprimem esses sinais como LV1/LV2 e HV1/HV2.
Confirme a serigrafia do módulo físico antes de montar o circuito.

## 2. Pinos não utilizados

Os pinos abaixo não participam das ligações desta versão do circuito e
devem permanecer sem conexão.

  -----------------------------------------------------------------------
  Componente                          Pinos não utilizados
  ----------------------------------- -----------------------------------
  ESP32 --- fileira superior          D13, D12, D14, D27, D26, D25, D33,
                                      D32, D35, VN, VP, EN

  ESP32 --- fileira inferior          D15, D2, D4, RX2, TX2, D5, D18,
                                      D19, RX0, TX0, D23

  LCD I²C                             Nenhum

  Sensor de umidade                   D0

  Conversor --- lado LV               A3, A4

  Conversor --- lado HV               B3, B4
  -----------------------------------------------------------------------

## 3. Conferência de todos os pinos

  -----------------------------------------------------------------------
  Componente       Pinos conectados   Pinos não usados              Total
                                                            contabilizado
  -------------- ------------------ ------------------ ------------------
  ESP32 DevKit   7 posições de pino                 23                 30
                    (VIN, 3V3, dois                    
                     GND, D34, D21,                    
                               D22)                    

  LCD I²C                         4                  0                  4

  Sensor de        3 (A0, GND, VCC)                  1                  4
  umidade                                              

  Conversor de      8 (HV, LV, dois                  4                 12
  nível lógico     GND, A1, A2, B1,                    
                                B2)                    
  -----------------------------------------------------------------------

**Observação:** os dois pinos GND do ESP32 são posições físicas
distintas, ambas ligadas à rede GND. Da mesma forma, os dois pinos GND
do conversor são posições distintas e ambos devem ser conectados à
referência comum.

## 4. Verificações antes de transformar a tabela em netlist

-   [ ] Confirmar que o pino VIN do ESP32 fornece 5 V quando alimentado
    pelo USB.
-   [ ] Confirmar a ordem física e a serigrafia dos pinos do LCD I²C.
-   [ ] Confirmar a ordem física e a serigrafia dos pinos do módulo do
    sensor.
-   [ ] Confirmar no conversor quais terminais correspondem aos canais
    A1/B1 e A2/B2.
-   [ ] Confirmar que HV está ligado a 5 V e LV a 3,3 V.
-   [ ] Confirmar que todos os GND estão interligados.
-   [ ] Confirmar que cada pino está conectado a uma rede ou marcado
    como não usado.
