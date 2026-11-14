"""Modelo de dados da base de componentes.

O esquema é o da Parte 2 do guia do MVP. Por cima dele, o modelo recusa o que seria
aceito em silêncio e viraria dado errado para o agente (ver ADR-006):

- campo desconhecido (por exemplo, um erro de digitação como ``tensao_maxima``), que o
  Pydantic, por padrão, simplesmente ignoraria;
- tipo convertido por conta própria (o texto ``"3.3"`` virando número, ``true`` virando 1);
- texto vazio onde o dado é obrigatório (descrição, fonte, nome do pino...);
- valores que não fazem sentido físico ou se contradizem: tensão zero ou negativa,
  alimentação mínima maior que a máxima, pino com número repetido, componente sem pinos.

Unidades: todas as tensões estão em volts.
"""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

# Texto obrigatório: pelo menos um caractere que não seja espaço.
Texto = Annotated[str, StringConstraints(min_length=1, pattern=r"\S")]

# Referência a uma biblioteca oficial do KiCad, no formato "Biblioteca:Nome".
ReferenciaKicad = Annotated[str, StringConstraints(pattern=r"^[^:\s]+:[^:\s]+$")]

# Tensão em volts, sempre positiva.
Volts = Annotated[float, Field(gt=0)]


class _Estrito(BaseModel):
    """Base comum: campo desconhecido é erro e nenhum tipo é convertido por conta própria."""
    model_config = ConfigDict(extra="forbid", strict=True)


class Fonte(_Estrito):
    """De onde veio um dado."""
    documento: Texto                     # ex.: "datasheet ESP32-WROOM-32, v3.4"
    pagina: Annotated[int, Field(ge=1)] | None = None


class Pino(_Estrito):
    numero: Annotated[int, Field(ge=1)]  # posição física no conector do módulo
    nome: Texto                          # nome impresso na peça
    tipo: Literal["alimentacao", "terra", "entrada", "saida",
                  "entrada_saida", "analogico", "nao_usado"]
    tensao_max: Volts | None = None      # em volts
    funcoes: list[Texto] = []            # ex.: ["ADC1_CH6"]
    fonte: Fonte


class Regra(_Estrito):
    """Uma restrição de uso que o verificador vai checar."""
    id: Texto
    descricao: Texto
    severidade: Literal["aviso", "erro"]


class Componente(_Estrito):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    descricao: Texto
    kicad_simbolo: ReferenciaKicad       # aponta para a biblioteca do KiCad
    kicad_footprint: ReferenciaKicad
    alimentacao_min: Volts               # em volts
    alimentacao_max: Volts
    nivel_logico: Volts | None = None    # em volts
    pinos: list[Pino] = Field(min_length=1)
    regras: list[Regra] = []
    status: Literal["rascunho", "revisado"]

    @model_validator(mode="after")
    def _consistente(self) -> "Componente":
        if self.alimentacao_min > self.alimentacao_max:
            raise ValueError(
                f"alimentacao_min ({self.alimentacao_min} V) é maior que "
                f"alimentacao_max ({self.alimentacao_max} V)")
        repetidos = _repetidos(p.numero for p in self.pinos)
        if repetidos:
            raise ValueError(f"número de pino repetido: {repetidos}")
        repetidas = _repetidos(r.id for r in self.regras)
        if repetidas:
            raise ValueError(f"id de regra repetido: {repetidas}")
        return self


def _repetidos(valores) -> list:
    vistos, repetidos = set(), []
    for v in valores:
        if v in vistos and v not in repetidos:
            repetidos.append(v)
        vistos.add(v)
    return repetidos
