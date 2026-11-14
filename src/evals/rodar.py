"""Eval do gabarito: roda o agente N vezes e mede cada execução (Marco 4, Parte 6).

Para cada execução, sobre o ``spec.yaml`` da placa:

1. roda o agente (``laco.rodar_agente``) com ferramentas novas e um provedor novo;
2. gera a netlist do estado final (``gerar_netlist``) e compara com o gabarito pela
   estrutura (``comparar``);
3. registra se bateu, quantas tentativas de peça inexistente houve, quantas chamadas, os
   tokens e o custo.

Cada execução fica em ``<saida>/<n>/``: o registro do laço (``registro.txt``), o estado do
projeto (``estado.json``), a netlist (``agente.net``, se deu para gerar) e o resultado
(``resultado.json``). Um erro numa execução (da API, da geração ou da leitura da netlist)
conta como execução que não bateu, com o motivo, e o eval segue para a próxima.

Uso, dentro do container (``make eval``), com a chave em ``ANTHROPIC_API_KEY``:

    python -m src.evals.rodar --n 5 --registrar

``--registrar`` acrescenta a linha da rodada à tabela de ``docs/evals.md`` (ADR-013).
"""
import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path

from ..agente.ferramentas import Ferramentas
from ..agente.laco import VERSAO_DO_PROMPT, Provedor, montar_pedido, rodar_agente
from ..agente.terminal import Terminal, dolares
from ..componentes.carregar import carregar_todos
from ..componentes.modelo import Componente
from ..especificacao import ler_especificacao
from ..gerar_netlist import ErroGeracao, gerar_netlist
from .comparar import ErroNetlist, comparar

RAIZ = Path(__file__).resolve().parents[2]
SPEC = RAIZ / "placas" / "monitor-umidade" / "spec.yaml"
GABARITO = RAIZ / "placas" / "monitor-umidade" / "gabarito.net"
EVALS_MD = RAIZ / "docs" / "evals.md"
SAIDA = RAIZ / "saida" / "evals"
META = 4            # execuções equivalentes ao gabarito, em 5 (guia, Parte 6)


@dataclass(frozen=True)
class ResultadoExecucao:
    """O que o eval mede numa execução do agente."""
    indice: int
    equivalente: bool
    motivo: str                    # resumo da comparação, ou o erro que impediu a medida
    terminou: bool
    passos: int
    chamadas: int
    tentativas_inexistentes: int
    pendencias: int
    tokens_entrada: int
    tokens_saida: int
    custo_usd: float | None
    segundos: float


@dataclass
class Rodada:
    """Uma rodada do eval: N execuções com o mesmo prompt e o mesmo modelo."""
    data: str
    versao_do_prompt: str
    modelo: str
    esforco: str
    execucoes: list[ResultadoExecucao] = field(default_factory=list)

    @property
    def acertos(self) -> int:
        return sum(e.equivalente for e in self.execucoes)

    @property
    def custo_total(self) -> float | None:
        custos = [e.custo_usd for e in self.execucoes]
        return None if not custos or None in custos else sum(custos)

    @property
    def meta_atingida(self) -> bool:
        """4 de 5, ou a mesma proporção para outro N."""
        n = len(self.execucoes)
        return n > 0 and self.acertos * 5 >= META * n

    def linha_markdown(self, observacao: str = "") -> str:
        n = len(self.execucoes)
        total = self.custo_total
        inexistentes = sum(e.tentativas_inexistentes for e in self.execucoes)
        chamadas = sum(e.chamadas for e in self.execucoes) / n if n else 0
        celulas = [
            self.data, self.versao_do_prompt, self.modelo, self.esforco,
            f"{self.acertos} de {n}", "sim" if self.meta_atingida else "não",
            str(inexistentes), f"{chamadas:.1f}",
            "?" if total is None else f"{total / n:.2f}",
            "?" if total is None else f"{total:.2f}",
            observacao.replace("|", "/").strip() or "-",
        ]
        return "| " + " | ".join(celulas) + " |"


def executar_uma(indice: int, provedor: Provedor, spec: Path, gabarito: Path,
                 base: dict[str, Componente], pasta: Path,
                 terminal: Terminal | None = None) -> ResultadoExecucao:
    """Roda o agente uma vez, mede contra o gabarito e grava os arquivos em ``pasta``.

    Com ``terminal``, mostra cada passo do agente e cada etapa da medida enquanto acontece.
    """
    pasta.mkdir(parents=True, exist_ok=True)
    info = terminal.info if terminal else (lambda _m: None)
    linhas: list[str] = []
    inicio = time.monotonic()
    ferramentas = Ferramentas(base, ler_especificacao(spec, base))
    try:
        execucao = rodar_agente(montar_pedido(spec), provedor, ferramentas,
                                registrar=linhas.append, eventos=terminal)
    except Exception as erro:          # a API pode falhar (rede, chave, limite de uso)
        info(f"o agente falhou: {type(erro).__name__}: {erro}")
        (pasta / "registro.txt").write_text("\n".join(linhas), encoding="utf-8")
        estado = ferramentas.estado()
        return ResultadoExecucao(
            indice=indice, equivalente=False,
            motivo=f"o agente falhou: {type(erro).__name__}: {erro}", terminou=False,
            passos=0, chamadas=0,
            tentativas_inexistentes=len(ferramentas.tentativas_inexistentes),
            pendencias=len(estado["pendencias"]), tokens_entrada=0, tokens_saida=0,
            custo_usd=None, segundos=time.monotonic() - inicio)

    (pasta / "registro.txt").write_text("\n".join(linhas + ["", execucao.texto_final]),
                                        encoding="utf-8")
    (pasta / "estado.json").write_text(
        json.dumps(execucao.estado, indent=2, ensure_ascii=False, default=list),
        encoding="utf-8")
    info(f"agente {'terminou' if execucao.terminou else 'NÃO terminou'} em "
         f"{execucao.passos} passo(s); gerando a netlist do estado")
    try:
        netlist = pasta / "agente.net"
        gerar_netlist(execucao.estado, netlist, base)
        info(f"netlist em {netlist}; comparando com {gabarito.name}")
        comparacao = comparar(gabarito, netlist, base)
        equivalente, motivo = comparacao.equivalente, comparacao.resumo()
    except (ErroGeracao, ErroNetlist) as erro:
        equivalente, motivo = False, str(erro)
        info(f"não deu para medir: {type(erro).__name__}")
    if not execucao.terminou:
        motivo = f"{motivo} (o agente não terminou: {execucao.texto_final})"
    return ResultadoExecucao(
        indice=indice, equivalente=equivalente, motivo=motivo, terminou=execucao.terminou,
        passos=execucao.passos, chamadas=len(execucao.chamadas),
        tentativas_inexistentes=len(execucao.tentativas_inexistentes),
        pendencias=len(execucao.estado["pendencias"]),
        tokens_entrada=execucao.tokens_entrada, tokens_saida=execucao.tokens_saida,
        custo_usd=execucao.custo_usd, segundos=time.monotonic() - inicio)


def rodar_eval(n: int, criar_provedor: Callable[[], Provedor], modelo: str, esforco: str,
               spec: Path = SPEC, gabarito: Path = GABARITO,
               base: dict[str, Componente] | None = None, saida: Path = SAIDA,
               avisar: Callable[[str], None] | None = None) -> Rodada:
    """Roda ``n`` execuções e devolve a ``Rodada``. ``criar_provedor`` dá um provedor novo
    a cada execução, para nenhuma conversa vazar para a seguinte. ``avisar`` recebe as
    linhas do andamento (o ``main`` usa ``print`` com ``flush``); ``None`` silencia."""
    if n < 1:
        raise ValueError("n precisa ser pelo menos 1")
    base = carregar_todos() if base is None else base
    ler_especificacao(spec, base)                      # falha antes de gastar com a API
    agora = datetime.now()
    pasta = Path(saida) / agora.strftime("%Y-%m-%d_%H%M%S")
    rodada = Rodada(data=agora.strftime("%Y-%m-%d"), versao_do_prompt=VERSAO_DO_PROMPT,
                    modelo=modelo, esforco=esforco)
    terminal = Terminal(avisar) if avisar else None
    if terminal:
        terminal.info(f"eval: {n} execução(ões) · {modelo} · esforço {esforco} · "
                      f"prompt {VERSAO_DO_PROMPT} · arquivos em {pasta}")
    for i in range(1, n + 1):
        if terminal:
            terminal.reiniciar()
            avisar("")
            terminal.info(f"=== execução {i} de {n} ===")
        resultado = executar_uma(i, criar_provedor(), spec, gabarito, base, pasta / str(i),
                                 terminal)
        (pasta / str(i) / "resultado.json").write_text(
            json.dumps(asdict(resultado), indent=2, ensure_ascii=False), encoding="utf-8")
        rodada.execucoes.append(resultado)
        if avisar:
            avisar(_linha_da_execucao(resultado))
    (pasta / "rodada.md").write_text(_relatorio(rodada), encoding="utf-8")
    if avisar:
        avisar(f"\n{rodada.acertos} de {n} equivalentes ao gabarito "
               f"(meta: {'atingida' if rodada.meta_atingida else 'não atingida'}); "
               f"custo total {dolares(rodada.custo_total)}; resultados em {pasta}")
    return rodada


CABECALHO = ("| Data | Prompt | Modelo | Esforço | Equivalentes | Meta | Peças inexistentes "
             "| Chamadas (média) | Custo médio (US$) | Custo total (US$) | Observação |\n"
             "|---|---|---|---|---|---|---|---|---|---|---|")
MARCADOR = "<!-- rodadas: rodar.py --registrar acrescenta as linhas abaixo -->"


def _linha_da_execucao(r: ResultadoExecucao) -> str:
    marca = "BATEU" if r.equivalente else "NÃO BATEU"
    return (f"[{r.indice}] {marca}: {r.chamadas} chamadas, {r.passos} passos, "
            f"{r.tentativas_inexistentes} peça(s) inexistente(s), {r.pendencias} pendência(s), "
            f"{r.tokens_entrada} + {r.tokens_saida} tokens, {dolares(r.custo_usd)}, "
            f"{r.segundos:.0f} s\n    {r.motivo.splitlines()[0]}")


def _relatorio(rodada: Rodada) -> str:
    linhas = [f"# Rodada de {rodada.data}", "",
              f"Prompt {rodada.versao_do_prompt}, {rodada.modelo}, esforço {rodada.esforco}.",
              "", CABECALHO, rodada.linha_markdown(), ""]
    for r in rodada.execucoes:
        linhas += [f"## Execução {r.indice}", "", "```", r.motivo, "```", ""]
    return "\n".join(linhas)


def registrar(rodada: Rodada, arquivo: Path = EVALS_MD, observacao: str = "") -> None:
    """Acrescenta a linha da rodada no fim da tabela de ``arquivo``."""
    texto = Path(arquivo).read_text(encoding="utf-8")
    if MARCADOR not in texto:
        raise ValueError(f"{arquivo} não tem o marcador da tabela de rodadas")
    antes, depois = texto.split(MARCADOR, 1)
    tabela, resto = _separar_tabela(depois)
    linhas = [ln for ln in tabela if not ln.startswith("| (nenhuma")]
    linhas.append(rodada.linha_markdown(observacao))
    Path(arquivo).write_text(antes + MARCADOR + "\n" + "\n".join(linhas) + "\n" + resto,
                             encoding="utf-8")


def _separar_tabela(texto: str) -> tuple[list[str], str]:
    """Divide o texto depois do marcador nas linhas da tabela e no que vem depois dela."""
    linhas = texto.lstrip("\n").split("\n")
    fim = next((i for i, ln in enumerate(linhas) if not ln.startswith("|")), len(linhas))
    return linhas[:fim], "\n".join(linhas[fim:])


def main(argumentos: list[str] | None = None) -> int:
    from ..agente.provedores.claude import ESFORCO, MODELO, PRECOS, ProvedorClaude

    parser = argparse.ArgumentParser(prog="python -m src.evals.rodar",
                                     description="Roda o agente N vezes contra o gabarito.")
    parser.add_argument("--n", type=int, default=5, help="número de execuções (padrão: 5)")
    parser.add_argument("--modelo", default=MODELO, help=f"padrão: {MODELO}")
    parser.add_argument("--esforco", default=ESFORCO,
                        choices=["low", "medium", "high", "xhigh", "max"],
                        help=f"padrão: {ESFORCO}")
    parser.add_argument("--spec", type=Path, default=SPEC)
    parser.add_argument("--gabarito", type=Path, default=GABARITO)
    parser.add_argument("--saida", type=Path, default=SAIDA)
    parser.add_argument("--registrar", action="store_true",
                        help="acrescenta a rodada à tabela de docs/evals.md")
    parser.add_argument("--observacao", default="", help="texto da coluna Observação")
    opcoes = parser.parse_args(argumentos)
    if opcoes.n < 1:
        parser.error("--n precisa ser pelo menos 1")
    if opcoes.modelo not in PRECOS:
        print(f"aviso: sem preço para {opcoes.modelo}; o custo sai como '?'")

    rodada = rodar_eval(opcoes.n, lambda: ProvedorClaude(opcoes.modelo, esforco=opcoes.esforco),
                        opcoes.modelo, opcoes.esforco, opcoes.spec, opcoes.gabarito,
                        saida=opcoes.saida, avisar=lambda linha: print(linha, flush=True))
    print(CABECALHO + "\n" + rodada.linha_markdown(opcoes.observacao))
    if opcoes.registrar:
        registrar(rodada, EVALS_MD, opcoes.observacao)
        print(f"Rodada registrada em {EVALS_MD}")
    return 0 if rodada.meta_atingida else 1


if __name__ == "__main__":
    sys.exit(main())
