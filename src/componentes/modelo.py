"""Modelo de dados da base de componentes."""
from typing import Literal
from pydantic import BaseModel, Field


class Fonte(BaseModel):
    """De onde veio um dado."""
    documento: str                    # ex.: "datasheet ESP32-WROOM-32, v3.4"
    pagina: int | None = None


class Pino(BaseModel):
    numero: int                       # posição física no conector do módulo
    nome: str                         # nome impresso na peça
    tipo: Literal["alimentacao", "terra", "entrada", "saida",
                  "entrada_saida", "analogico", "nao_usado"]
    tensao_max: float | None = None   # em volts
    funcoes: list[str] = []           # ex.: ["ADC1_CH6"]
    fonte: Fonte


class Regra(BaseModel):
    """Uma restrição de uso que o verificador vai checar."""
    id: str
    descricao: str
    severidade: Literal["aviso", "erro"]


class Componente(BaseModel):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    descricao: str
    kicad_simbolo: str                # aponta para a biblioteca do KiCad
    kicad_footprint: str
    alimentacao_min: float            # em volts
    alimentacao_max: float
    nivel_logico: float | None = None # em volts
    pinos: list[Pino]
    regras: list[Regra] = []
    status: Literal["rascunho", "revisado"]
