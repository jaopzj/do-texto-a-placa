"""Testes das equivalências de pinos do eval (ADR-015). Não precisam do SKiDL."""
from pathlib import Path

import pytest

from src.componentes.carregar import carregar_todos
from src.evals.comparar import Estrutura, comparar
from src.evals.equivalencias import ErroEquivalencias, Equivalencia, ler_equivalencias

from test_comparar import COMPONENTES_DO_GABARITO, ESP, GRUPOS_DO_GABARITO, SENSOR

PLACA = Path(__file__).resolve().parents[1] / "placas" / "monitor-umidade"
SPEC = PLACA / "spec.yaml"
BASE = carregar_todos()
REQUISITO = "A saída AOUT do sensor vai num pino do ESP32 com função ADC1."
GABARITO = Estrutura(frozenset(COMPONENTES_DO_GABARITO), frozenset(GRUPOS_DO_GABARITO))


def _sensor_em(*pinos: str) -> Estrutura:
    """O gabarito com o AOUT do sensor ligado a ``pinos`` no lugar do IO34."""
    sensor = frozenset({f"{SENSOR}: AOUT", f"{ESP}: IO34"})
    grupos = (GRUPOS_DO_GABARITO - {sensor}) | {
        frozenset({f"{SENSOR}: AOUT", *(f"{ESP}: {p}" for p in pinos)})}
    return Estrutura(frozenset(COMPONENTES_DO_GABARITO), frozenset(grupos))


def _escrever(tmp_path, texto: str) -> Path:
    arquivo = tmp_path / "equivalencias.yaml"
    arquivo.write_text(texto, encoding="utf-8")
    return arquivo


def _entrada(pino=f"{ESP}: IO34", funcao="ADC1_", requisito=REQUISITO, extra=""):
    return (f'equivalencias:\n  - pino: "{pino}"\n    funcao: {funcao}\n'
            f"    requisito: {requisito}\n{extra}")


@pytest.fixture(scope="module")
def equivalencias():
    return ler_equivalencias(PLACA / "equivalencias.yaml", SPEC, BASE)


# --- Leitura do arquivo ------------------------------------------------------------------------

def test_arquivo_da_placa_tem_os_pinos_do_adc1(equivalencias):
    [eq] = equivalencias
    assert eq.pino == f"{ESP}: IO34" and eq.requisito == REQUISITO
    assert eq.alternativas == {f"{ESP}: {p}" for p in ("VP", "VN", "IO35", "IO32", "IO33")}


def test_arquivo_ausente_nao_tem_equivalencias(tmp_path):
    assert ler_equivalencias(tmp_path / "nao-existe.yaml", SPEC, BASE) == []


@pytest.mark.parametrize("texto, trecho", [
    (_entrada(requisito="Um requisito que o spec não tem."), "não está no spec"),
    (_entrada(pino="peca-que-nao-existe: X"), "<id da peça da base>"),
    (_entrada(pino=f"{ESP}: IO99"), "não tem esse pino"),
    (_entrada(pino=f"{ESP}: IO21"), "o próprio pino não tem função"),
    (_entrada(funcao="DAC9_"), "o próprio pino não tem função"),
    (_entrada(extra="    pinos: [IO32]\n"), "pinos"),
    (_entrada() + _entrada().replace("equivalencias:\n", ""), "mais de uma equivalência"),
    ("equivalencias: [\n", "YAML inválido"),
])
def test_arquivo_com_problema_e_recusado(tmp_path, texto, trecho):
    with pytest.raises(ErroEquivalencias) as erro:
        ler_equivalencias(_escrever(tmp_path, texto), SPEC, BASE)
    assert trecho in str(erro.value)


# --- Comparação --------------------------------------------------------------------------------

def test_sem_equivalencias_a_comparacao_continua_exata():
    resultado = comparar(GABARITO, _sensor_em("IO32"), BASE)
    assert not resultado.equivalente and resultado.trocas == {}


@pytest.mark.parametrize("pino", ["IO32", "IO33", "IO35", "VP", "VN"])
def test_outro_pino_do_adc1_e_aceito(equivalencias, pino):
    resultado = comparar(GABARITO, _sensor_em(pino), BASE, equivalencias)
    assert resultado.equivalente, resultado.resumo()
    assert resultado.trocas == {f"{ESP}: IO34": f"{ESP}: {pino}"}
    assert resultado.resumo() == (f"equivalente ao gabarito (troca aceita: {ESP}: {pino} "
                                  f"no lugar de {ESP}: IO34)")


def test_o_proprio_gabarito_continua_equivalente_sem_troca(equivalencias):
    resultado = comparar(GABARITO, GABARITO, BASE, equivalencias)
    assert resultado.equivalente and resultado.trocas == {}


@pytest.mark.parametrize("pino", ["IO25", "IO26", "IO27", "IO14", "IO4"])
def test_pino_fora_do_adc1_continua_errado(equivalencias, pino):
    resultado = comparar(GABARITO, _sensor_em(pino), BASE, equivalencias)
    assert not resultado.equivalente and resultado.trocas == {}
    assert f"{ESP}: IO34" in resultado.pinos_divergentes


def test_dois_pinos_do_adc1_ao_mesmo_tempo_continuam_errados(equivalencias):
    resultado = comparar(GABARITO, _sensor_em("IO32", "IO33"), BASE, equivalencias)
    assert not resultado.equivalente and resultado.trocas == {}


def test_pino_do_gabarito_mais_um_alternativo_continua_errado(equivalencias):
    resultado = comparar(GABARITO, _sensor_em("IO34", "IO32"), BASE, equivalencias)
    assert not resultado.equivalente and resultado.trocas == {}


def test_troca_nao_esconde_outro_erro(equivalencias):
    errada = _sensor_em("IO32")
    i2c = frozenset({f"{ESP}: IO21", "conversor-nivel-logico-4-canais: LV1"})
    errada = Estrutura(errada.componentes, (errada.grupos - {i2c}) | {
        frozenset({f"{ESP}: IO19", "conversor-nivel-logico-4-canais: LV1"})})
    resultado = comparar(GABARITO, errada, BASE, equivalencias)
    assert not resultado.equivalente
    assert resultado.trocas == {f"{ESP}: IO34": f"{ESP}: IO32"}
    assert f"{ESP}: IO21" in resultado.pinos_divergentes
    assert f"{ESP}: IO34" not in resultado.pinos_divergentes
    assert "troca aceita" in resultado.resumo()


def test_alternativo_ja_usado_no_esperado_nao_e_trocado():
    # Uma equivalência cujo alternativo o próprio esperado já usa não pode ser aplicada.
    eq = Equivalencia(f"{ESP}: IO34", frozenset({f"{ESP}: IO21"}), REQUISITO)
    resultado = comparar(GABARITO, _sensor_em("IO21"), BASE, [eq])
    assert not resultado.equivalente and resultado.trocas == {}
