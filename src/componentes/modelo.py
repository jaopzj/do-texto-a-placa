"""Modelo de dados da base de componentes.

O esquema é o da Parte 2 do guia do MVP. Por cima dele, o modelo recusa o que seria
aceito em silêncio e viraria dado errado para o agente (ver ADR-006):

- campo desconhecido (por exemplo, um erro de digitação como ``tensao_maxima``), que o
  Pydantic, por padrão, simplesmente ignoraria;
- tipo convertido por conta própria (o texto ``"3.3"`` virando número, ``true`` virando 1);
- texto vazio onde o dado é obrigatório (descrição, fonte, nome do pino...);
- valores que não fazem sentido físico ou se contradizem: tensão zero ou negativa,
  alimentação mínima maior que a máxima, pino com número repetido, componente sem pinos.

Símbolo e footprint (ADR-007): uma peça de um conector só usa ``kicad_simbolo`` e
``kicad_footprint``. Uma peça com várias fileiras (o ESP32 DevKitC, o conversor de nível)
usa ``conectores``: um símbolo e um footprint por fileira, cada um com a lista dos números
de pino da peça que ele leva, na ordem física. Cada pino da peça fica em exatamente um
conector. ``conectores_fisicos()`` devolve a lista nos dois casos.

Unidades: todas as tensões estão em volts.
"""
from typing import Annotated, Literal

from pydantic import (BaseModel, ConfigDict, Field, StringConstraints, ValidationError,
                      model_validator)

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


class Conector(_Estrito):
    """Uma fileira de pinos da peça, que vira um conector na placa (ADR-005 e ADR-007)."""
    nome: Texto                          # ex.: "esquerda", "HV"
    kicad_simbolo: ReferenciaKicad
    kicad_footprint: ReferenciaKicad
    pinos: list[Annotated[int, Field(ge=1)]] = Field(min_length=1)  # na ordem física


class Componente(_Estrito):
    id: str = Field(pattern=r"^[a-z0-9-]+$")
    descricao: Texto
    # Peça de um conector só: símbolo e footprint aqui. Peça com várias fileiras:
    # use "conectores" e deixe estes dois de fora (ADR-007).
    kicad_simbolo: ReferenciaKicad | None = None    # aponta para a biblioteca do KiCad
    kicad_footprint: ReferenciaKicad | None = None
    conectores: list[Conector] = []
    alimentacao_min: Volts               # em volts
    alimentacao_max: Volts
    nivel_logico: Volts | None = None    # em volts
    pinos: list[Pino] = Field(min_length=1)
    regras: list[Regra] = []
    status: Literal["rascunho", "revisado"]

    def conectores_fisicos(self) -> list[Conector]:
        """Os conectores da peça na placa: os de ``conectores`` ou, se não houver, um só
        com ``kicad_simbolo``, ``kicad_footprint`` e todos os pinos na ordem do YAML."""
        if self.conectores:
            return list(self.conectores)
        return [Conector(nome=self.id, kicad_simbolo=self.kicad_simbolo,
                         kicad_footprint=self.kicad_footprint,
                         pinos=[p.numero for p in self.pinos])]

    @model_validator(mode="wrap")
    @classmethod
    def _simbolo_e_footprint(cls, dados, validar):
        comp = validar(dados)
        if comp.conectores:
            sobrando = [c for c in ("kicad_simbolo", "kicad_footprint")
                        if getattr(comp, c) is not None]
            if sobrando:
                raise ValueError(f"com conectores, deixe de fora {sobrando} (ADR-007)")
        else:
            faltando = [c for c in ("kicad_simbolo", "kicad_footprint")
                        if getattr(comp, c) is None]
            if faltando:
                raise ValidationError.from_exception_data(cls.__name__, [
                    {"type": "missing", "loc": (c,), "input": dados} for c in faltando])
        return comp

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
        self._conectores_consistentes()
        return self

    def _conectores_consistentes(self) -> None:
        if not self.conectores:
            return
        repetidos = _repetidos(c.nome for c in self.conectores)
        if repetidos:
            raise ValueError(f"nome de conector repetido: {repetidos}")
        numeros = {p.numero for p in self.pinos}
        nos_conectores = [n for c in self.conectores for n in c.pinos]
        inexistentes = sorted({n for n in nos_conectores if n not in numeros})
        if inexistentes:
            raise ValueError(f"conectores citam pinos que a peça não tem: {inexistentes}")
        em_dois = _repetidos(nos_conectores)
        if em_dois:
            raise ValueError(f"pino em mais de um conector (ou repetido): {em_dois}")
        fora = sorted(numeros - set(nos_conectores))
        if fora:
            raise ValueError(f"pinos fora de qualquer conector: {fora}")


def _repetidos(valores) -> list:
    vistos, repetidos = set(), []
    for v in valores:
        if v in vistos and v not in repetidos:
            repetidos.append(v)
        vistos.add(v)
    return repetidos
