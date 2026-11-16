"""Registro de custos de execução (Marco 5; ADR-017).

Cada execução (um briefing, uma rodada do agente, uma verificação do motor de regras) tem
um ``Custos``. Ele anota, em ordem, um ``Lancamento`` por acontecimento:

- ``chamada_llm``: uma resposta do modelo, com modelo, passo, tokens de entrada e de saída
  (e a parte de cache), segundos de espera e custo;
- ``operacao``: algo que não chama o modelo (uma ferramenta do agente, o motor de regras),
  com o tempo que levou. Não tem custo de API.

O que é conhecido e o que é estimado fica separado, campo a campo:

- tokens e modelo são **medidos**: vêm da resposta da API, como a API os conta;
- o custo em US$ é **calculado** (``custo: "calculado"``): tokens vezes a tabela de preços do
  adaptador, citada em ``tabela_de_precos``. Não é o valor cobrado, que só a fatura da
  Anthropic dá;
- um modelo fora da tabela dá ``custo: "desconhecido"`` e ``custo_usd: null``. Nunca um preço
  chutado. Um resumo com algum desconhecido diz ``custo_completo: false``;
- uma operação tem ``custo: "sem_custo"`` (nenhuma chamada paga).

``gravar`` acrescenta os lançamentos, um JSON por linha, em
``saida/custos/<projeto>.jsonl`` (``sem-projeto.jsonl`` quando a execução não sabe o
projeto). O arquivo só cresce: cada execução tem um ``execucao`` próprio, e o resumo junta
por etapa e no total do projeto.

    python -m src.custos monitor-umidade              # resumo do projeto
    python -m src.custos monitor-umidade --detalhe    # cada lançamento
    python -m src.custos saida/custos/monitor-umidade.jsonl --execucao <id>
"""
import argparse
import json
import sys
import uuid
from collections.abc import Callable, Iterable
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from .agente.laco import Evento, Resposta

SAIDA = Path("saida/custos")
SEM_PROJETO = "sem-projeto"

Tipo = Literal["chamada_llm", "operacao"]
Custo = Literal["calculado", "desconhecido", "sem_custo"]


@dataclass(frozen=True)
class Lancamento:
    """Um acontecimento de uma execução, com o que ele custou."""
    momento: str                     # ISO 8601, UTC
    execucao: str
    projeto: str
    etapa: str                       # briefing, agente, motor_de_regras...
    tipo: Tipo
    nome: str                        # "resposta do modelo", o nome da ferramenta...
    segundos: float
    custo: Custo
    custo_usd: float | None = None   # só com custo "calculado"
    custo_acumulado_usd: float = 0.0  # soma dos custos calculados da execução até aqui
    modelo: str | None = None
    passo: int | None = None
    tokens_entrada: int = 0          # toda a entrada, com a parte de cache
    tokens_saida: int = 0
    tokens_cache_leitura: int = 0
    tokens_cache_escrita: int = 0
    tabela_de_precos: str | None = None
    detalhe: str | None = None


class Custos:
    """Os lançamentos de uma execução, na ordem em que aconteceram."""

    def __init__(self, projeto: str | None = None, execucao: str | None = None,
                 agora: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
        self.projeto = projeto or SEM_PROJETO
        self.execucao = execucao or uuid.uuid4().hex[:12]
        self._agora = agora
        self.lancamentos: list[Lancamento] = []

    @property
    def acumulado_usd(self) -> float:
        return sum(l.custo_usd for l in self.lancamentos if l.custo_usd is not None)

    def _anotar(self, **dados) -> Lancamento:
        lancamento = Lancamento(momento=self._agora().isoformat(timespec="seconds"),
                                execucao=self.execucao, projeto=self.projeto,
                                custo_acumulado_usd=self.acumulado_usd + (dados.get("custo_usd")
                                                                          or 0.0),
                                **dados)
        self.lancamentos.append(lancamento)
        return lancamento

    def chamada(self, etapa: str, resposta: Resposta, segundos: float = 0.0,
                passo: int | None = None, nome: str = "resposta do modelo") -> Lancamento:
        """Uma resposta do modelo. Sem preço conhecido, o custo fica desconhecido."""
        conhecido = resposta.custo_usd is not None
        return self._anotar(
            etapa=etapa, tipo="chamada_llm", nome=nome, segundos=round(segundos, 3),
            custo="calculado" if conhecido else "desconhecido",
            custo_usd=resposta.custo_usd, modelo=resposta.modelo, passo=passo,
            tokens_entrada=resposta.tokens_entrada, tokens_saida=resposta.tokens_saida,
            tokens_cache_leitura=resposta.tokens_cache_leitura,
            tokens_cache_escrita=resposta.tokens_cache_escrita,
            tabela_de_precos=resposta.custo_fonte if conhecido else None,
            detalhe=None if conhecido else f"o modelo {resposta.modelo!r} não está na tabela "
                                           "de preços do adaptador")

    def operacao(self, etapa: str, nome: str, segundos: float = 0.0,
                 detalhe: str | None = None, passo: int | None = None) -> Lancamento:
        """Algo que não chama o modelo: não tem custo de API, só tempo."""
        return self._anotar(etapa=etapa, tipo="operacao", nome=nome,
                            segundos=round(segundos, 3), custo="sem_custo", passo=passo,
                            detalhe=detalhe)

    def ouvinte(self, etapa: str, repassar: Callable[[Evento], None] | None = None
                ) -> Callable[[Evento], None]:
        """Um ``eventos`` para ``laco.conversar``: anota cada resposta e cada ferramenta, e
        repassa o evento (ao ``Terminal``, por exemplo)."""
        def ouvir(evento: Evento) -> None:
            if evento.tipo == "resposta" and evento.resposta is not None:
                self.chamada(etapa, evento.resposta, evento.segundos, evento.passo)
            elif evento.tipo == "chamada" and evento.chamada is not None:
                ok = (evento.saida or {}).get("ok")
                self.operacao(etapa, evento.chamada.nome, evento.segundos,
                              None if ok is not False else "a ferramenta recusou",
                              evento.passo)
            if repassar is not None:
                repassar(evento)
        return ouvir

    def resumo(self) -> dict:
        return resumir(self.lancamentos)

    def gravar(self, pasta: Path = SAIDA) -> Path:
        """Acrescenta os lançamentos em ``pasta/<projeto>.jsonl``. Devolve o arquivo."""
        pasta.mkdir(parents=True, exist_ok=True)
        arquivo = pasta / f"{self.projeto}.jsonl"
        with arquivo.open("a", encoding="utf-8") as f:
            for lancamento in self.lancamentos:
                f.write(json.dumps(asdict(lancamento), ensure_ascii=False) + "\n")
        return arquivo


# --- Leitura e consulta -----------------------------------------------------------------------

class ErroCustos(ValueError):
    """Um arquivo de custos que não está no formato de ``Lancamento``."""


_CAMPOS = {f.name for f in fields(Lancamento)}


def ler(arquivo: Path) -> list[Lancamento]:
    """Os lançamentos gravados num arquivo, conferidos campo a campo."""
    lancamentos = []
    for numero, linha in enumerate(arquivo.read_text(encoding="utf-8").splitlines(), 1):
        if not linha.strip():
            continue
        try:
            dados = json.loads(linha)
        except json.JSONDecodeError as e:
            raise ErroCustos(f"{arquivo}:{numero}: não é JSON ({e.msg})") from None
        if not isinstance(dados, dict) or set(dados) != _CAMPOS:
            raise ErroCustos(f"{arquivo}:{numero}: campos diferentes dos de um lançamento")
        lancamentos.append(Lancamento(**dados))
    return lancamentos


def _somar(lancamentos: list[Lancamento]) -> dict:
    llm = [l for l in lancamentos if l.tipo == "chamada_llm"]
    desconhecidos = sum(1 for l in llm if l.custo == "desconhecido")
    return {
        "chamadas_llm": len(llm),
        "operacoes": len(lancamentos) - len(llm),
        "modelos": sorted({l.modelo for l in llm if l.modelo}),
        "tokens_entrada": sum(l.tokens_entrada for l in llm),
        "tokens_saida": sum(l.tokens_saida for l in llm),
        "tokens_cache_leitura": sum(l.tokens_cache_leitura for l in llm),
        "tokens_cache_escrita": sum(l.tokens_cache_escrita for l in llm),
        "custo_calculado_usd": round(sum(l.custo_usd or 0.0 for l in llm), 6),
        "chamadas_sem_preco": desconhecidos,
        "custo_completo": desconhecidos == 0,
        "segundos": round(sum(l.segundos for l in lancamentos), 3),
    }


def resumir(lancamentos: Iterable[Lancamento]) -> dict:
    """Totais por etapa e do conjunto (um projeto, uma execução)."""
    lancamentos = list(lancamentos)
    etapas: dict[str, list[Lancamento]] = {}
    for l in lancamentos:
        etapas.setdefault(l.etapa, []).append(l)
    return {"execucoes": len({l.execucao for l in lancamentos}),
            "etapas": {nome: _somar(itens) for nome, itens in etapas.items()},
            "total": _somar(lancamentos)}


def dolares(valor: float, completo: bool) -> str:
    texto = f"US$ {valor:.4f} (calculado pela tabela de preços)"
    return texto if completo else texto + " + chamadas sem preço conhecido"


def texto_do_resumo(resumo: dict) -> str:
    linhas = [f"execuções: {resumo['execucoes']}"]
    for nome, s in list(resumo["etapas"].items()) + [("TOTAL", resumo["total"])]:
        linhas.append(f"{nome}: {s['chamadas_llm']} chamada(s) ao modelo, {s['operacoes']} "
                      f"operação(ões), tokens {s['tokens_entrada']} + {s['tokens_saida']}, "
                      f"{dolares(s['custo_calculado_usd'], s['custo_completo'])}, "
                      f"{s['segundos']:g} s")
    return "\n".join(linhas)


def main(argumentos: list[str], escrever: Callable[[str], None] = print) -> int:
    parser = argparse.ArgumentParser(prog="python -m src.custos",
                                     description="Consulta o registro de custos.")
    parser.add_argument("alvo", help="id do projeto (procura em --pasta) ou caminho de um "
                                     ".jsonl")
    parser.add_argument("--pasta", type=Path, default=SAIDA)
    parser.add_argument("--execucao", help="só uma execução")
    parser.add_argument("--detalhe", action="store_true", help="lista cada lançamento")
    parser.add_argument("--json", action="store_true", help="resumo em JSON")
    opcoes = parser.parse_args(argumentos)

    arquivo = Path(opcoes.alvo)
    if arquivo.suffix != ".jsonl":
        arquivo = opcoes.pasta / f"{opcoes.alvo}.jsonl"
    try:
        lancamentos = ler(arquivo)
    except (OSError, ErroCustos) as e:
        escrever(f"Não consegui ler os custos: {e}")
        return 2
    if opcoes.execucao:
        lancamentos = [l for l in lancamentos if l.execucao == opcoes.execucao]
    resumo = resumir(lancamentos)
    if opcoes.json:
        escrever(json.dumps(resumo, ensure_ascii=False, indent=2))
        return 0
    if opcoes.detalhe:
        for l in lancamentos:
            custo = (f"US$ {l.custo_usd:.6f}" if l.custo == "calculado" else l.custo)
            extra = (f"{l.modelo}, {l.tokens_entrada}+{l.tokens_saida} tokens, "
                     if l.tipo == "chamada_llm" else "")
            escrever(f"{l.momento} {l.execucao} {l.etapa:<16} {l.tipo:<11} {l.nome}: {extra}"
                     f"{custo}, acumulado US$ {l.custo_acumulado_usd:.6f}, {l.segundos:g} s"
                     + (f" ({l.detalhe})" if l.detalhe else ""))
    escrever(texto_do_resumo(resumo))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
