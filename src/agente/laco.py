"""O laço do agente: PENSA -> AGE -> OBSERVA -> PENSA... (Marco 4, Parte 3).

Veio do ``agente_minimo.py`` do protótipo (seção 3, "O LAÇO DO AGENTE"). O que mudou:

- as ferramentas são as reais (``ferramentas.Ferramentas``), que conferem tudo na base;
- o laço não conhece nenhum provedor de IA. Ele conversa com um objeto ``Provedor``
  (princípio 5 do CLAUDE.md: toda dependência externa fica atrás de um adaptador). O
  adaptador da Anthropic está em ``provedores/claude.py`` (ADR-011);
- cada execução devolve um ``Execucao`` com o texto final, o estado do projeto, as chamadas,
  os tokens e o custo, que o eval da Parte 6 (``src/evals/rodar.py``) mede.

O laço não executa código gerado pelo modelo: só chama as seis ferramentas, pelo nome.

``rodar_agente`` é o agente do Marco 4. O laço em si está em ``conversar``, que recebe o
prompt, os contratos e quem executa as ferramentas; o briefing do Marco 5
(``src/briefing.py``, ADR-016) usa o mesmo laço com as ferramentas dele.
"""
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Literal, Protocol

from .contratos import CONTRATOS
from .ferramentas import Ferramentas

# Mude a versão sempre que mudar SISTEMA, PEDIDO ou o texto de um contrato (docs/evals.md).
VERSAO_DO_PROMPT = "1"

SISTEMA = """Você é um engenheiro eletrônico projetando uma PCB.
Regras:
- NUNCA use dados de componentes da sua memória. Consulte sempre as ferramentas.
- Só use componentes que existem na base, pelo id exato que buscar_componente devolve.
- Se uma peça necessária não existir na base, registre uma pendência com registrar_pendencia.
  Nunca invente um id, um pino ou um dado técnico.
- Antes de conectar, leia os dados da peça com ler_dados_componente e use os nomes de pino
  da base.
- Registre cada decisão de engenharia com o motivo e a fonte (componente, regra ou pino da
  base, ou decisão da especificação).
- Se uma ferramenta recusar um pedido, leia o erro e o próximo passo antes de tentar de novo.
Responda em português."""

PEDIDO = """Especificação da placa (YAML):

{spec}

Selecione os componentes da base, faça todas as ligações de cada pino usado e registre as
decisões e as pendências necessárias."""


def montar_pedido(arquivo: Path) -> str:
    """O primeiro pedido ao agente: o texto da especificação dentro de ``PEDIDO``."""
    return PEDIDO.format(spec=Path(arquivo).read_text(encoding="utf-8").strip())


@dataclass(frozen=True)
class Chamada:
    """Um pedido de ferramenta feito pelo modelo."""
    nome: str
    argumentos: dict
    id: str | None = None          # alguns provedores identificam cada chamada


@dataclass(frozen=True)
class Resposta:
    """Uma resposta do modelo, já traduzida pelo adaptador."""
    texto: str = ""
    chamadas: tuple[Chamada, ...] = ()
    tokens_entrada: int = 0            # toda a entrada, incluindo a lida e a gravada no cache
    tokens_saida: int = 0
    tokens_cache_leitura: int = 0      # parte de tokens_entrada lida do cache
    tokens_cache_escrita: int = 0      # parte de tokens_entrada gravada no cache
    custo_usd: float | None = None     # None quando o adaptador não sabe o preço


class Provedor(Protocol):
    """O que o laço precisa de um provedor de IA. O adaptador guarda o histórico."""

    def iniciar(self, sistema: str, contratos: list[dict], pedido: str) -> Resposta: ...

    def continuar(self, resultados: list[tuple[Chamada, dict]]) -> Resposta: ...

    def responder(self, texto: str) -> Resposta:
        """Manda uma mensagem de texto quando a última resposta não pediu ferramenta.

        Só o briefing usa (``conversar`` com ``ao_parar``, ADR-016)."""
        ...


@dataclass(frozen=True)
class Evento:
    """O que acontece no laço, para quem acompanha (``terminal.Terminal``).

    ``resposta``: o modelo respondeu (com ``resposta`` e ``segundos`` de espera).
    ``chamada``: uma ferramenta rodou (com ``chamada`` e ``saida``).
    """
    tipo: Literal["resposta", "chamada"]
    passo: int
    resposta: Resposta | None = None
    segundos: float = 0.0
    chamada: Chamada | None = None
    saida: dict | None = None


@dataclass
class Execucao:
    """O resultado de uma execução do agente."""
    texto_final: str
    terminou: bool                 # False se o limite de passos acabou antes
    passos: int                    # respostas do modelo
    chamadas: list[tuple[Chamada, dict]] = field(default_factory=list)
    estado: dict = field(default_factory=dict)
    tentativas_inexistentes: list[str] = field(default_factory=list)
    tokens_entrada: int = 0
    tokens_saida: int = 0
    tokens_cache_leitura: int = 0
    tokens_cache_escrita: int = 0
    custo_usd: float | None = 0.0      # soma das respostas; None se alguma não tinha preço


def rodar_agente(pedido: str, provedor: Provedor, ferramentas: Ferramentas | None = None,
                 max_passos: int = 30,
                 registrar: Callable[[str], None] | None = print,
                 eventos: Callable[[Evento], None] | None = None) -> Execucao:
    """Roda o agente sobre ``pedido`` até ele parar de pedir ferramentas ou acabar os passos.

    ``registrar`` recebe cada linha do registro completo (PENSA, AGE, OBSERVA); ``None``
    silencia. ``eventos`` recebe cada ``Evento``, para mostrar o andamento no terminal.
    """
    ferramentas = Ferramentas() if ferramentas is None else ferramentas
    execucao = conversar(pedido, provedor, SISTEMA, CONTRATOS, ferramentas.executar_ferramenta,
                         max_passos=max_passos, registrar=registrar, eventos=eventos)
    execucao.estado = ferramentas.estado()
    execucao.tentativas_inexistentes = list(ferramentas.tentativas_inexistentes)
    return execucao


def conversar(pedido: str, provedor: Provedor, sistema: str, contratos: list[dict],
              executar: Callable[[str, dict], dict], max_passos: int = 30,
              registrar: Callable[[str], None] | None = print,
              eventos: Callable[[Evento], None] | None = None,
              encerrar: Callable[[], bool] | None = None,
              ao_parar: Callable[[Resposta], str | None] | None = None) -> Execucao:
    """O laço PENSA -> AGE -> OBSERVA, sem saber quais são as ferramentas.

    ``executar(nome, argumentos)`` roda cada pedido do modelo e devolve o dicionário que
    volta para ele. O laço para quando o modelo não pede nenhuma ferramenta, quando
    ``encerrar()`` fica verdadeiro depois das ferramentas de um passo (o briefing para assim
    que a especificação é aprovada, ADR-016) ou quando acabam os passos. A ``Execucao``
    volta sem ``estado``: quem conhece as ferramentas preenche.

    ``ao_parar(resposta)`` é chamado quando o modelo para sem pedir ferramenta. Se devolver
    um texto, ele vai ao modelo (``provedor.responder``) e o laço segue; se devolver
    ``None``, o laço termina. Sem ``ao_parar``, o laço termina, como no Marco 4.
    """
    log = registrar or (lambda _linha: None)
    avisar = eventos or (lambda _evento: None)
    execucao = Execucao(texto_final="", terminou=False, passos=0)

    inicio = time.monotonic()
    resposta = provedor.iniciar(sistema, contratos, pedido)
    for passo in range(1, max_passos + 1):
        avisar(Evento("resposta", passo, resposta=resposta,
                      segundos=time.monotonic() - inicio))
        execucao.passos = passo
        execucao.tokens_entrada += resposta.tokens_entrada
        execucao.tokens_saida += resposta.tokens_saida
        execucao.tokens_cache_leitura += resposta.tokens_cache_leitura
        execucao.tokens_cache_escrita += resposta.tokens_cache_escrita
        if execucao.custo_usd is not None:
            execucao.custo_usd = (None if resposta.custo_usd is None
                                  else execucao.custo_usd + resposta.custo_usd)
        if resposta.texto:
            log(f"[passo {passo}] PENSA: {resposta.texto}")
        if not resposta.chamadas:               # nenhum pedido de ferramenta
            lembrete = ao_parar(resposta) if ao_parar is not None else None
            if lembrete is None:                # terminou
                execucao.texto_final = (resposta.texto
                                        or "O agente encerrou sem resposta textual.")
                execucao.terminou = True
                break
            if passo == max_passos:
                execucao.texto_final = "Limite de passos atingido sem conclusão."
                break
            log(f"[passo {passo}] LEMBRETE: {lembrete}")
            inicio = time.monotonic()
            resposta = provedor.responder(lembrete)
            continue
        resultados = []
        for chamada in resposta.chamadas:
            log(f"[passo {passo}] AGE: {chamada.nome}({chamada.argumentos})")
            saida = executar(chamada.nome, chamada.argumentos)
            log(f"[passo {passo}] OBSERVA: {saida}")
            avisar(Evento("chamada", passo, chamada=chamada, saida=saida))
            resultados.append((chamada, saida))
        execucao.chamadas.extend(resultados)
        if encerrar is not None and encerrar():
            execucao.texto_final = resposta.texto
            execucao.terminou = True
            break
        if passo == max_passos:
            execucao.texto_final = "Limite de passos atingido sem conclusão."
            break
        inicio = time.monotonic()
        resposta = provedor.continuar(resultados)

    return execucao
