"""Roda o agente uma vez sobre uma especificação, como o ``__main__`` do protótipo.

Uso (precisa da biblioteca anthropic e da chave em ANTHROPIC_API_KEY):
    python -m src.agente [spec.yaml] [--modelo claude-haiku-5-5] [--esforco medium]

Mostra o andamento passo a passo (``terminal.Terminal``) e, no fim, a resposta final, as
decisões, as pendências e as redes. Cada resposta do modelo e cada ferramenta vão para o
registro de custos (``src/custos.py``, ADR-017). No fim, o motor de regras confere o
circuito do agente (``src/regras.py``) e grava ``estado.json`` e ``regras.json`` em
``saida/agente/<projeto>/``.
"""
import argparse
import json
import sys
import time
from pathlib import Path

from ..componentes.carregar import carregar_todos
from ..custos import SAIDA as SAIDA_CUSTOS
from ..custos import Custos
from ..especificacao import ler_especificacao
from ..regras import ErroCircuito, verificar
from .ferramentas import Ferramentas
from .laco import montar_pedido, rodar_agente
from .terminal import Terminal, dolares

SPEC = Path(__file__).resolve().parents[2] / "placas" / "monitor-umidade" / "spec.yaml"
SAIDA = Path("saida/agente")


def conferir_regras(estado: dict, base, spec, pasta: Path, custos: Custos) -> None:
    """Depois do agente, o motor de regras confere o circuito (ADR-017). Grava o estado e o
    relatório em ``pasta``. O agente não participa: ele só propôs as ligações."""
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "estado.json").write_text(
        json.dumps(estado, indent=2, ensure_ascii=False, default=list), encoding="utf-8")
    inicio = time.monotonic()
    try:
        relatorio = verificar(estado, base, wifi=spec.wifi.valor if spec.wifi else None)
    except ErroCircuito as e:
        custos.operacao("motor_de_regras", "verificar", time.monotonic() - inicio,
                        "circuito inválido, nada verificado")
        print(f"\n=== MOTOR DE REGRAS ===\nNada verificado: {e}")
        return
    c = relatorio.contagem()
    custos.operacao("motor_de_regras", "verificar", time.monotonic() - inicio,
                    f"{'aprovado' if relatorio.aprovado else 'reprovado'}: {c['violada']} "
                    f"violada(s), {c['nao_verificavel']} não verificável(is)")
    (pasta / "regras.json").write_text(
        json.dumps(relatorio.para_dict(), indent=2, ensure_ascii=False), encoding="utf-8")
    print("\n=== MOTOR DE REGRAS ===\n" + relatorio.texto())
    print(f"(estado e relatório em {pasta})")


def main(argumentos: list[str]) -> int:
    from .provedores.claude import ESFORCO, MODELO, ProvedorClaude
    parser = argparse.ArgumentParser(prog="python -m src.agente",
                                     description="Roda o agente uma vez sobre a especificação.")
    parser.add_argument("spec", nargs="?", type=Path, default=SPEC)
    parser.add_argument("--modelo", default=MODELO, help=f"padrão: {MODELO}")
    parser.add_argument("--esforco", default=ESFORCO,
                        choices=["low", "medium", "high", "xhigh", "max"],
                        help=f"padrão: {ESFORCO}")
    parser.add_argument("--saida", type=Path, default=SAIDA,
                        help=f"pasta do estado e do relatório de regras (padrão: {SAIDA})")
    parser.add_argument("--custos", type=Path, default=SAIDA_CUSTOS,
                        help=f"pasta do registro de custos (padrão: {SAIDA_CUSTOS})")
    opcoes = parser.parse_args(argumentos)

    terminal = Terminal()
    base = carregar_todos()
    spec = ler_especificacao(opcoes.spec, base)
    ferramentas = Ferramentas(base, spec)
    custos = Custos(spec.projeto.id)
    terminal.info(f"agente sobre {opcoes.spec} · {opcoes.modelo} · esforço {opcoes.esforco}")
    try:
        execucao = rodar_agente(montar_pedido(opcoes.spec),
                                ProvedorClaude(opcoes.modelo, esforco=opcoes.esforco),
                                ferramentas, registrar=None,
                                eventos=custos.ouvinte("agente", terminal))
        print("\n=== RESPOSTA FINAL ===\n" + execucao.texto_final)
        for titulo, chave in [("DECISÕES", "decisoes"), ("PENDÊNCIAS", "pendencias"),
                              ("REDES", "redes")]:
            print(f"\n=== {titulo} ===")
            print(json.dumps(execucao.estado[chave], indent=2, ensure_ascii=False,
                             default=list))
        print(f"\npassos: {execucao.passos}, chamadas: {len(execucao.chamadas)}, "
              f"tokens: {execucao.tokens_entrada} + {execucao.tokens_saida}, "
              f"custo: {dolares(execucao.custo_usd)}")
        conferir_regras(execucao.estado, base, spec, opcoes.saida / spec.projeto.id, custos)
    finally:
        if custos.lancamentos:
            print(f"custos desta execução ({custos.execucao}) em "
                  f"{custos.gravar(opcoes.custos)}")
    return 0 if execucao.terminou else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
