"""A primeira aprovação do usuário (Marco 5, Parte 2 do guia do MVP; ADR-016).

Depois do briefing, antes de qualquer ligação, o usuário vê no terminal o que o agente
entendeu: os componentes escolhidos, as decisões que o próprio agente tomou (as marcadas
com ``decidido_por: agente``), as pendências e o custo estimado, se a base tiver preços. Ele
responde ``s`` para seguir ou escreve uma correção em português, que volta para o agente.

Este módulo não chama nenhum modelo de IA: monta o resumo a partir da especificação já
validada e da base de componentes, e interpreta a resposta. Quem leva a correção ao agente
é o briefing (``src/briefing.py``).

Uso:
    veredito = pedir_aprovacao(spec, base, pendencias)
    if veredito.aprovada: ...
    else: correcao = veredito.correcao
"""
from collections.abc import Callable, Sequence
from dataclasses import dataclass

from .agente.ferramentas import Pendencia
from .componentes.modelo import Componente
from .especificacao import Decisao, Especificacao

# Respostas que aprovam, comparadas sem maiúsculas e sem espaços nas pontas.
APROVA = frozenset({"s", "sim"})

PERGUNTA = "Responda s para seguir, ou escreva o que deve mudar: "

ROTULOS = {"alimentacao": "alimentação", "restricoes.camadas": "camadas",
           "restricoes.contorno": "contorno", "restricoes.montagem": "montagem"}


@dataclass(frozen=True)
class Veredito:
    """A resposta do usuário: aprovada, ou uma correção para o agente."""
    aprovada: bool
    correcao: str | None = None


def interpretar(resposta: str) -> Veredito | None:
    """``s`` (ou ``sim``) aprova; outro texto é correção; vazio é ``None`` (pergunte de novo)."""
    texto = resposta.strip()
    if not texto:
        return None
    if texto.casefold() in APROVA:
        return Veredito(aprovada=True)
    return Veredito(aprovada=False, correcao=texto)


def rotulo(caminho: str, spec: Especificacao) -> str:
    """Nome legível de uma decisão: ``modulos.2`` vira ``módulo "display"``."""
    partes = caminho.split(".")
    if partes[0] == "modulos":
        modulo = spec.modulos[int(partes[1])]
        if len(partes) == 2:
            return f'módulo "{modulo.papel}"'
        return f'requisito {int(partes[3]) + 1} do módulo "{modulo.papel}"'
    return ROTULOS.get(caminho, caminho)


def _valor(caminho: str, spec: Especificacao, decisao: Decisao) -> str:
    """O que foi decidido, em poucas palavras."""
    if caminho == "alimentacao":
        return f"{spec.alimentacao.origem}, {spec.alimentacao.tensao:g} V"
    if caminho == "restricoes.camadas":
        return f"{spec.restricoes.camadas.valor} camada(s)"
    if caminho == "restricoes.contorno":
        c = spec.restricoes.contorno
        return f"{c.largura:g} x {c.altura:g} mm"
    if caminho == "restricoes.montagem":
        return spec.restricoes.montagem.valor
    if hasattr(decisao, "componente"):
        return decisao.componente
    return decisao.descricao


def _fonte(decisao: Decisao) -> str:
    partes = []
    if decisao.fonte is not None:
        pagina = f", p. {decisao.fonte.pagina}" if decisao.fonte.pagina else ""
        partes.append(decisao.fonte.documento + pagina)
    partes += [f"regra {r.regra} de {r.componente}" for r in decisao.regras]
    return "; ".join(partes)


# A base ainda não guarda preços (CLAUDE.md: preços ficam separados dos dados físicos, com
# loja e data). Sem preço na base, nenhum valor é estimado, nem de memória.
SEM_PRECOS = "não estimado: a base de componentes ainda não tem preços."


def resumir(spec: Especificacao, base: dict[str, Componente],
            pendencias: Sequence[Pendencia] = ()) -> str:
    """O resumo da primeira aprovação, pronto para o terminal."""
    linhas = [f"=== {spec.projeto.nome} ({spec.projeto.id}) ===",
              spec.projeto.descricao, "", "Componentes escolhidos:"]
    for m in spec.modulos:
        comp = base[m.componente]
        aviso = "" if comp.status == "revisado" else f" [{comp.status}: dados ainda não conferidos]"
        linhas.append(f"  - {m.papel}: {m.componente} ({comp.descricao}) · "
                      f"decidido por {m.decidido_por}{aviso}")
    r = spec.restricoes
    linhas += ["", f"Alimentação: {spec.alimentacao.origem}, {spec.alimentacao.tensao:g} V",
               f"Placa: {r.camadas.valor} camada(s), {r.contorno.largura:g} x "
               f"{r.contorno.altura:g} mm, montagem {r.montagem.valor}"]

    do_agente = [(c, d) for c, d in spec.decisoes() if d.decidido_por == "agente"]
    linhas += ["", f"Decisões tomadas pelo agente ({len(do_agente)}):"]
    if not do_agente:
        linhas.append("  (nenhuma)")
    for caminho, d in do_agente:
        linhas.append(f"  - {rotulo(caminho, spec)}: {_valor(caminho, spec, d)}")
        linhas.append(f"      motivo: {' '.join(d.motivo.split())}")
        linhas.append(f"      fonte: {_fonte(d)}")

    linhas += ["", f"Pendências ({len(pendencias)}):"]
    if not pendencias:
        linhas.append("  (nenhuma)")
    linhas += [f"  - {p.necessidade}: {p.motivo}" for p in pendencias]

    linhas += ["", f"Custo estimado: {SEM_PRECOS}"]
    return "\n".join(linhas)


def pedir_aprovacao(spec: Especificacao, base: dict[str, Componente],
                    pendencias: Sequence[Pendencia] = (),
                    ler: Callable[[str], str] = input,
                    escrever: Callable[[str], None] = print) -> Veredito:
    """Mostra o resumo e lê a resposta até ela ser ``s`` ou uma correção.

    ``ler`` é o ``input``: um ``EOFError`` ou ``KeyboardInterrupt`` dele passa direto, e quem
    chamou decide como cancelar.
    """
    escrever("\n" + resumir(spec, base, pendencias) + "\n")
    while True:
        veredito = interpretar(ler(PERGUNTA))
        if veredito is not None:
            return veredito
