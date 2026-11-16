"""O circuito de referência como o agente o montaria, e um provedor de roteiro.

Não é um arquivo de teste (o pytest não coleta): é o dado comum aos testes do laço de
correção (``test_correcao.py``) e do fluxo completo (``test_projeto.py``).
"""
from src.agente.laco import Chamada, Resposta

ESP, LCD, SENSOR, CONV = ("esp32-devkitc-v4", "display-lcd-1602-i2c",
                          "sensor-umidade-capacitivo", "conversor-nivel-logico-4-canais")
SELECOES = {"U1": ESP, "LCD1": LCD, "S1": SENSOR, "U2": CONV}
REFERENCIA = {
    "+5V": [("U1", "5V"), ("LCD1", "VCC"), ("U2", "HV")],
    "+3V3": [("U1", "3V3"), ("S1", "VCC"), ("U2", "LV")],
    "GND": [("U1", "GND"), ("LCD1", "GND"), ("S1", "GND"), ("U2", "GND")],
    "SENSOR": [("S1", "AOUT"), ("U1", "IO34")],
    "SDA_3V3": [("U1", "IO21"), ("U2", "LV1")],
    "SCL_3V3": [("U1", "IO22"), ("U2", "LV2")],
    "SDA_5V": [("U2", "HV1"), ("LCD1", "SDA")],
    "SCL_5V": [("U2", "HV2"), ("LCD1", "SCL")],
}


def chamadas(*pares) -> tuple[Chamada, ...]:
    return tuple(Chamada(nome, args, f"c{i}") for i, (nome, args) in enumerate(pares))


def montar_referencia():
    pares = [("selecionar_componente", {"id": id_, "ref": ref}) for ref, id_ in SELECOES.items()]
    pares += [("conectar", {"ref": ref, "pino": pino, "rede": rede})
              for rede, pinos in REFERENCIA.items() for ref, pino in pinos]
    return Resposta(chamadas=chamadas(*pares))


class Roteiro:
    """Um provedor que devolve respostas prontas e guarda o que recebeu."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.iniciados, self.mensagens, self.resultados = [], [], []

    def _proxima(self):
        if not self.respostas:
            raise AssertionError("o roteiro acabou")
        return self.respostas.pop(0)

    def iniciar(self, sistema, contratos, pedido):
        self.iniciados.append((sistema, contratos, pedido))
        return self._proxima()

    def continuar(self, resultados):
        self.resultados.append(resultados)
        return self._proxima()

    def responder(self, texto):
        self.mensagens.append(texto)
        return self._proxima()


PRONTO = Resposta(texto="Pronto.")
