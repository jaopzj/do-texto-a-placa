"""Motor de regras: confere o circuito contra as regras da base de componentes (Marco 5,
Parte 3 do guia do MVP; ADR-017).

O motor é o revisor que nunca se cansa. Ele recebe as peças e as ligações do circuito (o
``Ferramentas.estado()`` do agente, conferido de novo por ``gerar_netlist.planejar``) e, para
cada peça, roda cada regra que a base registra para ela. As regras são código: a tabela
``REGRAS`` liga cada regra da base (id do componente e id da regra) a uma função que a
verifica, ou ao motivo de ela não ser verificável pelas ligações (uma regra de firmware, por
exemplo). Nada é configurável de fora: o motor não tem opção para pular regra, a tabela é só
de leitura e nenhuma ferramenta do agente chega aqui. O agente só vê o resultado.

Cada regra devolve uma das situações:

- ``ok``: verificada, e o circuito cumpre;
- ``violada``: verificada, e o circuito não cumpre (com a peça, os pinos, as redes, o porquê e
  como corrigir);
- ``nao_verificavel``: falta um dado na base ou na especificação para julgar. Nunca vira
  ``ok``: uma regra de severidade ``erro`` que não pôde ser verificada reprova o circuito;
- ``manual``: a regra não é sobre ligações (firmware, operação), e quem confere é uma pessoa.

Uma regra que está na base e não está em ``REGRAS`` sai como ``nao_verificavel``: uma regra
nova nunca passa calada.

Tensões (em volts), sem nada de memória:

- a tensão de uma rede de alimentação vem dos pinos de alimentação dela que têm
  ``tensao_max`` na base (o 3V3 do ESP32, o VCC do LCD, o HV e o LV do conversor);
- a tensão de um pino de sinal vem do ``referencia`` dele (a tensão da rede do pino de
  alimentação citado) ou, sem isso, do ``nivel_logico`` da peça;
- o limite de um pino é o ``tensao_max`` dele.

Uso:
    relatorio = verificar(estado, base, wifi=True)
    relatorio.aprovado          # False se houver erro violado ou não verificável
    relatorio.para_dict()       # para o agente, para o laço de correção e para arquivo

    python -m src.regras estado.json --spec placas/monitor-umidade/spec.yaml
"""
import argparse
import json
import re
import sys
import time
from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Literal

from .componentes.carregar import carregar_todos
from .componentes.modelo import Componente, Pino
from .gerar_netlist import ErroGeracao, planejar

Severidade = Literal["erro", "aviso"]
Situacao = Literal["ok", "violada", "nao_verificavel", "manual"]


# --- Resultado --------------------------------------------------------------------------------

@dataclass(frozen=True)
class Problema:
    """Uma violação, ou um ponto que não pôde ser verificado, numa peça do circuito."""
    situacao: Literal["violada", "nao_verificavel"]
    explicacao: str                      # o porquê, em português
    correcao: str | None = None          # o que fazer para corrigir, quando dá para dizer
    pinos: tuple[str, ...] = ()          # "U1:9 (IO25)"
    redes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ResultadoRegra:
    """O resultado de uma regra da base numa peça do circuito."""
    regra: str                           # id da regra na base
    componente: str                      # id do componente na base
    ref: str                             # referência da peça no circuito (U1, LCD1...)
    severidade: Severidade               # da base
    descricao: str                       # da base
    situacao: Situacao
    problemas: tuple[Problema, ...] = ()
    motivo_manual: str | None = None     # por que não é verificável pelas ligações

    @property
    def bloqueia(self) -> bool:
        """Regra de erro violada, ou que não pôde ser verificada."""
        return self.severidade == "erro" and self.situacao in ("violada", "nao_verificavel")


@dataclass(frozen=True)
class Relatorio:
    """Todas as regras de todas as peças do circuito."""
    resultados: tuple[ResultadoRegra, ...]
    wifi: bool | None

    @property
    def aprovado(self) -> bool:
        return not any(r.bloqueia for r in self.resultados)

    def contagem(self) -> dict[str, int]:
        cont = {s: 0 for s in ("ok", "violada", "nao_verificavel", "manual")}
        for r in self.resultados:
            cont[r.situacao] += 1
        return cont

    def para_dict(self) -> dict:
        """O relatório inteiro, pronto para JSON (agente, laço de correção, arquivo)."""
        return {"aprovado": self.aprovado, "wifi": self.wifi, "contagem": self.contagem(),
                "resultados": [asdict(r) | {"bloqueia": r.bloqueia} for r in self.resultados]}

    def texto(self) -> str:
        """O relatório em poucas linhas, para o terminal."""
        c = self.contagem()
        linhas = [f"Motor de regras: {'APROVADO' if self.aprovado else 'REPROVADO'} · "
                  f"{c['ok']} ok, {c['violada']} violada(s), {c['nao_verificavel']} não "
                  f"verificável(is), {c['manual']} manual(is)"]
        ordem = {"violada": 0, "nao_verificavel": 1, "manual": 2, "ok": 3}
        for r in sorted(self.resultados, key=lambda r: (ordem[r.situacao], r.ref, r.regra)):
            marca = {"ok": "ok", "violada": "VIOLADA", "nao_verificavel": "NÃO VERIFICÁVEL",
                     "manual": "manual"}[r.situacao]
            linhas.append(f"  [{marca}] {r.ref} ({r.componente}) · {r.regra} · {r.severidade}")
            for p in r.problemas:
                onde = ", ".join(p.pinos + tuple(f"rede {n}" for n in p.redes))
                linhas.append(f"      {p.explicacao}" + (f" [{onde}]" if onde else ""))
                if p.correcao:
                    linhas.append(f"      como corrigir: {p.correcao}")
            if r.motivo_manual:
                linhas.append(f"      {r.motivo_manual}")
        return "\n".join(linhas)


# --- O circuito, visto pelo motor -------------------------------------------------------------

class ErroCircuito(ValueError):
    """O estado não descreve um circuito válido; nada foi verificado."""

    def __init__(self, problemas: list[str]):
        self.problemas = list(problemas)
        super().__init__("circuito inválido:\n- " + "\n- ".join(self.problemas))


@dataclass(frozen=True)
class PinoLigado:
    ref: str
    peca: Componente
    pino: Pino

    @property
    def rotulo(self) -> str:
        return f"{self.ref}:{self.pino.numero} ({self.pino.nome})"


@dataclass(frozen=True)
class Nivel:
    """A tensão de algo no circuito: ``valor`` em volts, ou ``None`` com o ``porque``."""
    valor: float | None
    porque: str = ""


@dataclass
class Circuito:
    """Peças e redes, já conferidas contra a base. Só leitura para as regras."""
    pecas: dict[str, Componente]                       # ref -> componente
    redes: dict[str, list[PinoLigado]]                 # rede -> pinos
    rede_do_pino: dict[tuple[str, int], str] = field(default_factory=dict)

    @classmethod
    def do_estado(cls, estado: dict, base: dict[str, Componente]) -> "Circuito":
        """Monta a partir de ``Ferramentas.estado()``. Só ``selecoes`` e ``ligacoes`` contam."""
        if not isinstance(estado, dict):
            raise ErroCircuito(["o estado precisa ser um mapa com 'selecoes' e 'ligacoes'"])
        try:
            planejar(estado, base)               # a mesma conferência da netlist (ADR-012)
        except ErroGeracao as e:
            raise ErroCircuito(e.problemas) from None
        pecas = {ref: base[id_] for ref, id_ in estado["selecoes"].items()}
        circuito = cls(pecas, {})
        for lig in estado["ligacoes"]:
            ref, numero, rede = lig["ref"], lig["pino"], lig["rede"]
            if (ref, numero) in circuito.rede_do_pino:
                continue                         # repetida na mesma rede (planejar conferiu)
            pino = next(p for p in pecas[ref].pinos if p.numero == numero)
            circuito.rede_do_pino[(ref, numero)] = rede
            circuito.redes.setdefault(rede, []).append(PinoLigado(ref, pecas[ref], pino))
        return circuito

    def rede(self, ref: str, pino: Pino) -> str | None:
        return self.rede_do_pino.get((ref, pino.numero))

    def outros(self, rede: str, ref: str, pino: Pino) -> list[PinoLigado]:
        return [p for p in self.redes[rede] if (p.ref, p.pino.numero) != (ref, pino.numero)]

    def tensao_da_alimentacao(self, rede: str, exceto_ref: str | None = None) -> Nivel:
        """A tensão de uma rede pelos pinos de alimentação com ``tensao_max`` na base."""
        valores, sem_dado = set(), []
        for p in self.redes.get(rede, []):
            if p.pino.tipo != "alimentacao" or p.ref == exceto_ref:
                continue
            if p.pino.tensao_max is None:
                sem_dado.append(p.rotulo)
            else:
                valores.add(p.pino.tensao_max)
        if len(valores) > 1:
            return Nivel(None, f"a rede {rede} junta alimentações de "
                               f"{sorted(valores)} V")
        if valores:
            return Nivel(valores.pop())
        if sem_dado:
            return Nivel(None, f"a base não diz a tensão de {', '.join(sem_dado)} (tensao_max)")
        return Nivel(None, f"a rede {rede} não tem pino de alimentação")

    def nivel_do_pino(self, p: PinoLigado) -> Nivel:
        """A tensão que um pino põe na rede, pelos dados da base."""
        if p.pino.tipo == "terra":
            return Nivel(0.0)
        if p.pino.tipo == "alimentacao":
            if p.pino.tensao_max is None:
                return Nivel(None, f"a base não diz a tensão de {p.rotulo} (tensao_max)")
            return Nivel(p.pino.tensao_max)
        if p.pino.referencia is not None:
            alim = next(x for x in p.peca.pinos if x.nome == p.pino.referencia)
            rede = self.rede(p.ref, alim)
            if rede is None:
                return Nivel(None, f"{p.rotulo} segue o pino {alim.nome} de {p.ref}, que não "
                                   "está ligado")
            nivel = self.tensao_da_alimentacao(rede)
            if nivel.valor is None:
                return Nivel(None, f"{p.rotulo} segue o pino {alim.nome}: {nivel.porque}")
            return nivel
        if p.peca.nivel_logico is not None:
            return Nivel(p.peca.nivel_logico)
        return Nivel(None, f"a base não diz a tensão do sinal de {p.rotulo} (nem nivel_logico "
                           f"de {p.peca.id}, nem referencia do pino)")


@dataclass(frozen=True)
class Contexto:
    """O que vem da especificação e não do circuito."""
    wifi: bool | None = None


# --- Funções auxiliares das regras ------------------------------------------------------------

def _gpio(pino: Pino) -> int | None:
    """O número GPIO do pino, pela função ``GPIOnn`` na base (ESP32)."""
    for f in pino.funcoes:
        m = re.fullmatch(r"GPIO(\d+)", f)
        if m:
            return int(m.group(1))
    return None


def _ligados(c: Circuito, ref: str, peca: Componente, filtro: Callable[[Pino], bool]
             ) -> list[tuple[Pino, str]]:
    return [(p, r) for p in peca.pinos if filtro(p) and (r := c.rede(ref, p)) is not None]


def _rotulo(ref: str, pino: Pino) -> str:
    return f"{ref}:{pino.numero} ({pino.nome})"


def _gpios_da_regra(gpios: frozenset[int], c: Circuito, ref: str, peca: Componente
                    ) -> list[tuple[Pino, str]]:
    return _ligados(c, ref, peca, lambda p: _gpio(p) in gpios)


def _sobretensao(c: Circuito, ref: str, pino: Pino, rede: str) -> list[Problema]:
    """O pino recebe, na rede, mais tensão que o ``tensao_max`` dele? (ou não dá para saber)"""
    limite = pino.tensao_max
    if limite is None:
        return [Problema("nao_verificavel",
                         f"a base não diz a tensão máxima de {_rotulo(ref, pino)}",
                         pinos=(_rotulo(ref, pino),), redes=(rede,))]
    acima, sem_dado = [], []
    for outro in c.outros(rede, ref, pino):
        nivel = c.nivel_do_pino(outro)
        if nivel.valor is None:
            sem_dado.append((outro, nivel.porque))
        elif nivel.valor > limite:
            acima.append((outro, nivel.valor))
    if acima:
        quem = ", ".join(f"{o.rotulo} em {v:g} V" for o, v in acima)
        return [Problema(
            "violada", f"{_rotulo(ref, pino)} aguenta até {limite:g} V e está na rede {rede} "
                       f"com {quem}",
            "passe o sinal por um conversor de nível lógico (o lado de maior tensão no HV, o "
            f"de {limite:g} V no LV) ou ligue o pino a uma rede de até {limite:g} V",
            pinos=(_rotulo(ref, pino),) + tuple(o.rotulo for o, _ in acima), redes=(rede,))]
    return [Problema("nao_verificavel",
                     f"não dá para saber se {_rotulo(ref, pino)} (até {limite:g} V) recebe "
                     f"mais que isso na rede {rede}: {porque}",
                     "complete na base a tensão do sinal (nivel_logico da peça ou referencia "
                     "do pino), com a fonte",
                     pinos=(_rotulo(ref, pino), o.rotulo), redes=(rede,))
            for o, porque in sem_dado]


def _so(problemas: list[Problema]) -> tuple[Situacao, tuple[Problema, ...]]:
    """A situação de uma regra a partir dos problemas dela."""
    if any(p.situacao == "violada" for p in problemas):
        return "violada", tuple(problemas)
    if problemas:
        return "nao_verificavel", tuple(problemas)
    return "ok", ()


Verificacao = Callable[[Circuito, str, Componente, Contexto], list[Problema]]


# --- ESP32 DevKitC V4 -------------------------------------------------------------------------
# Os números GPIO de cada regra estão na descrição da própria regra, na base; os testes
# conferem que estes conjuntos batem com o texto de lá.

GPIO_SO_ENTRADA = frozenset({34, 35, 36, 39})
GPIO_FLASH = frozenset(range(6, 12))
GPIO_STRAPPING = frozenset({0, 2, 5, 12, 15})


def esp32_adc2_wifi(c: Circuito, ref: str, peca: Componente, ctx: Contexto) -> list[Problema]:
    """Sinal analógico num pino com função ADC2_* não pode ser lido com o Wi-Fi ativo."""
    problemas = []
    for pino, rede in _ligados(c, ref, peca,
                               lambda p: any(f.startswith("ADC2_") for f in p.funcoes)):
        analogicos = [o for o in c.outros(rede, ref, pino) if o.pino.tipo == "analogico"]
        if not analogicos or ctx.wifi is False:
            continue
        pinos = (_rotulo(ref, pino),) + tuple(o.rotulo for o in analogicos)
        canal = next(f for f in pino.funcoes if f.startswith("ADC2_"))
        if ctx.wifi is None:
            problemas.append(Problema(
                "nao_verificavel",
                f"o sinal analógico de {analogicos[0].rotulo} chega em {_rotulo(ref, pino)} "
                f"({canal}), e a especificação não diz se o Wi-Fi é usado",
                "diga na especificação se o projeto usa Wi-Fi (campo wifi) ou ligue o sinal "
                "num pino com função ADC1_*", pinos=pinos, redes=(rede,)))
        else:
            problemas.append(Problema(
                "violada",
                f"o sinal analógico de {analogicos[0].rotulo} chega em {_rotulo(ref, pino)} "
                f"({canal}); o ADC2 não lê com o Wi-Fi ativo, e o projeto usa Wi-Fi",
                "ligue o sinal num pino com função ADC1_* (por exemplo IO32 a IO39)",
                pinos=pinos, redes=(rede,)))
    return problemas


def esp32_gpio_nao_tolera_5v(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                             ) -> list[Problema]:
    """Nenhum GPIO pode receber mais que o ``tensao_max`` dele (3,3 V), por exemplo 5 V
    direto, sem conversor."""
    problemas = []
    for pino, rede in _ligados(c, ref, peca, lambda p: _gpio(p) is not None):
        problemas += _sobretensao(c, ref, pino, rede)
    return problemas


def esp32_gpio_so_entrada(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                          ) -> list[Problema]:
    """GPIO34, 35, 36 e 39 só leem: numa rede em que ninguém mais gera o sinal (todos os
    outros pinos são ``entrada``), o ESP32 teria de ser a saída."""
    problemas = []
    for pino, rede in _gpios_da_regra(GPIO_SO_ENTRADA, c, ref, peca):
        outros = c.outros(rede, ref, pino)
        if outros and all(o.pino.tipo == "entrada" for o in outros):
            problemas.append(Problema(
                "violada",
                f"{_rotulo(ref, pino)} é só entrada, e na rede {rede} todos os outros pinos "
                f"também são entradas ({', '.join(o.rotulo for o in outros)}): o ESP32 teria "
                "de gerar o sinal",
                "use um GPIO que também é saída, ou ligue aqui um sinal que vem de outra peça",
                pinos=(_rotulo(ref, pino),) + tuple(o.rotulo for o in outros), redes=(rede,)))
    return problemas


def esp32_gpio_flash(c: Circuito, ref: str, peca: Componente, ctx: Contexto) -> list[Problema]:
    """GPIO6 a GPIO11 são da memória Flash do módulo: não se ligam a nada."""
    return [Problema("violada",
                     f"{_rotulo(ref, pino)} é GPIO{_gpio(pino)}, usado pela Flash do módulo, e "
                     f"está ligado à rede {rede}",
                     "use outro GPIO; deixe GPIO6 a GPIO11 sem ligação",
                     pinos=(_rotulo(ref, pino),), redes=(rede,))
            for pino, rede in _gpios_da_regra(GPIO_FLASH, c, ref, peca)]


def esp32_gpio_strapping(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                         ) -> list[Problema]:
    """GPIO0, 2, 5, 12 e 15 definem o modo de boot: um circuito externo pode atrapalhar."""
    return [Problema("violada",
                     f"{_rotulo(ref, pino)} é GPIO{_gpio(pino)}, pino de configuração do boot, "
                     f"e está ligado à rede {rede}: confira que o que está ligado não muda o "
                     "nível dele na inicialização",
                     "prefira outro GPIO, se houver livre",
                     pinos=(_rotulo(ref, pino),), redes=(rede,))
            for pino, rede in _gpios_da_regra(GPIO_STRAPPING, c, ref, peca)]


# --- LCD 1602 com adaptador I2C ---------------------------------------------------------------

def _faixa_de_alimentacao(c: Circuito, ref: str, peca: Componente, pino: Pino, rede: str | None,
                          minimo: float, maximo: float) -> list[Problema]:
    alvo = _rotulo(ref, pino)
    if rede is None:
        return [Problema("violada", f"{alvo} não está ligado: a peça fica sem alimentação",
                         f"ligue {alvo} a uma alimentação de {minimo:g} a {maximo:g} V",
                         pinos=(alvo,))]
    nivel = c.tensao_da_alimentacao(rede, exceto_ref=ref)
    if nivel.valor is None:
        return [Problema("nao_verificavel",
                         f"não dá para saber a tensão que chega em {alvo}: {nivel.porque}",
                         pinos=(alvo,), redes=(rede,))]
    if not minimo <= nivel.valor <= maximo:
        return [Problema("violada",
                         f"{alvo} recebe {nivel.valor:g} V na rede {rede}, e a peça pede de "
                         f"{minimo:g} a {maximo:g} V",
                         f"ligue {alvo} a uma alimentação de {minimo:g} a {maximo:g} V",
                         pinos=(alvo,), redes=(rede,))]
    return []


def lcd_alimentacao_5v(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                       ) -> list[Problema]:
    """O LCD precisa de alimentação dentro de ``alimentacao_min``..``alimentacao_max`` (5 V)."""
    problemas = []
    for pino in (p for p in peca.pinos if p.tipo == "alimentacao"):
        problemas += _faixa_de_alimentacao(c, ref, peca, pino, c.rede(ref, pino),
                                           peca.alimentacao_min, peca.alimentacao_max)
    return problemas


def lcd_i2c_niveis(c: Circuito, ref: str, peca: Componente, ctx: Contexto) -> list[Problema]:
    """As linhas I2C do LCD ligadas direto a um pino que não aguenta a tensão delas.

    A tensão das linhas depende dos pull-ups do adaptador. Se a base não a diz, e a rede tem
    um pino com limite abaixo da alimentação do LCD, não dá para aprovar."""
    problemas = []
    for pino, rede in _ligados(c, ref, peca,
                               lambda p: any(f.startswith("I2C_") for f in p.funcoes)):
        limitados = [o for o in c.outros(rede, ref, pino)
                     if o.pino.tensao_max is not None and o.pino.tipo != "alimentacao"
                     and o.pino.tensao_max < peca.alimentacao_max]
        if not limitados:
            continue
        nivel = c.nivel_do_pino(PinoLigado(ref, peca, pino))
        quem = ", ".join(f"{o.rotulo} (até {o.pino.tensao_max:g} V)" for o in limitados)
        pinos = (_rotulo(ref, pino),) + tuple(o.rotulo for o in limitados)
        if nivel.valor is None:
            problemas.append(Problema(
                "nao_verificavel",
                f"{_rotulo(ref, pino)} está ligado direto a {quem}, e a base não diz a tensão "
                f"dos pull-ups do LCD; com pull-ups em {peca.alimentacao_max:g} V, o outro "
                "pino receberia essa tensão",
                "ligue a linha pelo conversor de nível lógico, ou registre na base a tensão "
                "dos pull-ups do adaptador, com a fonte", pinos=pinos, redes=(rede,)))
        elif any(nivel.valor > o.pino.tensao_max for o in limitados):
            problemas.append(Problema(
                "violada", f"{_rotulo(ref, pino)} trabalha em {nivel.valor:g} V e está ligado "
                           f"direto a {quem}",
                "ligue a linha pelo conversor de nível lógico", pinos=pinos, redes=(rede,)))
    return problemas


# --- Conversor de nível lógico de 4 canais ----------------------------------------------------

def _lados(peca: Componente) -> list[Pino]:
    """Os pinos de alimentação dos lados (HV e LV), os citados como referencia."""
    citados = {p.referencia for p in peca.pinos if p.referencia}
    return [p for p in peca.pinos if p.tipo == "alimentacao" and p.nome in citados]


def _nivel_do_lado(c: Circuito, ref: str, lado: Pino) -> tuple[Nivel, str | None]:
    rede = c.rede(ref, lado)
    if rede is None:
        return Nivel(None, f"{_rotulo(ref, lado)} não está ligado"), None
    return c.tensao_da_alimentacao(rede, exceto_ref=ref), rede


def _canal(pino: Pino) -> int | None:
    for f in pino.funcoes:
        m = re.match(r"Canal (\d+)\b", f)
        if m:
            return int(m.group(1))
    return None


def conversor_duas_alimentacoes(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                                ) -> list[Problema]:
    """HV e LV ligados, cada um numa rede com outra alimentação."""
    problemas = []
    for lado in _lados(peca):
        rede = c.rede(ref, lado)
        alvo = _rotulo(ref, lado)
        if rede is None:
            problemas.append(Problema("violada", f"{alvo} não está ligado",
                                      f"ligue {alvo} à alimentação do seu lado", pinos=(alvo,)))
        elif not any(o.pino.tipo == "alimentacao" for o in c.outros(rede, ref, lado)):
            problemas.append(Problema(
                "violada", f"{alvo} está na rede {rede}, que não tem nenhuma alimentação",
                f"ligue {alvo} à alimentação do seu lado", pinos=(alvo,), redes=(rede,)))
    return problemas


def conversor_terra_comum(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                          ) -> list[Problema]:
    """Os terras do conversor e das peças ligadas aos canais dele estão na mesma rede."""
    terras = [p for p in peca.pinos if p.tipo == "terra"]
    soltos = [p for p in terras if c.rede(ref, p) is None]
    if soltos:
        return [Problema("violada", f"{', '.join(_rotulo(ref, p) for p in soltos)} sem ligação",
                         "ligue todos os GND do conversor ao terra comum",
                         pinos=tuple(_rotulo(ref, p) for p in soltos))]
    redes_terra = {c.rede(ref, p) for p in terras}
    vizinhos = {o.ref for p in peca.pinos if p.referencia and (r := c.rede(ref, p))
                for o in c.outros(r, ref, p)}
    problemas = []
    for viz in sorted(vizinhos):
        outra = c.pecas[viz]
        redes_viz = {c.rede(viz, p) for p in outra.pinos if p.tipo == "terra"} - {None}
        if not redes_viz:
            problemas.append(Problema(
                "violada", f"{viz} ({outra.id}) troca sinais com o conversor e não tem o GND "
                           "ligado", f"ligue o GND de {viz} ao terra do conversor"))
        elif not redes_viz <= redes_terra or len(redes_terra) > 1:
            problemas.append(Problema(
                "violada", f"o terra de {viz} ({sorted(redes_viz)}) não é o mesmo do conversor "
                           f"({sorted(redes_terra)})",
                "ponha os GND do conversor e das peças dos dois lados na mesma rede",
                redes=tuple(sorted(redes_viz | redes_terra))))
    if len(redes_terra) > 1 and not problemas:
        problemas.append(Problema("violada", f"os GND do conversor estão em redes diferentes: "
                                             f"{sorted(redes_terra)}",
                                  "ponha os GND do conversor na mesma rede",
                                  redes=tuple(sorted(redes_terra))))
    return problemas


def conversor_sentido(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                      ) -> list[Problema]:
    """O lado HV tem a tensão maior, e nenhum pino de tensão menor fica num canal HV."""
    lados = {p.nome: p for p in _lados(peca)}
    if set(lados) != {"HV", "LV"}:
        return [Problema("nao_verificavel", f"a base de {peca.id} não marca os lados HV e LV")]
    (nivel_hv, rede_hv), (nivel_lv, rede_lv) = (_nivel_do_lado(c, ref, lados["HV"]),
                                                _nivel_do_lado(c, ref, lados["LV"]))
    problemas = []
    if nivel_hv.valor is None or nivel_lv.valor is None:
        porque = "; ".join(n.porque for n in (nivel_hv, nivel_lv) if n.valor is None)
        problemas.append(Problema("nao_verificavel",
                                  f"não dá para comparar os lados do conversor: {porque}",
                                  redes=tuple(r for r in (rede_hv, rede_lv) if r)))
    elif nivel_hv.valor < nivel_lv.valor:
        problemas.append(Problema(
            "violada", f"o lado HV está em {nivel_hv.valor:g} V e o LV em {nivel_lv.valor:g} V: "
                       "os lados estão invertidos",
            "ligue a alimentação maior no HV e a menor no LV, e troque os canais junto",
            pinos=(_rotulo(ref, lados["HV"]), _rotulo(ref, lados["LV"])),
            redes=(rede_hv, rede_lv)))
    if nivel_hv.valor is not None:
        for pino in (p for p in peca.pinos if p.referencia == "HV"):
            rede = c.rede(ref, pino)
            if rede is None:
                continue
            baixos = [o for o in c.outros(rede, ref, pino) if o.pino.tipo != "alimentacao"
                      and o.pino.tensao_max is not None and o.pino.tensao_max < nivel_hv.valor]
            if baixos:
                problemas.append(Problema(
                    "violada",
                    f"{', '.join(f'{o.rotulo} (até {o.pino.tensao_max:g} V)' for o in baixos)} "
                    f"está no canal {_rotulo(ref, pino)}, do lado HV ({nivel_hv.valor:g} V)",
                    "ligue o sinal de menor tensão no canal LV correspondente",
                    pinos=(_rotulo(ref, pino),) + tuple(o.rotulo for o in baixos),
                    redes=(rede,)))
    return problemas


def conversor_canais(c: Circuito, ref: str, peca: Componente, ctx: Contexto) -> list[Problema]:
    """Canal usado de um lado tem de estar usado do outro (HVn com LVn)."""
    lados: dict[int, dict[str, Pino]] = {}
    for p in peca.pinos:
        n = _canal(p)
        if n is not None and p.referencia:
            lados.setdefault(n, {})[p.referencia] = p
    problemas = []
    for n, pinos in sorted(lados.items()):
        ligados = {lado: c.rede(ref, p) for lado, p in pinos.items()}
        usados = [lado for lado, r in ligados.items() if r is not None]
        if len(usados) == 1:
            falta = next(lado for lado in pinos if lado not in usados)
            p_usado, p_falta = pinos[usados[0]], pinos[falta]
            problemas.append(Problema(
                "violada", f"o canal {n} está ligado só do lado {usados[0]} "
                           f"({_rotulo(ref, p_usado)}); {_rotulo(ref, p_falta)} está solto",
                f"ligue {_rotulo(ref, p_falta)} ao sinal correspondente do outro lado, ou não "
                f"use o canal {n}", pinos=(_rotulo(ref, p_usado), _rotulo(ref, p_falta)),
                redes=(ligados[usados[0]],)))
    return problemas


def conversor_tensoes_compativeis(c: Circuito, ref: str, peca: Componente, ctx: Contexto
                                  ) -> list[Problema]:
    """As tensões de HV e LV dentro de ``alimentacao_min``..``alimentacao_max`` da peça."""
    problemas = []
    for lado in _lados(peca):
        problemas += _faixa_de_alimentacao(c, ref, peca, lado, c.rede(ref, lado),
                                           peca.alimentacao_min, peca.alimentacao_max)
    return problemas


# --- A tabela das regras ----------------------------------------------------------------------
# Cada regra da base: uma função que a verifica, ou o motivo de não ser verificável pelas
# ligações. Só leitura (MappingProxyType): não existe caminho para mudar ou tirar uma regra
# em tempo de execução.

ESP32, LCD, CONVERSOR = ("esp32-devkitc-v4", "display-lcd-1602-i2c",
                         "conversor-nivel-logico-4-canais")

REGRAS: Mapping[tuple[str, str], Verificacao | str] = MappingProxyType({
    (ESP32, "adc2-wifi"): esp32_adc2_wifi,
    (ESP32, "gpio-not-5v-tolerant"): esp32_gpio_nao_tolera_5v,
    (ESP32, "gpio-input-only"): esp32_gpio_so_entrada,
    (ESP32, "gpio-flash-reserved"): esp32_gpio_flash,
    (ESP32, "gpio-strapping"): esp32_gpio_strapping,
    (LCD, "lcd-supply-voltage"): lcd_alimentacao_5v,
    (LCD, "i2c-voltage-compatibility"): lcd_i2c_niveis,
    (LCD, "i2c-address"): "o endereço depende do expansor e dos jumpers A0 a A2: é configuração "
                          "do firmware, não ligação",
    (LCD, "lcd-display-format"): "16 colunas por 2 linhas é configuração do firmware",
    (LCD, "i2c-pullups"): "os pull-ups ficam no adaptador; conferir se existem é olhar a peça, "
                          "não as ligações",
    (CONVERSOR, "level-shifter-dual-supply"): conversor_duas_alimentacoes,
    (CONVERSOR, "level-shifter-common-ground"): conversor_terra_comum,
    (CONVERSOR, "level-shifter-voltage-direction"): conversor_sentido,
    (CONVERSOR, "level-shifter-supply-order"): "a ordem em que as alimentações sobem é operação "
                                               "da placa, não ligação",
    (CONVERSOR, "level-shifter-channel-mapping"): conversor_canais,
    (CONVERSOR, "level-shifter-voltage-compatibility"): conversor_tensoes_compativeis,
})


def verificar(estado: dict, base: dict[str, Componente] | None = None,
              wifi: bool | None = None) -> Relatorio:
    """Roda todas as regras de todas as peças do circuito. Levanta ``ErroCircuito`` se o
    estado não for um circuito válido (nada é verificado pela metade)."""
    base = carregar_todos() if base is None else base
    circuito = Circuito.do_estado(estado, base)
    ctx = Contexto(wifi=wifi)
    resultados = []
    for ref, peca in circuito.pecas.items():
        for regra in peca.regras:
            item = REGRAS.get((peca.id, regra.id))
            comum = dict(regra=regra.id, componente=peca.id, ref=ref,
                         severidade=regra.severidade, descricao=regra.descricao)
            if item is None:
                resultados.append(ResultadoRegra(**comum, situacao="nao_verificavel", problemas=(
                    Problema("nao_verificavel",
                             "a regra está na base, mas o motor ainda não tem uma verificação "
                             "para ela", "escreva a função da regra em src/regras.py"),)))
            elif isinstance(item, str):
                resultados.append(ResultadoRegra(**comum, situacao="manual",
                                                 motivo_manual=item))
            else:
                situacao, problemas = _so(item(circuito, ref, peca, ctx))
                resultados.append(ResultadoRegra(**comum, situacao=situacao,
                                                 problemas=problemas))
    return Relatorio(tuple(resultados), wifi)


# --- Terminal ---------------------------------------------------------------------------------

def main(argumentos: list[str], escrever: Callable[[str], None] = print) -> int:
    """0: aprovado; 1: reprovado; 2: entrada inválida."""
    from .custos import SAIDA as SAIDA_CUSTOS
    from .custos import Custos
    from .especificacao import ErroEspecificacao, ler_especificacao
    parser = argparse.ArgumentParser(
        prog="python -m src.regras",
        description="Confere um circuito (estado do agente, em JSON) contra as regras da base.")
    parser.add_argument("estado", type=Path, help="JSON com 'selecoes' e 'ligacoes' "
                        "(o estado.json do agente)")
    parser.add_argument("--spec", type=Path, help="especificação da placa (diz se usa Wi-Fi e "
                        "o projeto em que o custo é registrado)")
    parser.add_argument("--json", action="store_true", help="mostra o relatório em JSON")
    parser.add_argument("--custos", type=Path, default=SAIDA_CUSTOS,
                        help=f"pasta do registro de custos (padrão: {SAIDA_CUSTOS})")
    opcoes = parser.parse_args(argumentos)

    try:
        base = carregar_todos()
        spec = ler_especificacao(opcoes.spec, base) if opcoes.spec else None
        estado = json.loads(opcoes.estado.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, ErroEspecificacao) as e:
        escrever(f"Entrada inválida: {e}")
        return 2
    custos = Custos(spec.projeto.id if spec else None)
    inicio = time.monotonic()
    try:
        relatorio = verificar(estado, base, wifi=spec.wifi.valor if spec and spec.wifi else None)
    except ErroCircuito as e:
        escrever(str(e))
        return 2
    c = relatorio.contagem()
    custos.operacao("motor_de_regras", "verificar", time.monotonic() - inicio,
                    f"{'aprovado' if relatorio.aprovado else 'reprovado'}: {c['violada']} "
                    f"violada(s), {c['nao_verificavel']} não verificável(is), {opcoes.estado}")
    arquivo = custos.gravar(opcoes.custos)
    escrever(json.dumps(relatorio.para_dict(), ensure_ascii=False, indent=2)
             if opcoes.json else relatorio.texto())
    escrever(f"(registrado em {arquivo})")
    return 0 if relatorio.aprovado else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
