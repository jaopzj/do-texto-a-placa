"""As seis ferramentas do agente (Marco 4, Parte 3 do guia do MVP; ADR-010).

O agente nunca escreve a netlist nem dados de componente. Ele chama estas ferramentas, e o
código confere cada pedido contra a base de componentes (``carregar_todos()``) antes de
mudar o estado do projeto. É a regra de ouro do projeto: o LLM propõe, o código decide.

    buscar_componente(termo)                  procura na base
    ler_dados_componente(id)                  devolve o componente inteiro, como na base
    selecionar_componente(id, ref)            põe uma peça da base no projeto
    conectar(ref, pino, rede)                 liga um pino de uma peça selecionada a uma rede
    registrar_decisao(decisao, motivo, fonte) guarda uma decisão com fonte verificável
    registrar_pendencia(necessidade, motivo)  guarda o que falta para um humano resolver

Contrato de todas as ferramentas:

- devolvem sempre um dicionário, pronto para virar JSON e voltar ao modelo;
- no sucesso, ``{"ok": True, ...}``;
- na recusa, ``{"ok": False, "erro": <código>, "mensagem": <o que houve>,
  "proximo_passo": <o que o agente pode fazer>}``, às vezes com mais dados (as peças
  selecionadas, os pinos da peça...). Recusa nunca levanta exceção;
- uma chamada recusada não muda o estado do projeto. A única exceção é o registro das
  tentativas de selecionar um id que não existe na base (``tentativas_inexistentes``), que
  não é estado do projeto: é a medida que o eval da Parte 6 usa.

``executar_ferramenta(nome, entrada)`` recebe o pedido como o modelo o envia (nome e
dicionário de argumentos) e devolve o mesmo tipo de resultado, inclusive para ferramenta
desconhecida ou argumento errado.

Este módulo não chama nenhum modelo de IA. Os contratos que o modelo enxerga estão em
``contratos.py``, o laço em ``laco.py`` e o adaptador do provedor em ``provedores/``.
"""
import re
import unicodedata
from dataclasses import asdict, dataclass
from typing import Annotated, Callable

from pydantic import Field, StringConstraints, ValidationError

from ..componentes.carregar import carregar_todos
from ..componentes.modelo import Componente, Pino, Texto, _Estrito
from ..especificacao import Especificacao

FERRAMENTAS = ("buscar_componente", "ler_dados_componente", "selecionar_componente",
               "conectar", "registrar_decisao", "registrar_pendencia")

# Referência de uma peça no projeto: letra seguida de letras, dígitos ou "_" (ex.: U1, LCD1).
Referencia = Annotated[str, StringConstraints(pattern=r"^[A-Za-z][A-Za-z0-9_]*$")]

# Nome de rede: sem espaços (ex.: GND, +5V, +3V3, SDA_3V3).
NomeRede = Annotated[str, StringConstraints(pattern=r"^[A-Za-z0-9_+\-./]+$")]

FORMATOS_DE_FONTE = (
    "componente:<id>",
    "componente:<id>/regra:<id da regra>",
    "componente:<id>/pino:<nome ou número do pino>",
    "especificacao:<caminho da decisão na especificação, ex.: modulos.3>",
)


# --- Entradas de cada ferramenta (validadas como a base: ADR-006) ------------------------

class _BuscarEntrada(_Estrito):
    termo: Texto


class _LerEntrada(_Estrito):
    id: Texto


class _SelecionarEntrada(_Estrito):
    id: Texto
    ref: Referencia


class _ConectarEntrada(_Estrito):
    ref: Texto
    pino: Annotated[int, Field(ge=1)] | Texto     # número ou nome do pino, como na base
    rede: NomeRede


class _DecisaoEntrada(_Estrito):
    decisao: Texto
    motivo: Texto
    fonte: Texto | Annotated[list[Texto], Field(min_length=1)]


class _PendenciaEntrada(_Estrito):
    necessidade: Texto
    motivo: Texto


# --- O que fica guardado no projeto -------------------------------------------------------

@dataclass(frozen=True)
class Ligacao:
    ref: str
    pino: int          # número do pino na peça
    nome: str          # nome do pino na base
    rede: str


@dataclass(frozen=True)
class Decisao:
    decisao: str
    motivo: str
    fontes: tuple[str, ...]


@dataclass(frozen=True)
class Pendencia:
    necessidade: str
    motivo: str


# --- Normalização da busca ----------------------------------------------------------------

# Tudo que não é letra ou dígito separa palavras: espaço, "_", "-", parênteses, vírgula...
_SEPARADORES = re.compile(r"[^0-9a-z]+")


def normalizar(texto: str) -> str:
    """Minúsculas e sem acentos: ``"Módulo LCD"`` vira ``"modulo lcd"``."""
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto)
                         if not unicodedata.combining(c))
    return sem_acento.casefold()


def _compacto(texto: str) -> str:
    """Normalizado e sem separadores: ``"SENSOR_UMIDADE"`` -> ``"sensorumidade"``."""
    return "".join(_palavras(texto))


def _palavras(texto: str) -> list[str]:
    return [p for p in _SEPARADORES.split(normalizar(texto)) if p]


def _ok(**dados) -> dict:
    return {"ok": True, **dados}


def _erro(codigo: str, mensagem: str, proximo_passo: str, **extra) -> dict:
    return {"ok": False, "erro": codigo, "mensagem": mensagem,
            "proximo_passo": proximo_passo, **extra}


class Ferramentas:
    """As ferramentas do agente e o estado do projeto que elas montam.

    ``base`` é a base de componentes (por padrão, ``carregar_todos()``). ``especificacao``
    é opcional: com ela, uma decisão pode citar uma decisão da especificação como fonte.
    """

    def __init__(self, base: dict[str, Componente] | None = None,
                 especificacao: Especificacao | None = None):
        self.base = carregar_todos() if base is None else dict(base)
        self.especificacao = especificacao
        self.selecoes: dict[str, str] = {}               # ref -> id do componente
        self.ligacoes: dict[tuple[str, int], Ligacao] = {}  # (ref, número do pino) -> ligação
        self.decisoes: list[Decisao] = []
        self.pendencias: list[Pendencia] = []
        self.tentativas_inexistentes: list[str] = []     # ids pedidos que a base não tem

    # --- As seis ferramentas ----------------------------------------------------------------

    def buscar_componente(self, termo) -> dict:
        """Procura ``termo`` no id e na descrição dos componentes da base.

        Ignora maiúsculas, acentos, espaços, sublinhados, hífens e pontuação. Um componente
        aparece se o termo, sem separadores, está dentro do id sem separadores, ou se cada
        palavra do termo é o começo de uma palavra do id ou da descrição ("umid" acha
        "umidade"; "ado" não acha "adaptar"). Devolve todos os que baterem, em ordem de id,
        sem escolher entre eles.
        """
        return self._rodar("buscar_componente", _BuscarEntrada, self._buscar, termo=termo)

    def ler_dados_componente(self, id) -> dict:
        """Devolve o componente ``id`` com os campos que estão no YAML, e só eles."""
        return self._rodar("ler_dados_componente", _LerEntrada, self._ler, id=id)

    def selecionar_componente(self, id, ref) -> dict:
        """Põe o componente ``id`` da base no projeto com a referência ``ref``."""
        return self._rodar("selecionar_componente", _SelecionarEntrada, self._selecionar,
                           id=id, ref=ref)

    def conectar(self, ref, pino, rede) -> dict:
        """Liga o ``pino`` (número ou nome, como na base) da peça ``ref`` à ``rede``.

        Um nome que aparece em mais de um pino da peça (os GND do ESP32) liga todos os
        pinos com esse nome, como no ``circuito.py``. Um pino fica em uma rede só.
        """
        return self._rodar("conectar", _ConectarEntrada, self._conectar,
                           ref=ref, pino=pino, rede=rede)

    def registrar_decisao(self, decisao, motivo, fonte) -> dict:
        """Guarda uma decisão. ``fonte`` (texto ou lista) precisa apontar para algo que
        existe: veja ``FORMATOS_DE_FONTE``."""
        return self._rodar("registrar_decisao", _DecisaoEntrada, self._registrar_decisao,
                           decisao=decisao, motivo=motivo, fonte=fonte)

    def registrar_pendencia(self, necessidade, motivo) -> dict:
        """Guarda algo que o projeto precisa e que a base não tem."""
        return self._rodar("registrar_pendencia", _PendenciaEntrada, self._registrar_pendencia,
                           necessidade=necessidade, motivo=motivo)

    # --- Pedido do modelo -------------------------------------------------------------------

    def executar_ferramenta(self, nome, entrada) -> dict:
        """Executa o pedido ``nome(**entrada)`` e devolve o resultado, mesmo se for inválido."""
        if nome not in FERRAMENTAS:
            return _erro("ferramenta_inexistente", f"não existe a ferramenta {nome!r}",
                         "use uma das ferramentas disponíveis", ferramentas=list(FERRAMENTAS))
        if not isinstance(entrada, dict):
            return _erro("entrada_invalida", "os argumentos precisam ser um objeto (mapa)",
                         f"chame {nome} com os argumentos nomeados")
        entradas = {"buscar_componente": _BuscarEntrada, "ler_dados_componente": _LerEntrada,
                    "selecionar_componente": _SelecionarEntrada, "conectar": _ConectarEntrada,
                    "registrar_decisao": _DecisaoEntrada,
                    "registrar_pendencia": _PendenciaEntrada}
        modelo = entradas[nome]
        try:
            validado = modelo.model_validate(entrada)
        except ValidationError as e:
            return self._entrada_invalida(nome, e)
        return getattr(self, nome)(**validado.model_dump())

    # --- Estado -----------------------------------------------------------------------------

    def estado(self) -> dict:
        """Cópia do estado do projeto, para o gerador de netlist e para os testes.

        As tentativas de selecionar um id inexistente ficam fora: estão em
        ``tentativas_inexistentes``, que é medida do eval e não parte do projeto.
        """
        redes: dict[str, list[str]] = {}
        for lig in self.ligacoes.values():
            redes.setdefault(lig.rede, []).append(f"{lig.ref}:{lig.pino}")
        return {
            "selecoes": dict(self.selecoes),
            "ligacoes": [asdict(lig) for lig in self.ligacoes.values()],
            "redes": redes,
            "decisoes": [asdict(d) for d in self.decisoes],
            "pendencias": [asdict(p) for p in self.pendencias],
        }

    # --- Implementação ----------------------------------------------------------------------

    def _rodar(self, nome: str, modelo, funcao: Callable[..., dict], **argumentos) -> dict:
        try:
            entrada = modelo.model_validate(argumentos)
        except ValidationError as e:
            return self._entrada_invalida(nome, e)
        return funcao(entrada)

    @staticmethod
    def _entrada_invalida(nome: str, erro: ValidationError) -> dict:
        problemas = [f"{'.'.join(str(p) for p in e['loc']) or '(entrada)'}: {e['msg']}"
                     for e in erro.errors()]
        return _erro("entrada_invalida", "argumento inválido: " + "; ".join(problemas),
                     f"corrija os argumentos de {nome} e chame de novo", problemas=problemas)

    def _encontrar(self, termo: str) -> list[str]:
        compacto, palavras = _compacto(termo), _palavras(termo)
        if not compacto:
            return []
        achados = []
        for id_, comp in self.base.items():
            existentes = _palavras(id_) + _palavras(comp.descricao)
            if compacto in _compacto(id_) or all(
                    any(w.startswith(p) for w in existentes) for p in palavras):
                achados.append(id_)
        return sorted(achados)

    def _resumo(self, id_: str) -> dict:
        comp = self.base[id_]
        return {"id": id_, "descricao": comp.descricao, "status": comp.status}

    def _buscar(self, e: _BuscarEntrada) -> dict:
        if not _compacto(e.termo):
            return _erro("entrada_invalida", "o termo só tem espaços e separadores",
                         "busque por uma palavra, como 'umidade' ou 'conversor'")
        achados = self._encontrar(e.termo)
        if not achados:
            return _erro("nenhum_componente", f"nenhum componente encontrado para {e.termo!r}",
                         "tente outro termo; se a peça não estiver na base, registre a "
                         "necessidade com registrar_pendencia e não invente um id")
        return _ok(encontrados=[self._resumo(i) for i in achados])

    def _nao_esta_na_base(self, id_: str) -> dict:
        return _erro("componente_inexistente", f"o componente {id_!r} não está na base",
                     "confira o id com buscar_componente; se a peça não existir na base, "
                     "registre a necessidade com registrar_pendencia e não invente um id",
                     sugestoes=self._encontrar(id_))

    def _ler(self, e: _LerEntrada) -> dict:
        if e.id not in self.base:
            return self._nao_esta_na_base(e.id)
        return _ok(componente=self.base[e.id].model_dump(exclude_unset=True))

    def _selecionar(self, e: _SelecionarEntrada) -> dict:
        if e.id not in self.base:
            self.tentativas_inexistentes.append(e.id)
            return self._nao_esta_na_base(e.id)
        repetida = next((r for r in self.selecoes if r.casefold() == e.ref.casefold()), None)
        if repetida is not None:
            return _erro("referencia_repetida",
                         f"a referência {repetida!r} já é do componente "
                         f"{self.selecoes[repetida]!r}",
                         "use outra referência para a nova peça",
                         selecoes=dict(self.selecoes))
        self.selecoes[e.ref] = e.id
        comp = self.base[e.id]
        resultado = _ok(ref=e.ref, componente=e.id, status=comp.status,
                        pinos=[{"numero": p.numero, "nome": p.nome, "tipo": p.tipo}
                               for p in comp.pinos])
        if comp.status != "revisado":
            resultado["aviso"] = (f"{e.id} está em {comp.status!r}: os dados ainda não foram "
                                  "conferidos contra a fonte")
        return resultado

    def _pinos_por_nome_ou_numero(self, comp: Componente, pino: int | str) -> list[Pino]:
        if isinstance(pino, int):
            return [p for p in comp.pinos if p.numero == pino]
        return [p for p in comp.pinos if p.nome == pino]

    def _conectar(self, e: _ConectarEntrada) -> dict:
        if e.ref not in self.selecoes:
            return _erro("peca_nao_selecionada", f"a referência {e.ref!r} não foi selecionada",
                         "selecione a peça com selecionar_componente antes de conectar",
                         selecoes=dict(self.selecoes))
        id_ = self.selecoes[e.ref]
        comp = self.base[id_]
        pinos = self._pinos_por_nome_ou_numero(comp, e.pino)
        if not pinos:
            return _erro("pino_inexistente", f"{id_} ({e.ref}) não tem o pino {e.pino!r}",
                         "use um número ou um nome de pino da lista; não presuma pinos que "
                         "a base não documenta",
                         pinos=[f"{p.numero}:{p.nome}" for p in comp.pinos])
        inusaveis = [f"{p.numero}:{p.nome}" for p in pinos if p.tipo == "nao_usado"]
        if inusaveis:
            return _erro("pino_nao_usavel", f"a base marca {inusaveis} de {id_} como não usado",
                         "escolha outro pino")
        ocupados = {f"{p.numero}:{p.nome}": self.ligacoes[(e.ref, p.numero)].rede
                    for p in pinos if (e.ref, p.numero) in self.ligacoes
                    and self.ligacoes[(e.ref, p.numero)].rede != e.rede}
        if ocupados:
            return _erro("pino_ja_ligado",
                         f"pino(s) de {e.ref} já ligado(s) a outra rede: {ocupados}",
                         "um pino fica em uma rede só; escolha outro pino ou use a mesma rede",
                         ligados=ocupados)
        novos = [p for p in pinos if (e.ref, p.numero) not in self.ligacoes]
        for p in novos:
            self.ligacoes[(e.ref, p.numero)] = Ligacao(e.ref, p.numero, p.nome, e.rede)
        return _ok(ref=e.ref, rede=e.rede,
                   pinos=[{"numero": p.numero, "nome": p.nome} for p in pinos],
                   ja_existia=not novos,
                   pinos_na_rede=sum(1 for lig in self.ligacoes.values() if lig.rede == e.rede))

    def _problema_da_fonte(self, fonte: str) -> str | None:
        """Devolve o problema da fonte, ou None se ela aponta para algo que existe."""
        if fonte.startswith("especificacao:"):
            caminho = fonte.removeprefix("especificacao:")
            if self.especificacao is None:
                return f"{fonte!r}: nenhuma especificação foi carregada nesta sessão"
            caminhos = dict(self.especificacao.decisoes())
            if caminho not in caminhos:
                return (f"{fonte!r}: a especificação não tem a decisão {caminho!r} "
                        f"(existem: {sorted(caminhos)})")
            return None
        m = re.fullmatch(r"componente:([^/\s]+)(?:/(regra|pino):(.+))?", fonte)
        if m is None:
            return f"{fonte!r} não está num formato aceito"
        id_, tipo, alvo = m.groups()
        if id_ not in self.base:
            return f"{fonte!r}: o componente {id_!r} não está na base"
        comp = self.base[id_]
        if tipo == "regra" and alvo not in {r.id for r in comp.regras}:
            return (f"{fonte!r}: {id_} não tem a regra {alvo!r} "
                    f"(tem: {[r.id for r in comp.regras]})")
        if tipo == "pino":
            pino = int(alvo) if alvo.isdigit() else alvo
            if not self._pinos_por_nome_ou_numero(comp, pino):
                return f"{fonte!r}: {id_} não tem o pino {alvo!r}"
        return None

    def _registrar_decisao(self, e: _DecisaoEntrada) -> dict:
        fontes = [e.fonte] if isinstance(e.fonte, str) else list(e.fonte)
        fontes = list(dict.fromkeys(f.strip() for f in fontes))
        problemas = [p for p in map(self._problema_da_fonte, fontes) if p]
        if problemas:
            return _erro("fonte_invalida", "fonte sem origem verificável: " + "; ".join(problemas),
                         "cite um componente, uma regra ou um pino da base (ou uma decisão da "
                         "especificação); se o dado não está na base, registre uma pendência "
                         "em vez de decidir",
                         formatos=list(FORMATOS_DE_FONTE), problemas=problemas)
        self.decisoes.append(Decisao(e.decisao.strip(), e.motivo.strip(), tuple(fontes)))
        return _ok(total_decisoes=len(self.decisoes))

    def _registrar_pendencia(self, e: _PendenciaEntrada) -> dict:
        chave = " ".join(_palavras(e.necessidade))
        if any(" ".join(_palavras(p.necessidade)) == chave for p in self.pendencias):
            return _ok(ja_existia=True, total_pendencias=len(self.pendencias))
        self.pendencias.append(Pendencia(e.necessidade.strip(), e.motivo.strip()))
        return _ok(ja_existia=False, total_pendencias=len(self.pendencias))
