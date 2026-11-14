"""Adaptador da API da Anthropic (Claude) para o laço do agente (ADR-011).

É o único lugar do projeto que importa a biblioteca ``anthropic``. O laço (``laco.py``) não
muda: este adaptador traduz os contratos para ferramentas da API, guarda o histórico da
conversa e devolve cada resposta no formato neutro (``Resposta``).

Escolhas:

- modelo ``claude-opus-5-5``, com raciocínio adaptativo (o padrão do modelo) e esforço
  ``high``, porque o trabalho é um laço de várias chamadas de ferramenta;
- o conteúdo inteiro de cada resposta volta para o histórico sem alteração, inclusive os
  blocos de raciocínio, como a API exige;
- os resultados de todas as ferramentas de um passo voltam numa única mensagem, com
  ``is_error`` quando a ferramenta recusou (``ok: False``);
- cache de prompt automático: o prompt de sistema e os contratos não mudam entre passos;
- se o modelo recusar o pedido por segurança, a API tenta de novo num modelo reserva
  (``fallbacks: "default"``). Se a recusa continuar, o laço termina com o motivo no texto.

A biblioteca é importada só quando o adaptador é criado, então o resto do projeto (e os
testes) funciona sem ela. A chave vem da variável de ambiente ``ANTHROPIC_API_KEY`` (ou de
um login feito com ``ant auth login``), lida pela própria biblioteca. Nunca escreva a chave
no código.
"""
import json

from ..laco import Chamada, Resposta

MODELO = "claude-opus-5-5"
ESFORCO = "high"
MAX_TOKENS = 16000
BETA_FALLBACK = "server-side-fallback-2026-07-01"


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
        resposta = self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=self.max_tokens,
            system=self.sistema,
            tools=self.ferramentas,
            messages=self.mensagens,
            thinking={"type": "adaptive"},
            output_config={"effort": self.esforco},
            cache_control={"type": "ephemeral"},
            betas=[BETA_FALLBACK],
            fallbacks="default",
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
    return Resposta(
        texto=texto, chamadas=chamadas,
        tokens_entrada=(uso.input_tokens or 0) + (getattr(uso, "cache_read_input_tokens", 0) or 0)
        + (getattr(uso, "cache_creation_input_tokens", 0) or 0),
        tokens_saida=uso.output_tokens or 0)
