"""Eval do gabarito: compara duas netlists pela estrutura elétrica (Marco 4, Parte 5).

Comparar o texto não funciona: o agente pode dar outros nomes às redes, outras referências
às peças (J5 no lugar de J6) ou listar tudo em outra ordem, e mesmo assim acertar o circuito.
O que importa é quais pinos estão ligados entre si (ADR-012).

``ler_estrutura`` transforma uma netlist KiCad (formato S-expression, versão "D", a que o
SKiDL e o KiCad escrevem) em:

- ``componentes``: as peças da placa, cada uma como ``id`` ou ``id/conector`` da base;
- ``grupos``: um conjunto por rede com dois pinos ou mais, e cada pino identificado pela peça
  e pelo nome na base, como ``"display-lcd-1602-i2c: SDA"``. Quando o nome se repete na
  peça (os três GND do ESP32, os dois GND do conversor), o número do pino entra junto:
  ``"esp32-devkitc-v4: GND#14"``. Assim nenhum pino se confunde com outro;
- ``isolados``: pinos que estão sozinhos numa rede. Eletricamente são pinos sem ligação, como
  os que o KiCad escreve em redes ``unconnected-(...)``; ficam fora dos grupos, mas são
  devolvidos para ninguém perdê-los de vista.

Duas netlists são equivalentes quando têm os mesmos componentes e os mesmos grupos. O nome
das redes, as referências (J1...), a ordem e os campos de desenho (data, tstamps, linha do
SKiDL) não entram.

A peça de cada componente vem do ``value`` (``"id"`` ou ``"id conector"``, como o
``circuito.py`` e o ``gerar_netlist.py`` escrevem) e é conferida contra a base: o símbolo, o
footprint e a quantidade de pinos precisam bater com o conector da base. A posição do pino
no conector vira o número e o nome do pino na peça. Nada é adivinhado: um componente que não
confere, um pino que o conector não tem, um pino em duas redes ou duas unidades da mesma peça
levantam ``ErroNetlist``.

Este módulo não usa o SKiDL: lê o arquivo por conta própria, para o eval não depender do
gerador que ele avalia.
"""
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from ..componentes.carregar import carregar_todos
from ..componentes.modelo import Componente


class ErroNetlist(ValueError):
    """A netlist não pôde ser lida ou não confere com a base. ``problemas`` lista os motivos."""

    def __init__(self, problemas: list[str], origem: str = "netlist"):
        self.problemas = list(problemas)
        super().__init__(f"{origem}: não deu para ler a estrutura:\n- " + "\n- ".join(problemas))


@dataclass(frozen=True)
class Estrutura:
    """O que uma netlist diz eletricamente."""
    componentes: frozenset[str]
    grupos: frozenset[frozenset[str]]
    isolados: frozenset[str] = frozenset()


@dataclass
class Comparacao:
    """O resultado de ``comparar``. ``equivalente`` é o que o eval mede."""
    equivalente: bool
    componentes_faltando: list[str] = field(default_factory=list)   # no esperado, não no obtido
    componentes_sobrando: list[str] = field(default_factory=list)   # no obtido, não no esperado
    grupos_faltando: list[list[str]] = field(default_factory=list)
    grupos_sobrando: list[list[str]] = field(default_factory=list)
    # Pino -> (ligado a, no esperado; ligado a, no obtido), para os pinos que mudaram.
    pinos_divergentes: dict[str, tuple[list[str], list[str]]] = field(default_factory=dict)

    def resumo(self) -> str:
        if self.equivalente:
            return "equivalente ao gabarito"
        linhas = ["diferente do gabarito:"]
        for c in self.componentes_faltando:
            linhas.append(f"- falta o componente {c}")
        for c in self.componentes_sobrando:
            linhas.append(f"- sobra o componente {c}")
        for pino, (antes, depois) in self.pinos_divergentes.items():
            linhas.append(f"- {pino}: esperado com {antes or 'nada'}, "
                          f"obtido com {depois or 'nada'}")
        return "\n".join(linhas)


# --- Leitura da S-expression -----------------------------------------------------------------

def _tokens(texto: str):
    i, n = 0, len(texto)
    while i < n:
        c = texto[i]
        if c.isspace():
            i += 1
        elif c in "()":
            yield c
            i += 1
        elif c == '"':
            j, partes = i + 1, []
            while j < n and texto[j] != '"':
                if texto[j] == "\\" and j + 1 < n:
                    j += 1
                partes.append(texto[j])
                j += 1
            if j >= n:
                raise ErroNetlist(["texto entre aspas sem fechar"])
            yield ("str", "".join(partes))
            i = j + 1
        else:
            j = i
            while j < n and not texto[j].isspace() and texto[j] not in '()"':
                j += 1
            yield ("str", texto[i:j])
            i = j


def ler_sexpr(texto: str) -> list:
    """Lê uma S-expression: cada lista vira uma lista Python, cada átomo um ``str``."""
    pilha: list[list] = [[]]
    for tok in _tokens(texto):
        if tok == "(":
            pilha.append([])
        elif tok == ")":
            if len(pilha) == 1:
                raise ErroNetlist(["parêntese ')' sem '(' correspondente"])
            feito = pilha.pop()
            pilha[-1].append(feito)
        else:
            pilha[-1].append(tok[1])
    if len(pilha) != 1:
        raise ErroNetlist(["parêntese '(' sem fechar"])
    if len(pilha[0]) != 1 or not isinstance(pilha[0][0], list):
        raise ErroNetlist(["o arquivo precisa ter uma única expressão (export ...)"])
    return pilha[0][0]


def _filhos(no: list, chave: str) -> list[list]:
    return [f for f in no[1:] if isinstance(f, list) and f and f[0] == chave]


def _valor(no: list, chave: str) -> str | None:
    """O primeiro átomo de ``(chave átomo)`` dentro de ``no``, ou None."""
    achados = _filhos(no, chave)
    if not achados or len(achados[0]) < 2 or not isinstance(achados[0][1], str):
        return None
    return achados[0][1]


# --- Estrutura ---------------------------------------------------------------------------------

def _identificar(ref: str, comp: list, base: dict[str, Componente], problemas: list[str]):
    """(chave do componente, id da peça, [(número, rótulo do pino) por posição]) ou None."""
    valor = _valor(comp, "value")
    footprint = _valor(comp, "footprint")
    lib = _filhos(comp, "libsource")
    simbolo = f"{_valor(lib[0], 'lib')}:{_valor(lib[0], 'part')}" if lib else None
    if not valor:
        problemas.append(f"{ref}: sem 'value'; não dá para saber qual peça da base é")
        return None
    id_peca, _, nome_conector = valor.partition(" ")
    peca = base.get(id_peca)
    if peca is None:
        problemas.append(f"{ref}: value {valor!r} não começa pelo id de uma peça da base")
        return None
    fisicos = {c.nome: c for c in peca.conectores_fisicos()}
    if peca.conectores:
        conector = fisicos.get(nome_conector)
        if conector is None:
            problemas.append(f"{ref}: {id_peca} não tem o conector {nome_conector!r} "
                             f"(tem {sorted(fisicos)})")
            return None
        chave = f"{id_peca}/{conector.nome}"
    else:
        if nome_conector:
            problemas.append(f"{ref}: {id_peca} tem um conector só; value {valor!r} não confere")
            return None
        [conector] = fisicos.values()
        chave = id_peca
    if footprint != conector.kicad_footprint:
        problemas.append(f"{ref}: footprint {footprint!r} não é o da base "
                         f"({conector.kicad_footprint!r}) para {chave}")
        return None
    if simbolo != conector.kicad_simbolo:
        problemas.append(f"{ref}: símbolo {simbolo!r} não é o da base "
                         f"({conector.kicad_simbolo!r}) para {chave}")
        return None
    nomes = {p.numero: p.nome for p in peca.pinos}
    contagem = Counter(nomes.values())
    pinos = [(n, f"{id_peca}: {nomes[n]}" + (f"#{n}" if contagem[nomes[n]] > 1 else ""))
             for n in conector.pinos]
    return chave, id_peca, pinos


def ler_estrutura(netlist, base: dict[str, Componente] | None = None) -> Estrutura:
    """Lê a netlist (caminho ou texto) e devolve a ``Estrutura``. Levanta ``ErroNetlist``."""
    base = carregar_todos() if base is None else base
    if isinstance(netlist, Path) or (isinstance(netlist, str) and not netlist.lstrip()
                                     .startswith("(")):
        origem = str(netlist)
        texto = Path(netlist).read_text(encoding="utf-8")
    else:
        origem, texto = "netlist", netlist
    try:
        raiz = ler_sexpr(texto)
    except ErroNetlist as e:
        raise ErroNetlist(e.problemas, origem) from None
    if raiz[0] != "export":
        raise ErroNetlist([f"esperava (export ...), achei ({raiz[0]} ...)"], origem)

    problemas: list[str] = []
    posicoes: dict[str, list[tuple[int, str]]] = {}     # ref -> pinos por posição
    componentes: list[str] = []
    for bloco in _filhos(raiz, "components"):
        for comp in _filhos(bloco, "comp"):
            ref = _valor(comp, "ref")
            if not ref:
                problemas.append("componente sem 'ref'")
                continue
            if ref in posicoes:
                problemas.append(f"referência {ref} repetida")
                continue
            achado = _identificar(ref, comp, base, problemas)
            posicoes[ref] = achado[2] if achado else []
            if achado:
                componentes.append(achado[0])
    for chave, n in Counter(componentes).items():
        if n > 1:
            problemas.append(f"{chave} aparece {n} vezes: duas unidades da mesma peça ainda "
                             "não são comparáveis (ADR-012)")

    grupos, isolados, rede_do_pino = [], [], {}
    for bloco in _filhos(raiz, "nets"):
        for net in _filhos(bloco, "net"):
            nome = _valor(net, "name") or f"(código {_valor(net, 'code')})"
            pinos = []
            for node in _filhos(net, "node"):
                ref, pino = _valor(node, "ref"), _valor(node, "pin")
                if ref not in posicoes:
                    problemas.append(f"rede {nome}: o componente {ref!r} não existe")
                    continue
                if not posicoes[ref]:
                    continue                           # componente já apontado acima
                if not pino or not pino.isdigit() or not 1 <= int(pino) <= len(posicoes[ref]):
                    problemas.append(f"rede {nome}: {ref} não tem o pino {pino!r}")
                    continue
                rotulo = posicoes[ref][int(pino) - 1][1]
                if rotulo in rede_do_pino:
                    problemas.append(f"{ref} pino {pino} ({rotulo}) está nas redes "
                                     f"{rede_do_pino[rotulo]} e {nome}")
                    continue
                rede_do_pino[rotulo] = nome
                pinos.append(rotulo)
            if len(pinos) >= 2:
                grupos.append(frozenset(pinos))
            else:
                isolados.extend(pinos)
    if problemas:
        raise ErroNetlist(problemas, origem)
    return Estrutura(frozenset(componentes), frozenset(grupos), frozenset(isolados))


def comparar(esperado, obtido, base: dict[str, Componente] | None = None) -> Comparacao:
    """Compara duas netlists (caminho, texto ou ``Estrutura``) pela estrutura elétrica."""
    base = carregar_todos() if base is None else base
    a = esperado if isinstance(esperado, Estrutura) else ler_estrutura(esperado, base)
    b = obtido if isinstance(obtido, Estrutura) else ler_estrutura(obtido, base)

    def vizinhos(estrutura: Estrutura) -> dict[str, frozenset[str]]:
        return {p: g - {p} for g in estrutura.grupos for p in g}

    va, vb = vizinhos(a), vizinhos(b)
    divergentes = {p: (sorted(va.get(p, ())), sorted(vb.get(p, ())))
                   for p in sorted(set(va) | set(vb)) if va.get(p) != vb.get(p)}
    resultado = Comparacao(
        equivalente=a.componentes == b.componentes and a.grupos == b.grupos,
        componentes_faltando=sorted(a.componentes - b.componentes),
        componentes_sobrando=sorted(b.componentes - a.componentes),
        grupos_faltando=sorted(sorted(g) for g in a.grupos - b.grupos),
        grupos_sobrando=sorted(sorted(g) for g in b.grupos - a.grupos),
        pinos_divergentes=divergentes,
    )
    return resultado


def main(argumentos: list[str]) -> int:
    """``python -m src.evals.comparar esperado.net obtido.net``: 0 se equivalentes, 1 se não."""
    if len(argumentos) != 2:
        print("uso: python -m src.evals.comparar <esperado.net> <obtido.net>")
        return 2
    try:
        resultado = comparar(Path(argumentos[0]), Path(argumentos[1]))
    except ErroNetlist as e:
        print(e)
        return 2
    print(resultado.resumo())
    return 0 if resultado.equivalente else 1


if __name__ == "__main__":
    import sys
    sys.exit(main(sys.argv[1:]))
