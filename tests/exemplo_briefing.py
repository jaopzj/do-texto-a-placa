"""A especificação que os testes do briefing e da aprovação usam como entrega do agente.

Não é um arquivo de teste (o pytest não coleta): é só o dado comum aos dois.
"""
import copy

import yaml

# Uma especificação como o agente do briefing entregaria para a frase "quero um monitor de
# umidade do solo com ESP32 e um LCD", com as fontes no formato que o briefing aceita.
ENTREGA = """
projeto:
  id: monitor-umidade
  nome: Monitor de umidade do solo
  descricao: Lê a umidade do solo com um sensor capacitivo e mostra o valor num LCD 16x2.
modulos:
  - papel: microcontrolador
    componente: esp32-devkitc-v4
    decidido_por: usuario
  - papel: sensor de umidade
    componente: sensor-umidade-capacitivo
    decidido_por: usuario
    requisitos:
      - descricao: A saída AOUT do sensor vai num pino com função ADC1.
        decidido_por: agente
        motivo: O ADC2 do ESP32 não funciona com o Wi-Fi ligado.
        fonte: {documento: componentes/esp32-devkitc-v4.yaml}
        regras:
          - {componente: esp32-devkitc-v4, regra: adc2-wifi}
  - papel: display
    componente: display-lcd-1602-i2c
    decidido_por: usuario
  - papel: conversor de nível lógico
    componente: conversor-nivel-logico-4-canais
    decidido_por: agente
    motivo: O LCD trabalha em 5 V e o ESP32 em 3,3 V, sem tolerar 5 V nos pinos.
    fonte: {documento: componentes/display-lcd-1602-i2c.yaml}
    regras:
      - {componente: display-lcd-1602-i2c, regra: i2c-voltage-compatibility}
      - {componente: esp32-devkitc-v4, regra: gpio-not-5v-tolerant}
alimentacao:
  origem: usb_do_devkit
  tensao: 5.0
  decidido_por: usuario
restricoes:
  camadas:
    valor: 2
    decidido_por: agente
    motivo: Padrão do projeto, a placa-modelo tem duas camadas.
    fonte: {documento: placas/monitor-umidade/modelo/modelo.kicad_pcb}
  contorno:
    largura: 100.0
    altura: 100.0
    decidido_por: agente
    motivo: Padrão do projeto, o contorno da placa-modelo.
    fonte: {documento: placas/monitor-umidade/modelo/modelo.kicad_pcb}
  montagem:
    valor: barra_pinos_macho
    decidido_por: agente
    motivo: O usuário não sabe; os módulos entram com barra de pinos macho.
    fonte: {documento: docs/adr/0008-barras-de-pinos-macho.md}
"""


def entrega(**mudancas) -> str:
    """A ENTREGA com campos trocados: ``entrega(**{"restricoes.montagem.decidido_por": "usuario"})``."""
    dados = copy.deepcopy(yaml.safe_load(ENTREGA))
    for caminho, valor in mudancas.items():
        alvo, *partes, ultima = caminho.split(".")
        no = dados[alvo]
        for p in partes:
            no = no[int(p)] if p.isdigit() else no[p]
        chave = int(ultima) if ultima.isdigit() else ultima
        if valor is None:
            del no[chave]
        else:
            no[chave] = valor
    return yaml.safe_dump(dados, allow_unicode=True, sort_keys=False)
