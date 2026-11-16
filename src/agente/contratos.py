"""Contratos das ferramentas: a única parte que o modelo de IA enxerga (Marco 4, Parte 3).

Vieram do ``agente_minimo.py`` do protótipo (seção 2, "CONTRATOS") e agora descrevem as
seis ferramentas reais de ``ferramentas.py``. Cada contrato tem nome, descrição e os
parâmetros em JSON Schema, num formato neutro: o adaptador de cada provedor
(``provedores/``) converte para o formato dele. Os testes conferem que cada contrato bate
com os argumentos que a ferramenta aceita.

As descrições são parte do prompt: mudar o texto de um contrato é mudar a versão do prompt
(``laco.VERSAO_DO_PROMPT``), que o eval registra.
"""
from .ferramentas import FORMATOS_DE_FONTE

_TEXTO = {"type": "string", "minLength": 1}

CONTRATOS: list[dict] = [
    {
        "name": "buscar_componente",
        "description": (
            "Procura componentes na base pelo id e pela descrição. Não diferencia maiúsculas, "
            "acentos, espaços, '_' e '-'. Devolve todos os que baterem, com id, descrição e "
            "status. Se nada for encontrado, tente outro termo; se a peça não existir na "
            "base, registre uma pendência."),
        "parameters": {
            "type": "object",
            "properties": {"termo": {**_TEXTO, "description": "palavra ou trecho, ex.: 'umidade'"}},
            "required": ["termo"],
        },
    },
    {
        "name": "ler_dados_componente",
        "description": (
            "Devolve todos os dados de um componente da base (pinos, tensões, regras, fontes), "
            "exatamente como estão cadastrados. Use antes de decidir qualquer coisa sobre a peça."),
        "parameters": {
            "type": "object",
            "properties": {"id": {**_TEXTO, "description": "id exato, como buscar_componente devolve"}},
            "required": ["id"],
        },
    },
    {
        "name": "selecionar_componente",
        "description": (
            "Põe um componente da base no projeto com uma referência única (ex.: U1). Só aceita "
            "ids que existem na base. Se o id não existir, nada é selecionado: registre a "
            "necessidade com registrar_pendencia, nunca invente um id."),
        "parameters": {
            "type": "object",
            "properties": {
                "id": {**_TEXTO, "description": "id exato do componente na base"},
                "ref": {"type": "string", "pattern": "^[A-Za-z][A-Za-z0-9_]*$",
                        "description": "referência única no projeto, ex.: U1, U2"},
            },
            "required": ["id", "ref"],
        },
    },
    {
        "name": "conectar",
        "description": (
            "Liga um pino de uma peça já selecionada a uma rede (ex.: GND, +5V, SDA_3V3). O "
            "pino é o número ou o nome exato da base (veja ler_dados_componente). Um nome "
            "usado em vários pinos da peça (ex.: GND) liga todos eles. Cada pino fica em uma "
            "rede só."),
        "parameters": {
            "type": "object",
            "properties": {
                "ref": {**_TEXTO, "description": "referência dada em selecionar_componente"},
                "pino": {"anyOf": [{"type": "integer", "minimum": 1}, _TEXTO],
                         "description": "número ou nome do pino, como na base"},
                "rede": {"type": "string", "pattern": "^[A-Za-z0-9_+\\-./]+$",
                         "description": "nome da rede, sem espaços"},
            },
            "required": ["ref", "pino", "rede"],
        },
    },
    {
        "name": "registrar_decisao",
        "description": (
            "Registra uma decisão de engenharia com o motivo e a fonte. A fonte é obrigatória "
            "e precisa apontar para algo que existe, num destes formatos: "
            + "; ".join(FORMATOS_DE_FONTE) + ". "
            "Texto livre (como 'datasheet') é recusado. Se o dado não está na base, registre "
            "uma pendência em vez de decidir."),
        "parameters": {
            "type": "object",
            "properties": {
                "decisao": _TEXTO,
                "motivo": _TEXTO,
                "fonte": {"type": "array", "items": _TEXTO, "minItems": 1,
                          "description": "uma ou mais fontes nos formatos aceitos"},
            },
            "required": ["decisao", "motivo", "fonte"],
        },
    },
    {
        "name": "registrar_pendencia",
        "description": (
            "Registra algo que o projeto precisa e que a base não tem (uma peça ausente, um "
            "dado técnico que falta), com detalhe suficiente para uma pessoa resolver depois."),
        "parameters": {
            "type": "object",
            "properties": {
                "necessidade": {**_TEXTO, "description": "o que falta, ex.: 'conversor de nível 3,3 V / 5 V'"},
                "motivo": {**_TEXTO, "description": "por que o projeto precisa disso"},
            },
            "required": ["necessidade", "motivo"],
        },
    },
]


# Só no laço de correção (Marco 5, Parte 4; ADR-018).
CONTRATO_DESCONECTAR = {
    "name": "desconectar",
    "description": (
        "Tira um pino de uma peça da rede em que ele está, para corrigir uma ligação que o "
        "relatório de problemas apontou. O pino é o número ou o nome exato da base; um nome "
        "usado em vários pinos (ex.: GND) tira todos eles. Depois, ligue o pino certo com "
        "conectar."),
    "parameters": {
        "type": "object",
        "properties": {
            "ref": {**_TEXTO, "description": "referência dada em selecionar_componente"},
            "pino": {"anyOf": [{"type": "integer", "minimum": 1}, _TEXTO],
                     "description": "número ou nome do pino, como na base"},
        },
        "required": ["ref", "pino"],
    },
}
CONTRATOS_DE_CORRECAO = [*CONTRATOS, CONTRATO_DESCONECTAR]
