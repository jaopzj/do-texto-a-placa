"""Modelo da especificação de uma placa (Marco 4, Parte 2 do guia do MVP).

A especificação é a representação intermediária da proposta: fica entre o pedido do
usuário, em português, e a netlist. Ela diz o que a placa é (projeto), com quais módulos
da base de componentes, como é alimentada e quais são as restrições físicas. Cada decisão
registra quem a tomou, em ``decidido_por``: ``"usuario"`` ou ``"agente"``. É essa
rastreabilidade que permite saber, quando algo der errado, se o problema veio de um pedido
do usuário ou de uma suposição do sistema (ADR-009).

O modelo segue as regras da base de componentes (ADR-006): campo desconhecido é erro,
nenhum tipo é convertido (``"5.0"`` entre aspas é recusado) e texto obrigatório não pode ser
vazio. Por cima delas:

- decisão do agente exige ``motivo`` e ``fonte``, como a ferramenta
  ``registrar_decisao(decisao, motivo, fonte)`` da Parte 3 do guia;
- dois módulos não podem ter o mesmo ``papel``.

O modelo sozinho confere a forma. Que os ids citados existem na base de componentes é
conferido por ``ler_especificacao``, que lê o YAML, valida pelo modelo e cruza cada
referência com ``carregar_todos()``. Com qualquer problema, levanta ``ErroEspecificacao``
com todos eles, e nada é devolvido.

Uso:
    from src.especificacao import ler_especificacao
    spec = ler_especificacao(Path("placas/monitor-umidade/spec.yaml"))

Unidades: tensões em volts e medidas em milímetros.
"""
from pathlib import Path
from typing import Annotated, Literal

import yaml
from pydantic import Field, ValidationError, model_validator

from .componentes.carregar import (Problema, _CarregadorSemChaveRepetida, _local,
                                   carregar_todos)
from .componentes.modelo import Componente, Fonte, Texto, Volts, _Estrito, _repetidos

# Mesmo formato do id de um componente da base (src/componentes/modelo.py).
Id = Annotated[str, Field(pattern=r"^[a-z0-9-]+$")]

# Medida em milímetros, sempre positiva.
Milimetros = Annotated[float, Field(gt=0)]

DecididoPor = Literal["usuario", "agente"]


class RegraCitada(_Estrito):
    """Uma regra da base de componentes que motivou a decisão."""
    componente: Id                       # id do componente na base
    regra: Texto                         # id da regra nesse componente


class Decisao(_Estrito):
    """Base de toda decisão da especificação: quem decidiu, por quê e com que fonte."""
    decidido_por: DecididoPor
    motivo: Texto | None = None
    fonte: Fonte | None = None           # documento (e página) que sustenta a decisão
    regras: list[RegraCitada] = []       # regras da base que levaram à decisão

    @model_validator(mode="after")
    def _agente_justifica(self) -> "Decisao":
        if self.decidido_por == "agente":
            faltando = [c for c in ("motivo", "fonte") if getattr(self, c) is None]
            if faltando:
                raise ValueError(f"decisão do agente precisa de {faltando} (ADR-009)")
        return self


class Projeto(_Estrito):
    id: Id                               # ex.: "monitor-umidade", o nome da pasta da placa
    nome: Texto
    descricao: Texto                     # o que a placa faz, em uma ou duas frases


class Requisito(Decisao):
    """Uma exigência sobre como um módulo é usado (ex.: sensor num pino do ADC1)."""
    descricao: Texto


class Modulo(Decisao):
    """Um módulo da placa: a escolha de um componente da base para um papel."""
    papel: Texto                         # ex.: "microcontrolador", "sensor de umidade"
    componente: Id                       # id do componente na base
    requisitos: list[Requisito] = []


class Alimentacao(Decisao):
    origem: Literal["usb_do_devkit"]     # de onde vem a energia da placa
    tensao: Volts                        # em volts


class Camadas(Decisao):
    valor: Annotated[int, Field(ge=1)]   # camadas de cobre


class Contorno(Decisao):
    largura: Milimetros                  # em milímetros
    altura: Milimetros                   # em milímetros


class Montagem(Decisao):
    """Como os módulos entram na placa (ADR-005 e ADR-008)."""
    valor: Literal["barra_pinos_macho", "barra_pinos_femea"]


class Restricoes(_Estrito):
    camadas: Camadas
    contorno: Contorno
    montagem: Montagem


class Especificacao(_Estrito):
    projeto: Projeto
    modulos: list[Modulo] = Field(min_length=1)
    alimentacao: Alimentacao
    restricoes: Restricoes

    @model_validator(mode="after")
    def _papeis_unicos(self) -> "Especificacao":
        repetidos = _repetidos(m.papel for m in self.modulos)
        if repetidos:
            raise ValueError(f"papel de módulo repetido: {repetidos}")
        return self

    def decisoes(self) -> list[tuple[str, Decisao]]:
        """Todas as decisões, cada uma com o caminho dela no arquivo."""
        lista: list[tuple[str, Decisao]] = []
        for i, m in enumerate(self.modulos):
            lista.append((f"modulos.{i}", m))
            lista.extend((f"modulos.{i}.requisitos.{j}", r) for j, r in enumerate(m.requisitos))
        lista.append(("alimentacao", self.alimentacao))
        for nome in ("camadas", "contorno", "montagem"):
            lista.append((f"restricoes.{nome}", getattr(self.restricoes, nome)))
        return lista


class ErroEspecificacao(Exception):
    """A especificação tem um ou mais problemas."""

    def __init__(self, problemas: list[Problema]):
        self.problemas = problemas
        linhas = "\n".join(f"  - {p}" for p in problemas)
        super().__init__(f"especificação inválida ({len(problemas)} problema(s)):\n{linhas}")


def referencias_invalidas(spec: Especificacao, base: dict[str, Componente]) -> list[str]:
    """Confere cada id citado contra a base e devolve a lista de problemas (vazia se ok).

    - todo ``componente`` de módulo existe na base;
    - toda regra citada é de um componente usado num módulo da placa e existe nele.
    """
    problemas = []
    for i, m in enumerate(spec.modulos):
        if m.componente not in base:
            problemas.append(f"modulos.{i}.componente: {m.componente!r} não está na base")
    usados = {m.componente for m in spec.modulos}
    for caminho, decisao in spec.decisoes():
        for k, citada in enumerate(decisao.regras):
            local = f"{caminho}.regras.{k}"
            if citada.componente not in base:
                problemas.append(f"{local}: {citada.componente!r} não está na base")
            elif citada.componente not in usados:
                problemas.append(f"{local}: {citada.componente!r} não é módulo desta placa")
            elif citada.regra not in {r.id for r in base[citada.componente].regras}:
                problemas.append(
                    f"{local}: {citada.componente!r} não tem a regra {citada.regra!r}")
    return problemas


def ler_especificacao(arquivo: Path, base: dict[str, Componente] | None = None) -> Especificacao:
    """Lê o YAML, valida pelo modelo e confere as referências contra a base.

    ``base`` é a base de componentes; se ficar de fora, é lida por ``carregar_todos()``
    (que levanta ``ErroBase`` se a própria base tiver problema). Levanta
    ``ErroEspecificacao`` com todos os problemas encontrados.
    """
    arquivo = Path(arquivo)
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise ErroEspecificacao([Problema(arquivo, "o arquivo não existe")]) from None
    except UnicodeDecodeError:
        raise ErroEspecificacao([Problema(arquivo, "o arquivo não está em UTF-8")]) from None
    try:
        dados = yaml.load(texto, Loader=_CarregadorSemChaveRepetida)  # noqa: S506 (SafeLoader)
    except yaml.YAMLError as e:
        raise ErroEspecificacao([Problema(arquivo, f"YAML inválido: {e}")]) from None
    if not isinstance(dados, dict):
        tipo = "vazio" if dados is None else type(dados).__name__
        raise ErroEspecificacao([Problema(
            arquivo, f"o conteúdo precisa ser um mapa de campos, mas é {tipo}")])
    try:
        spec = Especificacao.model_validate(dados)
    except ValidationError as e:
        raise ErroEspecificacao([
            Problema(arquivo, f"{_local(err['loc'])}: {err['msg']}") for err in e.errors()
        ]) from None

    base = carregar_todos() if base is None else base
    problemas = referencias_invalidas(spec, base)
    if problemas:
        raise ErroEspecificacao([Problema(arquivo, p) for p in problemas])
    return spec
