"""Testes do fluxo completo (Marco 5; ADR-019): do pedido aos arquivos da fábrica.

O modelo é um provedor de roteiro e o usuário é um roteiro de respostas, escolhidas pelo texto
que o programa pergunta (pergunta do briefing, primeira e segunda aprovação). A placa e a
fábrica são falsas, exceto no teste de ponta a ponta de verdade, que só roda dentro do
container (SKiDL, pcbnew, Freerouting e kicad-cli).
"""
import importlib.util
import shutil
from pathlib import Path

import pytest

from src import projeto
from src.agente.laco import Resposta
from src.aprovacao import PERGUNTA, PERGUNTA_DA_FABRICA
from src.componentes.carregar import carregar_todos
from src.correcao import PEDIDO_DO_USUARIO
from src.custos import Custos, ler
from src.drc import ResultadoPlaca
from src.fabrica import ErroFabrica, ResultadoFabrica
from src.projeto import AVISO_DE_PENDENCIAS, Fluxo, restricoes_incompativeis
from src.especificacao import especificacao_de_texto

from exemplo_briefing import ENTREGA, entrega
from exemplo_circuito import PRONTO, Roteiro, chamadas, montar_referencia

BASE = carregar_todos()
PEDIDO = "quero um monitor de umidade do solo com ESP32 e um LCD"


def _entregar(texto=ENTREGA, *antes):
    return Resposta(chamadas=chamadas(*antes, ("entregar_especificacao",
                                               {"especificacao": texto})))


class Usuario:
    """As respostas do usuário, pelo que o programa pergunta."""

    def __init__(self, perguntas=(), primeira=("s",), segunda=("s",)):
        self.filas = {"> ": list(perguntas), PERGUNTA: list(primeira),
                      PERGUNTA_DA_FABRICA: list(segunda)}
        self.lidos: list[str] = []

    def __call__(self, pergunta: str) -> str:
        self.lidos.append(pergunta)
        fila = self.filas[pergunta]
        if not fila:
            raise AssertionError(f"o usuário não tinha resposta para {pergunta!r}")
        return fila.pop(0)


class PlacaFalsa:
    """O caminho da placa sem KiCad: grava a placa, a netlist e o DRC vazios na pasta."""

    def __init__(self, drc=()):
        self.drc, self.pastas = tuple(drc), []

    def __call__(self, estado, pasta, base):
        self.pastas.append(pasta)
        pasta.mkdir(parents=True, exist_ok=True)
        arquivos = [pasta / n for n in ("agente_roteada.kicad_pcb", "drc.json", "agente.net",
                                        "posicoes.yaml")]
        for a in arquivos:
            a.write_text("x", encoding="utf-8")
        return ResultadoPlaca(self.drc, *arquivos)


class FabricaFalsa:
    def __init__(self, erro=None):
        self.erro, self.chamadas = erro, []

    def __call__(self, placa, pasta):
        self.chamadas.append((placa, pasta))
        if self.erro:
            raise self.erro
        pasta.mkdir(parents=True)
        arquivos = [pasta / n for n in ("placa-F_Cu.gbr", "placa.drl", "bom.csv")]
        for a in arquivos:
            a.write_text("x", encoding="utf-8")
        return ResultadoFabrica(pasta, tuple(arquivos), "OK: tudo conferido")


def _fluxo(tmp_path, roteiro, usuario, placa=None, fabrica=None, base=BASE, **extra):
    saida: list[str] = []
    fluxo = Fluxo(roteiro, usuario, saida.append, base=base, saida=tmp_path,
                  custos=Custos(), placa=PlacaFalsa() if placa is None else placa,
                  fabrica=fabrica or FabricaFalsa(), **extra)
    fim = fluxo.rodar(PEDIDO)
    return fim, "\n".join(saida)


def _relatorio(tmp_path) -> str:
    return (tmp_path / "monitor-umidade" / "relatorio.md").read_text(encoding="utf-8")


# --- O caminho feliz --------------------------------------------------------------------------

def test_pedido_vira_arquivos_da_fabrica_com_duas_aprovacoes(tmp_path):
    roteiro = Roteiro([_entregar(), montar_referencia(), PRONTO])
    usuario = Usuario()
    fabrica = FabricaFalsa()
    fim, texto = _fluxo(tmp_path, roteiro, usuario, fabrica=fabrica)
    assert fim.situacao == "fabrica" and fim.codigo == 0
    # As duas aprovações, nesta ordem, e nenhuma outra pergunta.
    assert usuario.lidos == [PERGUNTA, PERGUNTA_DA_FABRICA]
    pasta = tmp_path / "monitor-umidade"
    assert (pasta / "spec.yaml").is_file() and (pasta / "registro-briefing.txt").is_file()
    assert (pasta / "registro-agente.txt").is_file()
    [(placa, destino)] = fabrica.chamadas
    assert destino == pasta / "fabrica" and placa.placa.parent == pasta / "placa" / "conferencia-1"
    # O usuário acompanha: as etapas, as ferramentas do agente e o resultado das verificações.
    for trecho in ("Etapa 1 de 4", "Etapa 2 de 4", "Etapa 3 de 4", "Etapa 4 de 4",
                   "selecionar_componente", "=== VERIFICAÇÕES ===",
                   "=== SEGUNDA APROVAÇÃO", "DRC da placa roteada: 0 item(ns)",
                   "=== RESULTADO: PRONTO", "Arquivos produzidos nesta execução"):
        assert trecho in texto, trecho
    assert "monitor-umidade/fabrica/bom.csv" in texto
    relatorio = _relatorio(tmp_path)
    for secao in ("## Decisões e fontes", "## Regras verificadas",
                  "## Conferências e correções", "## DRC", "## BOM", "## Pendências",
                  "## Arquivos da fábrica", "## Custos"):
        assert secao in relatorio, secao
    assert "PRONTO: arquivos da fábrica gerados e conferidos" in relatorio
    assert "OK: tudo conferido" in relatorio and "`bom.csv`" in relatorio


def test_segunda_aprovacao_mostra_o_relatorio_antes_dos_arquivos(tmp_path):
    """Na hora da segunda pergunta, o relatório já existe e diz que espera a aprovação."""
    vistos = []

    def usuario(pergunta):
        if pergunta == PERGUNTA_DA_FABRICA:
            vistos.append(_relatorio(tmp_path))
            assert not (tmp_path / "monitor-umidade" / "fabrica").exists()
        return "s"

    fim, _ = _fluxo(tmp_path, Roteiro([_entregar(), montar_referencia(), PRONTO]), usuario)
    assert fim.situacao == "fabrica"
    assert "aguardando a segunda aprovação" in vistos[0]


def test_n_na_segunda_aprovacao_para_sem_arquivos(tmp_path):
    fabrica = FabricaFalsa()
    fim, texto = _fluxo(tmp_path, Roteiro([_entregar(), montar_referencia(), PRONTO]),
                        Usuario(segunda=["n"]), fabrica=fabrica)
    assert fim.situacao == "recusado" and fim.codigo == 1 and fabrica.chamadas == []
    assert "respondeu n" in _relatorio(tmp_path)
    assert "PARADO PELO USUÁRIO" in texto


def test_mudanca_na_segunda_aprovacao_volta_ao_agente_e_e_conferida(tmp_path):
    placa = PlacaFalsa()
    mudanca = Resposta(chamadas=chamadas(("desconectar", {"ref": "U1", "pino": "IO34"}),
                                         ("conectar", {"ref": "U1", "pino": "IO35",
                                                       "rede": "SENSOR"})))
    roteiro = Roteiro([_entregar(), montar_referencia(), PRONTO, mudanca, PRONTO])
    fim, _ = _fluxo(tmp_path, roteiro, Usuario(segunda=["use o IO35 no sensor", "s"]),
                    placa=placa)
    assert fim.situacao == "fabrica"
    [mensagem] = roteiro.mensagens
    assert mensagem == PEDIDO_DO_USUARIO.format(texto="use o IO35 no sensor")
    # A mudança passou por todas as conferências de novo, com placa nova.
    assert len(placa.pastas) == 2 and len(fim.andamento.historico) == 2
    ligacoes = {(l["ref"], l["nome"]): l["rede"] for l in fim.andamento.laco.estado["ligacoes"]}
    assert ligacoes[("U1", "IO35")] == "SENSOR" and ("U1", "IO34") not in ligacoes


# --- Erros e paradas --------------------------------------------------------------------------

def test_erro_injetado_e_detectado_e_corrigido_no_fluxo(tmp_path):
    """Tira a alimentação do sensor depois que o agente termina; o laço acha e o agente liga."""
    def tirar_vcc_do_sensor(ferramentas):
        assert ferramentas.desconectar("S1", "VCC")["ok"]

    religa = Resposta(chamadas=chamadas(("conectar", {"ref": "S1", "pino": "VCC",
                                                      "rede": "+3V3"})))
    roteiro = Roteiro([_entregar(), montar_referencia(), PRONTO, religa, PRONTO])
    fim, texto = _fluxo(tmp_path, roteiro, Usuario(), depois_do_agente=tirar_vcc_do_sensor)
    assert fim.situacao == "fabrica"
    assert "alimentacao-ligada" in roteiro.mensagens[0] and "S1" in roteiro.mensagens[0]
    primeira, segunda = fim.andamento.historico
    assert primeira.problemas[0].etapa == "alimentacao" and not segunda.problemas
    assert "correção 1: nenhum problema" in _relatorio(tmp_path)


def _sem_tensao_do_aout():
    b = dict(BASE)
    sensor = "sensor-umidade-capacitivo"
    b[sensor] = b[sensor].model_copy(update={"pinos": [
        p.model_copy(update={"tensao_max": None}) if p.nome == "AOUT" else p
        for p in b[sensor].pinos]})
    return b


def test_circuito_reprovado_para_e_explica_sem_placa(tmp_path):
    fabrica = FabricaFalsa()
    roteiro = Roteiro([_entregar(), montar_referencia(), PRONTO, Resposta(texto="Não sei.")])
    fim, texto = _fluxo(tmp_path, roteiro, Usuario(), fabrica=fabrica,
                        base=_sem_tensao_do_aout())
    assert fim.situacao == "reprovado" and fim.codigo == 1 and fabrica.chamadas == []
    assert "Nenhuma placa foi entregue" in texto and "gpio-not-5v-tolerant" in texto
    relatorio = _relatorio(tmp_path)
    assert "REPROVADO" in relatorio and "**não verificável**" in relatorio
    assert "Não gerados" in relatorio


def test_pendencia_do_briefing_para_antes_do_circuito(tmp_path):
    """Peça que a base não tem: o briefing registra, o usuário é avisado, nada é montado."""
    pendencia = ("registrar_pendencia", {"necessidade": "relé para a bomba d'água",
                                         "motivo": "a base não tem relé"})
    roteiro = Roteiro([_entregar(ENTREGA, pendencia)])
    fim, texto = _fluxo(tmp_path, roteiro, Usuario())
    assert fim.situacao == "pendencias" and fim.codigo == 1
    # O agente do circuito não rodou: só a conversa do briefing foi iniciada.
    assert roteiro.respostas == [] and len(roteiro.iniciados) == 1
    assert AVISO_DE_PENDENCIAS.format(n=1) in texto
    relatorio = _relatorio(tmp_path)
    assert "(briefing) **relé para a bomba d'água**: a base não tem relé" in relatorio
    assert "PARADO: há pendências" in relatorio
    assert not (tmp_path / "monitor-umidade" / "placa").exists()


def test_placa_que_o_pipeline_nao_faz_vira_pendencia(tmp_path):
    menor = entrega(**{"restricoes.contorno.largura": 50.0})
    roteiro = Roteiro([_entregar(menor)])
    fim, _ = _fluxo(tmp_path, roteiro, Usuario())
    assert fim.situacao == "pendencias"
    assert "contorno de 50 x 100 mm" in _relatorio(tmp_path)


def test_restricoes_incompativeis():
    referencia = especificacao_de_texto(ENTREGA, Path("x"), BASE)
    assert restricoes_incompativeis(referencia, referencia) == []
    outra = especificacao_de_texto(entrega(**{"restricoes.camadas.valor": 4,
                                              "restricoes.montagem.valor": "barra_pinos_femea"}),
                                   Path("x"), BASE)
    problemas = restricoes_incompativeis(outra, referencia)
    assert len(problemas) == 2 and "4 camada(s)" in problemas[0]


def test_pendencia_do_agente_bloqueia_a_fabrica(tmp_path):
    pendencia = Resposta(chamadas=chamadas(("registrar_pendencia", {
        "necessidade": "resistor de pull-up", "motivo": "a base não tem resistores"})))
    fabrica = FabricaFalsa()
    roteiro = Roteiro([_entregar(), montar_referencia(), pendencia, PRONTO])
    usuario = Usuario()
    fim, _ = _fluxo(tmp_path, roteiro, usuario, fabrica=fabrica)
    assert fim.situacao == "pendencias" and fabrica.chamadas == []
    assert PERGUNTA_DA_FABRICA not in usuario.lidos
    assert "(agente) **resistor de pull-up**" in _relatorio(tmp_path)


def test_falha_da_fabrica_nao_e_apresentada_como_pronta(tmp_path):
    fabrica = FabricaFalsa(ErroFabrica("conferencia", "FALHOU: Gerber de F.Cu"))
    fim, texto = _fluxo(tmp_path, Roteiro([_entregar(), montar_referencia(), PRONTO]),
                        Usuario(), fabrica=fabrica)
    assert fim.situacao == "falha_da_fabrica" and fim.codigo == 1
    assert "FALHOU: Gerber de F.Cu" in texto and "não está pronto para a fábrica" in texto
    assert "PRONTO:" not in _relatorio(tmp_path)


def test_sem_placa_para_depois_das_regras(tmp_path):
    saida: list[str] = []
    fluxo = Fluxo(Roteiro([_entregar(), montar_referencia(), PRONTO]), Usuario(),
                  saida.append, base=BASE, saida=tmp_path, custos=Custos(), placa=None)
    fim = fluxo.rodar(PEDIDO)
    assert fim.situacao == "sem_placa" and fim.codigo == 0
    assert "Etapa 2 de 3" in "\n".join(saida)
    assert "Não rodou" in _relatorio(tmp_path)


def test_briefing_sem_especificacao(tmp_path):
    roteiro = Roteiro([Resposta(texto="Não dá para fazer essa placa."),
                       Resposta(texto="Não dá."), Resposta(texto="Não."),
                       Resposta(texto="Não.")])
    fim, texto = _fluxo(tmp_path, roteiro, Usuario())
    assert fim.situacao == "sem_especificacao" and fim.codigo == 1
    assert "sem uma especificação aprovada" in texto


def test_execucao_anterior_nao_fica_misturada(tmp_path):
    antiga = tmp_path / "monitor-umidade" / "fabrica"
    antiga.mkdir(parents=True)
    (antiga / "velho.gbr").write_text("x", encoding="utf-8")
    fim, _ = _fluxo(tmp_path, Roteiro([_entregar(), montar_referencia(), PRONTO,
                                       Resposta(texto="Não sei.")]),
                    Usuario(), base=_sem_tensao_do_aout())
    assert fim.situacao == "reprovado" and not antiga.exists()


# --- Terminal ---------------------------------------------------------------------------------

def _main(tmp_path, roteiro, respostas, *extra):
    saida: list[str] = []
    codigo = projeto.main([PEDIDO, "--saida", str(tmp_path / "projetos"), "--custos",
                           str(tmp_path / "custos"), *extra], provedor=roteiro,
                          ler=Usuario(**respostas), escrever=saida.append)
    return codigo, "\n".join(saida)


def test_main_sem_placa_grava_custos(tmp_path):
    codigo, texto = _main(tmp_path, Roteiro([_entregar(), montar_referencia(), PRONTO]), {},
                          "--sem-placa")
    assert codigo == 0
    etapas = {l.etapa for l in ler(tmp_path / "custos" / "monitor-umidade.jsonl")}
    assert {"briefing", "agente", "motor_de_regras"} <= etapas
    assert "make custos PROJETO=monitor-umidade" in texto


def test_main_sem_kicad_para_antes_de_chamar_o_modelo(tmp_path, monkeypatch):
    monkeypatch.setattr(projeto.shutil, "which", lambda _: None)
    roteiro = Roteiro([])
    codigo, texto = _main(tmp_path, roteiro, {})
    assert codigo == 1 and roteiro.iniciados == []
    assert "kicad-cli" in texto and "nenhuma chamada ao modelo" in texto


def test_main_sem_tabelas_do_kicad_pede_make_configurar(tmp_path, monkeypatch):
    monkeypatch.setattr(projeto.shutil, "which", lambda _: "/usr/bin/kicad-cli")
    monkeypatch.setenv("HOME", str(tmp_path))
    codigo, texto = _main(tmp_path, Roteiro([]), {})
    assert codigo == 1 and "make configurar" in texto


def test_main_cancelado(tmp_path):
    def cancela(_):
        raise KeyboardInterrupt

    saida: list[str] = []
    codigo = projeto.main([PEDIDO, "--sem-placa", "--saida", str(tmp_path), "--custos",
                           str(tmp_path / "custos")],
                          provedor=Roteiro([_entregar()]), ler=cancela, escrever=saida.append)
    assert codigo == 130 and "Cancelado" in "\n".join(saida)


# --- Ponta a ponta de verdade (só no container) -----------------------------------------------

TEM_KICAD = (importlib.util.find_spec("pcbnew") is not None
             and importlib.util.find_spec("skidl") is not None
             and shutil.which("kicad-cli") is not None
             and not projeto.problemas_do_ambiente())


@pytest.mark.skipif(not TEM_KICAD, reason="precisa do SKiDL, do pcbnew, do kicad-cli e do make "
                                          "configurar (make testes, dentro do container)")
def test_ponta_a_ponta_de_verdade_gera_e_confere_os_arquivos_da_fabrica(tmp_path):
    """O agente é de roteiro, mas a placa, o roteamento, o DRC, os Gerbers, a furação, as
    posições, a BOM e a conferência dos arquivos são os de verdade."""
    from src.drc import conferir_placa
    from src.fabrica import gerar_fabrica
    saida: list[str] = []
    fluxo = Fluxo(Roteiro([_entregar(), montar_referencia(), PRONTO]), Usuario(),
                  saida.append, base=BASE, saida=tmp_path, custos=Custos(),
                  placa=conferir_placa, fabrica=gerar_fabrica)
    fim = fluxo.rodar(PEDIDO)
    assert fim.situacao == "fabrica", "\n".join(saida)
    f = fim.andamento.fabrica
    nomes = {a.name for a in f.arquivos}
    assert {"bom.csv", "posicoes.csv"} <= nomes
    assert sum(n.endswith(".gbrjob") for n in nomes) == 1
    assert sum(n.endswith(".drl") for n in nomes) == 1
    assert f.conferencia.startswith("OK:"), f.conferencia
    bom = (f.pasta / "bom.csv").read_text(encoding="utf-8")
    assert "esp32-devkitc-v4 J2" in bom and "display-lcd-1602-i2c" in bom
    relatorio = _relatorio(tmp_path)
    assert "`kicad-cli pcb drc`" in relatorio and "**0 item(ns)**" in relatorio
