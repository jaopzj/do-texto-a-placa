"""Adaptador da API da Anthropic (Claude) para o laço do agente (ADR-011).

É o único lugar do projeto que importa a biblioteca ``anthropic``. O laço (``laco.py``) não
muda: este adaptador traduz os contratos para ferramentas da API, guarda o histórico da
conversa e devolve cada resposta no formato neutro (``Resposta``).

Escolhas:

- modelo ``claude-haiku-5-5`` por padrão (escolha do john, ADR-014; era o
  ``claude-opus-5-5`` no ADR-011), com raciocínio adaptativo e esforço ``high``, porque o
  trabalho é um laço de várias chamadas de ferramenta;
- o conteúdo inteiro de cada resposta volta para o histórico sem alteração, inclusive os
  blocos de raciocínio, como a API exige;
- os resultados de todas as ferramentas de um passo voltam numa única mensagem, com
  ``is_error`` quando a ferramenta recusou (``ok: False``);
- cache de prompt automático: o prompt de sistema e os contratos não mudam entre passos;
- se o modelo recusar o pedido por segurança, a API tenta de novo num modelo reserva
  (``fallbacks: "default"``). Se a recusa continuar, o laço termina com o motivo no texto.
  O Claude Haiku 5.5 não tem modelo reserva: para ele o pedido vai sem ``fallbacks``
  (``SEM_RESERVA``, ADR-014).

O custo de cada resposta é calculado com ``PRECOS``, pelo modelo que de fato respondeu
(``resposta.model``, que pode ser o reserva). Um modelo fora da tabela dá custo ``None``,
nunca um preço chutado.

A biblioteca é importada só quando o adaptador é criado, então o resto do projeto (e os
testes) funciona sem ela. A chave vem da variável de ambiente ``ANTHROPIC_API_KEY`` (ou de
um login feito com ``ant auth login``), lida pela própria biblioteca. Nunca escreva a chave
no código.
"""
import json

from ..laco import Chamada, Resposta

MODELO = "claude-haiku-5-5"
ESFORCO = "high"
MAX_TOKENS = 16000
BETA_FALLBACK = "server-side-fallback-2026-07-01"

# Modelos sem modelo reserva no servidor: o pedido não pode levar ``fallbacks``.
SEM_RESERVA = frozenset({"claude-haiku-5-5"})

# Preços em US$ por milhão de tokens: entrada, saída, leitura do cache e gravação no cache
# (TTL de 5 minutos, 1,25 vez a entrada). Cada modelo tem uma ou mais faixas
# (limite do prompt em tokens, preços); vale a primeira faixa cujo limite comporta o prompt
# inteiro do pedido (entrada + cache), e ``None`` é sem limite. O Haiku 5.5 cobra mais caro
# acima de 100 mil tokens de prompt. Fonte: tabela de preços dos modelos da Anthropic,
# consultada em 2026-11-14. Atualize junto com a data se o preço mudar.
Precos = tuple[float, float, float, float]
PRECOS: dict[str, tuple[tuple[int | None, Precos], ...]] = {
    "claude-opus-5-5": ((None, (4.00, 20.00, 0.20, 5.00)),),
    "claude-sonnet-5-5": ((None, (2.00, 10.00, 0.10, 2.50)),),
    "claude-haiku-5-5": ((100_000, (0.10, 0.50, 0.01, 0.125)),
                         (None, (0.50, 2.50, 0.05, 0.625))),
}


class ProvedorClaude:
    def __init__(self, modelo: str = MODELO, cliente=None, esforco: str = ESFORCO,
                 max_tokens: int = MAX_TOKENS):
        if cliente is None:
            import anthropic
            cliente = anthropic.Anthropic()
        self.cliente = cliente
        self.modelo = modelo
        self.esforco = esforco
        self.max_tokens = max_tokens
        self.sistema = ""
        self.ferramentas: list[dict] = []
        self.mensagens: list[dict] = []

    def iniciar(self, sistema: str, contratos: list[dict], pedido: str) -> Resposta:
        self.sistema = sistema
        self.ferramentas = [{"name": c["name"], "description": c["description"],
                             "input_schema": c["parameters"]} for c in contratos]
        self.mensagens = [{"role": "user", "content": pedido}]
        return self._gerar()

    def continuar(self, resultados: list[tuple[Chamada, dict]]) -> Resposta:
        self.mensagens.append({"role": "user", "content": [
            {"type": "tool_result", "tool_use_id": chamada.id,
             "content": json.dumps(saida, ensure_ascii=False),
             "is_error": not saida.get("ok", False)}
            for chamada, saida in resultados]})
        return self._gerar()

    def _gerar(self) -> Resposta:
        reserva = {} if self.modelo in SEM_RESERVA else {
            "betas": [BETA_FALLBACK], "fallbacks": "default"}
        resposta = self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=self.max_tokens,
            system=self.sistema,
            tools=self.ferramentas,
            messages=self.mensagens,
            thinking={"type": "adaptive"},
            output_config={"effort": self.esforco},
            cache_control={"type": "ephemeral"},
            **reserva,
        )
        self.mensagens.append({"role": "assistant", "content": resposta.content})
        return traduzir(resposta)


def traduzir(resposta) -> Resposta:
    """Converte a resposta da API no formato neutro do laço."""
    texto = "".join(b.text for b in resposta.content if b.type == "text")
    chamadas = tuple(Chamada(nome=b.name, argumentos=dict(b.input), id=b.id)
                     for b in resposta.content if b.type == "tool_use")
    if resposta.stop_reason == "refusal":
        detalhe = getattr(resposta, "stop_details", None)
        categoria = getattr(detalhe, "category", None) if detalhe else None
        texto = (texto + "\n" if texto else "") + f"[o modelo recusou o pedido: {categoria}]"
        chamadas = ()               # numa recusa, nenhum pedido de ferramenta é executado
    elif resposta.stop_reason == "max_tokens":
        texto = (texto + "\n" if texto else "") + "[resposta cortada no limite de tokens]"
        chamadas = ()               # um pedido cortado pode estar incompleto
    uso = resposta.usage
    sem_cache = uso.input_tokens or 0
    leitura = getattr(uso, "cache_read_input_tokens", 0) or 0
    escrita = getattr(uso, "cache_creation_input_tokens", 0) or 0
    saida = uso.output_tokens or 0
    return Resposta(
        texto=texto, chamadas=chamadas,
        tokens_entrada=sem_cache + leitura + escrita, tokens_saida=saida,
        tokens_cache_leitura=leitura, tokens_cache_escrita=escrita,
        custo_usd=custo(getattr(resposta, "model", None), sem_cache, saida, leitura, escrita))


def custo(modelo: str | None, entrada: int, saida: int, leitura: int, escrita: int
          ) -> float | None:
    """Custo em US$ de uma resposta, ou None se o modelo não está em ``PRECOS``."""
    faixas = PRECOS.get(modelo or "")
    if faixas is None:
        return None
    prompt = entrada + leitura + escrita
    precos = next(p for limite, p in faixas if limite is None or prompt <= limite)
    por_milhao = (entrada * precos[0] + saida * precos[1] + leitura * precos[2]
                  + escrita * precos[3])
    return por_milhao / 1_000_000
