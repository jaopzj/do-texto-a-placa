"""O fluxo completo: do pedido em português aos arquivos da fábrica (Marco 5; ADR-019).

Junta as partes do Marco 5 (e o caminho da placa dos Marcos 2 a 4) num comando só, para o
usuário não precisar rodar nenhuma ferramenta interna à mão:

1. **Briefing** (Parte 1): o usuário descreve a placa; o agente faz até seis perguntas e
   monta a especificação, validada pelo código.
2. **Primeira aprovação** (Parte 2): o usuário vê o resumo e responde ``s`` ou uma correção.
   A especificação aprovada vai para ``saida/projetos/<projeto>/spec.yaml``.
3. **Pendências**: se faltou uma peça ou um dado na base, ou se a especificação pede uma placa
   que o pipeline não faz (camadas, contorno ou montagem diferentes da placa-modelo), o
   fluxo para aqui, com o relatório explicando. Nenhum circuito incompleto vira placa.
4. **Circuito e laço de correção** (Partes 3 e 4): o agente monta o circuito; o código
   confere netlist, alimentação, regras e o DRC da placa roteada, e devolve os problemas ao
   agente, até três correções. Sem aprovação, o fluxo para e explica.
5. **Relatório e segunda aprovação** (Parte 5): o ``relatorio.md`` é gravado, e o usuário vê
   o resultado das verificações antes dos arquivos da fábrica. Responde ``s``, ``n`` ou uma
   mudança no circuito, que volta ao agente e passa por todas as conferências de novo.
6. **Fábrica**: Gerbers, furação, posições e BOM da placa aprovada, conferidos por
   ``scripts/verificar_saidas.py``. O relatório é atualizado com os arquivos gerados.

Quem decide é sempre o código: o agente propõe, as conferências aprovam ou reprovam, e o
usuário só aprova o que já passou nelas.

Uso, dentro do container, com a chave em ``ANTHROPIC_API_KEY`` (``make projeto``):

    python -m src.projeto "quero um monitor de umidade do solo com ESP32 e um LCD"
"""
import argparse
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from .agente.ferramentas import Ferramentas
from .agente.laco import ErroProvedor, Provedor
from .agente.terminal import Terminal
from .aprovacao import pedir_segunda_aprovacao
from .briefing import REGISTRO, conduzir_briefing, no_terminal, salvar
from .componentes.carregar import carregar_todos
from .componentes.modelo import Componente
from .correcao import Laco, ResultadoDoLaco, explicar
from .custos import Custos
from .drc import ResultadoPlaca, conferir_placa
from .especificacao import Especificacao, ler_especificacao
from .fabrica import ErroFabrica, ResultadoFabrica, gerar_fabrica
from .relatorio import TITULOS, Andamento, caminho_legivel, gravar

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "saida" / "projetos"
# A placa-modelo, as posições e o gabarito do pipeline são os da placa de referência; as
# restrições físicas que ele consegue fazer são as da especificação dela.
REFERENCIA = RAIZ / "placas" / "monitor-umidade" / "spec.yaml"

ConferirPlaca = Callable[[dict, Path, dict[str, Componente]], ResultadoPlaca]
GerarFabrica = Callable[[ResultadoPlaca, Path], ResultadoFabrica]

AVISO_DE_PENDENCIAS = (
    "Atenção: há {n} pendência(s). Uma pendência quer dizer que falta uma peça ou um dado na "
    "base. Se você aprovar assim, o programa grava a especificação e o relatório e para: "
    "com pendências, nenhum circuito é montado e nenhuma placa é feita. Para seguir, "
    "escreva uma correção que dispense o que falta.")


@dataclass
class Fim:
    """Onde o fluxo terminou. ``situacao`` é uma das do relatório, ou ``sem_especificacao``,
    ``cancelado`` ou ``erro_da_api``, que acontecem antes de haver projeto."""
    situacao: str
    andamento: Andamento | None = None
    relatorio: Path | None = None

    @property
    def codigo(self) -> int:
        """0: arquivos da fábrica gerados (ou circuito aprovado sem placa); 130: cancelado."""
        if self.situacao in ("fabrica", "sem_placa"):
            return 0
        return 130 if self.situacao == "cancelado" else 1


def restricoes_incompativeis(spec: Especificacao, referencia: Especificacao) -> list[str]:
    """O que a especificação pede e o pipeline da placa não faz (ele só usa a placa-modelo)."""
    r, ref = spec.restricoes, referencia.restricoes
    problemas = []
    if r.camadas.valor != ref.camadas.valor:
        problemas.append(f"{r.camadas.valor} camada(s); a placa-modelo tem {ref.camadas.valor}")
    if (r.contorno.largura, r.contorno.altura) != (ref.contorno.largura, ref.contorno.altura):
        problemas.append(f"contorno de {r.contorno.largura:g} x {r.contorno.altura:g} mm; a "
                         f"placa-modelo tem {ref.contorno.largura:g} x "
                         f"{ref.contorno.altura:g} mm")
    if r.montagem.valor != ref.montagem.valor:
        problemas.append(f"montagem {r.montagem.valor}; o pipeline usa {ref.montagem.valor}")
    return problemas


def problemas_do_ambiente() -> list[str]:
    """O que falta no container para rotear e gerar a placa (``make configurar``, KiCad)."""
    problemas = []
    if shutil.which("kicad-cli") is None:
        problemas.append("o kicad-cli não está instalado: rode dentro do container (make "
                         "projeto)")
    tabelas = Path.home() / ".config" / "kicad" / "10.0"
    for nome in ("fp-lib-table", "sym-lib-table"):
        if not (tabelas / nome).is_file():
            problemas.append(f"falta {tabelas / nome}: rode make configurar uma vez")
    return problemas


class Fluxo:
    """Uma execução do fluxo completo. ``ler`` e ``escrever`` são o terminal (ou um roteiro,
    no eval e nos testes)."""

    def __init__(self, provedor: Provedor, ler: Callable[[str], str],
                 escrever: Callable[[str], None], base: dict[str, Componente] | None = None,
                 saida: Path = SAIDA, custos: Custos | None = None,
                 placa: ConferirPlaca | None = conferir_placa,
                 fabrica: GerarFabrica = gerar_fabrica, andamento_do_briefing: bool = False,
                 depois_do_agente: Callable[[Ferramentas], None] | None = None):
        self.provedor, self.ler, self.escrever = provedor, ler, escrever
        self.base = carregar_todos() if base is None else base
        self.saida = Path(saida)
        self.custos = custos or Custos()
        self.placa, self.fabrica = placa, fabrica
        self.andamento_do_briefing = andamento_do_briefing
        self.depois_do_agente = depois_do_agente
        self.terminal = Terminal(escrever)
        self.conferencias = 0

    # --- Etapas ---------------------------------------------------------------------------

    def rodar(self, pedido: str) -> Fim:
        etapas = 4 if self.placa else 3
        self._etapa(1, etapas, "briefing: o agente entende o pedido e faz perguntas")
        especificacao = self._briefing(pedido)
        if especificacao is None:
            return Fim("sem_especificacao")
        spec, arquivo, pendencias = especificacao
        pasta = arquivo.parent
        for antiga in ("placa", "fabrica"):              # nada de uma execução anterior
            shutil.rmtree(pasta / antiga, ignore_errors=True)
        andamento = Andamento(pedido, spec, arquivo, "pendencias", "", pendencias)

        incompativeis = restricoes_incompativeis(spec, ler_especificacao(REFERENCIA,
                                                                         self.base))
        andamento.pendencias += [{"origem": "pipeline", "necessidade": p,
                                  "motivo": "o pipeline só faz a placa-modelo "
                                            "(placas/monitor-umidade)"}
                                 for p in incompativeis]
        if andamento.pendencias:
            andamento.explicacao = self._explicar_pendencias(andamento.pendencias, "briefing")
            return self._terminar(andamento, pasta)

        self._etapa(2, etapas, "circuito: o agente monta, o código confere e pede correções")
        with (pasta / "registro-agente.txt").open("w", encoding="utf-8") as registro:
            def registrar(linha: str) -> None:
                registro.write(linha + "\n")
                registro.flush()

            laco = Laco(arquivo, spec, self.provedor, self.base,
                        placa=self._conferir_placa(pasta) if self.placa else None,
                        custos=self.custos, registrar=registrar,
                        eventos=self.terminal)
            resultado = laco.comecar(self.depois_do_agente)
            while True:
                fim = self._depois_do_laco(andamento, resultado, pasta, etapas)
                if not isinstance(fim, str):
                    return fim
                self.escrever("(aguardando o agente...)")
                resultado = laco.pedido_do_usuario(fim)

    def _briefing(self, pedido: str) -> tuple[Especificacao, Path, list[dict]] | None:
        def avisar(pendencias: list) -> None:
            if pendencias:
                self.escrever("\n" + AVISO_DE_PENDENCIAS.format(n=len(pendencias)))

        briefing = no_terminal(self.ler, self.escrever, self.base, antes_de_aprovar=avisar)
        self.saida.mkdir(parents=True, exist_ok=True)
        provisorio = self.saida / REGISTRO          # o projeto só se sabe na aprovação
        with provisorio.open("w", encoding="utf-8") as registro:
            def registrar(linha: str) -> None:
                registro.write(linha + "\n")
                registro.flush()

            resultado = conduzir_briefing(
                pedido, self.provedor, briefing, registrar=registrar,
                eventos=self.custos.ouvinte(
                    "briefing", self.terminal if self.andamento_do_briefing else None))
        spec = resultado.especificacao
        if spec is None:
            self.escrever("\nO briefing terminou sem uma especificação aprovada, então não há "
                          "placa para montar.")
            if resultado.execucao.texto_final:
                self.escrever(f"Última mensagem do agente: {resultado.execucao.texto_final}")
            self.escrever(f"A conversa está em {caminho_legivel(provisorio)}.")
            return None
        self.custos.projeto = spec.projeto.id
        arquivo = salvar(resultado, self.saida)
        shutil.move(provisorio, arquivo.parent / "registro-briefing.txt")
        self.escrever(f"\nEspecificação aprovada e gravada em {caminho_legivel(arquivo)}.")
        pendencias = [{"origem": "briefing", "necessidade": p.necessidade,
                       "motivo": p.motivo} for p in briefing.pendencias]
        return spec, arquivo, pendencias

    def _conferir_placa(self, pasta: Path):
        """A placa de cada conferência numa pasta própria (``placa/conferencia-<n>``)."""
        def conferir(estado: dict, numero: int) -> ResultadoPlaca:
            self.conferencias += 1
            self.escrever(f"(netlist, placa, roteamento e DRC da conferência "
                          f"{self.conferencias}: leva alguns segundos...)")
            return self.placa(estado, pasta / "placa" / f"conferencia-{self.conferencias}",
                              self.base)
        return conferir

    def _depois_do_laco(self, andamento: Andamento, resultado: ResultadoDoLaco, pasta: Path,
                        etapas: int) -> "Fim | str":
        """O que fazer com o resultado do laço: um ``Fim``, ou o texto de uma mudança pedida
        pelo usuário, que volta ao agente."""
        andamento.laco = resultado
        andamento.historico += resultado.rodadas
        self.escrever("\n=== VERIFICAÇÕES ===\n" + explicar(resultado))
        do_agente = [{"origem": "agente", **p} for p in resultado.estado.get("pendencias") or []]
        andamento.pendencias = [p for p in andamento.pendencias if p["origem"] != "agente"]
        andamento.pendencias += do_agente
        if not resultado.aprovado:
            andamento.situacao = "reprovado"
            andamento.explicacao = explicar(resultado)
            return self._terminar(andamento, pasta)
        if do_agente:
            andamento.situacao = "pendencias"
            andamento.explicacao = self._explicar_pendencias(do_agente, "agente")
            return self._terminar(andamento, pasta)
        if self.placa is None:
            andamento.situacao = "sem_placa"
            andamento.explicacao = (explicar(resultado) + " Sem placa, os arquivos da fábrica "
                                    "não são gerados.")
            return self._terminar(andamento, pasta)

        self._etapa(3, etapas, "relatório e segunda aprovação")
        andamento.situacao = "aguardando"
        andamento.explicacao = explicar(resultado)
        relatorio = self._gravar(andamento, pasta)
        veredito = pedir_segunda_aprovacao(self._resumo(resultado, relatorio), self.ler,
                                           self.escrever)
        if veredito.correcao is not None:
            return veredito.correcao
        if not veredito.aprovada:
            andamento.situacao = "recusado"
            andamento.explicacao = ("O circuito passou em todas as verificações, mas você "
                                    "respondeu n: os arquivos da fábrica não foram gerados.")
            return self._terminar(andamento, pasta)

        self._etapa(4, etapas, "arquivos da fábrica: Gerbers, furação, posições e BOM")
        try:
            andamento.fabrica = self.fabrica(resultado.rodadas[-1].placa, pasta / "fabrica")
        except ErroFabrica as e:
            andamento.situacao = "falha_da_fabrica"
            andamento.explicacao = (f"O circuito foi aprovado, mas a geração dos arquivos da "
                                    f"fábrica falhou em {e.etapa}: {e.mensagem}. O que saiu "
                                    f"ficou em {caminho_legivel(pasta / 'fabrica')}, mas não "
                                    "está pronto para a fábrica.")
            return self._terminar(andamento, pasta)
        andamento.situacao = "fabrica"
        andamento.explicacao = (explicar(resultado) + " Você aprovou na segunda aprovação, e "
                                f"os arquivos da fábrica foram gerados e conferidos: "
                                f"{andamento.fabrica.conferencia}")
        return self._terminar(andamento, pasta)

    # --- Mensagens ------------------------------------------------------------------------

    def _etapa(self, numero: int, total: int, texto: str) -> None:
        self.escrever(f"\n##### Etapa {numero} de {total}: {texto}")

    @staticmethod
    def _explicar_pendencias(pendencias: list[dict], quando: str) -> str:
        onde = {"briefing": "Na especificação", "agente": "Ao montar o circuito"}[quando]
        linhas = [f"{onde}, ficaram {len(pendencias)} pendência(s). Sem a peça ou o dado "
                  "que falta, o circuito ficaria incompleto ou não verificado, então o "
                  "programa parou: nenhuma placa foi feita e nenhum arquivo da fábrica foi "
                  "gerado."]
        linhas += [f"- {p['necessidade']}: {p['motivo']}" for p in pendencias]
        linhas.append("Para seguir, resolva a pendência (por exemplo, acrescente a peça ou o "
                      "dado na base de componentes, com a fonte) ou peça uma placa que use só "
                      "as peças da base, e rode de novo.")
        return "\n".join(linhas)

    def _resumo(self, resultado: ResultadoDoLaco, relatorio: Path) -> str:
        """O que o usuário vê na segunda aprovação."""
        ultima = resultado.rodadas[-1]
        c = ultima.regras.contagem()
        manuais = [r for r in ultima.regras.resultados if r.situacao == "manual"]
        linhas = ["=== SEGUNDA APROVAÇÃO: resultado das verificações ===",
                  f"Netlist e alimentação: ok. Correções pedidas ao agente: "
                  f"{resultado.correcoes}.",
                  f"Regras: {c['ok']} ok, {c['violada']} violada(s), {c['nao_verificavel']} "
                  f"não verificável(is), {c['manual']} para conferir à mão:"]
        linhas += [f"  - {r.ref} · {r.regra}: {r.motivo_manual}" for r in manuais]
        contam = [i for i in ultima.placa.drc if i.severidade != "ignore"]
        linhas.append(f"DRC da placa roteada: {len(contam)} item(ns) "
                      f"({caminho_legivel(ultima.placa.placa)}).")
        linhas.append(f"Relatório completo (decisões, fontes, regras, BOM): "
                      f"{caminho_legivel(relatorio)}")
        return "\n".join(linhas)

    def _gravar(self, andamento: Andamento, pasta: Path) -> Path:
        andamento.custos = self.custos.resumo()
        return gravar(andamento, self.base, pasta)

    def _terminar(self, andamento: Andamento, pasta: Path) -> Fim:
        relatorio = self._gravar(andamento, pasta)
        self.escrever(f"\n=== RESULTADO: {TITULOS[andamento.situacao]} ===")
        self.escrever(andamento.explicacao)
        self.escrever(f"\nRelatório do projeto: {caminho_legivel(relatorio)}")
        self.escrever("Arquivos produzidos nesta execução:")
        for arquivo in sorted(p for p in pasta.rglob("*") if p.is_file()):
            self.escrever(f"  - {caminho_legivel(arquivo)}")
        return Fim(andamento.situacao, andamento, relatorio)


# --- Terminal ---------------------------------------------------------------------------------

def main(argumentos: list[str], provedor: Provedor | None = None,
         ler: Callable[[str], str] = input,
         escrever: Callable[[str], None] = lambda linha: print(linha, flush=True)) -> int:
    """0: arquivos da fábrica gerados; 1: parou sem eles (o porquê está no relatório);
    130: cancelado."""
    from .agente.provedores.claude import ESFORCO, MODELO
    parser = argparse.ArgumentParser(
        prog="python -m src.projeto",
        description="Do pedido em português aos arquivos da fábrica, com duas aprovações.")
    parser.add_argument("pedido", nargs="?", default="",
                        help="o que você quer, entre aspas (se faltar, é perguntado)")
    parser.add_argument("--modelo", default=MODELO, help=f"padrão: {MODELO}")
    parser.add_argument("--esforco", default=ESFORCO,
                        choices=["low", "medium", "high", "xhigh", "max"],
                        help=f"padrão: {ESFORCO}")
    parser.add_argument("--saida", type=Path, default=SAIDA, help=f"padrão: {SAIDA}")
    parser.add_argument("--custos", type=Path, default=None,
                        help="pasta do registro de custos (padrão: saida/custos)")
    parser.add_argument("--sem-placa", action="store_true",
                        help="para depois das regras, sem rotear, sem DRC e sem arquivos da "
                             "fábrica (fora do container)")
    parser.add_argument("--andamento", action="store_true",
                        help="mostra também cada passo do agente no briefing")
    opcoes = parser.parse_args(argumentos)

    if not opcoes.sem_placa:
        problemas = problemas_do_ambiente()
        if problemas:
            escrever("O ambiente não consegue gerar a placa:\n- " + "\n- ".join(problemas))
            escrever("Nada foi feito, e nenhuma chamada ao modelo foi paga.")
            return 1
    custos = Custos()
    try:
        pedido = opcoes.pedido.strip() or ler("Descreva a placa que você quer: ").strip()
        if not pedido:
            escrever("Nenhum pedido: nada a fazer.")
            return 1
        if provedor is None:
            from .agente.provedores.claude import ProvedorClaude
            provedor = ProvedorClaude(opcoes.modelo, esforco=opcoes.esforco)
        Terminal(escrever).info(f"projeto · {opcoes.modelo} · esforço {opcoes.esforco}")
        fluxo = Fluxo(provedor, ler, escrever, saida=opcoes.saida, custos=custos,
                      placa=None if opcoes.sem_placa else conferir_placa,
                      andamento_do_briefing=opcoes.andamento)
        fim = fluxo.rodar(pedido)
    except (EOFError, KeyboardInterrupt):
        escrever("\nCancelado. Nenhum arquivo da fábrica foi gerado nesta execução.")
        return 130
    except ErroProvedor as e:
        escrever(f"\nA API do modelo falhou: {e}\nO projeto parou e nenhum arquivo da "
                 "fábrica foi gerado. Rode de novo.")
        return 1
    finally:
        if custos.lancamentos:
            pasta = opcoes.custos or opcoes.saida.parent / "custos"
            consulta = f"; veja com make custos PROJETO={custos.projeto}" if custos.projeto else ""
            escrever(f"Custos desta execução ({custos.execucao}) em "
                     f"{caminho_legivel(custos.gravar(pasta))}{consulta}")
    return fim.codigo


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
