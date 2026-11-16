"""O relatório de projeto (Marco 5, Parte 5 do guia do MVP; ADR-019).

Um ``relatorio.md`` por projeto, em ``saida/projetos/<projeto>/``, escrito pelo fluxo
completo (``src/projeto.py``) a cada etapa que muda o resultado. Ele diz, em português:

- em que situação o projeto parou e por quê;
- as decisões da especificação, quem decidiu, o motivo e a fonte, e as decisões que o
  agente registrou ao montar o circuito;
- as regras verificadas pelo motor de regras, regra a regra;
- as correções pedidas ao agente, e o que cada conferência encontrou;
- o resultado do DRC da placa roteada;
- a BOM (pela netlist do circuito, a mesma que vai para a fábrica);
- as pendências, do briefing e do agente;
- os arquivos da fábrica que foram de fato gerados e a conferência deles;
- os custos, por etapa.

Tudo vem dos objetos que o código já conferiu (especificação validada, ``Relatorio`` do
motor, ``ResultadoPlaca`` do DRC, ``ResultadoFabrica``). Este módulo só formata: não chama
modelo, não roda ferramenta e não decide nada.
"""
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Literal

from .aprovacao import fonte_da_decisao, rotulo, valor_da_decisao
from .componentes.modelo import Componente
from .correcao import ResultadoDoLaco, Rodada
from .custos import dolares
from .drc import caminho_legivel
from .especificacao import Especificacao
from .fabrica import ResultadoFabrica
from .gerar_netlist import ErroGeracao, planejar


Situacao = Literal["pendencias", "reprovado", "aguardando", "recusado", "fabrica",
                   "falha_da_fabrica", "sem_placa"]

TITULOS: dict[str, str] = {
    "pendencias": "PARADO: há pendências, nenhuma placa foi feita",
    "reprovado": "REPROVADO: o circuito não passou nas verificações, nenhuma placa foi entregue",
    "aguardando": "APROVADO PELO CÓDIGO: aguardando a segunda aprovação do usuário",
    "recusado": "PARADO PELO USUÁRIO: os arquivos da fábrica não foram gerados",
    "fabrica": "PRONTO: arquivos da fábrica gerados e conferidos",
    "falha_da_fabrica": ("FALHOU: os arquivos da fábrica não passaram na geração ou na "
                         "conferência"),
    "sem_placa": "CIRCUITO APROVADO, SEM PLACA: execução sem roteamento nem DRC",
}

SEM_WIFI = "não informado na especificação"

SITUACAO_DA_REGRA = {"ok": "ok", "violada": "**VIOLADA**",
                     "nao_verificavel": "**não verificável**", "manual": "manual"}


@dataclass
class Andamento:
    """O que o relatório descreve: até onde o projeto foi e o que o código conferiu."""
    pedido: str
    spec: Especificacao
    arquivo_spec: Path
    situacao: Situacao
    explicacao: str
    pendencias: list[dict] = field(default_factory=list)   # origem, necessidade, motivo
    laco: ResultadoDoLaco | None = None
    historico: list[Rodada] = field(default_factory=list)  # todas as conferências
    fabrica: ResultadoFabrica | None = None
    custos: dict | None = None                             # Custos.resumo()
    data: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))


def _celula(texto: object) -> str:
    """Texto de uma célula de tabela Markdown: numa linha só e sem quebrar as colunas."""
    return " ".join(str(texto).split()).replace("|", "\\|") or "—"


def _tabela(cabecalho: list[str], linhas: list[list[object]]) -> list[str]:
    saida = ["| " + " | ".join(cabecalho) + " |", "|" + "---|" * len(cabecalho)]
    saida += ["| " + " | ".join(_celula(c) for c in linha) + " |" for linha in linhas]
    return saida


def _decisoes(spec: Especificacao, laco: ResultadoDoLaco | None) -> list[str]:
    linhas = ["## Decisões e fontes", "",
              "Da especificação aprovada na primeira aprovação:", ""]
    linhas += _tabela(
        ["Decisão", "Valor", "Decidido por", "Motivo", "Fonte"],
        [[rotulo(c, spec), valor_da_decisao(c, spec, d), d.decidido_por, d.motivo or "",
          fonte_da_decisao(d)] for c, d in spec.decisoes()])
    decisoes = (laco.estado.get("decisoes") or []) if laco else []
    linhas += ["", f"Registradas pelo agente ao montar o circuito ({len(decisoes)}):", ""]
    if decisoes:
        linhas += _tabela(["Decisão", "Motivo", "Fontes"],
                          [[d["decisao"], d["motivo"], "; ".join(d["fontes"])]
                           for d in decisoes])
    else:
        linhas.append("(nenhuma)")
    return linhas


def _regras(laco: ResultadoDoLaco | None) -> list[str]:
    linhas = ["## Regras verificadas", ""]
    ultima = laco.rodadas[-1] if laco and laco.rodadas else None
    if ultima is None or ultima.regras is None:
        motivo = ("o agente não montou o circuito" if laco is None else
                  "o circuito parou antes do motor de regras (veja as conferências)")
        return linhas + [f"Não verificadas: {motivo}."]
    r = ultima.regras
    c = r.contagem()
    linhas.append(f"Motor de regras (ADR-017), na última conferência: "
                  f"**{'APROVADO' if r.aprovado else 'REPROVADO'}**, {c['ok']} ok, "
                  f"{c['violada']} violada(s), {c['nao_verificavel']} não verificável(is), "
                  f"{c['manual']} manual(is). Wi-Fi: "
                  f"{'sim' if r.wifi else 'não' if r.wifi is False else SEM_WIFI}.")
    linhas.append("")
    tabela = []
    for res in r.resultados:
        detalhe = [p.explicacao for p in res.problemas]
        if res.motivo_manual:
            detalhe.append(f"conferir à mão: {res.motivo_manual}")
        tabela.append([res.ref, res.componente, res.regra, res.severidade,
                       SITUACAO_DA_REGRA[res.situacao], " ".join(detalhe)])
    return linhas + _tabela(["Peça", "Componente", "Regra", "Severidade", "Situação",
                             "Detalhe"], tabela)


def _conferencias(historico: list[Rodada]) -> list[str]:
    linhas = ["## Conferências e correções", ""]
    if not historico:
        return linhas + ["Nenhuma conferência: o circuito não foi montado."]
    linhas.append("Cada conferência roda netlist, alimentação, regras e, se tudo passar, o "
                  "DRC. Os problemas voltam ao agente, até 3 correções (ADR-018).")
    linhas.append("")
    for i, rodada in enumerate(historico, 1):
        quem = "circuito entregue" if rodada.numero == 0 else f"correção {rodada.numero}"
        if rodada.erro_da_placa:
            linhas.append(f"{i}. {quem}: a placa não pôde ser feita ({rodada.erro_da_placa}).")
        elif not rodada.problemas:
            linhas.append(f"{i}. {quem}: nenhum problema.")
        else:
            linhas.append(f"{i}. {quem}: {len(rodada.problemas)} problema(s).")
            linhas += [f"   - [{p.etapa}] {p.regra}, em {p.onde}: {p.porque}"
                       for p in rodada.problemas]
    return linhas


def _drc(laco: ResultadoDoLaco | None) -> list[str]:
    linhas = ["## DRC", ""]
    ultima = laco.rodadas[-1] if laco and laco.rodadas else None
    if ultima is None or (ultima.placa is None and ultima.erro_da_placa is None):
        return linhas + ["Não rodou: o DRC só roda depois que o circuito passa na netlist, na "
                         "alimentação e nas regras, numa execução com placa."]
    if ultima.erro_da_placa:
        return linhas + [f"Não rodou: a placa não pôde ser feita ({ultima.erro_da_placa})."]
    placa = ultima.placa
    contam = [i for i in placa.drc if i.severidade != "ignore"]
    linhas.append(f"`kicad-cli pcb drc` na placa roteada `{caminho_legivel(placa.placa)}`: "
                  f"**{len(contam)} item(ns)** (relatório em "
                  f"`{caminho_legivel(placa.relatorio)}`).")
    for item in contam:
        linhas.append(f"- {item.tipo} ({item.severidade}): {item.descricao}")
    return linhas


def _bom(laco: ResultadoDoLaco | None, base: dict[str, Componente]) -> list[str]:
    linhas = ["## BOM", ""]
    if laco is None or not laco.estado.get("selecoes"):
        return linhas + ["Sem circuito, sem BOM."]
    circuito = {"selecoes": laco.estado["selecoes"], "ligacoes": laco.estado["ligacoes"]}
    try:
        plano = planejar(circuito, base)
    except ErroGeracao as e:
        return linhas + [f"Sem BOM: o circuito não vira netlist ({'; '.join(e.problemas)})."]
    linhas.append("Uma linha por conector da placa, pela netlist do circuito (a mesma da "
                  "`bom.csv` da fábrica):")
    linhas.append("")
    return linhas + _tabela(
        ["Referência", "Peça", "Módulo (base)", "Conector", "Footprint"],
        [[c.ref, c.ref_agente, c.id_peca, c.conector or "único", c.footprint]
         for c in plano.conectores])


def _pendencias(pendencias: list[dict]) -> list[str]:
    linhas = ["## Pendências", ""]
    if not pendencias:
        return linhas + ["(nenhuma)"]
    return linhas + [f"- ({p['origem']}) **{p['necessidade']}**: {p['motivo']}"
                     for p in pendencias]


def _fabrica(andamento: Andamento) -> list[str]:
    linhas = ["## Arquivos da fábrica", ""]
    f = andamento.fabrica
    if f is None:
        motivo = {"aguardando": "aguardando a segunda aprovação",
                  "recusado": "o usuário respondeu n na segunda aprovação",
                  "falha_da_fabrica": andamento.explicacao}.get(
            andamento.situacao, "o projeto parou antes (veja o resultado acima)")
        return linhas + [f"Não gerados: {motivo}."]
    linhas.append(f"Pasta `{caminho_legivel(f.pasta)}`. Conferência "
                  f"(`scripts/verificar_saidas.py`): {f.conferencia}")
    linhas.append("")
    return linhas + [f"- `{a.name}` ({a.stat().st_size} bytes)" for a in f.arquivos]


def _custos(custos: dict | None) -> list[str]:
    linhas = ["## Custos", ""]
    if not custos:
        return linhas + ["(sem registro)"]
    tabela = []
    for nome, s in list(custos["etapas"].items()) + [("total", custos["total"])]:
        tabela.append([nome, s["chamadas_llm"], s["operacoes"],
                       f"{s['tokens_entrada']} + {s['tokens_saida']}",
                       dolares(s["custo_calculado_usd"], s["custo_completo"],
                               s["chamadas_llm"]), f"{s['segundos']:g} s"])
    return linhas + _tabela(["Etapa", "Chamadas ao modelo", "Operações", "Tokens",
                             "Custo", "Tempo"], tabela) + [
        "", "O custo é calculado pela tabela de preços do adaptador; o valor cobrado está na "
            "fatura (ADR-017)."]


def montar(andamento: Andamento, base: dict[str, Componente]) -> str:
    """O ``relatorio.md`` inteiro."""
    spec = andamento.spec
    linhas = [f"# Relatório do projeto: {spec.projeto.nome} (`{spec.projeto.id}`)", "",
              f"- Data: {andamento.data}",
              f"- Pedido: {' '.join(andamento.pedido.split())}",
              f"- Especificação: `{caminho_legivel(andamento.arquivo_spec)}`",
              f"- Situação: **{TITULOS[andamento.situacao]}**", "",
              "## Resultado", "", andamento.explicacao, ""]
    for secao in (_decisoes(spec, andamento.laco), _regras(andamento.laco),
                  _conferencias(andamento.historico), _drc(andamento.laco),
                  _bom(andamento.laco, base), _pendencias(andamento.pendencias),
                  _fabrica(andamento), _custos(andamento.custos)):
        linhas += secao + [""]
    return "\n".join(linhas)


def gravar(andamento: Andamento, base: dict[str, Componente], pasta: Path) -> Path:
    """Grava ``pasta/relatorio.md`` e devolve o caminho."""
    pasta.mkdir(parents=True, exist_ok=True)
    arquivo = pasta / "relatorio.md"
    arquivo.write_text(montar(andamento, base), encoding="utf-8")
    return arquivo
