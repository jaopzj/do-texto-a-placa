"""Do resultado do agente à netlist (Marco 4, Parte 4).

Recebe as peças selecionadas e as ligações registradas pelas ferramentas do agente
(``Ferramentas.estado()``, ADR-010) e monta o circuito com o SKiDL, do mesmo jeito que o
``placas/monitor-umidade/circuito.py`` faz à mão, mas sem nenhuma ligação escrita no código
(ADR-012):

- cada peça vira um conector genérico por fileira de pinos (ADR-005, ADR-007 e ADR-008), com
  símbolo, footprint e ordem dos pinos lidos da base por ``carregar_todos()``;
- as referências da placa (J1, J2...) são dadas em ordem: as peças na ordem em que o agente as
  selecionou e, dentro de cada peça, os conectores na ordem da base. O ``value`` de cada
  conector é o id da peça, seguido do nome do conector quando a peça tem mais de um, como no
  ``circuito.py``. É por ele que o eval (``src/evals/comparar.py``) reconhece a peça;
- os pinos que o agente não ligou vão para a rede especial NC do SKiDL, como a tabela
  NAO_USADOS do ``circuito.py``, e voltam listados no resultado, para nada sumir em silêncio.

Antes de montar, ``planejar`` confere o estado inteiro de novo, sem confiar nas ferramentas:
peça que não está na base, pino que a peça não tem, nome que não bate com o número, pino em
duas redes, pino ``nao_usado`` ligado e rede com menos de dois pinos levantam
``ErroGeracao`` com a lista de problemas. ``planejar`` não precisa do SKiDL; só
``montar_circuito`` e ``gerar_netlist`` precisam.
"""
from dataclasses import dataclass, field
from pathlib import Path

from .componentes.carregar import carregar_todos
from .componentes.modelo import Componente


class ErroGeracao(ValueError):
    """O estado do agente não vira uma netlist válida. ``problemas`` lista cada motivo."""

    def __init__(self, problemas: list[str]):
        self.problemas = list(problemas)
        super().__init__("O estado do agente não vira uma netlist:\n- " + "\n- ".join(problemas))


@dataclass(frozen=True)
class ConectorDaPlaca:
    """Um conector na placa: uma fileira de pinos de uma peça selecionada."""
    ref: str                       # referência na netlist: J1, J2...
    ref_agente: str                # referência da peça no estado do agente: U1, LCD1...
    id_peca: str
    conector: str | None           # nome do conector na base; None se a peça tem um só
    valor: str                     # "id" ou "id conector", como no circuito.py
    simbolo: str
    footprint: str
    pinos: tuple[tuple[int, str], ...]  # (número na peça, nome), na ordem física


@dataclass
class Plano:
    """O circuito pronto para o SKiDL, já conferido contra a base."""
    conectores: list[ConectorDaPlaca]
    # Rede -> pinos, como (referência na netlist, posição 1..N no conector).
    redes: dict[str, list[tuple[str, int]]]
    # Pinos sem ligação, como (referência na netlist, posição 1..N no conector).
    sem_ligacao: list[tuple[str, int]]
    # Referência do agente -> nomes dos pinos sem ligação ("GND#14" quando o nome repete).
    sem_ligacao_por_peca: dict[str, list[str]] = field(default_factory=dict)


def planejar(estado: dict, base: dict[str, Componente] | None = None) -> Plano:
    """Confere ``estado`` (``selecoes`` e ``ligacoes`` de ``Ferramentas.estado()``) contra a
    base e devolve o plano do circuito. Levanta ``ErroGeracao`` se algo não confere."""
    base = carregar_todos() if base is None else base
    problemas: list[str] = []
    selecoes = estado.get("selecoes")
    ligacoes = estado.get("ligacoes")
    if not isinstance(selecoes, dict) or not isinstance(ligacoes, list):
        raise ErroGeracao(["o estado precisa de 'selecoes' (mapa) e 'ligacoes' (lista)"])
    if not selecoes:
        problemas.append("nenhuma peça selecionada")

    # Peças e conectores.
    conectores: list[ConectorDaPlaca] = []
    posicao: dict[tuple[str, int], tuple[str, int]] = {}  # (ref agente, nº) -> (J, posição)
    vistos: dict[str, str] = {}
    for ref_agente, id_peca in selecoes.items():
        dobra = vistos.get(ref_agente.casefold())
        if dobra is not None:
            problemas.append(f"referências repetidas: {dobra!r} e {ref_agente!r}")
            continue
        vistos[ref_agente.casefold()] = ref_agente
        peca = base.get(id_peca)
        if peca is None:
            problemas.append(f"{ref_agente}: a peça {id_peca!r} não está na base")
            continue
        nomes = {p.numero: p.nome for p in peca.pinos}
        fisicos = peca.conectores_fisicos()
        for con in fisicos:
            ref = f"J{len(conectores) + 1}"
            varios = len(fisicos) > 1
            conectores.append(ConectorDaPlaca(
                ref=ref, ref_agente=ref_agente, id_peca=id_peca,
                conector=con.nome if varios else None,
                valor=f"{id_peca} {con.nome}" if varios else id_peca,
                simbolo=con.kicad_simbolo, footprint=con.kicad_footprint,
                pinos=tuple((n, nomes[n]) for n in con.pinos)))
            for i, numero in enumerate(con.pinos, start=1):
                posicao[(ref_agente, numero)] = (ref, i)

    # Ligações.
    redes: dict[str, list[tuple[str, int]]] = {}
    rede_do_pino: dict[tuple[str, int], str] = {}
    for indice, lig in enumerate(ligacoes):
        rotulo = f"ligação {indice}"
        if not isinstance(lig, dict) or not {"ref", "pino", "rede"} <= set(lig):
            problemas.append(f"{rotulo}: precisa de 'ref', 'pino' (número) e 'rede': {lig!r}")
            continue
        ref_agente, numero, rede = lig["ref"], lig["pino"], lig["rede"]
        rotulo = f"ligação {ref_agente}:{numero} -> {rede!r}"
        if ref_agente not in selecoes:
            problemas.append(f"{rotulo}: a peça {ref_agente!r} não foi selecionada")
            continue
        peca = base.get(selecoes[ref_agente])
        if peca is None:
            continue                                   # já apontado acima
        if not isinstance(rede, str) or not rede.strip() or any(c.isspace() for c in rede):
            problemas.append(f"{rotulo}: nome de rede vazio ou com espaços")
            continue
        if not isinstance(numero, int) or isinstance(numero, bool):
            problemas.append(f"{rotulo}: o pino precisa ser o número inteiro da base")
            continue
        pino = next((p for p in peca.pinos if p.numero == numero), None)
        if pino is None:
            problemas.append(f"{rotulo}: {peca.id} não tem o pino {numero}")
            continue
        if "nome" in lig and lig["nome"] != pino.nome:
            problemas.append(f"{rotulo}: o pino {numero} de {peca.id} se chama {pino.nome!r}, "
                             f"não {lig['nome']!r}")
            continue
        if pino.tipo == "nao_usado":
            problemas.append(f"{rotulo}: o pino {numero}:{pino.nome} é 'nao_usado' na base")
            continue
        anterior = rede_do_pino.get((ref_agente, numero))
        if anterior is not None:
            if anterior != rede:
                problemas.append(f"{rotulo}: o pino já está na rede {anterior!r}")
            continue                                   # repetida na mesma rede: nada muda
        rede_do_pino[(ref_agente, numero)] = rede
        redes.setdefault(rede, []).append(posicao[(ref_agente, numero)])

    for rede, pinos in redes.items():
        if len(pinos) < 2:
            problemas.append(f"rede {rede!r}: só {len(pinos)} pino; uma rede liga pelo menos 2")

    if problemas:
        raise ErroGeracao(problemas)

    # Pinos sem ligação: vão para o NC e voltam listados.
    sem_ligacao, por_peca = [], {}
    for con in conectores:
        repetidos = _nomes_repetidos(base[con.id_peca])
        for i, (numero, nome) in enumerate(con.pinos, start=1):
            if (con.ref_agente, numero) not in rede_do_pino:
                sem_ligacao.append((con.ref, i))
                rotulo = f"{nome}#{numero}" if nome in repetidos else nome
                por_peca.setdefault(con.ref_agente, []).append(rotulo)
    return Plano(conectores, redes, sem_ligacao, por_peca)


def _nomes_repetidos(peca: Componente) -> set[str]:
    nomes = [p.nome for p in peca.pinos]
    return {n for n in nomes if nomes.count(n) > 1}


def montar_circuito(estado: dict, base: dict[str, Componente] | None = None,
                    nome: str = "agente"):
    """Monta o circuito no SKiDL e devolve ``(Circuit, Plano)``."""
    from skidl import Circuit, Net, Part

    plano = planejar(estado, base)
    circuito = Circuit(name=nome)
    partes = {}
    for con in plano.conectores:
        biblioteca, simbolo = con.simbolo.split(":", 1)
        partes[con.ref] = Part(biblioteca, simbolo, ref=con.ref,
                               tag=con.ref,   # etiqueta fixa: a netlist sai igual a cada vez
                               value=con.valor, footprint=con.footprint, circuit=circuito)
    for rede, pinos in plano.redes.items():
        net = Net(rede, circuit=circuito)
        for ref, posicao in pinos:
            net += partes[ref][posicao]
    for ref, posicao in plano.sem_ligacao:
        circuito.NC += partes[ref][posicao]
    return circuito, plano


def gerar_netlist(estado: dict, arquivo, base: dict[str, Componente] | None = None,
                  nome: str = "agente") -> Plano:
    """Gera a netlist KiCad do ``estado`` em ``arquivo`` e devolve o plano usado."""
    circuito, plano = montar_circuito(estado, base, nome)
    arquivo = Path(arquivo)
    arquivo.parent.mkdir(parents=True, exist_ok=True)
    circuito.generate_netlist(file_=str(arquivo))
    return plano
