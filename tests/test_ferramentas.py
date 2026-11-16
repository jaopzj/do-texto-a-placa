"""Testes das ferramentas do agente (Marco 4, Parte 3).

Nenhum teste chama o modelo de IA: cada ferramenta é chamada direto e o resultado é
conferido, como pede o CLAUDE.md. A base é a real (``carregar_todos()``); o caso "peça
ausente" usa uma cópia da base sem o conversor de nível, como no teste 2 do protótipo.
Estes testes só precisam do Pydantic e do PyYAML, então também rodam no GitHub Actions.
"""
import copy

import pytest
import yaml

from src.agente.ferramentas import FERRAMENTAS, Ferramentas, normalizar
from src.componentes.carregar import PASTA, carregar_todos
from src.especificacao import ler_especificacao

ESP32 = "esp32-devkitc-v4"
LCD = "display-lcd-1602-i2c"
SENSOR = "sensor-umidade-capacitivo"
CONVERSOR = "conversor-nivel-logico-4-canais"
SPEC = PASTA.parent / "placas" / "monitor-umidade" / "spec.yaml"


@pytest.fixture(scope="module")
def base():
    return carregar_todos()


@pytest.fixture
def f(base):
    return Ferramentas(base)


@pytest.fixture
def montado(f):
    """Projeto com o ESP32 (U1) e o LCD (U2) selecionados e uma ligação feita."""
    assert f.selecionar_componente(ESP32, "U1")["ok"]
    assert f.selecionar_componente(LCD, "U2")["ok"]
    assert f.conectar("U2", "SDA", "SDA_5V")["ok"]
    return f


def _recusa(resultado: dict, codigo: str) -> dict:
    assert resultado["ok"] is False, resultado
    assert resultado["erro"] == codigo, resultado
    assert resultado["mensagem"] and resultado["proximo_passo"], resultado
    return resultado


def _sem_mudanca(f: Ferramentas, chamada):
    """Confere que a chamada é recusada e não muda o estado do projeto."""
    antes = copy.deepcopy(f.estado())
    resultado = chamada()
    assert resultado["ok"] is False, resultado
    assert f.estado() == antes
    return resultado


# --- buscar_componente ---------------------------------------------------------------------

@pytest.mark.parametrize("termo, esperado", [
    ("umidade", SENSOR),
    ("sensor umidade", SENSOR),                 # o termo que falhou no protótipo
    ("SENSOR_UMIDADE_CAPACITIVO", SENSOR),       # o id do protótipo, em maiúsculas
    ("Sensor de Umidade", SENSOR),
    ("sensor-umidade-capacitivo", SENSOR),
    ("  umidade  ", SENSOR),
    ("umid", SENSOR),                           # começo de palavra
    ("ESP32", ESP32),
    ("esp 32", ESP32),
    ("esp32devkit", ESP32),
    ("ESP32_DEVKITC_V4", ESP32),
    ("LCD", LCD),
    ("display", LCD),
    ("conversor", CONVERSOR),
    ("nível lógico", CONVERSOR),                # acentos
    ("NIVEL_LOGICO", CONVERSOR),
    ("Nivel  Logico", CONVERSOR),
])
def test_busca_ignora_maiusculas_acentos_espacos_e_sublinhados(f, termo, esperado):
    r = f.buscar_componente(termo)
    assert r["ok"], r
    assert [c["id"] for c in r["encontrados"]] == [esperado]


def test_busca_devolve_id_descricao_e_status(f, base):
    [achado] = f.buscar_componente("umidade")["encontrados"]
    assert achado == {"id": SENSOR, "descricao": base[SENSOR].descricao,
                      "status": base[SENSOR].status}


@pytest.mark.parametrize("termo", ["xyz", "resistor", "ado", "sensor de temperatura"])
def test_busca_sem_resultado_manda_registrar_pendencia(f, termo):
    r = _recusa(f.buscar_componente(termo), "nenhum_componente")
    assert "registrar_pendencia" in r["proximo_passo"]


def test_busca_nao_casa_pedaco_do_meio_de_uma_palavra(f):
    # "ado" está dentro de "adaptar" (descrição do conversor), mas não é começo de palavra.
    _recusa(f.buscar_componente("ado"), "nenhum_componente")


def test_busca_exige_todas_as_palavras(f):
    # "sensor" existe, "temperatura" não: nada é devolvido.
    _recusa(f.buscar_componente("sensor temperatura"), "nenhum_componente")


def test_busca_com_varios_resultados_devolve_todos_em_ordem(f):
    r = f.buscar_componente("de")              # aparece em várias descrições
    ids = [c["id"] for c in r["encontrados"]]
    assert len(ids) > 1 and ids == sorted(ids)


@pytest.mark.parametrize("termo", ["", "   ", "___", "- _ -", 42, None, ["umidade"]])
def test_busca_com_termo_invalido(f, termo):
    _recusa(f.buscar_componente(termo), "entrada_invalida")


def test_busca_e_igual_para_termos_equivalentes(f):
    termos = ["Nível Lógico", "nivel_logico", "NIVEL LOGICO", "nível-lógico"]
    assert len({str(f.buscar_componente(t)) for t in termos}) == 1


def test_normalizar():
    assert normalizar("Módulo LÓGICO Ação") == "modulo logico acao"


def test_busca_nao_muda_o_estado(montado):
    antes = copy.deepcopy(montado.estado())
    montado.buscar_componente("umidade")
    montado.buscar_componente("xyz")
    assert montado.estado() == antes


# --- ler_dados_componente --------------------------------------------------------------------

@pytest.mark.parametrize("arquivo", sorted(PASTA.glob("*.yaml")), ids=lambda a: a.stem)
def test_leitura_devolve_exatamente_o_que_esta_no_yaml(f, arquivo):
    """Nada é acrescentado nem tirado: o dicionário é o próprio YAML."""
    dados = yaml.safe_load(arquivo.read_text(encoding="utf-8"))
    r = f.ler_dados_componente(dados["id"])
    assert r["ok"], r
    assert r["componente"] == dados


def test_leitura_nao_preenche_campo_ausente(f):
    comp = f.ler_dados_componente(SENSOR)["componente"]
    assert "nivel_logico" not in comp           # o YAML do sensor não tem esse campo
    assert "regras" not in comp and "conectores" not in comp
    assert all("funcoes" not in p for p in comp["pinos"])
    # Só o AOUT tem tensao_max (0 a 3,0 V, do datasheet); GND e VCC continuam sem.
    assert {p["nome"]: p.get("tensao_max") for p in comp["pinos"]} == {
        "GND": None, "VCC": None, "AOUT": 3.0}
    assert all("tensao_max" not in p for p in comp["pinos"] if p["nome"] != "AOUT")


def test_leitura_devolve_copia(f, base):
    comp = f.ler_dados_componente(SENSOR)["componente"]
    comp["pinos"].clear()
    comp["descricao"] = "alterado"
    assert f.ler_dados_componente(SENSOR)["componente"]["pinos"]
    assert base[SENSOR].descricao != "alterado"


@pytest.mark.parametrize("id_, sugestao", [
    ("ESP32-DEVKITC-V4", ESP32),               # o id é exato: maiúsculas não valem
    ("sensor_umidade_capacitivo", SENSOR),
    ("LCD1602_I2C", None),                     # id do protótipo, que não existe
    ("nao-existe", None),
])
def test_leitura_de_id_inexistente(f, id_, sugestao):
    r = _recusa(f.ler_dados_componente(id_), "componente_inexistente")
    assert "registrar_pendencia" in r["proximo_passo"]
    if sugestao:
        assert sugestao in r["sugestoes"]


@pytest.mark.parametrize("id_", ["", 3, None])
def test_leitura_com_id_invalido(f, id_):
    _recusa(f.ler_dados_componente(id_), "entrada_invalida")


# --- selecionar_componente -------------------------------------------------------------------

def test_selecao_valida(f, base):
    r = f.selecionar_componente(SENSOR, "U3")
    assert r["ok"] and r["ref"] == "U3" and r["componente"] == SENSOR
    assert r["pinos"] == [{"numero": p.numero, "nome": p.nome, "tipo": p.tipo}
                          for p in base[SENSOR].pinos]
    assert "aviso" not in r                    # o sensor está revisado
    assert f.estado()["selecoes"] == {"U3": SENSOR}


def test_selecao_de_componente_em_rascunho_avisa(f, base):
    assert base[ESP32].status == "rascunho"
    r = f.selecionar_componente(ESP32, "U1")
    assert r["ok"] and "rascunho" in r["aviso"]


def test_selecao_de_id_inexistente_e_recusada_e_contada(f):
    r = _sem_mudanca(f, lambda: f.selecionar_componente("nao-existe", "J9"))  # exemplo do guia
    assert r["erro"] == "componente_inexistente"
    assert "registrar_pendencia" in r["proximo_passo"]
    assert "J9" not in f.selecoes
    assert f.tentativas_inexistentes == ["nao-existe"]


def test_cada_tentativa_inexistente_e_contada(f):
    f.selecionar_componente("CONVERSOR_NIVEL_I2C", "U4")
    f.selecionar_componente("CONVERSOR_NIVEL_I2C", "U4")
    assert f.tentativas_inexistentes == ["CONVERSOR_NIVEL_I2C"] * 2
    assert f.estado()["selecoes"] == {}


def test_selecao_exige_o_id_exato(f):
    _recusa(f.selecionar_componente("ESP32-DEVKITC-V4", "U1"), "componente_inexistente")


@pytest.mark.parametrize("ref", ["U1", "u1"])
def test_referencia_repetida_e_recusada(montado, ref):
    r = _sem_mudanca(montado, lambda: montado.selecionar_componente(SENSOR, ref))
    assert r["erro"] == "referencia_repetida"
    assert r["selecoes"] == {"U1": ESP32, "U2": LCD}


def test_mesmo_componente_com_duas_referencias(f):
    assert f.selecionar_componente(SENSOR, "S1")["ok"]
    assert f.selecionar_componente(SENSOR, "S2")["ok"]
    assert f.estado()["selecoes"] == {"S1": SENSOR, "S2": SENSOR}


@pytest.mark.parametrize("ref", ["", " ", "1U", "U 1", "U-1", "U1!", 1, None])
def test_referencia_fora_do_formato_e_recusada(f, ref):
    r = _sem_mudanca(f, lambda: f.selecionar_componente(SENSOR, ref))
    assert r["erro"] == "entrada_invalida"


def test_selecao_sem_conversor_na_base(base):
    """Teste 2 do protótipo: sem o conversor, nada o coloca no projeto."""
    sem_conversor = {k: v for k, v in base.items() if k != CONVERSOR}
    f = Ferramentas(sem_conversor)
    _recusa(f.buscar_componente("conversor"), "nenhum_componente")
    _recusa(f.ler_dados_componente(CONVERSOR), "componente_inexistente")
    _recusa(f.selecionar_componente(CONVERSOR, "U4"), "componente_inexistente")
    assert f.selecoes == {} and f.tentativas_inexistentes == [CONVERSOR]
    r = f.registrar_pendencia("conversor de nível lógico bidirecional 3,3 V / 5 V",
                              "o LCD mantém SDA e SCL em 5 V e a base não tem conversor")
    assert r["ok"] and f.estado()["pendencias"][0]["necessidade"].startswith("conversor")


# --- conectar -----------------------------------------------------------------------------

def test_conexao_por_nome(montado):
    r = montado.conectar("U1", "IO21", "SDA_3V3")
    assert r["ok"] and r["pinos"] == [{"numero": 25, "nome": "IO21"}]
    assert r["ja_existia"] is False and r["pinos_na_rede"] == 1
    assert {"ref": "U1", "pino": 25, "nome": "IO21", "rede": "SDA_3V3"} in \
        montado.estado()["ligacoes"]


def test_conexao_por_numero(montado):
    r = montado.conectar("U1", 19, "+5V")
    assert r["ok"] and r["pinos"] == [{"numero": 19, "nome": "5V"}]


def test_nome_repetido_liga_todos_os_pinos_com_esse_nome(montado, base):
    gnds = [p.numero for p in base[ESP32].pinos if p.nome == "GND"]
    assert len(gnds) == 3
    r = montado.conectar("U1", "GND", "GND")
    assert r["ok"] and [p["numero"] for p in r["pinos"]] == gnds
    assert sorted(montado.estado()["redes"]["GND"]) == sorted(f"U1:{n}" for n in gnds)


def test_rede_junta_pinos_de_pecas_diferentes(montado):
    montado.conectar("U1", 19, "+5V")
    r = montado.conectar("U2", "VCC", "+5V")
    assert r["pinos_na_rede"] == 2
    assert montado.estado()["redes"]["+5V"] == ["U1:19", "U2:2"]


def test_conectar_de_novo_na_mesma_rede_nao_duplica(montado):
    antes = copy.deepcopy(montado.estado())
    r = montado.conectar("U2", "SDA", "SDA_5V")
    assert r["ok"] and r["ja_existia"] is True
    assert montado.estado() == antes


def test_conexao_sem_selecao_previa(montado):
    r = _sem_mudanca(montado, lambda: montado.conectar("U3", "AOUT", "SENSOR"))
    assert r["erro"] == "peca_nao_selecionada"
    assert "selecionar_componente" in r["proximo_passo"]
    assert r["selecoes"] == {"U1": ESP32, "U2": LCD}


def test_conexao_com_id_no_lugar_da_referencia(montado):
    _recusa(montado.conectar(ESP32, "IO21", "SDA_3V3"), "peca_nao_selecionada")


@pytest.mark.parametrize("pino", ["IO99", "GPIO21", "io21", "SDA ", 39, 99, "19"])
def test_pino_inexistente(montado, pino):
    r = _sem_mudanca(montado, lambda: montado.conectar("U1", pino, "X"))
    assert r["erro"] == "pino_inexistente"
    assert "25:IO21" in r["pinos"]             # a lista de pinos válidos volta ao agente


def test_pino_de_outra_peca_e_recusado(montado):
    # AOUT é do sensor, não do LCD.
    _sem_mudanca(montado, lambda: montado.conectar("U2", "AOUT", "SENSOR"))


def test_pino_ja_ligado_a_outra_rede(montado):
    r = _sem_mudanca(montado, lambda: montado.conectar("U2", "SDA", "SCL_5V"))
    assert r["erro"] == "pino_ja_ligado"
    assert r["ligados"] == {"3:SDA": "SDA_5V"}


def test_nome_repetido_com_um_pino_ocupado_nao_liga_nenhum(montado, base):
    gnd = next(p.numero for p in base[ESP32].pinos if p.nome == "GND")
    assert montado.conectar("U1", gnd, "OUTRA")["ok"]
    r = _sem_mudanca(montado, lambda: montado.conectar("U1", "GND", "GND"))
    assert r["erro"] == "pino_ja_ligado"
    assert "GND" not in montado.estado()["redes"]


def test_pino_nao_usado_e_recusado(base):
    comp = base[SENSOR]
    pinos = [p.model_copy(update={"tipo": "nao_usado"}) if p.nome == "AOUT" else p
             for p in comp.pinos]
    f = Ferramentas({SENSOR: comp.model_copy(update={"pinos": pinos})})
    f.selecionar_componente(SENSOR, "U3")
    r = _sem_mudanca(f, lambda: f.conectar("U3", "AOUT", "SENSOR"))
    assert r["erro"] == "pino_nao_usavel"


@pytest.mark.parametrize("rede", ["", "SDA 5V", "rede com espaço", 5, None])
def test_rede_invalida(montado, rede):
    r = _sem_mudanca(montado, lambda: montado.conectar("U1", "IO21", rede))
    assert r["erro"] == "entrada_invalida"


@pytest.mark.parametrize("pino", [0, -1, True, 2.0, None, ""])
def test_pino_com_tipo_invalido(montado, pino):
    r = _sem_mudanca(montado, lambda: montado.conectar("U1", pino, "X"))
    assert r["erro"] == "entrada_invalida"


# --- registrar_decisao --------------------------------------------------------------------

@pytest.mark.parametrize("fonte", [
    f"componente:{LCD}",
    f"componente:{ESP32}/regra:adc2-wifi",
    f"componente:{ESP32}/pino:IO34",
    f"componente:{ESP32}/pino:5",
    [f"componente:{LCD}/regra:i2c-voltage-compatibility",
     f"componente:{ESP32}/regra:gpio-not-5v-tolerant"],
])
def test_decisao_com_fonte_da_base(f, fonte):
    r = f.registrar_decisao("Ligar AOUT do sensor ao GPIO34", "GPIO34 é ADC1", fonte)
    assert r == {"ok": True, "total_decisoes": 1}
    guardada = f.estado()["decisoes"][0]
    assert guardada["fontes"] == ((fonte,) if isinstance(fonte, str) else tuple(fonte))


def test_decisao_com_fonte_na_especificacao(base):
    f = Ferramentas(base, ler_especificacao(SPEC, base))
    assert f.registrar_decisao("Usar o conversor", "pedido na especificação",
                               "especificacao:modulos.3")["ok"]
    r = _sem_mudanca(f, lambda: f.registrar_decisao("x", "y", "especificacao:modulos.9"))
    assert r["erro"] == "fonte_invalida"


def test_fonte_na_especificacao_sem_especificacao_carregada(f):
    _recusa(f.registrar_decisao("x", "y", "especificacao:modulos.3"), "fonte_invalida")


@pytest.mark.parametrize("fonte", [
    "memória do modelo",
    "datasheet do ESP32",
    "componente:nao-existe",
    "componente:CONVERSOR_NIVEL_I2C",
    f"componente:{ESP32}/regra:regra-inventada",
    f"componente:{ESP32}/pino:GPIO34",          # o nome na base é IO34
    f"componente:{ESP32}/pino:99",
    f"componente:{ESP32}/tensao:3.3",
    [f"componente:{LCD}", "intuição"],           # uma fonte ruim recusa a decisão toda
])
def test_decisao_com_fonte_nao_verificavel(montado, fonte):
    r = _sem_mudanca(montado, lambda: montado.registrar_decisao("Decisão", "Motivo", fonte))
    assert r["erro"] == "fonte_invalida"
    assert r["formatos"] and r["problemas"]
    assert "pendência" in r["proximo_passo"]


@pytest.mark.parametrize("argumentos", [
    {"decisao": "x", "motivo": "y", "fonte": ""},
    {"decisao": "x", "motivo": "y", "fonte": []},
    {"decisao": "x", "motivo": "y", "fonte": None},
    {"decisao": "x", "motivo": "", "fonte": f"componente:{LCD}"},
    {"decisao": "x", "motivo": "   ", "fonte": f"componente:{LCD}"},
    {"decisao": "", "motivo": "y", "fonte": f"componente:{LCD}"},
])
def test_decisao_sem_motivo_ou_sem_fonte(montado, argumentos):
    r = _sem_mudanca(montado, lambda: montado.registrar_decisao(**argumentos))
    assert r["erro"] == "entrada_invalida"


def test_decisao_sem_fonte_pela_chamada_do_modelo(f):
    r = f.executar_ferramenta("registrar_decisao", {"decisao": "x", "motivo": "y"})
    _recusa(r, "entrada_invalida")
    assert any("fonte" in p for p in r["problemas"])
    assert f.decisoes == []


def test_fontes_repetidas_sao_guardadas_uma_vez(f):
    fonte = f"componente:{LCD}"
    f.registrar_decisao("x", "y", [fonte, fonte])
    assert f.estado()["decisoes"][0]["fontes"] == (fonte,)


# --- registrar_pendencia --------------------------------------------------------------------

def test_pendencia_registrada(f):
    r = f.registrar_pendencia("Conversor de nível lógico 3,3 V / 5 V",
                              "a base não tem conversor de nível")
    assert r == {"ok": True, "ja_existia": False, "total_pendencias": 1}
    assert f.estado()["pendencias"] == [{
        "necessidade": "Conversor de nível lógico 3,3 V / 5 V",
        "motivo": "a base não tem conversor de nível"}]


def test_pendencia_repetida_nao_duplica(f):
    f.registrar_pendencia("Conversor de nível lógico", "falta na base")
    r = f.registrar_pendencia("  conversor de NIVEL logico ", "outro motivo")
    assert r == {"ok": True, "ja_existia": True, "total_pendencias": 1}
    assert len(f.pendencias) == 1


@pytest.mark.parametrize("argumentos", [
    {"necessidade": "", "motivo": "y"},
    {"necessidade": "x", "motivo": ""},
    {"necessidade": "   ", "motivo": "y"},
    {"necessidade": "x"},
    {"necessidade": 1, "motivo": "y"},
])
def test_pendencia_incompleta(f, argumentos):
    r = _sem_mudanca(f, lambda: f.executar_ferramenta("registrar_pendencia", argumentos))
    assert r["erro"] == "entrada_invalida"


# --- executar_ferramenta (o pedido como o modelo envia) --------------------------------------

def test_todas_as_ferramentas_pelo_nome(f):
    pedidos = [
        ("buscar_componente", {"termo": "umidade"}),
        ("ler_dados_componente", {"id": SENSOR}),
        ("selecionar_componente", {"id": SENSOR, "ref": "U3"}),
        ("conectar", {"ref": "U3", "pino": "AOUT", "rede": "SENSOR"}),
        ("registrar_decisao", {"decisao": "x", "motivo": "y",
                               "fonte": f"componente:{SENSOR}/pino:AOUT"}),
        ("registrar_pendencia", {"necessidade": "x", "motivo": "y"}),
    ]
    assert [n for n, _ in pedidos] == list(FERRAMENTAS)
    for nome, entrada in pedidos:
        assert f.executar_ferramenta(nome, entrada)["ok"], nome


def test_ferramenta_inexistente(f):
    r = _sem_mudanca(f, lambda: f.executar_ferramenta("criar_componente", {"id": "x"}))
    assert r["erro"] == "ferramenta_inexistente" and r["ferramentas"] == list(FERRAMENTAS)


@pytest.mark.parametrize("entrada", [None, "umidade", ["umidade"]])
def test_argumentos_que_nao_sao_um_mapa(f, entrada):
    _recusa(f.executar_ferramenta("buscar_componente", entrada), "entrada_invalida")


def test_argumento_desconhecido(f):
    # O protótipo usava "nome" em ler_dados_componente; o contrato agora é "id".
    r = f.executar_ferramenta("ler_dados_componente", {"nome": SENSOR})
    _recusa(r, "entrada_invalida")


def test_argumento_a_mais_e_recusado(f):
    r = _sem_mudanca(f, lambda: f.executar_ferramenta(
        "selecionar_componente", {"id": SENSOR, "ref": "U3", "quantidade": 2}))
    assert r["erro"] == "entrada_invalida"


# --- O estado no fim: a placa de referência montada pelas ferramentas ------------------------

def test_placa_de_referencia_montada_pelas_ferramentas(f):
    """As ligações do pecas.md, feitas pelas ferramentas, com os nomes de pino da base."""
    for ref, id_ in [("U1", ESP32), ("U2", LCD), ("U3", SENSOR), ("U4", CONVERSOR)]:
        assert f.selecionar_componente(id_, ref)["ok"]
    ligacoes = [
        ("U1", "5V", "+5V"), ("U2", "VCC", "+5V"), ("U4", "HV", "+5V"),
        ("U1", "3V3", "+3V3"), ("U3", "VCC", "+3V3"), ("U4", "LV", "+3V3"),
        ("U1", "GND", "GND"), ("U2", "GND", "GND"), ("U3", "GND", "GND"), ("U4", "GND", "GND"),
        ("U3", "AOUT", "SENSOR"), ("U1", "IO34", "SENSOR"),
        ("U1", "IO21", "SDA_3V3"), ("U4", "LV1", "SDA_3V3"),
        ("U1", "IO22", "SCL_3V3"), ("U4", "LV2", "SCL_3V3"),
        ("U4", "HV1", "SDA_5V"), ("U2", "SDA", "SDA_5V"),
        ("U4", "HV2", "SCL_5V"), ("U2", "SCL", "SCL_5V"),
    ]
    for ref, pino, rede in ligacoes:
        assert f.conectar(ref, pino, rede)["ok"], (ref, pino, rede)
    redes = f.estado()["redes"]
    assert sorted(redes) == ["+3V3", "+5V", "GND", "SCL_3V3", "SCL_5V", "SDA_3V3", "SDA_5V",
                             "SENSOR"]
    assert len(redes["GND"]) == 3 + 1 + 1 + 2   # três GND no ESP32, dois no conversor
    assert len(f.ligacoes) == 23                 # 8 + 4 + 3 + 8 pinos ligados (pecas.md)
