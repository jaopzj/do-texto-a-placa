"""Roda o agente uma vez sobre uma especificação, como o ``__main__`` do protótipo.

Uso (precisa da biblioteca anthropic e da chave em ANTHROPIC_API_KEY):
    python -m src.agente [spec.yaml] [--modelo claude-haiku-5-5] [--esforco medium]

Mostra o andamento passo a passo (``terminal.Terminal``) e, no fim, a resposta final, as
decisões, as pendências e as redes.
"""
import argparse
import json
import sys
from pathlib import Path

from ..componentes.carregar import carregar_todos
from ..especificacao import ler_especificacao
from .ferramentas import Ferramentas
from .laco import montar_pedido, rodar_agente
from .terminal import Terminal, dolares

SPEC = Path(__file__).resolve().parents[2] / "placas" / "monitor-umidade" / "spec.yaml"


def main(argumentos: list[str]) -> int:
    from .provedores.claude import ESFORCO, MODELO, ProvedorClaude
    parser = argparse.ArgumentParser(prog="python -m src.agente",
                                     description="Roda o agente uma vez sobre a especificação.")
    parser.add_argument("spec", nargs="?", type=Path, default=SPEC)
    parser.add_argument("--modelo", default=MODELO, help=f"padrão: {MODELO}")
    parser.add_argument("--esforco", default=ESFORCO,
                        choices=["low", "medium", "high", "xhigh", "max"],
                        help=f"padrão: {ESFORCO}")
    opcoes = parser.parse_args(argumentos)

    terminal = Terminal()
    base = carregar_todos()
    ferramentas = Ferramentas(base, ler_especificacao(opcoes.spec, base))
    terminal.info(f"agente sobre {opcoes.spec} · {opcoes.modelo} · esforço {opcoes.esforco}")
    execucao = rodar_agente(montar_pedido(opcoes.spec),
                            ProvedorClaude(opcoes.modelo, esforco=opcoes.esforco),
                            ferramentas, registrar=None, eventos=terminal)
    print("\n=== RESPOSTA FINAL ===\n" + execucao.texto_final)
    for titulo, chave in [("DECISÕES", "decisoes"), ("PENDÊNCIAS", "pendencias"),
                          ("REDES", "redes")]:
        print(f"\n=== {titulo} ===")
        print(json.dumps(execucao.estado[chave], indent=2, ensure_ascii=False, default=list))
    print(f"\npassos: {execucao.passos}, chamadas: {len(execucao.chamadas)}, "
          f"tokens: {execucao.tokens_entrada} + {execucao.tokens_saida}, "
          f"custo: {dolares(execucao.custo_usd)}")
    return 0 if execucao.terminou else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
