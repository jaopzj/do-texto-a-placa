"""O laço de correção (Marco 5, Parte 4 do guia do MVP; ADR-018).

Depois que o agente monta o circuito, o código confere, nesta ordem:

1. a netlist: o estado precisa virar um plano válido (``gerar_netlist.planejar``);
2. as regras: o motor de regras (``src/regras.py``, ADR-017) sobre o circuito;
3. a placa: netlist, placa, posições, roteamento e DRC (``src/drc.py``), só se 1 e 2
   passaram, porque não adianta rotear um circuito que viola uma regra.

Se houver problema, o código monta um relatório curto e estruturado (etapa, regra, onde,
por quê, como corrigir) e devolve ao agente, na mesma conversa, pedindo a correção. O
agente corrige com as ferramentas de sempre e mais ``desconectar``. O código confere tudo
de novo. São no máximo ``MAX_CORRECOES`` (3) pedidos de correção. Se o circuito ainda tiver
problema, ou se o agente não mudar nada numa correção (repetir não adiantaria), o laço para
e explica o problema em português, e nenhuma placa é entregue.

Quem decide é o código: o agente só vê o relatório, e o relatório não tem opção para
ignorar nada. Uma regra que o motor não conseguiu verificar (falta um dado na base) também
volta como problema, com o dado que falta: o agente pode trocar a ligação ou registrar uma
pendência, mas o circuito não é aprovado sem o dado.

Uso (precisa da biblioteca anthropic e da chave em ANTHROPIC_API_KEY):
    python -m src.correcao [spec.yaml] [--sem-placa] [--modelo ...] [--esforco ...]
"""
import argparse
import json
import sys
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Literal

from .agente.contratos import CONTRATOS_DE_CORRECAO
from .agente.ferramentas import Ferramentas
from .agente.laco import SISTEMA, Evento, Execucao, Provedor, conversar, montar_pedido
from .componentes.carregar import carregar_todos
from .componentes.modelo import Componente
from .custos import Custos
from .drc import ErroPlaca, ResultadoPlaca
from .especificacao import Especificacao
from .gerar_netlist import ErroGeracao, planejar
from .regras import Relatorio, verificar

MAX_CORRECOES = 3
MAX_PASSOS = 30
# Mude a versão sempre que mudar SISTEMA_DE_CORRECAO, PEDIDO_DE_CORRECAO ou o contrato de
# desconectar.
VERSAO_DO_PROMPT = "1"

SISTEMA_DE_CORRECAO = SISTEMA + """
Depois que você terminar, o código confere o circuito: a netlist, as regras da base (o motor
de regras) e o DRC da placa roteada. Se houver problema, você recebe um relatório e deve
corrigir as ligações com conectar e desconectar. Você não pode mudar, ignorar nem desligar
uma regra: só o circuito. Se um problema não tiver solução com as peças da base, registre uma
pendência com registrar_pendencia e diga por quê."""

PEDIDO_DE_CORRECAO = """O código conferiu o circuito e encontrou {n} problema(s). Esta é a
correção {numero} de no máximo {maximo}. Corrija as ligações (desconectar e conectar) e termine
quando acabar. Se não houver como corrigir com as peças da base, registre uma pendência.

{relatorio}"""

Etapa = Literal["netlist", "regras", "drc"]


@dataclass(frozen=True)
class Problema:
    """Um problema do relatório ao agente: qual etapa, qual regra, onde e por quê."""
    etapa: Etapa
    regra: str                       # id da regra, tipo do DRC ou "netlist"
    onde: str
    porque: str
    correcao: str | None = None


@dataclass
class Rodada:
    """Uma conferência do circuito: o que o código achou."""
    numero: int                      # 0: o circuito que o agente entregou; 1..3: correções
    problemas: list[Problema]
    regras: Relatorio | None = None
    placa: ResultadoPlaca | None = None
    erro_da_placa: str | None = None


@dataclass
class ResultadoDoLaco:
    aprovado: bool
    motivo: str                      # aprovado, limite, sem_mudanca, placa, sem_circuito
    rodadas: list[Rodada]
    estado: dict
    execucoes: list[Execucao] = field(default_factory=list)

    @property
    def correcoes(self) -> int:
        return len(self.rodadas) - 1

    @property
    def problemas(self) -> list[Problema]:
        return self.rodadas[-1].problemas if self.rodadas else []


def _da_netlist(erro: ErroGeracao) -> list[Problema]:
    return [Problema("netlist", "netlist", "estado do agente", p,
                     "corrija a ligação ou a peça apontada") for p in erro.problemas]


def _das_regras(relatorio: Relatorio) -> list[Problema]:
    problemas = []
    for r in relatorio.resultados:
        if not r.bloqueia:
            continue
        for p in r.problemas:
            onde = ", ".join(p.pinos + tuple(f"rede {n}" for n in p.redes)) or r.ref
            porque = (p.explicacao if p.situacao == "violada"
                      else f"não verificável: {p.explicacao}")
            problemas.append(Problema("regras", f"{r.componente}/{r.regra}", onde, porque,
                                      p.correcao))
    return problemas


def _do_drc(placa: ResultadoPlaca) -> list[Problema]:
    return [Problema("drc", item.tipo, "; ".join(item.itens) or "placa",
                     f"{item.descricao} ({item.severidade})",
                     "confira as ligações dessas peças; o posicionamento é o da placa de "
                     "referência") for item in placa.drc if item.severidade != "ignore"]


ConferirPlaca = Callable[[dict, int], ResultadoPlaca]


def conferir(estado: dict, base: dict[str, Componente], wifi: bool | None, numero: int,
             placa: ConferirPlaca | None = None, custos: Custos | None = None) -> Rodada:
    """Netlist, regras e (se as duas passarem e houver ``placa``) DRC do circuito."""
    custos = custos or Custos()
    inicio = time.monotonic()
    try:
        planejar(estado, base)
    except ErroGeracao as e:
        custos.operacao("netlist", "planejar", time.monotonic() - inicio,
                        f"{len(e.problemas)} problema(s)")
        return Rodada(numero, _da_netlist(e))
    inicio = time.monotonic()
    relatorio = verificar(estado, base, wifi=wifi)
    problemas = _das_regras(relatorio)
    c = relatorio.contagem()
    custos.operacao("motor_de_regras", "verificar", time.monotonic() - inicio,
                    f"rodada {numero}: {'aprovado' if relatorio.aprovado else 'reprovado'}, "
                    f"{c['violada']} violada(s), {c['nao_verificavel']} não verificável(is)")
    rodada = Rodada(numero, problemas, regras=relatorio)
    if problemas or placa is None:
        return rodada
    inicio = time.monotonic()
    try:
        rodada.placa = placa(estado, numero)
    except ErroPlaca as e:
        custos.operacao("drc", "placa", time.monotonic() - inicio, f"falhou em {e.etapa}")
        rodada.erro_da_placa = str(e)
        return rodada
    rodada.problemas = _do_drc(rodada.placa)
    custos.operacao("drc", "placa", time.monotonic() - inicio,
                    f"rodada {numero}: {len(rodada.problemas)} item(ns) no DRC")
    return rodada


def relatorio_para_o_agente(problemas: list[Problema]) -> str:
    """O relatório curto e estruturado que volta ao agente (JSON, um item por problema)."""
    return json.dumps({"problemas": [asdict(p) for p in problemas]}, ensure_ascii=False,
                      indent=1)


def corrigir(arquivo_spec: Path, spec: Especificacao, provedor: Provedor,
             base: dict[str, Componente] | None = None, placa: ConferirPlaca | None = None,
             max_correcoes: int = MAX_CORRECOES, custos: Custos | None = None,
             registrar: Callable[[str], None] | None = None,
             eventos: Callable[[Evento], None] | None = None,
             depois_do_agente: Callable[[Ferramentas], None] | None = None) -> ResultadoDoLaco:
    """O agente monta o circuito; o código confere; até ``max_correcoes`` pedidos de correção.

    ``depois_do_agente`` roda uma vez, depois que o agente entrega o primeiro circuito e
    antes da primeira conferência (os testes e o eval usam para injetar um erro)."""
    base = carregar_todos() if base is None else base
    custos = custos or Custos(spec.projeto.id)
    wifi = spec.wifi.valor if spec.wifi else None
    ferramentas = Ferramentas(base, spec, correcao=True)

    def rodar(pedido: str, etapa: str, retomar: bool) -> Execucao:
        return conversar(pedido, provedor, SISTEMA_DE_CORRECAO, CONTRATOS_DE_CORRECAO,
                         ferramentas.executar_ferramenta, max_passos=MAX_PASSOS,
                         registrar=registrar, eventos=custos.ouvinte(etapa, eventos),
                         retomar=retomar)

    execucoes = [rodar(montar_pedido(arquivo_spec), "agente", retomar=False)]
    if depois_do_agente is not None:
        depois_do_agente(ferramentas)
    rodadas: list[Rodada] = []
    anterior = None
    while True:
        estado = ferramentas.estado()
        circuito = {"selecoes": estado["selecoes"], "ligacoes": estado["ligacoes"]}
        rodada = conferir(circuito, base, wifi, len(rodadas), placa, custos)
        rodadas.append(rodada)
        if rodada.erro_da_placa:
            motivo = "placa"
        elif not rodada.problemas:
            motivo = "aprovado"
        elif not circuito["selecoes"]:
            motivo = "sem_circuito"
        elif anterior is not None and circuito == anterior:
            motivo = "sem_mudanca"
        elif rodada.numero >= max_correcoes:
            motivo = "limite"
        else:
            anterior = circuito
            pedido = PEDIDO_DE_CORRECAO.format(n=len(rodada.problemas),
                                               numero=rodada.numero + 1, maximo=max_correcoes,
                                               relatorio=relatorio_para_o_agente(rodada.problemas))
            execucoes.append(rodar(pedido, "correcao", retomar=True))
            continue
        return ResultadoDoLaco(motivo == "aprovado", motivo, rodadas, estado, execucoes)


def explicar(resultado: ResultadoDoLaco) -> str:
    """O resultado em português, para o usuário."""
    c = resultado.correcoes
    feitas = f"{c} correção(ões) pedida(s) ao agente"
    if resultado.aprovado:
        ultima = resultado.rodadas[-1]
        placa = (f" A placa roteada passou no DRC: {ultima.placa.placa}." if ultima.placa
                 else " O DRC não rodou (sem placa nesta execução).")
        return f"O circuito passou na netlist e nas regras, depois de {feitas}.{placa}"
    abertura = {
        "limite": f"O agente não resolveu os problemas em {feitas} (o limite é "
                  f"{MAX_CORRECOES}).",
        "sem_mudanca": f"Na última correção, o agente não mudou o circuito ({feitas}); "
                       "repetir o pedido não ia adiantar.",
        "sem_circuito": "O agente não montou nenhum circuito.",
        "placa": "O circuito passou nas regras, mas a placa não pôde ser feita: "
                 f"{resultado.rodadas[-1].erro_da_placa}.",
    }[resultado.motivo]
    linhas = [abertura, "Nenhuma placa foi entregue. O que ficou:"]
    for p in resultado.problemas:
        linhas.append(f"- [{p.etapa}] {p.regra}, em {p.onde}: {p.porque}"
                      + (f" Como corrigir: {p.correcao}" if p.correcao else ""))
    pendencias = resultado.estado.get("pendencias") or []
    if pendencias:
        linhas.append("Pendências registradas pelo agente:")
        linhas += [f"- {p.get('necessidade')}: {p.get('motivo')}" for p in pendencias]
    return "\n".join(linhas)


def para_dict(resultado: ResultadoDoLaco) -> dict:
    return {
        "aprovado": resultado.aprovado, "motivo": resultado.motivo,
        "correcoes": resultado.correcoes, "versao_do_prompt": VERSAO_DO_PROMPT,
        "rodadas": [{"numero": r.numero, "problemas": [asdict(p) for p in r.problemas],
                     "regras": r.regras.contagem() if r.regras else None,
                     "drc": (len(r.placa.drc) if r.placa else None),
                     "erro_da_placa": r.erro_da_placa} for r in resultado.rodadas],
    }


def main(argumentos: list[str], provedor: Provedor | None = None,
         escrever: Callable[[str], None] = print) -> int:
    """0: circuito aprovado (e placa no DRC, sem --sem-placa); 1: não aprovado."""
    from .agente.laco import ErroProvedor
    from .agente.provedores.claude import ESFORCO, MODELO
    from .agente.terminal import Terminal
    from .custos import SAIDA as SAIDA_CUSTOS
    from .drc import conferir_placa
    from .especificacao import ler_especificacao
    parser = argparse.ArgumentParser(
        prog="python -m src.correcao",
        description="Roda o agente com o laço de correção (regras e DRC).")
    parser.add_argument("spec", nargs="?", type=Path,
                        default=Path("placas/monitor-umidade/spec.yaml"))
    parser.add_argument("--modelo", default=MODELO, help=f"padrão: {MODELO}")
    parser.add_argument("--esforco", default=ESFORCO,
                        choices=["low", "medium", "high", "xhigh", "max"])
    parser.add_argument("--sem-placa", action="store_true",
                        help="confere só netlist e regras, sem rotear nem rodar o DRC "
                             "(fora do container)")
    parser.add_argument("--saida", type=Path, default=Path("saida/correcao"))
    parser.add_argument("--custos", type=Path, default=SAIDA_CUSTOS)
    opcoes = parser.parse_args(argumentos)

    base = carregar_todos()
    spec = ler_especificacao(opcoes.spec, base)
    pasta = opcoes.saida / spec.projeto.id
    custos = Custos(spec.projeto.id)
    placa = None if opcoes.sem_placa else (
        lambda estado, numero: conferir_placa(estado, pasta / f"rodada-{numero}", base))
    if provedor is None:
        from .agente.provedores.claude import ProvedorClaude
        provedor = ProvedorClaude(opcoes.modelo, esforco=opcoes.esforco)
    try:
        resultado = corrigir(opcoes.spec, spec, provedor, base, placa, custos=custos,
                             registrar=None, eventos=Terminal(escrever))
    except ErroProvedor as e:
        escrever(f"A API do modelo falhou: {e}. Nenhuma placa foi entregue.")
        return 1
    finally:
        if custos.lancamentos:
            escrever(f"custos desta execução ({custos.execucao}) em "
                     f"{custos.gravar(opcoes.custos)}")
    pasta.mkdir(parents=True, exist_ok=True)
    (pasta / "estado.json").write_text(json.dumps(resultado.estado, indent=2,
                                                  ensure_ascii=False, default=list),
                                       encoding="utf-8")
    (pasta / "correcao.json").write_text(json.dumps(para_dict(resultado), indent=2,
                                                    ensure_ascii=False), encoding="utf-8")
    escrever("\n=== LAÇO DE CORREÇÃO ===\n" + explicar(resultado))
    escrever(f"(estado e rodadas em {pasta})")
    return 0 if resultado.aprovado else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
