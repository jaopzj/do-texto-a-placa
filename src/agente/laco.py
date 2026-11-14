"""O laço do agente: PENSA -> AGE -> OBSERVA -> PENSA... (Marco 4, Parte 3).

Veio do ``agente_minimo.py`` do protótipo (seção 3, "O LAÇO DO AGENTE"). O que mudou:

- as ferramentas são as reais (``ferramentas.Ferramentas``), que conferem tudo na base;
- o laço não conhece nenhum provedor de IA. Ele conversa com um objeto ``Provedor``
  (princípio 5 do CLAUDE.md: toda dependência externa fica atrás de um adaptador). O
  adaptador da Anthropic está em ``provedores/claude.py`` (ADR-011);
- cada execução devolve um ``Execucao`` com o texto final, o estado do projeto, as chamadas
  e os tokens, que o eval da Parte 6 vai medir.

O laço não executa código gerado pelo modelo: só chama as seis ferramentas, pelo nome.
"""
from dataclasses import dataclass, field
from typing import Callable, Protocol

from .contratos import CONTRATOS
from .ferramentas import Ferramentas

# Mude a versão sempre que mudar SISTEMA ou o texto de um contrato (docs/evals.md).
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
    tokens_entrada: int = 0
    tokens_saida: int = 0


class Provedor(Protocol):
    """O que o laço precisa de um provedor de IA. O adaptador guarda o histórico."""

    def iniciar(self, sistema: str, contratos: list[dict], pedido: str) -> Resposta: ...

    def continuar(self, resultados: list[tuple[Chamada, dict]]) -> Resposta: ...


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


def rodar_agente(pedido: str, provedor: Provedor, ferramentas: Ferramentas | None = None,
                 max_passos: int = 30,
                 registrar: Callable[[str], None] | None = print) -> Execucao:
    """Roda o agente sobre ``pedido`` até ele parar de pedir ferramentas ou acabar os passos.

    ``registrar`` recebe cada linha do registro (PENSA, AGE, OBSERVA); ``None`` silencia.
    """
    ferramentas = Ferramentas() if ferramentas is None else ferramentas
    log = registrar or (lambda _linha: None)
    execucao = Execucao(texto_final="", terminou=False, passos=0)

    resposta = provedor.iniciar(SISTEMA, CONTRATOS, pedido)
    for passo in range(1, max_passos + 1):
        execucao.passos = passo
        execucao.tokens_entrada += resposta.tokens_entrada
        execucao.tokens_saida += resposta.tokens_saida
        if resposta.texto:
            log(f"[passo {passo}] PENSA: {resposta.texto}")
        if not resposta.chamadas:               # nenhum pedido de ferramenta: terminou
            execucao.texto_final = resposta.texto or "O agente encerrou sem resposta textual."
            execucao.terminou = True
            break
        resultados = []
        for chamada in resposta.chamadas:
            log(f"[passo {passo}] AGE: {chamada.nome}({chamada.argumentos})")
            saida = ferramentas.executar_ferramenta(chamada.nome, chamada.argumentos)
            log(f"[passo {passo}] OBSERVA: {saida}")
            resultados.append((chamada, saida))
        execucao.chamadas.extend(resultados)
        if passo == max_passos:
            execucao.texto_final = "Limite de passos atingido sem conclusão."
            break
        resposta = provedor.continuar(resultados)

    execucao.estado = ferramentas.estado()
    execucao.tentativas_inexistentes = list(ferramentas.tentativas_inexistentes)
    return execucao
