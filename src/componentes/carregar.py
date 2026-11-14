"""Carrega e valida todos os componentes da pasta componentes/.

Uso:
    from src.componentes.carregar import carregar_todos
    base = carregar_todos()          # dict: id do componente -> Componente

Se qualquer arquivo tiver problema, nada é devolvido: ``carregar_todos`` levanta
``ErroBase`` com a lista de todos os problemas encontrados, cada um com o arquivo e o
campo. Assim um componente inválido nunca entra na base em silêncio, e quem corrige vê
todos os erros de uma vez.
"""
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import ValidationError

from .modelo import Componente

PASTA = Path(__file__).resolve().parents[2] / "componentes"


@dataclass(frozen=True)
class Problema:
    arquivo: Path
    mensagem: str

    def __str__(self) -> str:
        return f"{self.arquivo.name}: {self.mensagem}"


class ErroBase(Exception):
    """A base de componentes tem um ou mais problemas."""

    def __init__(self, problemas: list[Problema]):
        self.problemas = problemas
        linhas = "\n".join(f"  - {p}" for p in problemas)
        super().__init__(f"base de componentes inválida ({len(problemas)} problema(s)):\n{linhas}")


class _CarregadorSemChaveRepetida(yaml.SafeLoader):
    """SafeLoader que recusa chave repetida no mesmo mapa.

    O PyYAML, por padrão, fica com o último valor e descarta o primeiro sem avisar.
    """


def _mapa_sem_repeticao(loader, no, deep=False):
    chaves = set()
    for no_chave, _ in no.value:
        chave = loader.construct_object(no_chave, deep=deep)
        if chave in chaves:
            raise yaml.constructor.ConstructorError(
                "ao ler um mapa", no.start_mark,
                f"chave repetida: {chave!r}", no_chave.start_mark)
        chaves.add(chave)
    return loader.construct_mapping(no, deep=deep)


_CarregadorSemChaveRepetida.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG, _mapa_sem_repeticao)


def _local(loc: tuple) -> str:
    return ".".join(str(parte) for parte in loc) or "(componente)"


def _problemas_de_validacao(arquivo: Path, erro: ValidationError) -> list[Problema]:
    return [Problema(arquivo, f"{_local(e['loc'])}: {e['msg']}") for e in erro.errors()]


def ler_arquivo(arquivo: Path) -> Componente:
    """Lê e valida um único YAML. Levanta ``ErroBase`` se houver problema."""
    try:
        texto = arquivo.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        raise ErroBase([Problema(arquivo, "o arquivo não está em UTF-8")]) from None
    try:
        dados = yaml.load(texto, Loader=_CarregadorSemChaveRepetida)  # noqa: S506 (SafeLoader)
    except yaml.YAMLError as e:
        raise ErroBase([Problema(arquivo, f"YAML inválido: {e}")]) from None
    if not isinstance(dados, dict):
        tipo = "vazio" if dados is None else type(dados).__name__
        raise ErroBase([Problema(
            arquivo, f"o conteúdo precisa ser um mapa de campos, mas é {tipo}")])
    try:
        return Componente.model_validate(dados)    # aqui o Pydantic valida
    except ValidationError as e:
        raise ErroBase(_problemas_de_validacao(arquivo, e)) from None


def carregar_todos(pasta: Path = PASTA) -> dict[str, Componente]:
    """Lê todos os ``*.yaml`` da pasta e devolve ``{id: Componente}``.

    Levanta ``ErroBase`` com todos os problemas se a pasta não existir, se algum arquivo
    for inválido, se dois arquivos tiverem o mesmo ``id`` ou se houver arquivo ``.yml``
    (que seria ignorado sem aviso).
    """
    pasta = Path(pasta)
    if not pasta.is_dir():
        raise ErroBase([Problema(pasta, "a pasta da base de componentes não existe")])

    problemas = [Problema(a, "use a extensão .yaml (arquivos .yml não são lidos)")
                 for a in sorted(pasta.glob("*.yml"))]
    base: dict[str, Componente] = {}
    origem: dict[str, Path] = {}
    for arquivo in sorted(pasta.glob("*.yaml")):
        try:
            comp = ler_arquivo(arquivo)
        except ErroBase as e:
            problemas.extend(e.problemas)
            continue
        if comp.id in base:
            problemas.append(Problema(
                arquivo, f"id {comp.id!r} repetido (já usado em {origem[comp.id].name})"))
            continue
        base[comp.id] = comp
        origem[comp.id] = arquivo

    if problemas:
        raise ErroBase(problemas)
    return base
