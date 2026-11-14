"""Mostra no terminal, em tempo real e em poucas linhas, o que o agente está fazendo.

O registro completo do laço (com o texto inteiro de cada resultado) vai para arquivo; aqui
cada passo vira uma linha com o tempo de espera, os tokens e o custo até agora, e cada
ferramenta vira uma linha com o resultado resumido:

    [10:02:21] passo 1 · 5.8 s · 12.345 + 800 tokens · US$ 0,0021 (até agora US$ 0,0021)
               pensa: Vou procurar os componentes da especificação.
               ok   buscar_componente(termo='esp32')
               ERRO selecionar_componente(id='x', ref='U9') -> componente_inexistente: ...

Tudo sai com ``flush``, para aparecer na hora mesmo dentro do Docker.
"""
from collections.abc import Callable
from datetime import datetime

from .laco import Evento

LARGURA = 110                       # corte das linhas longas, em caracteres
RECUO = " " * 11                    # alinha com o texto depois de "[hh:mm:ss] "


def _cortar(texto: str, largura: int = LARGURA) -> str:
    texto = " ".join(str(texto).split())
    return texto if len(texto) <= largura else texto[: largura - 3] + "..."


def _milhar(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def dolares(valor: float | None) -> str:
    """US$ com 4 casas e vírgula, ou "?" quando o custo é desconhecido."""
    return "?" if valor is None else "US$ " + f"{valor:.4f}".replace(".", ",")


class Terminal:
    """Recebe os ``Evento`` do laço e escreve o andamento. ``escrever`` é o ``print``."""

    def __init__(self, escrever: Callable[[str], None] | None = None):
        self.escrever = escrever or (lambda linha: print(linha, flush=True))
        self.custo: float | None = 0.0

    def info(self, mensagem: str) -> None:
        """Uma linha com a hora na frente."""
        self.escrever(f"[{datetime.now():%H:%M:%S}] {mensagem}")

    def detalhe(self, mensagem: str, marca: str = "") -> None:
        """Uma linha recuada, embaixo da anterior, com ``marca`` (ok, ERRO) na frente."""
        self.escrever(RECUO + (f"{marca:<5}" if marca else "") + _cortar(mensagem))

    def reiniciar(self) -> None:
        """Zera o custo acumulado (uma execução nova)."""
        self.custo = 0.0

    def __call__(self, evento: Evento) -> None:
        if evento.tipo == "resposta":
            self._resposta(evento)
        else:
            self._chamada(evento)

    def _resposta(self, evento: Evento) -> None:
        r = evento.resposta
        if self.custo is not None:
            self.custo = None if r.custo_usd is None else self.custo + r.custo_usd
        pedidos = f"{len(r.chamadas)} ferramenta(s)" if r.chamadas else "terminou"
        self.info(f"passo {evento.passo} · {evento.segundos:.1f} s · "
                  f"{_milhar(r.tokens_entrada)} + {_milhar(r.tokens_saida)} tokens · "
                  f"{dolares(r.custo_usd)} (até agora {dolares(self.custo)}) · {pedidos}")
        if r.texto:
            self.detalhe(f"pensa: {r.texto}")

    def _chamada(self, evento: Evento) -> None:
        c, saida = evento.chamada, evento.saida or {}
        argumentos = ", ".join(f"{k}={v!r}" for k, v in c.argumentos.items())
        if saida.get("ok"):
            self.detalhe(f"{c.nome}({argumentos})", "ok")
        else:
            self.detalhe(f"{c.nome}({argumentos}) -> {saida.get('erro')}: "
                         f"{saida.get('mensagem', '')}", "ERRO")
