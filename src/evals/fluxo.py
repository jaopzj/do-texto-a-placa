"""Eval do fluxo completo (Marco 5, Parte 6 do guia do MVP; ADR-019).

Duas medidas, registradas em ``docs/evals.md``:

1. **Pedidos** (``src/evals/pedidos/*.yaml``): cada pedido roda o fluxo inteiro
   (``src/projeto.py``), do briefing aos arquivos da fábrica, com um usuário de roteiro: ele
   responde às perguntas com as ``respostas`` do arquivo (depois delas, "não sei") e
   responde ``s`` às duas aprovações. O caso passa quando a situação final está em
   ``esperado``: a mesma placa com outras palavras chega aos arquivos; um pedido com uma peça
   que a base não tem para com a pendência; um pedido impossível para com uma explicação,
   nunca com uma placa.
2. **Erros injetados**: o agente monta o circuito da placa de referência
   (``placas/monitor-umidade/spec.yaml``) e, depois que ele termina, o código estraga uma
   ligação. Passa quando a primeira conferência aponta o erro e o laço termina aprovado.

Chama a API da Anthropic (custa dinheiro). Uso, dentro do container (``make eval-fluxo``):

    python -m src.evals.fluxo [--sem-placa] [--so ID] [--registrar]
"""
import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal

import yaml
from pydantic import Field

from ..agente.ferramentas import Ferramentas
from ..agente.laco import Provedor
from ..aprovacao import PERGUNTA, PERGUNTA_DA_FABRICA
from ..briefing import VERSAO_DO_PROMPT as VERSAO_DO_BRIEFING
from ..componentes.carregar import carregar_todos
from ..componentes.modelo import Componente, Texto, _Estrito
from ..correcao import VERSAO_DO_PROMPT as VERSAO_DA_CORRECAO
from ..correcao import Laco
from ..custos import Custos
from ..drc import conferir_placa
from ..especificacao import ler_especificacao
from ..projeto import Fluxo, problemas_do_ambiente
from .rodar import EVALS_MD, acrescentar_na_tabela

RAIZ = Path(__file__).resolve().parents[2]
PEDIDOS = Path(__file__).resolve().parent / "pedidos"
REFERENCIA = RAIZ / "placas" / "monitor-umidade" / "spec.yaml"
SAIDA = RAIZ / "saida" / "evals" / "fluxo"
NAO_SEI = "não sei"
MARCADOR = "<!-- fluxo: fluxo.py --registrar acrescenta as linhas abaixo -->"
VERSAO = f"b{VERSAO_DO_BRIEFING}+c{VERSAO_DA_CORRECAO}"

Situacao = Literal["fabrica", "sem_placa", "pendencias", "reprovado", "recusado",
                   "falha_da_fabrica", "sem_especificacao"]


class Pedido(_Estrito):
    """Um arquivo de ``src/evals/pedidos/``."""
    tipo: Literal["mesma_placa", "peca_fora_da_base", "impossivel"]
    pedido: Texto
    respostas: list[Texto] = []
    esperado: list[Situacao] = Field(min_length=1)


def ler_pedidos(pasta: Path = PEDIDOS) -> dict[str, Pedido]:
    """Os pedidos, pelo nome do arquivo (sem ``.yaml``), em ordem."""
    return {a.stem: Pedido.model_validate(yaml.safe_load(a.read_text(encoding="utf-8")))
            for a in sorted(pasta.glob("*.yaml"))}


class UsuarioDeRoteiro:
    """Responde às perguntas pela lista e ``s`` às duas aprovações."""

    def __init__(self, respostas: list[str]):
        self.respostas = list(respostas)
        self.perguntas = 0

    def __call__(self, pergunta: str) -> str:
        if pergunta in (PERGUNTA, PERGUNTA_DA_FABRICA):
            return "s"
        self.perguntas += 1
        return self.respostas.pop(0) if self.respostas else NAO_SEI


# --- Erros injetados --------------------------------------------------------------------------

def _tira_vcc_do_sensor(f: Ferramentas) -> None:
    """O exemplo do guia: tirar uma ligação (a alimentação do sensor)."""
    _exigir(f.desconectar(_ref_de(f, "sensor-umidade-capacitivo"), "VCC"))


def _sensor_no_adc2(f: Ferramentas) -> None:
    """O sinal do sensor sai do pino em que o agente ligou e vai para o IO25 (ADC2)."""
    ref_sensor, ref_esp = (_ref_de(f, "sensor-umidade-capacitivo"),
                           _ref_de(f, "esp32-devkitc-v4"))
    redes = [l.rede for l in f.ligacoes.values() if (l.ref, l.nome) == (ref_sensor, "AOUT")]
    if not redes:
        raise ErroInjecao("o agente não ligou o AOUT do sensor")
    for lig in [l for l in f.ligacoes.values() if l.ref == ref_esp and l.rede == redes[0]]:
        _exigir(f.desconectar(ref_esp, lig.nome))
    _exigir(f.conectar(ref_esp, "IO25", redes[0]))


def _ref_de(f: Ferramentas, componente: str) -> str:
    refs = [ref for ref, id_ in f.selecoes.items() if id_ == componente]
    if len(refs) != 1:
        raise ErroInjecao(f"o agente selecionou {len(refs)} peça(s) {componente}")
    return refs[0]


class ErroInjecao(RuntimeError):
    """O circuito do agente não tem o que o erro injetado precisa estragar."""


def _exigir(saida: dict) -> None:
    if not saida.get("ok"):
        raise ErroInjecao(f"a injeção não pôde ser feita: {saida.get('mensagem')}")


INJECOES: dict[str, Callable[[Ferramentas], None]] = {
    "tira-vcc-do-sensor": _tira_vcc_do_sensor,
    "sensor-no-adc2": _sensor_no_adc2,
}


# --- Execução ---------------------------------------------------------------------------------

@dataclass(frozen=True)
class Caso:
    """O resultado de um caso do eval."""
    id: str
    tipo: str
    esperado: str
    obtido: str
    passou: bool
    detalhe: str
    custo_usd: float | None
    segundos: float


def _custo(custos: Custos) -> float | None:
    total = custos.resumo()["total"]
    return total["custo_calculado_usd"] if total["custo_completo"] else None


def rodar_pedido(nome: str, pedido: Pedido, provedor: Provedor, base: dict[str, Componente],
                 pasta: Path, com_placa: bool) -> Caso:
    """O fluxo completo de um pedido, com o terminal gravado em ``pasta/terminal.txt``."""
    pasta.mkdir(parents=True, exist_ok=True)
    linhas: list[str] = []
    custos, inicio = Custos(), time.monotonic()
    usuario = UsuarioDeRoteiro(pedido.respostas)
    try:
        fim = Fluxo(provedor, usuario, linhas.append, base=base, saida=pasta, custos=custos,
                    placa=conferir_placa if com_placa else None).rodar(pedido.pedido)
        obtido = fim.situacao
        detalhe = (fim.andamento.explicacao.splitlines()[0] if fim.andamento
                   else "o briefing terminou sem especificação aprovada")
    except Exception as e:                  # a API pode falhar (rede, chave, limite de uso)
        obtido, detalhe = "erro", f"{type(e).__name__}: {e}"
    (pasta / "terminal.txt").write_text("\n".join(linhas), encoding="utf-8")
    custos.gravar(pasta / "custos")
    return Caso(nome, pedido.tipo, " ou ".join(pedido.esperado), obtido,
                obtido in pedido.esperado, f"{usuario.perguntas} pergunta(s); {detalhe}",
                _custo(custos), time.monotonic() - inicio)


def rodar_injecao(nome: str, injetar: Callable[[Ferramentas], None], provedor: Provedor,
                  base: dict[str, Componente], pasta: Path, com_placa: bool) -> Caso:
    """O laço de correção sobre a placa de referência, com o erro injetado depois do agente."""
    pasta.mkdir(parents=True, exist_ok=True)
    linhas: list[str] = []
    custos, inicio = Custos("monitor-umidade"), time.monotonic()
    spec = ler_especificacao(REFERENCIA, base)
    placa = ((lambda estado, n: conferir_placa(estado, pasta / f"rodada-{n}", base))
             if com_placa else None)
    try:
        r = Laco(REFERENCIA, spec, provedor, base, placa, custos=custos,
                 registrar=linhas.append).comecar(injetar)
        detectou = bool(r.rodadas[0].problemas)
        obtido = ("detectado e corrigido" if detectou and r.aprovado else
                  "não detectado" if not detectou else f"detectado, não corrigido ({r.motivo})")
        primeiro = r.rodadas[0].problemas[0] if detectou else None
        detalhe = (f"{primeiro.etapa}/{primeiro.regra} em {primeiro.onde}; "
                   f"{r.correcoes} correção(ões)" if primeiro
                   else "a conferência não achou nada")
        (pasta / "estado.json").write_text(json.dumps(r.estado, indent=2, ensure_ascii=False),
                                           encoding="utf-8")
    except Exception as e:
        obtido, detalhe = "erro", f"{type(e).__name__}: {e}"
    (pasta / "registro.txt").write_text("\n".join(linhas), encoding="utf-8")
    custos.gravar(pasta / "custos")
    return Caso(nome, "erro_injetado", "detectado e corrigido", obtido,
                obtido == "detectado e corrigido", detalhe, _custo(custos),
                time.monotonic() - inicio)


def linha_markdown(caso: Caso, data: str, modelo: str, esforco: str, placa: bool,
                   observacao: str = "") -> str:
    celulas = [data, VERSAO, modelo, esforco, "sim" if placa else "não", caso.id, caso.tipo,
               caso.esperado, caso.obtido, "sim" if caso.passou else "NÃO",
               "?" if caso.custo_usd is None else f"{caso.custo_usd:.2f}",
               caso.detalhe + (f" ({observacao})" if observacao else "")]
    return "| " + " | ".join(" ".join(str(c).split()).replace("|", "/") or "-"
                             for c in celulas) + " |"


def main(argumentos: list[str] | None = None,
         criar_provedor: Callable[[], Provedor] | None = None,
         escrever: Callable[[str], None] = lambda linha: print(linha, flush=True)) -> int:
    from ..agente.provedores.claude import ESFORCO, MODELO
    parser = argparse.ArgumentParser(prog="python -m src.evals.fluxo",
                                     description="Eval do fluxo completo e dos erros injetados.")
    parser.add_argument("--modelo", default=MODELO, help=f"padrão: {MODELO}")
    parser.add_argument("--esforco", default=ESFORCO,
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--sem-placa", action="store_true",
                        help="para nas regras, sem roteamento, DRC nem arquivos da fábrica")
    parser.add_argument("--so", action="append", default=[],
                        help="roda só este caso (o nome do arquivo ou da injeção); repetível")
    parser.add_argument("--saida", type=Path, default=SAIDA)
    parser.add_argument("--registrar", action="store_true",
                        help="acrescenta os casos à tabela do fluxo em docs/evals.md")
    parser.add_argument("--evals-md", type=Path, default=EVALS_MD, help=argparse.SUPPRESS)
    parser.add_argument("--observacao", default="")
    opcoes = parser.parse_args(argumentos)

    if criar_provedor is None:
        from ..agente.provedores.claude import ProvedorClaude
        def criar_provedor():
            return ProvedorClaude(opcoes.modelo, esforco=opcoes.esforco)
    pedidos = ler_pedidos()
    casos = list(pedidos) + list(INJECOES)
    desconhecidos = sorted(set(opcoes.so) - set(casos))
    if desconhecidos:
        parser.error(f"casos desconhecidos {desconhecidos}; existem {casos}")
    escolhidos = [c for c in casos if not opcoes.so or c in opcoes.so]
    com_placa = not opcoes.sem_placa
    problemas = problemas_do_ambiente() if com_placa else []
    if problemas:
        escrever("O ambiente não consegue gerar a placa:\n- " + "\n- ".join(problemas))
        return 1
    base = carregar_todos()
    agora = datetime.now()
    pasta = opcoes.saida / agora.strftime("%Y-%m-%d_%H%M%S")
    escrever(f"eval do fluxo · {opcoes.modelo} · esforço {opcoes.esforco} · prompt {VERSAO} · "
             f"placa: {'sim' if com_placa else 'não'} · {len(escolhidos)} caso(s) em {pasta}")
    resultados: list[Caso] = []
    for nome in escolhidos:
        escrever(f"\n=== {nome} ===")
        if nome in pedidos:
            caso = rodar_pedido(nome, pedidos[nome], criar_provedor(), base, pasta / nome,
                                com_placa)
        else:
            caso = rodar_injecao(nome, INJECOES[nome], criar_provedor(), base, pasta / nome,
                                 com_placa)
        resultados.append(caso)
        escrever(f"{'PASSOU' if caso.passou else 'NÃO PASSOU'}: esperado {caso.esperado}, "
                 f"obtido {caso.obtido} · {caso.detalhe}")
    (pasta / "resultados.json").write_text(
        json.dumps([asdict(c) for c in resultados], indent=2, ensure_ascii=False),
        encoding="utf-8")
    linhas = [linha_markdown(c, agora.strftime("%Y-%m-%d"), opcoes.modelo, opcoes.esforco,
                             com_placa, opcoes.observacao) for c in resultados]
    escrever("\n" + "\n".join(linhas))
    passaram = sum(c.passou for c in resultados)
    escrever(f"\n{passaram} de {len(resultados)} caso(s) passaram; detalhes em {pasta}")
    if opcoes.registrar:
        acrescentar_na_tabela(opcoes.evals_md, MARCADOR, linhas)
        escrever(f"Casos registrados em {opcoes.evals_md}")
    return 0 if passaram == len(resultados) else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
