"""Pinos do gabarito que o eval aceita trocar por outro equivalente (ADR-015).

O gabarito fixa uma resposta, mas a especificação às vezes deixa a escolha em aberto. No
monitor de umidade, o ``spec.yaml`` pede só "a saída AOUT do sensor vai num pino do ESP32
com função ADC1", e o gabarito usa o IO34. O IO32, o IO33 e os outros pinos do ADC1 cumprem
o mesmo requisito, e o eval não deve reprovar o agente por escolher um deles.

Cada equivalência fica em ``placas/<placa>/equivalencias.yaml``, escrita à mão e revisada
como o gabarito:

    equivalencias:
      - pino: "esp32-devkitc-v4: IO34"
        funcao: ADC1_
        requisito: A saída AOUT do sensor vai num pino do ESP32 com função ADC1.

Quem decide quais pinos valem é o código, pela base: as alternativas são os pinos da mesma
peça que têm alguma função começando por ``funcao`` (o IO34 tem ``ADC1_CH6``, o IO32 tem
``ADC1_CH4``). ``requisito`` precisa ser, palavra por palavra, a descrição de um requisito do
``spec.yaml``: uma equivalência só existe porque a especificação deixou a escolha aberta.
Qualquer problema levanta ``ErroEquivalencias``, com todos os motivos.
"""
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from ..componentes.carregar import carregar_todos
from ..componentes.modelo import Componente
from ..especificacao import ler_especificacao


class ErroEquivalencias(ValueError):
    """O arquivo de equivalências não pôde ser lido ou não confere com a base ou o spec."""

    def __init__(self, problemas: list[str], origem: str = "equivalências"):
        self.problemas = list(problemas)
        super().__init__(f"{origem}:\n- " + "\n- ".join(problemas))


class _Entrada(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    pino: str = Field(min_length=1)        # rótulo do comparar: "<id da peça>: <nome do pino>"
    funcao: str = Field(min_length=1)      # prefixo de função na base, ex.: "ADC1_"
    requisito: str = Field(min_length=1)   # descrição de um requisito do spec.yaml


class _Arquivo(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    equivalencias: list[_Entrada] = []


@dataclass(frozen=True)
class Equivalencia:
    """O pino do gabarito e os pinos que o substituem sem mudar o circuito."""
    pino: str
    alternativas: frozenset[str]
    requisito: str


def rotulos_da_peca(peca: Componente) -> dict[int, str]:
    """Número do pino -> rótulo, como o ``comparar`` escreve (``"id: nome"`` ou ``"#n"``)."""
    contagem = Counter(p.nome for p in peca.pinos)
    return {p.numero: f"{peca.id}: {p.nome}" + (f"#{p.numero}" if contagem[p.nome] > 1 else "")
            for p in peca.pinos}


def _requisitos(spec) -> set[str]:
    return {r.descricao for m in spec.modulos for r in m.requisitos}


def ler_equivalencias(arquivo: Path, spec: Path,
                      base: dict[str, Componente] | None = None) -> list[Equivalencia]:
    """Lê ``arquivo`` e devolve as equivalências. Arquivo ausente: nenhuma equivalência."""
    base = carregar_todos() if base is None else base
    arquivo = Path(arquivo)
    if not arquivo.exists():
        return []
    origem = str(arquivo)
    try:
        dados = yaml.safe_load(arquivo.read_text(encoding="utf-8")) or {}
        lido = _Arquivo.model_validate(dados)
    except yaml.YAMLError as e:
        raise ErroEquivalencias([f"YAML inválido: {e}"], origem) from None
    except ValidationError as e:
        raise ErroEquivalencias([f"{'.'.join(map(str, x['loc']))}: {x['msg']}"
                                 for x in e.errors()], origem) from None

    requisitos = _requisitos(ler_especificacao(spec, base))
    problemas: list[str] = []
    equivalencias: list[Equivalencia] = []
    for i, e in enumerate(lido.equivalencias):
        onde = f"equivalencias[{i}] ({e.pino})"
        if e.requisito not in requisitos:
            problemas.append(f"{onde}: o requisito {e.requisito!r} não está no spec")
        id_peca, sep, _ = e.pino.partition(": ")
        peca = base.get(id_peca) if sep else None
        if peca is None:
            problemas.append(f"{onde}: o pino precisa ser '<id da peça da base>: <nome>'")
            continue
        rotulos = rotulos_da_peca(peca)
        por_rotulo = {r: n for n, r in rotulos.items()}
        if e.pino not in por_rotulo:
            problemas.append(f"{onde}: {id_peca} não tem esse pino")
            continue
        funcoes = {p.numero: p.funcoes for p in peca.pinos}
        def cumpre(numero: int) -> bool:
            return any(f.startswith(e.funcao) for f in funcoes[numero])
        if not cumpre(por_rotulo[e.pino]):
            problemas.append(f"{onde}: o próprio pino não tem função {e.funcao}*")
            continue
        alternativas = frozenset(r for n, r in rotulos.items() if r != e.pino and cumpre(n))
        if not alternativas:
            problemas.append(f"{onde}: nenhum outro pino de {id_peca} tem função {e.funcao}*")
            continue
        equivalencias.append(Equivalencia(e.pino, alternativas, e.requisito))
    repetidos = [p for p, n in Counter(e.pino for e in equivalencias).items() if n > 1]
    problemas += [f"o pino {p} aparece em mais de uma equivalência" for p in repetidos]
    if problemas:
        raise ErroEquivalencias(problemas, origem)
    return equivalencias
