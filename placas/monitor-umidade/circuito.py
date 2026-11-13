"""Placa de referência: monitor de umidade do solo (Marco 2, Parte 4).

Descreve em SKiDL a tabela de ligações da Parte 3 (``pecas.md`` desta pasta).

Os módulos (ESP32, LCD, sensor e conversor) encaixam na placa, então cada um aparece
como um conector fêmea genérico com o número de pinos medido na Parte 2. O pino ``n``
de cada conector é o ``n``-ésimo nome da pinagem anotada no ``pecas.md``, na mesma
ordem física.

Os dados ficam em três tabelas (CONECTORES, LIGACOES e NAO_USADOS), escritas com os
nomes de pino do ``pecas.md``. O código converte nome em número e confere que cada
pino de cada conector aparece exatamente uma vez: numa rede ou como não usado.
Pinos não usados vão para a rede especial NC do SKiDL, para o ERC só acusar o que
estiver realmente esquecido.

Uso, dentro do container: ``python placas/monitor-umidade/circuito.py`` (ou
``make netlist``).
"""

from pathlib import Path

from skidl import Circuit, Net, Part

PASTA = Path(__file__).resolve().parent
NETLIST = PASTA / "monitor-umidade.net"

# Conector fêmea de uma fileira, passo 2,54 mm (biblioteca oficial do KiCad).
FEMEA = "Connector_PinSocket_2.54mm:PinSocket_1x{n:02d}_P2.54mm_Vertical"

# Referência -> (descrição, pinagem na ordem física). Fonte: pecas.md, Parte 2.
CONECTORES = {
    "J1": (
        "ESP32 fileira superior",
        ("VIN", "GND", "D13", "D12", "D14", "D27", "D26", "D25",
         "D33", "D32", "D35", "D34", "VN", "VP", "EN"),
    ),
    "J2": (
        "ESP32 fileira inferior",
        ("3V3", "GND", "D15", "D2", "D4", "RX2", "TX2", "D5",
         "D18", "D19", "D21", "RX0", "TX0", "D22", "D23"),
    ),
    "J3": ("LCD I2C", ("GND", "VCC", "SDA", "SCL")),
    "J4": ("Sensor de umidade", ("A0", "D0", "GND", "VCC")),
    "J5": ("Conversor de nivel LV", ("LV", "A1", "A2", "A3", "A4", "GND")),
    "J6": ("Conversor de nivel HV", ("HV", "B1", "B2", "B3", "B4", "GND")),
}

# Rede -> pinos ligados, como (referência, nome do pino). Fonte: pecas.md, Parte 3, tabela 1.
LIGACOES = {
    "+5V": (("J1", "VIN"), ("J3", "VCC"), ("J6", "HV")),
    "+3V3": (("J2", "3V3"), ("J4", "VCC"), ("J5", "LV")),
    "GND": (("J1", "GND"), ("J2", "GND"), ("J3", "GND"),
            ("J4", "GND"), ("J5", "GND"), ("J6", "GND")),
    "SENSOR": (("J4", "A0"), ("J1", "D34")),
    "SDA_3V3": (("J2", "D21"), ("J5", "A1")),
    "SCL_3V3": (("J2", "D22"), ("J5", "A2")),
    "SDA_5V": (("J6", "B1"), ("J3", "SDA")),
    "SCL_5V": (("J6", "B2"), ("J3", "SCL")),
}

# Referência -> pinos sem ligação. Fonte: pecas.md, Parte 3, tabela 2.
NAO_USADOS = {
    "J1": ("D13", "D12", "D14", "D27", "D26", "D25", "D33", "D32", "D35", "VN", "VP", "EN"),
    "J2": ("D15", "D2", "D4", "RX2", "TX2", "D5", "D18", "D19", "RX0", "TX0", "D23"),
    "J3": (),
    "J4": ("D0",),
    "J5": ("A3", "A4"),
    "J6": ("B3", "B4"),
}


def numero_do_pino(ref, nome):
    """Número do pino (1, 2, ...) de ``nome`` no conector ``ref``."""
    return CONECTORES[ref][1].index(nome) + 1


def validar():
    """Confere as três tabelas antes de montar o circuito.

    Levanta ValueError com a lista de problemas se: uma referência não existir, um
    nome de pino não existir ou se repetir num conector, uma rede tiver menos de dois
    pinos, ou um pino não aparecer exatamente uma vez entre as redes e os não usados.
    """
    problemas = []
    usos = {(ref, nome): [] for ref, (_, pinos) in CONECTORES.items() for nome in pinos}

    for ref, (_, pinos) in CONECTORES.items():
        repetidos = sorted({p for p in pinos if pinos.count(p) > 1})
        if repetidos:
            problemas.append(f"{ref}: nomes de pino repetidos {repetidos}")

    for rede, pinos in LIGACOES.items():
        if len(pinos) < 2:
            problemas.append(f"rede {rede}: só {len(pinos)} pino(s)")
        for pino in pinos:
            if pino not in usos:
                problemas.append(f"rede {rede}: pino inexistente {pino}")
            else:
                usos[pino].append(rede)

    if set(NAO_USADOS) != set(CONECTORES):
        problemas.append(
            f"NAO_USADOS deve listar os conectores {sorted(CONECTORES)}, lista {sorted(NAO_USADOS)}"
        )
    for ref, nomes in NAO_USADOS.items():
        for nome in nomes:
            if (ref, nome) not in usos:
                problemas.append(f"não usado inexistente {(ref, nome)}")
            else:
                usos[(ref, nome)].append("não usado")

    for pino, onde in usos.items():
        if len(onde) != 1:
            problemas.append(f"pino {pino} aparece {len(onde)} vez(es): {onde}")

    if problemas:
        raise ValueError("Tabela de ligações inconsistente:\n- " + "\n- ".join(problemas))


def montar(circuito=None):
    """Monta o circuito e devolve o objeto Circuit do SKiDL."""
    validar()
    circuito = circuito or Circuit(name="monitor-umidade")

    partes = {}
    for ref, (descricao, pinos) in CONECTORES.items():
        n = len(pinos)
        partes[ref] = Part(
            "Connector_Generic",
            f"Conn_01x{n:02d}",
            ref=ref,
            tag=ref,  # etiqueta fixa: a netlist sai igual a cada execução
            value=descricao,
            footprint=FEMEA.format(n=n),
            circuit=circuito,
        )

    for rede, pinos in LIGACOES.items():
        net = Net(rede, circuit=circuito)
        for ref, nome in pinos:
            net += partes[ref][numero_do_pino(ref, nome)]

    for ref, nomes in NAO_USADOS.items():
        for nome in nomes:
            circuito.NC += partes[ref][numero_do_pino(ref, nome)]

    return circuito


def main():
    circuito = montar()
    circuito.ERC()
    circuito.generate_netlist(file_=str(NETLIST))
    print(f"Netlist gerada em {NETLIST}")


if __name__ == "__main__":
    main()
