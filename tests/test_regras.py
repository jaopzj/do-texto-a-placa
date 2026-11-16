"""Testes do motor de regras (Marco 5, Parte 3; ADR-017).

Cada regra da base tem pelo menos um circuito que a cumpre e um que a viola (ou, quando o
dado falta, que a deixa não verificável). Os circuitos passam pelas ferramentas reais do
agente, como no ``test_gerar_netlist``. Rodam no GitHub Actions (não precisam do SKiDL nem
do KiCad).
"""
import copy
import dataclasses
import json
import re
from pathlib import Path

import pytest

from src import regras
from src.agente.contratos import CONTRATOS
from src.agente.ferramentas import Ferramentas
from src.briefing import CONTRATOS as CONTRATOS_BRIEFING
from src.componentes.carregar import carregar_todos
from src.custos import ler
from src.regras import REGRAS, ErroCircuito, verificar

RAIZ = Path(__file__).resolve().parents[1]
DADOS = RAIZ / "tests" / "dados" / "regras"
SPEC = RAIZ / "placas" / "monitor-umidade" / "spec.yaml"
BASE = carregar_todos()

ESP, LCD, SENSOR, CONV = ("esp32-devkitc-v4", "display-lcd-1602-i2c",
                          "sensor-umidade-capacitivo", "conversor-nivel-logico-4-canais")
SELECOES = {"U1": ESP, "LCD1": LCD, "S1": SENSOR, "U2": CONV}
REFERENCIA = {
    "+5V": [("U1", "5V"), ("LCD1", "VCC"), ("U2", "HV")],
    "+3V3": [("U1", "3V3"), ("S1", "VCC"), ("U2", "LV")],
    "GND": [("U1", "GND"), ("LCD1", "GND"), ("S1", "GND"), ("U2", "GND")],
    "SENSOR": [("S1", "AOUT"), ("U1", "IO34")],
    "SDA_3V3": [("U1", "IO21"), ("U2", "LV1")],
    "SCL_3V3": [("U1", "IO22"), ("U2", "LV2")],
    "SDA_5V": [("U2", "HV1"), ("LCD1", "SDA")],
    "SCL_5V": [("U2", "HV2"), ("LCD1", "SCL")],
}


def _estado(ligacoes=REFERENCIA, selecoes=SELECOES) -> dict:
    f = Ferramentas(BASE)
    for ref, id_ in selecoes.items():
        assert f.selecionar_componente(id_, ref)["ok"]
    for rede, pinos in ligacoes.items():
        for ref, pino in pinos:
            assert f.conectar(ref, pino, rede)["ok"], (ref, pino, rede)
    return f.estado()


def _com(**mudancas) -> dict:
    """As ligações de referência, com redes trocadas (None tira a rede)."""
    ligacoes = copy.deepcopy(REFERENCIA)
    for rede, pinos in mudancas.items():
        rede = rede.replace("__", "+").replace("_v", "V")
        if pinos is None:
            ligacoes.pop(rede)
        else:
            ligacoes[rede] = pinos
    return ligacoes


def _r(relatorio, regra, ref=None):
    [r] = [r for r in relatorio.resultados if r.regra == regra and (ref is None or r.ref == ref)]
    return r


# --- O circuito de referência -----------------------------------------------------------------

def test_circuito_de_referencia():
    rel = verificar(_estado(), BASE, wifi=True)
    situacoes = {r.regra: r.situacao for r in rel.resultados}
    assert situacoes == {
        "gpio-input-only": "ok", "gpio-flash-reserved": "ok", "gpio-strapping": "ok",
        "adc2-wifi": "ok", "gpio-not-5v-tolerant": "nao_verificavel",
        "lcd-supply-voltage": "ok", "i2c-voltage-compatibility": "ok",
        "i2c-address": "manual", "lcd-display-format": "manual", "i2c-pullups": "manual",
        "level-shifter-dual-supply": "ok", "level-shifter-common-ground": "ok",
        "level-shifter-voltage-direction": "ok", "level-shifter-supply-order": "manual",
        "level-shifter-channel-mapping": "ok", "level-shifter-voltage-compatibility": "ok"}
    # A base não diz a tensão da saída AOUT do sensor: o motor não presume que está certo.
    [p] = _r(rel, "gpio-not-5v-tolerant").problemas
    assert "S1:3 (AOUT)" in p.pinos and p.redes == ("SENSOR",)
    assert not rel.aprovado


def test_com_o_dado_do_sensor_o_circuito_de_referencia_passa():
    """Se a base disser a tensão do sinal do sensor, o mesmo circuito é aprovado. (Base de
    teste: o dado não está na base real.)"""
    base = dict(BASE)
    base[SENSOR] = base[SENSOR].model_copy(update={"nivel_logico": 3.3})
    rel = verificar(_estado(), base, wifi=True)
    assert rel.aprovado and _r(rel, "gpio-not-5v-tolerant").situacao == "ok"


# --- ESP32 ------------------------------------------------------------------------------------

def test_adc2_com_wifi_violada():
    rel = verificar(_estado(_com(SENSOR=[("S1", "AOUT"), ("U1", "IO25")])), BASE, wifi=True)
    r = _r(rel, "adc2-wifi")
    assert r.situacao == "violada" and r.bloqueia
    [p] = r.problemas
    assert p.pinos == ("U1:9 (IO25)", "S1:3 (AOUT)") and "ADC1" in p.correcao


def test_adc2_sem_wifi_ok_e_sem_dizer_nao_verificavel():
    estado = _estado(_com(SENSOR=[("S1", "AOUT"), ("U1", "IO25")]))
    assert _r(verificar(estado, BASE, wifi=False), "adc2-wifi").situacao == "ok"
    sem_dado = _r(verificar(estado, BASE, wifi=None), "adc2-wifi")
    assert sem_dado.situacao == "nao_verificavel" and sem_dado.bloqueia
    assert "Wi-Fi" in sem_dado.problemas[0].explicacao


def test_gpio_em_5v_violada():
    rel = verificar(_estado(_com(__5_v=REFERENCIA["+5V"] + [("U1", "IO23")])), BASE, wifi=True)
    r = _r(rel, "gpio-not-5v-tolerant")
    assert r.situacao == "violada"
    [violada] = [p for p in r.problemas if p.situacao == "violada"]
    assert violada.pinos[0] == "U1:21 (IO23)" and violada.redes == ("+5V",)
    assert "conversor" in violada.correcao


def test_gpio_direto_no_canal_hv_violada():
    """O IO21 ligado no lado de 5 V do conversor (HV1): recebe a tensão do lado HV."""
    rel = verificar(_estado(_com(SDA_3V3=None, SDA_5V=[("U2", "HV1"), ("LCD1", "SDA"),
                                                                    ("U1", "IO21")])),
                    BASE, wifi=True)
    assert _r(rel, "gpio-not-5v-tolerant").situacao == "violada"
    assert _r(rel, "level-shifter-voltage-direction").situacao == "violada"


def test_flash_violada():
    rel = verificar(_estado(_com(SENSOR=[("S1", "AOUT"), ("U1", "IO34"), ("U1", "D2")])), BASE,
                    wifi=True)
    r = _r(rel, "gpio-flash-reserved")
    assert r.situacao == "violada" and "GPIO9" in r.problemas[0].explicacao


def test_so_entrada_sem_quem_gere_o_sinal_violada():
    """IO35 ligado só ao SCL do LCD, que é entrada: ninguém gera o sinal."""
    rel = verificar(_estado(_com(SCL_3V3=None, SCL_5V=[("LCD1", "SCL"), ("U1", "IO35")])), BASE,
                    wifi=True)
    r = _r(rel, "gpio-input-only")
    assert r.situacao == "violada" and r.problemas[0].pinos[0] == "U1:6 (IO35)"


def test_so_entrada_com_sinal_de_outra_peca_ok():
    assert _r(verificar(_estado(), BASE, wifi=True), "gpio-input-only").situacao == "ok"


def test_strapping_e_aviso_e_nao_reprova():
    base = dict(BASE)
    base[SENSOR] = base[SENSOR].model_copy(update={"nivel_logico": 3.3})
    rel = verificar(_estado(_com(SDA_3V3=[("U1", "IO2"), ("U2", "LV1")])), base, wifi=True)
    r = _r(rel, "gpio-strapping")
    assert r.situacao == "violada" and r.severidade == "aviso" and not r.bloqueia
    assert rel.aprovado


# --- LCD --------------------------------------------------------------------------------------

def test_lcd_em_3v3_violada():
    ligacoes = _com(__5_v=[("U1", "5V"), ("U2", "HV")],
                    __3V3=REFERENCIA["+3V3"] + [("LCD1", "VCC")])
    r = _r(verificar(_estado(ligacoes), BASE, wifi=True), "lcd-supply-voltage")
    assert r.situacao == "violada" and "3.3 V" in r.problemas[0].explicacao


def test_lcd_sem_alimentacao_violada():
    r = _r(verificar(_estado(_com(__5_v=[("U1", "5V"), ("U2", "HV")])), BASE, wifi=True),
           "lcd-supply-voltage")
    assert r.situacao == "violada" and "não está ligado" in r.problemas[0].explicacao


def test_i2c_direto_no_esp32_nao_verificavel():
    """Sem conversor, a base não diz a tensão dos pull-ups: não verificável, nunca ok."""
    estado = json.loads((DADOS / "sem-conversor.json").read_text(encoding="utf-8"))
    rel = verificar(estado, BASE, wifi=True)
    r = _r(rel, "i2c-voltage-compatibility")
    assert r.situacao == "nao_verificavel" and r.bloqueia and len(r.problemas) == 2
    assert not rel.aprovado


def test_i2c_direto_com_pullups_em_5v_violada():
    base = dict(BASE)
    base[LCD] = base[LCD].model_copy(update={"nivel_logico": 5.0})
    estado = json.loads((DADOS / "sem-conversor.json").read_text(encoding="utf-8"))
    assert _r(verificar(estado, base, wifi=True), "i2c-voltage-compatibility").situacao == "violada"


# --- Conversor --------------------------------------------------------------------------------

def test_conversor_invertido_violada():
    estado = json.loads((DADOS / "conversor-invertido.json").read_text(encoding="utf-8"))
    r = _r(verificar(estado, BASE, wifi=True), "level-shifter-voltage-direction")
    assert r.situacao == "violada" and "invertidos" in r.problemas[0].explicacao


def test_conversor_sem_lv_violada():
    ligacoes = _com(__3V3=[("U1", "3V3"), ("S1", "VCC")])
    rel = verificar(_estado(ligacoes), BASE, wifi=True)
    assert _r(rel, "level-shifter-dual-supply").situacao == "violada"
    assert _r(rel, "level-shifter-voltage-direction").situacao == "nao_verificavel"


def test_conversor_lv_numa_rede_sem_alimentacao_violada():
    ligacoes = _com(__3V3=[("U1", "3V3"), ("S1", "VCC")], SOLTA=[("U2", "LV"), ("U2", "LV3")])
    r = _r(verificar(_estado(ligacoes), BASE, wifi=True), "level-shifter-dual-supply")
    assert r.situacao == "violada" and r.problemas[0].redes == ("SOLTA",)


def test_conversor_canal_de_um_lado_so_violada():
    ligacoes = _com(SCL_3V3=None)
    r = _r(verificar(_estado(ligacoes), BASE, wifi=True), "level-shifter-channel-mapping")
    assert r.situacao == "violada" and "canal 2" in r.problemas[0].explicacao


def test_conversor_terra_separado_violada():
    ligacoes = _com(GND=[("U1", "GND"), ("LCD1", "GND"), ("S1", "GND")], GND2=[("U2", "GND")])
    r = _r(verificar(_estado(ligacoes), BASE, wifi=True), "level-shifter-common-ground")
    assert r.situacao == "violada"


def test_conversor_sem_terra_violada():
    r = _r(verificar(_estado(_com(GND=[("U1", "GND"), ("LCD1", "GND"), ("S1", "GND")])), BASE,
                     wifi=True), "level-shifter-common-ground")
    assert r.situacao == "violada" and "sem ligação" in r.problemas[0].explicacao


def test_conversor_fora_da_faixa_e_aviso():
    base = dict(BASE)
    base[ESP] = base[ESP].model_copy(update={"pinos": [
        p.model_copy(update={"tensao_max": 1.2}) if p.nome == "3V3" else p
        for p in base[ESP].pinos]})
    r = _r(verificar(_estado(), base, wifi=True), "level-shifter-voltage-compatibility")
    assert r.situacao == "violada" and r.severidade == "aviso"


# --- Dados ausentes, entradas inválidas, extremos ---------------------------------------------

def test_regra_da_base_sem_verificacao_no_motor_nao_passa_calada():
    base = dict(BASE)
    nova = base[ESP].regras[0].model_copy(update={"id": "regra-nova"})
    base[ESP] = base[ESP].model_copy(update={"regras": [*base[ESP].regras, nova]})
    r = _r(verificar(_estado(), base, wifi=True), "regra-nova")
    assert r.situacao == "nao_verificavel" and r.bloqueia


@pytest.mark.parametrize("estado", [
    None, [], "texto", {}, {"selecoes": {"U1": ESP}},
    {"selecoes": {"U1": "peca-que-nao-existe"}, "ligacoes": []},
    {"selecoes": {"U1": ESP}, "ligacoes": [{"ref": "U9", "pino": 1, "rede": "X"}]},
    {"selecoes": {"U1": ESP}, "ligacoes": [{"ref": "U1", "pino": 99, "rede": "X"}]},
    {"selecoes": {"U1": ESP}, "ligacoes": [{"ref": "U1", "pino": 1, "rede": "A"},
                                           {"ref": "U1", "pino": 1, "rede": "B"}]},
])
def test_estado_invalido_nao_e_verificado(estado):
    with pytest.raises(ErroCircuito):
        verificar(estado, BASE)


def test_circuito_vazio_nao_e_aprovado():
    with pytest.raises(ErroCircuito, match="nenhuma peça"):
        verificar({"selecoes": {}, "ligacoes": []}, BASE)


def test_peca_sem_ligacoes():
    rel = verificar({"selecoes": {"U1": ESP}, "ligacoes": []}, BASE, wifi=True)
    assert {r.situacao for r in rel.resultados} == {"ok"}


def test_mesmo_estado_mesmo_relatorio():
    assert verificar(_estado(), BASE, wifi=True) == verificar(_estado(), BASE, wifi=True)


# --- As regras são código: o agente não muda, nem desliga, nem contorna ------------------------

def test_toda_regra_da_base_tem_entrada_no_motor():
    """Uma regra nova na base sem função no motor falha aqui, e não passa calada."""
    na_base = {(c.id, r.id) for c in BASE.values() for r in c.regras}
    assert na_base == set(REGRAS)


@pytest.mark.parametrize("nome, gpios", [("gpio-input-only", regras.GPIO_SO_ENTRADA),
                                         ("gpio-flash-reserved", regras.GPIO_FLASH),
                                         ("gpio-strapping", regras.GPIO_STRAPPING)])
def test_numeros_gpio_sao_os_da_descricao_na_base(nome, gpios):
    [regra] = [r for r in BASE[ESP].regras if r.id == nome]
    texto = regra.descricao
    citados = {int(n) for n in re.findall(r"GPIO(\d+)", texto)}
    if "até" in texto:                       # "GPIO6 até GPIO11"
        citados = set(range(min(citados), max(citados) + 1))
    assert citados == set(gpios)


def test_tabela_de_regras_e_so_de_leitura():
    with pytest.raises(TypeError):
        REGRAS[(ESP, "adc2-wifi")] = lambda *a: []          # type: ignore[index]
    with pytest.raises(TypeError):
        del REGRAS[(ESP, "adc2-wifi")]                      # type: ignore[attr-defined]


def test_resultado_nao_muda_depois_de_pronto():
    rel = verificar(_estado(), BASE, wifi=True)
    with pytest.raises(dataclasses.FrozenInstanceError):
        rel.resultados[0].situacao = "ok"                   # type: ignore[misc]
    with pytest.raises(dataclasses.FrozenInstanceError):
        rel.resultados = ()                                 # type: ignore[misc]


def test_verificar_nao_aceita_opcao_para_pular_regra():
    with pytest.raises(TypeError):
        verificar(_estado(), BASE, wifi=True, ignorar=["adc2-wifi"])  # type: ignore[call-arg]


@pytest.mark.parametrize("extra", [
    {"regras": []}, {"ignorar": ["adc2-wifi"]}, {"aprovado": True},
    {"decisoes": [{"regra": "adc2-wifi", "situacao": "ok"}]}])
def test_o_que_o_agente_poe_no_estado_alem_das_ligacoes_nao_conta(extra):
    estado = _estado(_com(SENSOR=[("S1", "AOUT"), ("U1", "IO25")]))
    antes = verificar(estado, BASE, wifi=True)
    assert verificar(estado | extra, BASE, wifi=True) == antes
    assert _r(antes, "adc2-wifi").situacao == "violada"


def test_nenhuma_ferramenta_do_agente_chega_ao_motor():
    nomes = {c["name"] for c in CONTRATOS} | {c["name"] for c in CONTRATOS_BRIEFING}
    assert not any("regra" in n or "verific" in n for n in nomes)
    assert not hasattr(Ferramentas, "verificar")


def test_motor_nao_muda_o_estado_nem_a_base():
    estado = _estado()
    copia, base_antes = copy.deepcopy(estado), {k: v.model_dump() for k, v in BASE.items()}
    verificar(estado, BASE, wifi=True)
    assert estado == copia
    assert {k: v.model_dump() for k, v in BASE.items()} == base_antes


# --- Relatório e terminal ---------------------------------------------------------------------

def test_relatorio_em_dict_vira_json():
    rel = verificar(_estado(_com(SENSOR=[("S1", "AOUT"), ("U1", "IO25")])), BASE, wifi=True)
    dados = json.loads(json.dumps(rel.para_dict()))
    assert dados["aprovado"] is False and dados["wifi"] is True
    [adc2] = [r for r in dados["resultados"] if r["regra"] == "adc2-wifi"]
    assert adc2["bloqueia"] and adc2["problemas"][0]["correcao"]
    assert sum(dados["contagem"].values()) == len(dados["resultados"]) == 16


def test_texto_mostra_violadas_primeiro():
    texto = verificar(_estado(_com(SENSOR=[("S1", "AOUT"), ("U1", "IO25")])), BASE,
                      wifi=True).texto()
    linhas = texto.splitlines()
    assert linhas[0].startswith("Motor de regras: REPROVADO")
    assert "[VIOLADA]" in linhas[1] and "adc2-wifi" in linhas[1]


@pytest.mark.parametrize("caso, codigo, violada", [
    ("referencia", 1, None), ("sensor-no-adc2", 1, "adc2-wifi"),
    ("gpio-em-5v", 1, "gpio-not-5v-tolerant"), ("sem-conversor", 1, None),
    ("conversor-invertido", 1, "level-shifter-voltage-direction")])
def test_terminal_com_os_exemplos(tmp_path, caso, codigo, violada):
    saida = []
    assert regras.main([str(DADOS / f"{caso}.json"), "--spec", str(SPEC), "--json",
                        "--custos", str(tmp_path)], saida.append) == codigo
    dados = json.loads(saida[0])
    assert dados["wifi"] is True
    if violada:
        assert any(r["regra"] == violada and r["situacao"] == "violada"
                   for r in dados["resultados"])
    [lancamento] = ler(tmp_path / "monitor-umidade.jsonl")
    assert (lancamento.etapa, lancamento.tipo, lancamento.custo) == (
        "motor_de_regras", "operacao", "sem_custo")


def test_terminal_aprovado_sai_com_zero(tmp_path, monkeypatch):
    base = dict(BASE)
    base[SENSOR] = base[SENSOR].model_copy(update={"nivel_logico": 3.3})
    monkeypatch.setattr(regras, "carregar_todos", lambda: base)
    saida = []
    assert regras.main([str(DADOS / "referencia.json"), "--spec", str(SPEC),
                        "--custos", str(tmp_path)], saida.append) == 0
    assert saida[0].startswith("Motor de regras: APROVADO")


def test_terminal_sem_spec_wifi_fica_sem_dizer(tmp_path):
    saida = []
    assert regras.main([str(DADOS / "sensor-no-adc2.json"), "--json", "--custos",
                        str(tmp_path)], saida.append) == 1
    [adc2] = [r for r in json.loads(saida[0])["resultados"] if r["regra"] == "adc2-wifi"]
    assert adc2["situacao"] == "nao_verificavel"
    assert (tmp_path / "sem-projeto.jsonl").exists()


@pytest.mark.parametrize("conteudo", ["não é json", "[]", '{"selecoes": {"U1": "x"}}'])
def test_terminal_entrada_invalida(tmp_path, conteudo):
    arquivo = tmp_path / "estado.json"
    arquivo.write_text(conteudo, encoding="utf-8")
    saida = []
    assert regras.main([str(arquivo), "--custos", str(tmp_path)], saida.append) == 2
    assert not list(tmp_path.glob("*.jsonl"))


def test_terminal_arquivo_que_nao_existe(tmp_path):
    saida = []
    assert regras.main([str(tmp_path / "nada.json"), "--custos", str(tmp_path)],
                       saida.append) == 2
    assert saida[0].startswith("Entrada inválida")


def test_depois_do_agente_o_motor_confere_e_grava(tmp_path, capsys):
    from src.agente.__main__ import conferir_regras
    from src.custos import Custos
    from src.especificacao import ler_especificacao
    custos = Custos("monitor-umidade")
    conferir_regras(_estado(), BASE, ler_especificacao(SPEC, BASE), tmp_path, custos)
    dados = json.loads((tmp_path / "regras.json").read_text(encoding="utf-8"))
    assert dados["wifi"] is True and dados["contagem"]["ok"] == 11
    assert json.loads((tmp_path / "estado.json").read_text(encoding="utf-8"))["selecoes"]
    [l] = custos.lancamentos
    assert l.etapa == "motor_de_regras" and "reprovado" in l.detalhe
    assert "=== MOTOR DE REGRAS ===" in capsys.readouterr().out
