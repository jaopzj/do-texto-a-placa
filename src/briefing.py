"""Briefing: do pedido em português à especificação da placa (Marco 5, Partes 1 e 2; ADR-016).

O briefing substitui o ``spec.yaml`` escrito à mão. O agente recebe o pedido em texto livre,
consulta a base de componentes, faz no máximo ``MAX_PERGUNTAS`` perguntas ao usuário e
entrega a especificação em YAML. O código decide o que vale:

- a especificação passa pelo mesmo caminho do ``spec.yaml`` escrito à mão
  (``especificacao_de_texto``: modelo Pydantic e referências à base). Se for inválida, os
  problemas voltam ao agente, que corrige e entrega de novo;
- toda decisão do agente cita como fonte um documento que existe: um arquivo do repositório
  (como ``componentes/<id>.yaml``) ou um documento citado pela própria base;
- toda pergunta respondida com "não sei" obriga as decisões sobre o assunto dela a ficarem
  com ``decidido_por: agente`` (e, portanto, com motivo e fonte);
- o limite de perguntas é conferido pelo código, não pelo prompt.

Com a especificação válida vem a primeira aprovação (``src/aprovacao.py``): o usuário vê o
resumo e responde ``s`` ou escreve uma correção, que volta ao agente como resultado da
entrega. A especificação aprovada é gravada em disco e é a entrada do agente do Marco 4
(``python -m src.agente <spec.yaml>``).

O briefing não executa código do modelo nem escreve nada que o modelo mandou sem validar: a
especificação gravada é a do modelo Pydantic, reescrita pelo código.

Uso (precisa da biblioteca anthropic e da chave em ANTHROPIC_API_KEY):
    python -m src.briefing "quero um monitor de umidade do solo com ESP32 e um LCD"
"""
import argparse
import json
import re
import sys
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Annotated

import yaml
from pydantic import Field, StringConstraints, ValidationError

from .agente.contratos import CONTRATOS as CONTRATOS_DO_AGENTE
from .agente.ferramentas import Ferramentas, normalizar
from .agente.laco import Evento, Execucao, Provedor, conversar
from .aprovacao import Veredito, pedir_aprovacao
from .componentes.carregar import carregar_todos
from .componentes.modelo import Componente, Texto, _Estrito
from .especificacao import (Decisao, ErroEspecificacao, Especificacao,
                            especificacao_de_texto)

RAIZ = Path(__file__).resolve().parents[1]
SAIDA = RAIZ / "saida" / "briefing"
REGISTRO = "registro.txt"            # o registro completo do último briefing, em --saida
AGUARDE = "(aguardando o agente...)"

# Mude a versão sempre que mudar SISTEMA, PEDIDO, PADROES, o lembrete (ao_parar) ou o texto
# de um contrato. Versão 2: lembrete quando o agente para sem usar ferramenta.
VERSAO_DO_PROMPT = "2"

MAX_PERGUNTAS = 6        # guia, Parte 1: perguntas demais viram formulário
MAX_PASSOS = 40          # respostas do modelo no briefing inteiro, com as correções
MAX_LEMBRETES = 3        # lembretes seguidos quando o agente para sem usar ferramenta

# Ferramentas do agente do Marco 4 que o briefing reaproveita, sem mudar nada nelas: o
# briefing consulta a base e registra o que falta, mas não seleciona nem liga peças.
DA_BASE = ("buscar_componente", "ler_dados_componente", "registrar_pendencia")
FERRAMENTAS = DA_BASE + ("perguntar_usuario", "entregar_especificacao")

# Assuntos de uma pergunta: as decisões fixas da especificação, "projeto" (que não é
# decisão) ou "modulo:<papel>", com o mesmo papel que o módulo terá na especificação.
FIXOS = ("alimentacao", "restricoes.camadas", "restricoes.contorno", "restricoes.montagem")
ASSUNTO = r"^(projeto|alimentacao|restricoes\.(camadas|contorno|montagem)|modulo:\S.*)$"
Assunto = Annotated[str, StringConstraints(pattern=ASSUNTO)]

# Respostas que contam como "não sei", comparadas sem maiúsculas, acentos e pontuação, no
# começo da resposta ("não sei, talvez USB" conta). Resposta vazia também conta.
NAO_SEI = ("nao sei", "sei la", "nao faco ideia", "nao tenho ideia", "nao tenho certeza",
           "tanto faz", "voce decide", "voce escolhe", "decide voce", "pode escolher",
           "qualquer um", "qualquer uma")

# Padrões do projeto para quando o usuário não sabe. São convenções do pipeline, cada uma
# com o documento que a sustenta; o agente cita esse documento como fonte.
PADROES = {
    "restricoes.montagem": ("barra_pinos_macho", "os módulos entram na placa com barra de "
                            "pinos macho", "docs/adr/0008-barras-de-pinos-macho.md"),
    "restricoes.camadas": ("2", "a placa-modelo do pipeline tem duas camadas de cobre",
                           "placas/monitor-umidade/modelo/modelo.kicad_pcb"),
    "restricoes.contorno": ("100 x 100 mm", "o contorno da placa-modelo do pipeline",
                            "placas/monitor-umidade/modelo/modelo.kicad_pcb"),
}


# --- Prompt -----------------------------------------------------------------------------------

def _formato() -> str:
    """O formato da especificação, tirado do próprio modelo Pydantic (nunca fica desatualizado)."""
    return json.dumps(Especificacao.model_json_schema(), ensure_ascii=False,
                      separators=(",", ":"))


def _padroes() -> str:
    return "\n".join(f"- {caminho}: {valor} ({motivo}; fonte: {doc})"
                     for caminho, (valor, motivo, doc) in PADROES.items())


SISTEMA = f"""Você é um engenheiro eletrônico conduzindo o briefing de uma PCB: entender o
pedido do usuário antes de projetar. O resultado é a especificação da placa, em YAML.

Como trabalhar:
1. Leia o pedido. Consulte a base de componentes com buscar_componente e
   ler_dados_componente para saber quais peças existem, como são alimentadas e quais regras
   de uso elas têm. A base é a única fonte de dados técnicos: NUNCA use a sua memória para
   pinos, tensões ou peças.
2. Pergunte ao usuário só o que falta e muda o projeto, com perguntar_usuario: uma pergunta
   por chamada, curta, em português, no máximo {MAX_PERGUNTAS} no briefing inteiro. Nunca
   pergunte em texto solto: só a ferramenta chega ao usuário. Perguntas típicas: como o
   microcontrolador é montado (placa de desenvolvimento encaixada em barra de pinos, ou
   módulo soldado), como a placa é alimentada, que display, que sensor, restrições de
   tamanho. Não pergunte o que o pedido já respondeu.
   Em "sobre", diga de que parte da especificação a pergunta trata: projeto, alimentacao,
   restricoes.camadas, restricoes.contorno, restricoes.montagem ou modulo:<papel>, com o
   mesmo papel que o módulo terá na especificação (ex.: modulo:display).
3. Traga o que o usuário não pensou em perguntar: aplique as regras de cada peça da base
   (níveis lógicos incompatíveis pedem um conversor de nível; o ADC2 do ESP32 não funciona
   com Wi-Fi). Cite as regras usadas no campo regras da decisão.
4. Entregue a especificação com entregar_especificacao, em YAML. Se voltarem problemas,
   corrija todos e entregue de novo. Se o usuário mandar uma correção, ajuste a
   especificação e entregue de novo.

Regras da especificação:
- componente: só ids que existem na base, exatamente como buscar_componente devolve. Se o
  projeto precisa de uma peça que a base não tem, registre com registrar_pendencia e deixe
  a peça fora da especificação. Nunca invente um id.
- decidido_por: usuario quando o pedido ou uma resposta do usuário disse aquilo; agente
  quando foi escolha sua. Decisão do agente sempre tem motivo e fonte.
- fonte.documento é um documento que existe: o arquivo da peça na base
  (componentes/<id>.yaml), um documento que a base cita nas fontes dos pinos (com a
  página) ou um dos documentos dos padrões abaixo. Nada de memória.
- Resposta "não sei" (ou nenhuma resposta): escolha um padrão sensato, marque decidido_por:
  agente e explique no motivo. Padrões do projeto:
{_padroes()}
- A especificação não guarda dados elétricos (pinos, tensões dos módulos): eles ficam na
  base. Tensões em volts e medidas em milímetros, como números.
- projeto.id em minúsculas, com hífens (ex.: monitor-umidade).

Formato da especificação (JSON Schema; entregue em YAML com estes campos e nenhum outro):
{_formato()}

Responda em português."""

PEDIDO = """Pedido do usuário:

{texto}

Conduza o briefing e entregue a especificação."""

_TEXTO = {"type": "string", "minLength": 1}

CONTRATOS: list[dict] = [c for c in CONTRATOS_DO_AGENTE if c["name"] in DA_BASE] + [
    {
        "name": "perguntar_usuario",
        "description": (
            "Faz uma pergunta ao usuário e devolve a resposta dele. Uma pergunta por chamada, "
            f"no máximo {MAX_PERGUNTAS} no briefing; depois do limite, a ferramenta recusa e "
            "você decide com padrões sensatos. Se a resposta for 'não sei', as decisões sobre "
            "o assunto da pergunta ficam com decidido_por: agente."),
        "parameters": {
            "type": "object",
            "properties": {
                "pergunta": {**_TEXTO, "description": "a pergunta, curta, em português"},
                "sobre": {"type": "array", "minItems": 1,
                          "items": {"type": "string", "pattern": ASSUNTO},
                          "description": "partes da especificação de que a pergunta trata, "
                                         "ex.: ['restricoes.montagem', 'modulo:microcontrolador']"},
            },
            "required": ["pergunta", "sobre"],
        },
    },
    {
        "name": "entregar_especificacao",
        "description": (
            "Entrega a especificação da placa, em YAML. O código valida o formato, confere os "
            "ids e as regras na base, as fontes das decisões do agente e as respostas 'não "
            "sei'. Se houver problema, volta a lista inteira para você corrigir. Se estiver "
            "válida, o usuário vê o resumo e aprova ou manda uma correção."),
        "parameters": {
            "type": "object",
            "properties": {"especificacao": {**_TEXTO, "description": "a especificação em YAML"}},
            "required": ["especificacao"],
        },
    },
]


def montar_pedido(texto: str) -> str:
    return PEDIDO.format(texto=texto.strip())


# --- Estado do briefing -----------------------------------------------------------------------

class _PerguntaEntrada(_Estrito):
    pergunta: Texto
    sobre: Annotated[list[Assunto], Field(min_length=1)]


class _EntregaEntrada(_Estrito):
    especificacao: Texto


@dataclass(frozen=True)
class Pergunta:
    pergunta: str
    sobre: tuple[str, ...]
    resposta: str
    nao_sabe: bool


def nao_sabe(resposta: str) -> bool:
    """A resposta é um "não sei"? (vazia também é)."""
    texto = " ".join(re.findall(r"[0-9a-z]+", normalizar(resposta)))
    return not texto or any(texto == f or texto.startswith(f + " ") for f in NAO_SEI)


def documentos_da_base(base: dict[str, Componente]) -> set[str]:
    """Os documentos que a base cita como fonte de algum dado."""
    return {p.fonte.documento for c in base.values() for p in c.pinos}


def _arquivo_do_repositorio(documento: str, raiz: Path) -> bool:
    caminho = Path(documento)
    if caminho.is_absolute():
        return False
    alvo = (raiz / caminho).resolve()
    return alvo.is_relative_to(raiz.resolve()) and alvo.is_file()


def fontes_invalidas(spec: Especificacao, base: dict[str, Componente], raiz: Path) -> list[str]:
    """Decisões do agente cuja fonte não é um documento que existe (lista vazia se ok)."""
    citados = documentos_da_base(base)
    problemas = []
    for caminho, d in spec.decisoes():
        if d.decidido_por != "agente":
            continue
        doc = d.fonte.documento
        if doc not in citados and not _arquivo_do_repositorio(doc, raiz):
            problemas.append(
                f"{caminho}.fonte.documento: {doc!r} não é um arquivo do repositório nem um "
                "documento citado pela base (use, por exemplo, componentes/<id>.yaml)")
    return problemas


def _decisoes_do_assunto(spec: Especificacao, assunto: str) -> list[tuple[str, Decisao]] | None:
    """As decisões sobre ``assunto``; ``None`` se o módulo do assunto não está na especificação."""
    if assunto == "projeto":
        return []
    if assunto in FIXOS:
        return [(assunto, dict(spec.decisoes())[assunto])]
    papel = normalizar(assunto.removeprefix("modulo:")).strip()
    for i, m in enumerate(spec.modulos):
        if normalizar(m.papel).strip() == papel:
            return [(f"modulos.{i}", m)]
    return None


def nao_sei_desrespeitado(spec: Especificacao, perguntas: list[Pergunta]) -> list[str]:
    """Perguntas respondidas com "não sei" cuja decisão não ficou com o agente."""
    problemas = []
    for n, p in enumerate(perguntas, start=1):
        if not p.nao_sabe:
            continue
        for assunto in p.sobre:
            decisoes = _decisoes_do_assunto(spec, assunto)
            if decisoes is None:
                problemas.append(
                    f"a pergunta {n} ({p.pergunta!r}) era sobre {assunto!r}, e nenhum módulo "
                    "tem esse papel; use o mesmo papel da pergunta")
                continue
            problemas += [
                f"{caminho}: o usuário respondeu 'não sei' à pergunta {n} ({p.pergunta!r}), "
                "então a decisão é do agente (decidido_por: agente, com motivo e fonte)"
                for caminho, d in decisoes if d.decidido_por != "agente"]
    return problemas


def sem_cerca(texto: str) -> str:
    """Tira a cerca de Markdown (```yaml ... ```) que o modelo às vezes põe em volta do YAML."""
    m = re.fullmatch(r"\s*```[A-Za-z]*\n(.*?)\n?```\s*", texto, flags=re.DOTALL)
    return m.group(1) if m else texto


def validar(texto: str, base: dict[str, Componente], perguntas: list[Pergunta],
            raiz: Path = RAIZ) -> tuple[Especificacao | None, list[str]]:
    """Valida a especificação entregue pelo agente: ``(spec, [])`` ou ``(None, problemas)``."""
    try:
        spec = especificacao_de_texto(sem_cerca(texto), Path("especificacao"), base)
    except ErroEspecificacao as e:
        return None, [p.mensagem for p in e.problemas]
    problemas = fontes_invalidas(spec, base, raiz) + nao_sei_desrespeitado(spec, perguntas)
    return (None, problemas) if problemas else (spec, [])


def _ok(**dados) -> dict:
    return {"ok": True, **dados}


def _erro(codigo: str, mensagem: str, proximo_passo: str, **extra) -> dict:
    return {"ok": False, "erro": codigo, "mensagem": mensagem,
            "proximo_passo": proximo_passo, **extra}


class Briefing:
    """As ferramentas do briefing e o que ele junta: perguntas, entregas e correções.

    ``perguntar(pergunta, numero, maximo)`` devolve a resposta do usuário.
    ``aprovar(spec, pendencias)`` mostra o resumo e devolve o ``Veredito`` do usuário.
    Os dois são do terminal no ``main`` e falsos nos testes.
    """

    def __init__(self, perguntar: Callable[[str, int, int], str],
                 aprovar: Callable[[Especificacao, list], Veredito],
                 base: dict[str, Componente] | None = None, raiz: Path = RAIZ):
        self.base = carregar_todos() if base is None else dict(base)
        self.ferramentas = Ferramentas(self.base)
        self.perguntar = perguntar
        self.aprovar = aprovar
        self.raiz = raiz
        self.perguntas: list[Pergunta] = []
        self.entregas_invalidas: list[list[str]] = []
        self.correcoes: list[str] = []
        self.lembretes = 0                                 # total, para o briefing.yaml
        self._lembretes_seguidos = 0
        self.especificacao: Especificacao | None = None    # só depois de aprovada

    @property
    def aprovada(self) -> bool:
        return self.especificacao is not None

    @property
    def pendencias(self) -> list:
        return list(self.ferramentas.pendencias)

    def ao_parar(self, resposta) -> str | None:
        """O agente parou sem pedir ferramenta: devolve o lembrete, ou ``None`` para encerrar.

        Texto solto não chega ao usuário (só ``perguntar_usuario`` e a aprovação chegam), e
        uma resposta cortada no limite de tokens também para assim. Sem o lembrete, o
        briefing acabaria ali, sem especificação, no meio da conversa. Depois de
        ``MAX_LEMBRETES`` lembretes seguidos sem nenhuma ferramenta, o briefing encerra.
        """
        if self.aprovada or self._lembretes_seguidos >= MAX_LEMBRETES:
            return None
        self._lembretes_seguidos += 1
        self.lembretes += 1
        restantes = MAX_PERGUNTAS - len(self.perguntas)
        perguntar = (f"se precisa perguntar algo, chame perguntar_usuario (restam {restantes} "
                     "pergunta(s))" if restantes else
                     "o limite de perguntas acabou: decida o que falta com padrões sensatos "
                     "(decidido_por: agente)")
        return ("[mensagem do sistema, não do usuário] A sua última mensagem não chegou ao "
                "usuário: ele só vê as perguntas feitas com perguntar_usuario e o resumo de "
                f"entregar_especificacao. Continue o briefing: {perguntar}; se já tem o que "
                "precisa, entregue a especificação inteira com entregar_especificacao.")

    def executar_ferramenta(self, nome, entrada) -> dict:
        """Executa o pedido do modelo e devolve o resultado, mesmo se for inválido."""
        self._lembretes_seguidos = 0
        if nome in DA_BASE:
            return self.ferramentas.executar_ferramenta(nome, entrada)
        if nome not in FERRAMENTAS:
            return _erro("ferramenta_inexistente", f"não existe a ferramenta {nome!r}",
                         "use uma das ferramentas disponíveis", ferramentas=list(FERRAMENTAS))
        modelo = _PerguntaEntrada if nome == "perguntar_usuario" else _EntregaEntrada
        try:
            validado = modelo.model_validate(entrada)
        except ValidationError as e:
            problemas = [f"{'.'.join(map(str, err['loc'])) or '(entrada)'}: {err['msg']}"
                         for err in e.errors()]
            return _erro("entrada_invalida", "argumento inválido: " + "; ".join(problemas),
                         f"corrija os argumentos de {nome} e chame de novo", problemas=problemas)
        if nome == "perguntar_usuario":
            return self._perguntar(validado)
        return self._entregar(validado)

    def _perguntar(self, e: _PerguntaEntrada) -> dict:
        if len(self.perguntas) >= MAX_PERGUNTAS:
            return _erro("limite_de_perguntas",
                         f"o limite de {MAX_PERGUNTAS} perguntas foi atingido",
                         "decida o que falta com padrões sensatos (decidido_por: agente, com "
                         "motivo e fonte) e entregue a especificação")
        numero = len(self.perguntas) + 1
        resposta = self.perguntar(e.pergunta.strip(), numero, MAX_PERGUNTAS).strip()
        pergunta = Pergunta(e.pergunta.strip(), tuple(e.sobre), resposta, nao_sabe(resposta))
        self.perguntas.append(pergunta)
        resultado = _ok(resposta=resposta or "(sem resposta)", nao_sabe=pergunta.nao_sabe,
                        perguntas_restantes=MAX_PERGUNTAS - numero)
        if pergunta.nao_sabe:
            resultado["instrucao"] = ("o usuário não sabe: escolha um padrão sensato e marque "
                                      f"as decisões sobre {list(e.sobre)} com decidido_por: "
                                      "agente, com motivo e fonte")
        return resultado

    def _entregar(self, e: _EntregaEntrada) -> dict:
        if self.aprovada:
            return _erro("ja_aprovada", "a especificação já foi aprovada pelo usuário",
                         "encerre o briefing")
        spec, problemas = validar(e.especificacao, self.base, self.perguntas, self.raiz)
        if spec is None:
            self.entregas_invalidas.append(problemas)
            return _erro("especificacao_invalida",
                         f"a especificação tem {len(problemas)} problema(s)",
                         "corrija todos os problemas e entregue a especificação inteira de novo",
                         problemas=problemas)
        veredito = self.aprovar(spec, self.pendencias)
        if veredito.aprovada:
            self.especificacao = spec
            return _ok(aprovada=True)
        self.correcoes.append(veredito.correcao)
        return _erro("correcao_do_usuario",
                     f"o usuário pediu uma correção: {veredito.correcao}",
                     "ajuste a especificação conforme a correção (o que o usuário pediu vira "
                     "decidido_por: usuario) e entregue de novo", correcao=veredito.correcao)


# --- Execução ---------------------------------------------------------------------------------

@dataclass
class Resultado:
    """O que o briefing produziu: a especificação aprovada (ou ``None``) e a conversa."""
    pedido: str
    briefing: Briefing
    execucao: Execucao
    data: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))

    @property
    def especificacao(self) -> Especificacao | None:
        return self.briefing.especificacao


def conduzir_briefing(texto: str, provedor: Provedor, briefing: Briefing,
                      max_passos: int = MAX_PASSOS,
                      registrar: Callable[[str], None] | None = None,
                      eventos: Callable[[Evento], None] | None = None) -> Resultado:
    """Roda o agente do briefing até a especificação ser aprovada, ele parar ou acabar os passos."""
    execucao = conversar(montar_pedido(texto), provedor, SISTEMA, CONTRATOS,
                         briefing.executar_ferramenta, max_passos=max_passos,
                         registrar=registrar, eventos=eventos,
                         encerrar=lambda: briefing.aprovada, ao_parar=briefing.ao_parar)
    return Resultado(texto.strip(), briefing, execucao)


def para_yaml(spec: Especificacao) -> str:
    """A especificação em YAML, reescrita pelo código a partir do modelo validado."""
    dados = spec.model_dump(mode="python", exclude_defaults=True)
    return yaml.safe_dump(dados, allow_unicode=True, sort_keys=False, width=100)


def salvar(resultado: Resultado, pasta: Path) -> Path:
    """Grava ``spec.yaml`` e ``briefing.yaml`` (a conversa) em ``pasta/<projeto.id>/``.

    Só grava especificação aprovada. Devolve o caminho do ``spec.yaml``.
    """
    spec = resultado.especificacao
    if spec is None:
        raise ValueError("só uma especificação aprovada é gravada")
    destino = Path(pasta) / spec.projeto.id
    destino.mkdir(parents=True, exist_ok=True)
    pedido = " ".join(resultado.pedido.split())
    cabecalho = (f"# Especificação gerada pelo briefing (Marco 5) em {resultado.data} e aprovada\n"
                 f"# pelo usuário. Pedido: {pedido}\n"
                 "# A conversa (perguntas, respostas e correções) está em briefing.yaml.\n\n")
    arquivo = destino / "spec.yaml"
    arquivo.write_text(cabecalho + para_yaml(spec), encoding="utf-8")

    b, ex = resultado.briefing, resultado.execucao
    conversa = {
        "data": resultado.data,
        "versao_do_prompt": VERSAO_DO_PROMPT,
        "pedido": resultado.pedido,
        "perguntas": [asdict(p) | {"sobre": list(p.sobre)} for p in b.perguntas],
        "entregas_invalidas": b.entregas_invalidas,
        "correcoes": b.correcoes,
        "lembretes": b.lembretes,
        "pendencias": [asdict(p) for p in b.pendencias],
        "passos": ex.passos,
        "tokens_entrada": ex.tokens_entrada,
        "tokens_saida": ex.tokens_saida,
        "custo_usd": ex.custo_usd,
    }
    (destino / "briefing.yaml").write_text(
        yaml.safe_dump(conversa, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8")
    return arquivo


# --- Terminal ---------------------------------------------------------------------------------

def main(argumentos: list[str], provedor: Provedor | None = None,
         ler: Callable[[str], str] = input,
         escrever: Callable[[str], None] = lambda linha: print(linha, flush=True)) -> int:
    """Briefing interativo no terminal. 0: aprovada e gravada; 1: sem aprovação; 130: cancelado."""
    from .agente.provedores.claude import ESFORCO, MODELO
    from .agente.terminal import Terminal, dolares
    parser = argparse.ArgumentParser(
        prog="python -m src.briefing",
        description="Transforma um pedido em português na especificação da placa.")
    parser.add_argument("pedido", nargs="?", default="",
                        help="o que você quer, entre aspas (se faltar, é perguntado)")
    parser.add_argument("--modelo", default=MODELO, help=f"padrão: {MODELO}")
    parser.add_argument("--esforco", default=ESFORCO,
                        choices=["low", "medium", "high", "xhigh", "max"],
                        help=f"padrão: {ESFORCO}")
    parser.add_argument("--saida", type=Path, default=SAIDA, help=f"padrão: {SAIDA}")
    parser.add_argument("--andamento", action="store_true",
                        help="mostra cada passo do agente (tokens, custo, ferramentas)")
    opcoes = parser.parse_args(argumentos)

    try:
        texto = opcoes.pedido.strip() or ler("Descreva a placa que você quer: ").strip()
        if not texto:
            escrever("Nenhum pedido: nada a fazer.")
            return 1
        if provedor is None:
            from .agente.provedores.claude import ProvedorClaude
            provedor = ProvedorClaude(opcoes.modelo, esforco=opcoes.esforco)

        # Entre uma resposta do usuário e a próxima pergunta, o modelo pode levar vários
        # segundos (raciocínio e consultas à base). O aviso diz que nada travou.
        def perguntar(pergunta: str, numero: int, maximo: int) -> str:
            escrever(f"\nPergunta {numero} de {maximo}: {pergunta}")
            resposta = ler("> ")
            escrever(AGUARDE)
            return resposta

        def aprovar(spec: Especificacao, pendencias: list) -> Veredito:
            veredito = pedir_aprovacao(spec, briefing.base, pendencias, ler=ler,
                                       escrever=escrever)
            if not veredito.aprovada:
                escrever(AGUARDE)
            return veredito

        briefing = Briefing(perguntar, aprovar)
        terminal = Terminal(escrever)
        terminal.info(f"briefing · {opcoes.modelo} · esforço {opcoes.esforco}")
        escrever(AGUARDE)
        # O registro completo (PENSA, AGE, OBSERVA, LEMBRETE) vai para arquivo, para dar
        # para ver depois o que o agente fez, inclusive num briefing que não terminou.
        opcoes.saida.mkdir(parents=True, exist_ok=True)
        with (opcoes.saida / REGISTRO).open("w", encoding="utf-8") as arquivo_registro:
            def registrar(linha: str) -> None:
                arquivo_registro.write(linha + "\n")
                arquivo_registro.flush()

            resultado = conduzir_briefing(texto, provedor, briefing, registrar=registrar,
                                          eventos=terminal if opcoes.andamento else None)
    except (EOFError, KeyboardInterrupt):
        escrever("\nBriefing cancelado. Nenhuma especificação foi gravada.")
        return 130

    ex = resultado.execucao
    resumo = (f"perguntas: {len(briefing.perguntas)}, entregas inválidas: "
              f"{len(briefing.entregas_invalidas)}, correções: {len(briefing.correcoes)}, "
              f"passos: {ex.passos}, custo do briefing: {dolares(ex.custo_usd)}")
    if resultado.especificacao is None:
        escrever("\nO briefing terminou sem uma especificação aprovada.")
        if ex.texto_final:
            escrever(f"Última mensagem do agente: {ex.texto_final}")
        escrever(f"O registro completo está em {opcoes.saida / REGISTRO}.")
        escrever(resumo)
        return 1
    arquivo = salvar(resultado, opcoes.saida)
    try:
        mostrar = arquivo.relative_to(Path.cwd())
    except ValueError:
        mostrar = arquivo
    escrever(f"\nEspecificação aprovada e gravada em {mostrar}")
    escrever(f"Próximo passo: python -m src.agente {mostrar}")
    escrever(resumo)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
