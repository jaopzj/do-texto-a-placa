"""Testes do eval do fluxo completo (Marco 5, Parte 6; ADR-019), sem a API.

O modelo é um provedor de roteiro e a placa fica de fora (``--sem-placa``): o que se testa é
o eval (os pedidos, o usuário de roteiro, as injeções, a medida e o registro), não o modelo.
"""
import json
import shutil
from pathlib import Path

import pytest

from src.agente.ferramentas import Ferramentas
from src.agente.laco import Resposta
from src.aprovacao import PERGUNTA, PERGUNTA_DA_FABRICA
from src.componentes.carregar import carregar_todos
from src.evals import fluxo
from src.evals.fluxo import (INJECOES, MARCADOR, ErroInjecao, UsuarioDeRoteiro, ler_pedidos,
                             rodar_injecao, rodar_pedido)

from exemplo_briefing import ENTREGA
from exemplo_circuito import PRONTO, Roteiro, chamadas, montar_referencia

RAIZ = Path(__file__).resolve().parents[1]
BASE = carregar_todos()


def _entregar(*antes):
    return Resposta(chamadas=chamadas(*antes, ("entregar_especificacao",
                                               {"especificacao": ENTREGA})))


def test_pedidos_do_guia():
    """De três a cinco pedidos: a mesma placa com outras palavras, uma peça fora da base e um
    pedido impossível, que nunca pode esperar uma placa."""
    pedidos = ler_pedidos()
    assert 3 <= len(pedidos) <= 5
    tipos = [p.tipo for p in pedidos.values()]
    assert {"mesma_placa", "peca_fora_da_base", "impossivel"} <= set(tipos)
    assert pedidos["1-frase-do-guia"].pedido == ("quero um monitor de umidade do solo com "
                                                 "ESP32 e um LCD")
    for p in pedidos.values():
        if p.tipo != "mesma_placa":
            assert not {"fabrica", "sem_placa"} & set(p.esperado)


def test_usuario_de_roteiro():
    usuario = UsuarioDeRoteiro(["um LCD"])
    assert [usuario("> "), usuario("> "), usuario(PERGUNTA), usuario(PERGUNTA_DA_FABRICA)] == [
        "um LCD", "não sei", "s", "s"]
    assert usuario.perguntas == 2


def test_pedido_da_mesma_placa_passa(tmp_path):
    pedido = ler_pedidos()["1-frase-do-guia"]
    caso = rodar_pedido("1-frase-do-guia", pedido,
                        Roteiro([_entregar(), montar_referencia(), PRONTO]), BASE, tmp_path,
                        com_placa=False)
    assert caso.passou and caso.obtido == "sem_placa"
    assert (tmp_path / "monitor-umidade" / "relatorio.md").is_file()
    assert "Etapa 1 de 3" in (tmp_path / "terminal.txt").read_text(encoding="utf-8")


def test_peca_fora_da_base_passa_com_pendencia(tmp_path):
    pedido = ler_pedidos()["4-peca-fora-da-base"]
    pendencia = ("registrar_pendencia", {"necessidade": "relé", "motivo": "a base não tem"})
    caso = rodar_pedido("4", pedido, Roteiro([_entregar(pendencia)]), BASE, tmp_path, False)
    assert caso.passou and caso.obtido == "pendencias"


def test_pedido_impossivel_que_vira_placa_nao_passa(tmp_path):
    """Se o agente ignorar o pedido e montar a placa de referência, o eval reprova."""
    pedido = ler_pedidos()["5-impossivel"]
    caso = rodar_pedido("5", pedido, Roteiro([_entregar(), montar_referencia(), PRONTO]), BASE,
                        tmp_path, False)
    assert not caso.passou and caso.obtido == "sem_placa"


def test_erro_da_api_conta_como_caso_que_nao_passou(tmp_path):
    caso = rodar_pedido("1", ler_pedidos()["1-frase-do-guia"], Roteiro([]), BASE, tmp_path,
                        False)
    assert not caso.passou and caso.obtido == "erro" and "roteiro acabou" in caso.detalhe


@pytest.mark.parametrize("nome,correcao,regra", [
    ("tira-vcc-do-sensor", [("conectar", {"ref": "S1", "pino": "VCC", "rede": "+3V3"})],
     "alimentacao-ligada"),
    ("sensor-no-adc2", [("desconectar", {"ref": "U1", "pino": "IO25"}),
                        ("conectar", {"ref": "U1", "pino": "IO34", "rede": "SENSOR"})],
     "adc2-wifi"),
])
def test_erro_injetado_detectado_e_corrigido(tmp_path, nome, correcao, regra):
    roteiro = Roteiro([montar_referencia(), PRONTO, Resposta(chamadas=chamadas(*correcao)),
                       PRONTO])
    caso = rodar_injecao(nome, INJECOES[nome], roteiro, BASE, tmp_path, com_placa=False)
    assert caso.passou, caso
    assert regra in caso.detalhe and "1 correção" in caso.detalhe


def test_erro_injetado_que_o_agente_nao_corrige_nao_passa(tmp_path):
    roteiro = Roteiro([montar_referencia(), PRONTO, Resposta(texto="Não sei.")])
    caso = rodar_injecao("tira-vcc-do-sensor", INJECOES["tira-vcc-do-sensor"], roteiro, BASE,
                         tmp_path, com_placa=False)
    assert not caso.passou and caso.obtido.startswith("detectado, não corrigido")


def test_injecao_sem_o_que_estragar_e_erro():
    with pytest.raises(ErroInjecao):
        INJECOES["tira-vcc-do-sensor"](Ferramentas(BASE))


def test_main_registra_na_tabela_do_fluxo(tmp_path):
    evals_md = tmp_path / "evals.md"
    shutil.copy(RAIZ / "docs" / "evals.md", evals_md)
    roteiros = [Roteiro([_entregar(), montar_referencia(), PRONTO]),
                Roteiro([montar_referencia(), PRONTO,
                         Resposta(chamadas=chamadas(("conectar", {"ref": "S1", "pino": "VCC",
                                                                  "rede": "+3V3"}))), PRONTO])]
    saida: list[str] = []
    codigo = fluxo.main(["--sem-placa", "--so", "1-frase-do-guia", "--so",
                         "tira-vcc-do-sensor", "--saida", str(tmp_path / "saida"),
                         "--registrar", "--evals-md", str(evals_md)],
                        criar_provedor=lambda: roteiros.pop(0), escrever=saida.append)
    assert codigo == 0, "\n".join(saida)
    texto = evals_md.read_text(encoding="utf-8")
    depois = texto.split(MARCADOR, 1)[1]
    assert "(nenhuma rodada" not in depois
    assert "| 1-frase-do-guia | mesma_placa |" in depois
    assert "| tira-vcc-do-sensor | erro_injetado |" in depois
    # A tabela do eval do gabarito continua como estava.
    assert texto.split(MARCADOR, 1)[0] == (RAIZ / "docs" / "evals.md").read_text(
        encoding="utf-8").split(MARCADOR, 1)[0]
    [pasta] = (tmp_path / "saida").iterdir()
    resultados = json.loads((pasta / "resultados.json").read_text(encoding="utf-8"))
    assert [r["passou"] for r in resultados] == [True, True]


def test_main_recusa_caso_desconhecido(tmp_path):
    with pytest.raises(SystemExit):
        fluxo.main(["--so", "nao-existe", "--saida", str(tmp_path)],
                   criar_provedor=lambda: Roteiro([]), escrever=lambda _: None)
