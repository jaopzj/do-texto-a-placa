"""Roda o agente uma vez sobre uma especificação, como o ``__main__`` do protótipo.

Uso (precisa da biblioteca google-genai e da chave em GEMINI_API_KEY):
    python -m src.agente [placas/monitor-umidade/spec.yaml]

Mostra o registro do laço, a resposta final, as decisões, as pendências e as redes.
"""
import json
import sys
from pathlib import Path

from ..componentes.carregar import carregar_todos
from ..especificacao import ler_especificacao
from .ferramentas import Ferramentas
from .laco import rodar_agente

SPEC = Path(__file__).resolve().parents[2] / "placas" / "monitor-umidade" / "spec.yaml"

PEDIDO = """Especificação da placa (YAML):

{spec}

Selecione os componentes da base, faça todas as ligações de cada pino usado e registre as
decisões e as pendências necessárias."""


def montar_pedido(arquivo: Path) -> str:
    return PEDIDO.format(spec=Path(arquivo).read_text(encoding="utf-8").strip())


def main(argumentos: list[str]) -> int:
    from .provedores.gemini import ProvedorGemini
    arquivo = Path(argumentos[0]) if argumentos else SPEC
    base = carregar_todos()
    ferramentas = Ferramentas(base, ler_especificacao(arquivo, base))
    execucao = rodar_agente(montar_pedido(arquivo), ProvedorGemini(), ferramentas)
    print("=== RESPOSTA FINAL ===\n" + execucao.texto_final)
    for titulo, chave in [("DECISÕES", "decisoes"), ("PENDÊNCIAS", "pendencias"),
                          ("REDES", "redes")]:
        print(f"\n=== {titulo} ===")
        print(json.dumps(execucao.estado[chave], indent=2, ensure_ascii=False, default=list))
    print(f"\npassos: {execucao.passos}, chamadas: {len(execucao.chamadas)}, "
          f"tokens: {execucao.tokens_entrada} + {execucao.tokens_saida}")
    return 0 if execucao.terminou else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
