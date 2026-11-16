"""Testes do laço de correção (Marco 5, Parte 4; ADR-018) e do caminho até o DRC.

O agente é um provedor de roteiro; a placa é um falso, exceto no teste que roda o caminho
de verdade (só dentro do container, com SKiDL, pcbnew e kicad-cli).
"""
import importlib.util
import json
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml

from src import correcao
from src.agente.contratos import CONTRATOS, CONTRATOS_DE_CORRECAO
from src.agente.ferramentas import FERRAMENTAS, Ferramentas
from src.agente.laco import Chamada, Resposta
from src.componentes.carregar import carregar_todos
from src.correcao import (MAX_CORRECOES, Problema, conferir, corrigir, explicar,
                          relatorio_para_o_agente)
from src.custos import Custos, ler
from src.drc import (GABARITO, POSICOES, ErroPlaca, ItemDRC, ResultadoPlaca, conferir_placa,
                     ler_drc, posicoes_do_agente)
from src.especificacao import ler_especificacao
from src.gerar_netlist import planejar

RAIZ = Path(__file__).resolve().parents[1]
SPEC = RAIZ / "placas" / "monitor-umidade" / "spec.yaml"
DADOS = RAIZ / "tests" / "dados" / "regras"
BASE_REAL = carregar_todos()

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


@pytest.fixture(scope="module")
def base():
    """A base real. Com a tensão do AOUT do sensor (0 a 3,0 V, ADR-017), o circuito de
    referência é aprovado."""
    return dict(BASE_REAL)


def _sem_tensao_do_aout():
    """A base como era antes do dado do datasheet: o AOUT do sensor sem tensao_max."""
    b = dict(BASE_REAL)
    b[SENSOR] = b[SENSOR].model_copy(update={"pinos": [
        p.model_copy(update={"tensao_max": None}) if p.nome == "AOUT" else p
        for p in b[SENSOR].pinos]})
    return b


@pytest.fixture(scope="module")
def spec(base):
    return ler_especificacao(SPEC, base)


def _chamadas(*pares) -> tuple[Chamada, ...]:
    return tuple(Chamada(nome, args, f"c{i}") for i, (nome, args) in enumerate(pares))


def _montar_referencia():
    pares = [("selecionar_componente", {"id": id_, "ref": ref}) for ref, id_ in SELECOES.items()]
    pares += [("conectar", {"ref": ref, "pino": pino, "rede": rede})
              for rede, pinos in REFERENCIA.items() for ref, pino in pinos]
    return Resposta(chamadas=_chamadas(*pares))


class Roteiro:
    """Um provedor que devolve respostas prontas e guarda o que recebeu."""

    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.iniciados, self.mensagens, self.resultados = [], [], []

    def _proxima(self):
        if not self.respostas:
            raise AssertionError("o roteiro acabou")
        return self.respostas.pop(0)

    def iniciar(self, sistema, contratos, pedido):
        self.iniciados.append((sistema, contratos, pedido))
        return self._proxima()

    def continuar(self, resultados):
        self.resultados.append(resultados)
        return self._proxima()

    def responder(self, texto):
        self.mensagens.append(texto)
        return self._proxima()


PRONTO = Resposta(texto="Pronto.")


def _corrigir(spec, base, roteiro, **extra):
    return corrigir(SPEC, spec, roteiro, base, custos=Custos("monitor-umidade"), **extra)


def _mover_sensor_para_adc2(ferramentas):
    """O erro injetado: o sinal do sensor sai do IO34 (ADC1) e vai para o IO25 (ADC2)."""
    assert ferramentas.desconectar("U1", "IO34")["ok"]
    assert ferramentas.conectar("U1", "IO25", "SENSOR")["ok"]


# --- O laço -----------------------------------------------------------------------------------

def test_circuito_certo_passa_sem_correcao(spec, base):
    roteiro = Roteiro([_montar_referencia(), PRONTO])
    resultado = _corrigir(spec, base, roteiro)
    assert resultado.aprovado and resultado.motivo == "aprovado" and resultado.correcoes == 0
    assert roteiro.mensagens == []
    sistema, contratos, _ = roteiro.iniciados[0]
    assert "desconectar" in sistema and contratos is CONTRATOS_DE_CORRECAO


def test_erro_injetado_e_detectado_e_corrigido(spec, base):
    correcao_do_agente = Resposta(chamadas=_chamadas(
        ("desconectar", {"ref": "U1", "pino": "IO25"}),
        ("conectar", {"ref": "U1", "pino": "IO34", "rede": "SENSOR"})))
    roteiro = Roteiro([_montar_referencia(), PRONTO, correcao_do_agente,
                       Resposta(texto="Corrigido.")])
    resultado = _corrigir(spec, base, roteiro, depois_do_agente=_mover_sensor_para_adc2)
    assert resultado.aprovado and resultado.correcoes == 1
    [mensagem] = roteiro.mensagens
    assert "correção 1 de no máximo 3" in mensagem
    relatorio = json.loads(mensagem[mensagem.index("{"):])
    [problema] = relatorio["problemas"]
    assert problema["etapa"] == "regras" and problema["regra"].endswith("adc2-wifi")
    assert "U1:9 (IO25)" in problema["onde"] and "ADC1" in problema["correcao"]
    primeira, segunda = resultado.rodadas
    assert primeira.problemas and not segunda.problemas


def test_limite_de_tres_correcoes(spec, base):
    """O agente mexe no circuito a cada pedido, mas nunca no que está errado."""
    def mexe(n):
        a, b = [("IO32", "IO33"), ("IO18", "IO19"), ("IO16", "IO17")][n]
        return Resposta(chamadas=_chamadas(("conectar", {"ref": "U1", "pino": a, "rede": f"X{n}"}),
                                           ("conectar", {"ref": "U1", "pino": b, "rede": f"X{n}"})))
    roteiro = Roteiro([_montar_referencia(), PRONTO,
                       mexe(0), PRONTO, mexe(1), PRONTO, mexe(2), PRONTO])
    resultado = _corrigir(spec, base, roteiro, depois_do_agente=_mover_sensor_para_adc2)
    assert not resultado.aprovado and resultado.motivo == "limite"
    assert resultado.correcoes == MAX_CORRECOES == len(roteiro.mensagens)
    texto = explicar(resultado)
    assert "Nenhuma placa foi entregue" in texto and "adc2-wifi" in texto


def test_agente_que_nao_muda_nada_para_antes(spec, base):
    roteiro = Roteiro([_montar_referencia(), PRONTO, Resposta(texto="Não sei corrigir.")])
    resultado = _corrigir(spec, base, roteiro, depois_do_agente=_mover_sensor_para_adc2)
    assert resultado.motivo == "sem_mudanca" and resultado.correcoes == 1
    assert "não mudou o circuito" in explicar(resultado)


def test_sem_o_dado_do_sensor_o_laco_nao_aprova(spec):
    """Sem a tensão do AOUT na base, o problema volta ao agente e o laço para."""
    roteiro = Roteiro([_montar_referencia(), PRONTO,
                       Resposta(chamadas=_chamadas(("registrar_pendencia", {
                           "necessidade": "tensão da saída AOUT do sensor",
                           "motivo": "a base não tem o dado"}))), PRONTO])
    resultado = _corrigir(spec, _sem_tensao_do_aout(), roteiro)
    assert not resultado.aprovado and resultado.motivo == "sem_mudanca"
    assert "não verificável" in roteiro.mensagens[0]
    texto = explicar(resultado)
    assert "Pendências registradas" in texto and "AOUT" in texto


def test_agente_sem_circuito(spec, base):
    resultado = _corrigir(spec, base, Roteiro([Resposta(texto="Desisto.")]))
    assert resultado.motivo == "sem_circuito" and not resultado.aprovado
    assert resultado.rodadas[0].problemas[0].etapa == "netlist"


def test_problema_de_netlist_volta_ao_agente(spec, base):
    solta = Resposta(chamadas=_chamadas(("conectar", {"ref": "U1", "pino": "IO23",
                                                      "rede": "SOLTA"})))
    conserto = Resposta(chamadas=_chamadas(("desconectar", {"ref": "U1", "pino": "IO23"})))
    roteiro = Roteiro([_montar_referencia(), solta, PRONTO, conserto, PRONTO])
    resultado = _corrigir(spec, base, roteiro)
    assert resultado.aprovado and resultado.correcoes == 1
    assert '"etapa": "netlist"' in roteiro.mensagens[0] and "SOLTA" in roteiro.mensagens[0]


class PlacaFalsa:
    def __init__(self, respostas):
        self.respostas, self.chamadas = list(respostas), []

    def __call__(self, estado, numero):
        self.chamadas.append(numero)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return ResultadoPlaca(tuple(r), Path(f"rodada-{numero}.kicad_pcb"), Path("drc.json"))


def test_drc_roda_depois_das_regras_e_volta_ao_agente(spec, base):
    item = ItemDRC("unconnected_items", "error", "Ligação pendente",
                   ("Pad 1 [GND] de J1", "Pad 1 [GND] de J3"))
    placa = PlacaFalsa([[item], []])
    roteiro = Roteiro([_montar_referencia(), PRONTO,
                       Resposta(chamadas=_chamadas(("conectar", {"ref": "LCD1", "pino": "GND",
                                                                 "rede": "GND"}))), PRONTO])
    resultado = _corrigir(spec, base, roteiro, placa=placa)
    assert resultado.aprovado and placa.chamadas == [0, 1]
    assert '"etapa": "drc"' in roteiro.mensagens[0] and "J3" in roteiro.mensagens[0]
    assert "passou no DRC" in explicar(resultado)


def test_drc_nao_roda_com_regra_violada(spec, base):
    placa = PlacaFalsa([])
    roteiro = Roteiro([_montar_referencia(), PRONTO, Resposta(texto="Não sei.")])
    resultado = _corrigir(spec, base, roteiro, placa=placa,
                          depois_do_agente=_mover_sensor_para_adc2)
    assert placa.chamadas == [] and resultado.motivo == "sem_mudanca"


def test_placa_que_nao_pode_ser_feita_para_e_explica(spec, base):
    placa = PlacaFalsa([ErroPlaca("posicoes", "sem posição para J7")])
    resultado = _corrigir(spec, base, Roteiro([_montar_referencia(), PRONTO]), placa=placa)
    assert resultado.motivo == "placa" and not resultado.aprovado
    assert "sem posição para J7" in explicar(resultado)


def test_aviso_do_drc_ignorado_pelo_kicad_nao_conta(spec, base):
    placa = PlacaFalsa([[ItemDRC("x", "ignore", "ignorado")]])
    assert _corrigir(spec, base, Roteiro([_montar_referencia(), PRONTO]), placa=placa).aprovado


def test_custos_de_cada_rodada(spec, base):
    custos = Custos("monitor-umidade")
    roteiro = Roteiro([_montar_referencia(), PRONTO,
                       Resposta(chamadas=_chamadas(("desconectar", {"ref": "U1", "pino": "IO25"}),
                                                   ("conectar", {"ref": "U1", "pino": "IO34",
                                                                 "rede": "SENSOR"}))), PRONTO])
    corrigir(SPEC, spec, roteiro, base, custos=custos, depois_do_agente=_mover_sensor_para_adc2)
    etapas = [l.etapa for l in custos.lancamentos]
    assert etapas.count("motor_de_regras") == 2
    assert {"agente", "correcao"} <= set(etapas)


def test_relatorio_para_o_agente_e_json():
    texto = relatorio_para_o_agente([Problema("regras", "esp/r", "U1:9", "porque", None)])
    assert json.loads(texto) == {"problemas": [{"etapa": "regras", "regra": "esp/r",
                                                "onde": "U1:9", "porque": "porque",
                                                "correcao": None}]}


def test_conferir_sem_placa_so_regras(base):
    estado = json.loads((DADOS / "referencia.json").read_text(encoding="utf-8"))
    rodada = conferir(estado, base, True, 0)
    assert rodada.problemas == [] and rodada.regras.aprovado and rodada.placa is None


# --- A ferramenta desconectar -----------------------------------------------------------------

def test_desconectar_so_no_laco_de_correcao():
    assert "desconectar" not in FERRAMENTAS
    assert "desconectar" not in {c["name"] for c in CONTRATOS}
    m4 = Ferramentas(BASE_REAL)
    assert m4.executar_ferramenta("desconectar", {"ref": "U1", "pino": 1})["erro"] == \
        "ferramenta_inexistente"
    assert {c["name"] for c in CONTRATOS_DE_CORRECAO} == set(FERRAMENTAS) | {"desconectar"}


def test_desconectar():
    f = Ferramentas(BASE_REAL, correcao=True)
    f.selecionar_componente(ESP, "U1")
    f.conectar("U1", "GND", "GND")
    r = f.executar_ferramenta("desconectar", {"ref": "U1", "pino": "GND"})
    assert r["ok"] and len(r["desligados"]) == 3 and f.estado()["ligacoes"] == []
    assert f.desconectar("U1", "GND")["erro"] == "pino_sem_ligacao"
    assert f.desconectar("U9", 1)["erro"] == "peca_nao_selecionada"
    assert f.desconectar("U1", "XYZ")["erro"] == "pino_inexistente"
    assert f.executar_ferramenta("desconectar", {"ref": "U1"})["erro"] == "entrada_invalida"


# --- Do estado ao DRC (src/drc.py) ------------------------------------------------------------

def _plano():
    return planejar(json.loads((DADOS / "referencia.json").read_text(encoding="utf-8")),
                    BASE_REAL)


def test_posicoes_do_agente_seguem_a_placa_de_referencia():
    posicoes = yaml.safe_load(POSICOES.read_text(encoding="utf-8"))
    resultado = posicoes_do_agente(_plano(), GABARITO.read_text(encoding="utf-8"), posicoes)
    por_valor = {c.valor: resultado[c.ref] for c in _plano().conectores}
    # O lado HV do conversor do agente é J5; no gabarito, J6. A posição é a do gabarito.
    assert por_valor["conversor-nivel-logico-4-canais HV"] == posicoes["J6"]
    assert por_valor["conversor-nivel-logico-4-canais LV"] == posicoes["J5"]
    assert len(resultado) == 6


def test_peca_que_a_referencia_nao_tem_fica_sem_posicao():
    estado = json.loads((DADOS / "referencia.json").read_text(encoding="utf-8"))
    estado["selecoes"]["U3"] = CONV
    plano = planejar(estado, BASE_REAL)
    with pytest.raises(ErroPlaca, match="tem um só"):
        posicoes_do_agente(plano, GABARITO.read_text(encoding="utf-8"),
                           yaml.safe_load(POSICOES.read_text(encoding="utf-8")))


def test_ler_drc():
    itens = ler_drc({"violations": [{"type": "clearance", "severity": "error",
                                     "description": "Folga", "items": [{"description": "a"}]}],
                     "unconnected_items": []})
    assert itens == [ItemDRC("clearance", "error", "Folga", ("a",))]
    with pytest.raises(ErroPlaca):
        ler_drc({"violations": []})


def _feito(codigo=0, saida=""):
    return subprocess.CompletedProcess([], codigo, stdout=saida, stderr="")


def test_conferir_placa_com_passos_falsos(tmp_path):
    comandos = []

    def executar(comando):
        comandos.append(comando)
        if comando[0] == "kicad-cli":
            Path(comando[comando.index("-o") + 1]).write_text(
                json.dumps({"violations": [], "unconnected_items": []}), encoding="utf-8")
        return _feito()

    estado = json.loads((DADOS / "referencia.json").read_text(encoding="utf-8"))
    r = conferir_placa(estado, tmp_path, BASE_REAL, executar=executar,
                       gerar=lambda e, arquivo, b: Path(arquivo).write_text("(export)"))
    assert r.drc == () and r.placa == tmp_path / "agente_roteada.kicad_pcb"
    assert [c[1] if c[0] != "kicad-cli" else "drc" for c in comandos] == [
        "scripts/gerar_placa.py", "scripts/aplicar_posicoes.py",
        "scripts/spike/round_trip_freerouting.py", "drc"]
    assert len(yaml.safe_load((tmp_path / "posicoes.yaml").read_text(encoding="utf-8"))) == 6


def test_conferir_placa_passo_que_falha(tmp_path):
    estado = json.loads((DADOS / "referencia.json").read_text(encoding="utf-8"))
    with pytest.raises(ErroPlaca, match="roteamento: java falhou"):
        conferir_placa(estado, tmp_path, BASE_REAL,
                       executar=lambda c: _feito(1 if "round_trip" in " ".join(c) else 0,
                                                 "java falhou"),
                       gerar=lambda e, a, b: None)


TEM_KICAD = (importlib.util.find_spec("pcbnew") is not None
             and importlib.util.find_spec("skidl") is not None
             and shutil.which("kicad-cli") is not None)


@pytest.mark.skipif(not TEM_KICAD, reason="precisa do SKiDL, do pcbnew e do kicad-cli "
                                          "(make testes, dentro do container)")
def test_caminho_de_verdade_do_circuito_de_referencia_passa_no_drc(tmp_path):
    estado = json.loads((DADOS / "referencia.json").read_text(encoding="utf-8"))
    r = conferir_placa(estado, tmp_path, BASE_REAL)
    assert r.drc == (), r.drc
    assert r.placa.is_file()


# --- Terminal ---------------------------------------------------------------------------------

def test_main_sem_placa(tmp_path):
    saida = []
    roteiro = Roteiro([_montar_referencia(), PRONTO])
    codigo = correcao.main([str(SPEC), "--sem-placa", "--saida", str(tmp_path), "--custos",
                            str(tmp_path / "custos")], provedor=roteiro, escrever=saida.append)
    assert codigo == 0
    dados = json.loads((tmp_path / "monitor-umidade" / "correcao.json").read_text("utf-8"))
    assert dados["aprovado"] and dados["correcoes"] == 0
    assert "=== LAÇO DE CORREÇÃO ===" in "\n".join(saida)
    assert ler(tmp_path / "custos" / "monitor-umidade.jsonl")


def test_main_nao_aprovado_sai_com_1(tmp_path, monkeypatch):
    monkeypatch.setattr(correcao, "carregar_todos", _sem_tensao_do_aout)
    roteiro = Roteiro([_montar_referencia(), PRONTO, Resposta(texto="Não sei.")])
    codigo = correcao.main([str(SPEC), "--sem-placa", "--saida", str(tmp_path), "--custos",
                            str(tmp_path / "custos")], provedor=roteiro, escrever=lambda _: None)
    assert codigo == 1
