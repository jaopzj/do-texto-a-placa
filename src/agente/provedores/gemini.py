"""Adaptador do Gemini (Google) para o laço do agente (ADR-010).

É o único lugar do projeto que importa a biblioteca ``google-genai``. A chamada ao modelo é
a do ``agente_minimo.py`` do protótipo: ``generate_content`` com as ferramentas declaradas
e a chamada automática de funções desligada, para que toda ferramenta passe pelo nosso
código.

A biblioteca é importada só quando o adaptador é criado, então o resto do projeto (e os
testes) funciona sem ela. Ela ainda não está em ``docker/requirements.txt``.

A chave vem da variável de ambiente ``GEMINI_API_KEY`` (ou ``GOOGLE_API_KEY``), lida pela
própria biblioteca. Nunca escreva a chave no código.
"""
from ..laco import Chamada, Resposta

MODELO = "gemini-3.5-flash"   # o do protótipo; confira a disponibilidade


class ProvedorGemini:
    def __init__(self, modelo: str = MODELO, cliente=None, temperatura: float = 0.2,
                 max_tokens: int = 2000):
        from google import genai
        from google.genai import types
        self._types = types
        self.modelo = modelo
        self.cliente = genai.Client() if cliente is None else cliente
        self.temperatura = temperatura
        self.max_tokens = max_tokens
        self.mensagens: list = []
        self._config = None

    def iniciar(self, sistema: str, contratos: list[dict], pedido: str) -> Resposta:
        t = self._types
        ferramenta = t.Tool(function_declarations=[
            t.FunctionDeclaration(name=c["name"], description=c["description"],
                                  parameters_json_schema=c["parameters"])
            for c in contratos])
        self._config = t.GenerateContentConfig(
            system_instruction=sistema, tools=[ferramenta],
            automatic_function_calling=t.AutomaticFunctionCallingConfig(disable=True),
            temperature=self.temperatura, max_output_tokens=self.max_tokens)
        self.mensagens = [t.Content(role="user", parts=[t.Part.from_text(text=pedido)])]
        return self._gerar()

    def continuar(self, resultados: list[tuple[Chamada, dict]]) -> Resposta:
        t = self._types
        partes = [t.Part.from_function_response(name=chamada.nome, response=saida)
                  for chamada, saida in resultados]
        self.mensagens.append(t.Content(role="user", parts=partes))
        return self._gerar()

    def _gerar(self) -> Resposta:
        resposta = self.cliente.models.generate_content(
            model=self.modelo, contents=self.mensagens, config=self._config)
        self.mensagens.append(resposta.candidates[0].content)   # inclusive os pedidos
        return traduzir(resposta)


def traduzir(resposta) -> Resposta:
    """Converte a resposta do Gemini no formato neutro do laço."""
    chamadas = tuple(Chamada(nome=c.name, argumentos=dict(c.args or {}), id=c.id)
                     for c in (resposta.function_calls or []))
    uso = resposta.usage_metadata
    texto = "".join(p.text for p in (resposta.candidates[0].content.parts or [])
                    if getattr(p, "text", None) and not getattr(p, "thought", False))
    return Resposta(
        texto=texto, chamadas=chamadas,
        tokens_entrada=(uso.prompt_token_count or 0) if uso else 0,
        tokens_saida=(uso.candidates_token_count or 0) if uso else 0)
