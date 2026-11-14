"""Placa de referência: monitor de umidade do solo (Marco 2, Parte 4; Marco 3, Parte 6).

Descreve em SKiDL a tabela de ligações da Parte 3 (``pecas.md`` desta pasta).

Os módulos (ESP32, LCD, sensor e conversor) entram na placa como conectores genéricos,
um por fileira de pinos (ADR-005, ADR-007 e ADR-008). Nada da peça fica escrito aqui:
símbolo, footprint e nomes dos pinos de cada conector vêm da base de componentes
(``componentes/``), lida por ``carregar_todos()``. A tabela PECAS só diz qual conector de
qual peça cada referência (J1, J2...) usa.

As ligações ficam em duas tabelas (LIGACOES e NAO_USADOS), escritas com os nomes de pino da
base. Um nome que aparece mais de uma vez no mesmo conector (por exemplo, os dois GND da
fileira J3 do ESP32) vale para todos os pinos com esse nome. O código converte nome em
número e confere que cada pino de cada conector aparece exatamente uma vez: numa rede ou
como não usado. Pinos não usados vão para a rede especial NC do SKiDL, para o ERC só
acusar o que estiver realmente esquecido.

Uso, dentro do container: ``python placas/monitor-umidade/circuito.py`` (ou
``make netlist``).
"""

import sys
from pathlib import Path

from skidl import Circuit, Net, Part

PASTA = Path(__file__).resolve().parent
NETLIST = PASTA / "monitor-umidade.net"

sys.path.insert(0, str(PASTA.parents[1]))   # raiz do repositório, para achar src/
from src.componentes.carregar import carregar_todos  # noqa: E402

# Referência na placa -> (id da peça na base, nome do conector da peça).
# None quando a peça tem um conector só (kicad_simbolo e kicad_footprint na própria peça).
PECAS = {
    "J1": ("esp32-devkitc-v4", "J2"),              # fileira com 3V3 ... 5V
    "J2": ("esp32-devkitc-v4", "J3"),              # fileira com GND ... CLK
    "J3": ("display-lcd-1602-i2c", None),
    "J4": ("sensor-umidade-capacitivo", None),
    "J5": ("conversor-nivel-logico-4-canais", "LV"),
    "J6": ("conversor-nivel-logico-4-canais", "HV"),
}


def conectores_da_base(base=None):
    """Referência -> (descrição, símbolo, footprint, nomes dos pinos na ordem física).

    Levanta ValueError se a peça ou o conector citado em PECAS não existir na base.
    """
    base = carregar_todos() if base is None else base
    conectores, problemas = {}, []
    for ref, (id_peca, nome_conector) in PECAS.items():
        if id_peca not in base:
            problemas.append(f"{ref}: a peça {id_peca!r} não está na base")
            continue
        peca = base[id_peca]
        fisicos = {c.nome: c for c in peca.conectores_fisicos()}
        if nome_conector is None:
            if len(fisicos) != 1:
                problemas.append(f"{ref}: {id_peca} tem conectores {sorted(fisicos)}; diga qual")
                continue
            [conector] = fisicos.values()
            descricao = id_peca
        elif nome_conector not in fisicos:
            problemas.append(
                f"{ref}: {id_peca} não tem o conector {nome_conector!r} ({sorted(fisicos)})")
            continue
        else:
            conector = fisicos[nome_conector]
            descricao = f"{id_peca} {nome_conector}"
        nome_por_numero = {p.numero: p.nome for p in peca.pinos}
        conectores[ref] = (descricao, conector.kicad_simbolo, conector.kicad_footprint,
                           tuple(nome_por_numero[n] for n in conector.pinos))
    if problemas:
        raise ValueError("A base não tem o que o circuito precisa:\n- " + "\n- ".join(problemas))
    return conectores


CONECTORES = conectores_da_base()

# Rede -> pinos ligados, como (referência, nome do pino). Fonte: pecas.md, Parte 3, tabela 1.
LIGACOES = {
    "+5V": (("J1", "5V"), ("J3", "VCC"), ("J6", "HV")),
    "+3V3": (("J1", "3V3"), ("J4", "VCC"), ("J5", "LV")),
    "GND": (("J1", "GND"), ("J2", "GND"), ("J3", "GND"),
            ("J4", "GND"), ("J5", "GND"), ("J6", "GND")),
    "SENSOR": (("J4", "AOUT"), ("J1", "IO34")),
    "SDA_3V3": (("J2", "IO21"), ("J5", "LV1")),
    "SCL_3V3": (("J2", "IO22"), ("J5", "LV2")),
    "SDA_5V": (("J6", "HV1"), ("J3", "SDA")),
    "SCL_5V": (("J6", "HV2"), ("J3", "SCL")),
}

# Referência -> pinos sem ligação. Fonte: pecas.md, Parte 3, tabela 2.
NAO_USADOS = {
    "J1": ("EN", "VP", "VN", "IO35", "IO32", "IO33", "IO25", "IO26", "IO27", "IO14", "IO12",
           "IO13", "D2", "D3", "CMD"),
    "J2": ("IO23", "TX", "RX", "IO19", "IO18", "IO5", "IO17", "IO16", "IO4", "IO0", "IO2",
           "IO15", "D1", "D0", "CLK"),
    "J3": (),
    "J4": (),
    "J5": ("LV3", "LV4"),
    "J6": ("HV3", "HV4"),
}


def numeros_do_pino(ref, nome):
    """Números (1, 2, ...) dos pinos chamados ``nome`` no conector ``ref``."""
    return [i + 1 for i, n in enumerate(CONECTORES[ref][3]) if n == nome]


def validar():
    """Confere as tabelas antes de montar o circuito.

    Levanta ValueError com a lista de problemas se: uma referência não existir, um nome de
    pino não existir no conector, uma rede tiver menos de dois pinos, ou um pino não
    aparecer exatamente uma vez entre as redes e os não usados.
    """
    problemas = []
    usos = {(ref, i + 1): [] for ref, c in CONECTORES.items() for i in range(len(c[3]))}

    def marcar(ref, nome, onde, rotulo):
        if ref not in CONECTORES or not numeros_do_pino(ref, nome):
            problemas.append(f"{rotulo}: pino inexistente {(ref, nome)}")
            return
        for numero in numeros_do_pino(ref, nome):
            usos[(ref, numero)].append(onde)

    for rede, pinos in LIGACOES.items():
        if len(pinos) < 2:
            problemas.append(f"rede {rede}: só {len(pinos)} pino(s)")
        for ref, nome in pinos:
            marcar(ref, nome, rede, f"rede {rede}")

    if set(NAO_USADOS) != set(CONECTORES):
        problemas.append(
            f"NAO_USADOS deve listar os conectores {sorted(CONECTORES)}, lista {sorted(NAO_USADOS)}"
        )
    for ref, nomes in NAO_USADOS.items():
        for nome in nomes:
            marcar(ref, nome, "não usado", "não usado")

    for (ref, numero), onde in usos.items():
        if len(onde) != 1:
            nome = CONECTORES[ref][3][numero - 1]
            problemas.append(f"pino {(ref, nome)} (nº {numero}) aparece {len(onde)} vez(es): {onde}")

    if problemas:
        raise ValueError("Tabela de ligações inconsistente:\n- " + "\n- ".join(problemas))


def montar(circuito=None):
    """Monta o circuito e devolve o objeto Circuit do SKiDL."""
    validar()
    circuito = circuito or Circuit(name="monitor-umidade")

    partes = {}
    for ref, (descricao, simbolo, footprint, _) in CONECTORES.items():
        biblioteca, nome = simbolo.split(":", 1)
        partes[ref] = Part(
            biblioteca,
            nome,
            ref=ref,
            tag=ref,  # etiqueta fixa: a netlist sai igual a cada execução
            value=descricao,
            footprint=footprint,
            circuit=circuito,
        )

    for rede, pinos in LIGACOES.items():
        net = Net(rede, circuit=circuito)
        for ref, nome in pinos:
            for numero in numeros_do_pino(ref, nome):
                net += partes[ref][numero]

    for ref, nomes in NAO_USADOS.items():
        for nome in nomes:
            for numero in numeros_do_pino(ref, nome):
                circuito.NC += partes[ref][numero]

    return circuito


def main():
    circuito = montar()
    circuito.ERC()
    circuito.generate_netlist(file_=str(NETLIST))
    print(f"Netlist gerada em {NETLIST}")


if __name__ == "__main__":
    main()
