"""Testes do briefing (Marco 5, Parte 1; ADR-016).

Nenhum teste chama um modelo de IA. O agente do briefing é um provedor falso, que devolve
respostas escritas à mão, e o usuário é uma lista de respostas. Estes testes só precisam do
Pydantic e do PyYAML, então também rodam no GitHub Actions.
"""

import pytest
import yaml

from src import briefing as mod
from src.agente.contratos import CONTRATOS as CONTRATOS_DO_AGENTE
from src.agente.ferramentas import Ferramentas
from src.agente.laco import Chamada, Resposta, montar_pedido as pedido_do_agente, rodar_agente
from src.aprovacao import Veredito
from src.briefing import (CONTRATOS, FERRAMENTAS, MAX_PERGUNTAS, PADROES, RAIZ, SISTEMA,
                          Briefing, Pergunta, conduzir_briefing, main, nao_sabe, para_yaml,
                          salvar, validar)
from src.componentes.carregar import carregar_todos
from src.especificacao import Especificacao, ler_especificacao

from exemplo_briefing import ENTREGA, entrega as _entrega

@pytest.fixture(scope="module")
def base():
    return carregar_todos()


class ProvedorFalso:
    """Devolve, em ordem, as respostas dadas; guarda o que o laço mandou."""

    def __init__(self, respostas: list[Resposta]):
        self.respostas = list(respostas)
        self.inicio = None
        self.resultados: list[list[tuple[Chamada, dict]]] = []
        self.textos: list[str] = []

    def iniciar(self, sistema, contratos, pedido):
        self.inicio = (sistema, contratos, pedido)
        return self.respostas.pop(0)

    def continuar(self, resultados):
        self.resultados.append(resultados)
        return self.respostas.pop(0)

    def responder(self, texto):
        self.textos.append(texto)
        return self.respostas.pop(0)


def _pede(*chamadas, texto="") -> Resposta:
    return Resposta(texto=texto, chamadas=tuple(Chamada(n, a) for n, a in chamadas))


class Usuario:
    """Responde às perguntas e às aprovações com listas escritas no teste."""

    def __init__(self, respostas=(), vereditos=()):
        self.respostas = list(respostas)
        self.vereditos = list(vereditos)
        self.perguntas: list[tuple[str, int, int]] = []
        self.resumos: list[tuple[Especificacao, list]] = []

    def perguntar(self, pergunta, numero, maximo):
        self.perguntas.append((pergunta, numero, maximo))
        return self.respostas.pop(0)

    def aprovar(self, spec, pendencias):
        self.resumos.append((spec, pendencias))
        return self.vereditos.pop(0)


def _briefing(base, usuario: Usuario) -> Briefing:
    return Briefing(usuario.perguntar, usuario.aprovar, base)


# --- Contratos e prompt -----------------------------------------------------------------------

def test_um_contrato_para_cada_ferramenta():
    assert [c["name"] for c in CONTRATOS] == list(FERRAMENTAS)


def test_reaproveita_os_contratos_do_agente_sem_copiar():
    do_agente = {c["name"]: c for c in CONTRATOS_DO_AGENTE}
    for c in CONTRATOS:
        if c["name"] in mod.DA_BASE:
            assert c is do_agente[c["name"]]
    # O briefing não seleciona nem liga peças: isso é do agente do Marco 4.
    assert not {"selecionar_componente", "conectar", "registrar_decisao"} & set(FERRAMENTAS)


@pytest.mark.parametrize("nome,modelo", [("perguntar_usuario", mod._PerguntaEntrada),
                                         ("entregar_especificacao", mod._EntregaEntrada)])
def test_contrato_bate_com_os_argumentos(nome, modelo):
    params = next(c for c in CONTRATOS if c["name"] == nome)["parameters"]
    assert set(params["properties"]) == set(modelo.model_fields)
    obrigatorios = {n for n, campo in modelo.model_fields.items() if campo.is_required()}
    assert set(params["required"]) == obrigatorios


def test_prompt_explica_formato_perguntas_tipicas_e_limite():
    assert f"no máximo {MAX_PERGUNTAS}" in SISTEMA
    for termo in ("microcontrolador", "alimentada", "display", "tamanho", "não sei",
                  "memória", "registrar_pendencia", "decidido_por"):
        assert termo in SISTEMA
    # O formato vem do próprio modelo Pydantic: todo campo da especificação aparece.
    for campo in ("projeto", "modulos", "alimentacao", "restricoes", "montagem",
                  "barra_pinos_macho", "usb_do_devkit"):
        assert campo in SISTEMA


def test_padroes_citam_documentos_que_existem():
    for caminho, (_valor, _motivo, documento) in PADROES.items():
        assert caminho in mod.FIXOS
        assert (RAIZ / documento).is_file(), documento


# --- "Não sei" --------------------------------------------------------------------------------

@pytest.mark.parametrize("resposta", ["não sei", "Não sei, talvez USB", "NAO SEI!", "", "   ",
                                      "sei lá", "Tanto faz.", "você decide"])
def test_nao_sei(resposta):
    assert nao_sabe(resposta)


@pytest.mark.parametrize("resposta", ["sim", "pelo USB", "não, quero bateria",
                                      "não seria melhor um OLED?", "um LCD 16x2"])
def test_resposta_que_nao_e_nao_sei(resposta):
    assert not nao_sabe(resposta)


# --- Validação da entrega ---------------------------------------------------------------------

def test_entrega_valida(base):
    spec, problemas = validar(ENTREGA, base, [])
    assert problemas == [] and spec is not None
    assert [m.componente for m in spec.modulos] == [
        "esp32-devkitc-v4", "sensor-umidade-capacitivo", "display-lcd-1602-i2c",
        "conversor-nivel-logico-4-canais"]


def test_entrega_com_cerca_de_markdown(base):
    assert validar(f"```yaml\n{ENTREGA.strip()}\n```\n", base, [])[1] == []
    assert validar(f"```\n{ENTREGA}```", base, [])[1] == []


def test_entrega_parecida_com_o_spec_de_referencia(base):
    # Mesmas peças, nos mesmos papéis, e mesmas restrições do spec.yaml escrito à mão.
    referencia = ler_especificacao(RAIZ / "placas" / "monitor-umidade" / "spec.yaml", base)
    spec, _ = validar(ENTREGA, base, [])
    assert ({(m.papel, m.componente) for m in spec.modulos}
            == {(m.papel, m.componente) for m in referencia.modulos})
    assert spec.restricoes.model_dump(include={"camadas": {"valor"}, "montagem": {"valor"}}) \
        == referencia.restricoes.model_dump(include={"camadas": {"valor"}, "montagem": {"valor"}})


@pytest.mark.parametrize("texto,trecho", [
    ("projeto: [", "YAML inválido"),
    ("- uma lista", "mapa de campos"),
    (_entrega(**{"modulos.2.componente": "lcd-oled-128x64"}), "não está na base"),
    (_entrega(**{"alimentacao.tensao": "5.0"}), "alimentacao.tensao"),
    (_entrega(**{"restricoes.camadas.motivo": None}), "motivo"),
    (_entrega(**{"modulos.3.regras": [{"componente": "esp32-devkitc-v4", "regra": "inventada"}]}),
     "não tem a regra"),
    (_entrega(**{"projeto.cor": "verde"}), "projeto.cor"),
])
def test_entrega_invalida_pelo_modelo_e_pela_base(base, texto, trecho):
    spec, problemas = validar(texto, base, [])
    assert spec is None
    assert any(trecho in p for p in problemas), problemas


@pytest.mark.parametrize("documento", ["datasheet do ESP32", "componentes/nao-existe.yaml",
                                       "/etc/passwd", "../fora-do-repositorio.md",
                                       "componentes"])
def test_fonte_do_agente_precisa_existir(base, documento):
    texto = _entrega(**{"restricoes.camadas.fonte": {"documento": documento}})
    spec, problemas = validar(texto, base, [])
    assert spec is None
    assert any(p.startswith("restricoes.camadas.fonte.documento") for p in problemas)


def test_fonte_pode_ser_documento_citado_pela_base(base):
    texto = _entrega(**{"restricoes.camadas.fonte": {
        "documento": "esp-dev-kits-en-master-esp32.pdf", "pagina": 5}})
    assert validar(texto, base, [])[1] == []


def test_fonte_do_usuario_nao_e_conferida(base):
    # Decisão do usuário não exige fonte (ADR-009); a fonte dela é o próprio pedido.
    texto = _entrega(**{"alimentacao.fonte": {"documento": "o que o usuário disse"}})
    assert validar(texto, base, [])[1] == []


def _nao_sei(*sobre) -> Pergunta:
    return Pergunta("Pergunta?", tuple(sobre), "não sei", True)


def test_nao_sei_obriga_a_decisao_do_agente(base):
    texto = _entrega(**{"restricoes.montagem.decidido_por": "usuario"})
    spec, problemas = validar(texto, base, [_nao_sei("restricoes.montagem")])
    assert spec is None
    assert len(problemas) == 1 and problemas[0].startswith("restricoes.montagem:")
    # Sem "não sei", a mesma entrega passa.
    assert validar(texto, base, [Pergunta("?", ("restricoes.montagem",), "macho", False)])[1] == []


def test_nao_sei_sobre_modulo(base):
    perguntas = [_nao_sei("modulo:Display")]       # papel comparado sem maiúsculas
    spec, problemas = validar(ENTREGA, base, perguntas)
    assert spec is None and problemas[0].startswith("modulos.2:")
    texto = _entrega(**{"modulos.2.decidido_por": "agente", "modulos.2.motivo": "padrão",
                        "modulos.2.fonte": {"documento": "componentes/display-lcd-1602-i2c.yaml"}})
    assert validar(texto, base, perguntas)[1] == []


def test_nao_sei_sobre_modulo_que_nao_existe(base):
    spec, problemas = validar(ENTREGA, base, [_nao_sei("modulo:tela")])
    assert spec is None and "nenhum módulo tem esse papel" in problemas[0]


def test_nao_sei_sobre_o_projeto_nao_e_decisao(base):
    assert validar(ENTREGA, base, [_nao_sei("projeto")])[1] == []


# --- Ferramentas do briefing ------------------------------------------------------------------

def test_pergunta_chega_ao_usuario(base):
    usuario = Usuario(respostas=["pelo USB do DevKit"])
    b = _briefing(base, usuario)
    saida = b.executar_ferramenta("perguntar_usuario", {
        "pergunta": " Como a placa é alimentada? ", "sobre": ["alimentacao"]})
    assert saida == {"ok": True, "resposta": "pelo USB do DevKit", "nao_sabe": False,
                     "perguntas_restantes": MAX_PERGUNTAS - 1}
    assert usuario.perguntas == [("Como a placa é alimentada?", 1, MAX_PERGUNTAS)]
    assert b.perguntas == [Pergunta("Como a placa é alimentada?", ("alimentacao",),
                                    "pelo USB do DevKit", False)]


def test_pergunta_com_nao_sei_instrui_o_agente(base):
    b = _briefing(base, Usuario(respostas=[""]))
    saida = b.executar_ferramenta("perguntar_usuario",
                                  {"pergunta": "Que tamanho?", "sobre": ["restricoes.contorno"]})
    assert saida["ok"] and saida["nao_sabe"] and "decidido_por: agente" in saida["instrucao"]
    assert saida["resposta"] == "(sem resposta)"


def test_limite_de_perguntas_conferido_pelo_codigo(base):
    usuario = Usuario(respostas=["sim"] * (MAX_PERGUNTAS + 1))
    b = _briefing(base, usuario)
    pergunta = {"pergunta": "Mais uma?", "sobre": ["projeto"]}
    saidas = [b.executar_ferramenta("perguntar_usuario", pergunta)
              for _ in range(MAX_PERGUNTAS + 1)]
    assert all(s["ok"] for s in saidas[:MAX_PERGUNTAS])
    assert saidas[-1]["erro"] == "limite_de_perguntas"
    assert len(usuario.perguntas) == MAX_PERGUNTAS == len(b.perguntas)


@pytest.mark.parametrize("entrada", [
    {"pergunta": "?"},
    {"pergunta": "?", "sobre": []},
    {"pergunta": "?", "sobre": ["cor"]},
    {"pergunta": "?", "sobre": ["modulo:"]},
    {"pergunta": " ", "sobre": ["projeto"]},
    {"pergunta": "?", "sobre": ["projeto"], "extra": 1},
    "não é um mapa",
])
def test_pergunta_invalida_nao_chega_ao_usuario(base, entrada):
    usuario = Usuario()
    b = _briefing(base, usuario)
    saida = b.executar_ferramenta("perguntar_usuario", entrada)
    assert saida["ok"] is False and saida["erro"] == "entrada_invalida"
    assert usuario.perguntas == [] and b.perguntas == []


def test_ferramentas_da_base_sao_as_do_agente(base):
    b = _briefing(base, Usuario())
    achou = b.executar_ferramenta("buscar_componente", {"termo": "lcd"})
    assert [c["id"] for c in achou["encontrados"]] == ["display-lcd-1602-i2c"]
    assert b.executar_ferramenta("ler_dados_componente", {"id": "x"})["erro"] == \
        "componente_inexistente"
    assert b.executar_ferramenta("registrar_pendencia", {
        "necessidade": "buzzer", "motivo": "o usuário pediu alarme"})["ok"]
    assert [p.necessidade for p in b.pendencias] == ["buzzer"]


@pytest.mark.parametrize("nome", ["selecionar_componente", "conectar", "apagar_tudo"])
def test_ferramenta_fora_do_briefing(base, nome):
    saida = _briefing(base, Usuario()).executar_ferramenta(nome, {})
    assert saida["erro"] == "ferramenta_inexistente" and saida["ferramentas"] == list(FERRAMENTAS)


def test_entrega_invalida_volta_ao_agente_sem_ir_ao_usuario(base):
    usuario = Usuario()
    b = _briefing(base, usuario)
    saida = b.executar_ferramenta("entregar_especificacao",
                                  {"especificacao": _entrega(**{"projeto.id": "Monitor"})})
    assert saida["ok"] is False and saida["erro"] == "especificacao_invalida"
    assert any(p.startswith("projeto.id") for p in saida["problemas"])
    assert usuario.resumos == [] and len(b.entregas_invalidas) == 1 and not b.aprovada


def test_entrega_valida_vai_para_a_aprovacao(base):
    usuario = Usuario(vereditos=[Veredito(False, "a placa tem 80 x 60 mm"), Veredito(True)])
    b = _briefing(base, usuario)
    b.executar_ferramenta("registrar_pendencia", {"necessidade": "buzzer", "motivo": "alarme"})
    primeira = b.executar_ferramenta("entregar_especificacao", {"especificacao": ENTREGA})
    assert primeira["erro"] == "correcao_do_usuario"
    assert primeira["correcao"] == "a placa tem 80 x 60 mm" and not b.aprovada
    assert [p.necessidade for p in usuario.resumos[0][1]] == ["buzzer"]
    segunda = b.executar_ferramenta("entregar_especificacao", {"especificacao": ENTREGA})
    assert segunda == {"ok": True, "aprovada": True} and b.aprovada
    assert b.correcoes == ["a placa tem 80 x 60 mm"]
    # Depois de aprovada, a especificação não muda mais.
    assert b.executar_ferramenta("entregar_especificacao",
                                 {"especificacao": ENTREGA})["erro"] == "ja_aprovada"
    assert len(usuario.resumos) == 2


# --- O briefing inteiro, com o laço -----------------------------------------------------------

def test_briefing_completo_com_nao_sei_erro_e_correcao(base):
    pedido = "quero um monitor de umidade do solo com ESP32 e um LCD"
    montagem = {"pergunta": "O ESP32 vai encaixado em barra de pinos ou soldado?",
                "sobre": ["restricoes.montagem", "modulo:microcontrolador"]}
    menor = _entrega(**{"restricoes.contorno": {
        "largura": 80.0, "altura": 60.0, "decidido_por": "usuario"},
        "modulos.0.decidido_por": "agente", "modulos.0.motivo": "o usuário não sabe",
        "modulos.0.fonte": {"documento": "componentes/esp32-devkitc-v4.yaml"}})
    provedor = ProvedorFalso([
        _pede(("buscar_componente", {"termo": "esp32"}), ("buscar_componente", {"termo": "lcd"})),
        _pede(("perguntar_usuario", montagem), texto="Preciso saber da montagem."),
        # O agente esquece que o usuário não sabia: o código recusa.
        _pede(("entregar_especificacao", {"especificacao": ENTREGA})),
        _pede(("entregar_especificacao", {"especificacao": _entrega(**{
            "modulos.0.decidido_por": "agente", "modulos.0.motivo": "o usuário não sabe",
            "modulos.0.fonte": {"documento": "componentes/esp32-devkitc-v4.yaml"}})})),
        # O usuário corrige o tamanho; o agente entrega de novo.
        _pede(("entregar_especificacao", {"especificacao": menor})),
    ])
    usuario = Usuario(respostas=["não sei"], vereditos=[
        Veredito(False, "a placa precisa ter 80 x 60 mm"), Veredito(True)])
    b = _briefing(base, usuario)
    resultado = conduzir_briefing(pedido, provedor, b)

    assert resultado.execucao.terminou and resultado.execucao.passos == 5
    assert provedor.respostas == []          # parou na aprovação, sem pedir outra resposta
    sistema, contratos, primeiro = provedor.inicio
    assert sistema == SISTEMA and contratos == CONTRATOS and pedido in primeiro
    invalida = provedor.resultados[2][0][1]
    assert invalida["erro"] == "especificacao_invalida"
    assert any("respondeu 'não sei'" in p for p in invalida["problemas"])
    correcao = provedor.resultados[3][0][1]
    assert correcao["erro"] == "correcao_do_usuario"
    spec = resultado.especificacao
    assert (spec.restricoes.contorno.largura, spec.restricoes.contorno.altura) == (80.0, 60.0)
    assert spec.modulos[0].decidido_por == "agente"
    assert len(b.perguntas) == 1 and len(b.entregas_invalidas) == 1 and len(b.correcoes) == 1


def test_agente_que_pergunta_em_texto_solto_recebe_lembrete_e_continua(base):
    # O travamento visto na primeira execução real: o modelo escreve a pergunta em texto, em
    # vez de usar perguntar_usuario, e o briefing acabava ali, sem especificação.
    provedor = ProvedorFalso([
        Resposta(texto="Qual display você quer?"),
        _pede(("perguntar_usuario", {"pergunta": "Qual display você quer?",
                                     "sobre": ["modulo:display"]})),
        _pede(("entregar_especificacao", {"especificacao": ENTREGA})),
    ])
    usuario = Usuario(respostas=["um LCD 16x2"], vereditos=[Veredito(True)])
    b = _briefing(base, usuario)
    resultado = conduzir_briefing("uma placa", provedor, b)
    assert resultado.especificacao is not None and provedor.respostas == []
    assert len(provedor.textos) == 1 and "não chegou ao usuário" in provedor.textos[0]
    assert "perguntar_usuario (restam 6" in provedor.textos[0]
    assert usuario.perguntas[0][0] == "Qual display você quer?" and b.lembretes == 1


def test_lembretes_seguidos_tem_limite(base):
    provedor = ProvedorFalso([Resposta(texto="Qual display você quer?")] * (mod.MAX_LEMBRETES + 1))
    b = _briefing(base, Usuario())
    resultado = conduzir_briefing("uma placa", provedor, b)
    assert resultado.especificacao is None and resultado.execucao.terminou
    assert resultado.execucao.texto_final == "Qual display você quer?"
    assert len(provedor.textos) == mod.MAX_LEMBRETES == b.lembretes
    assert provedor.respostas == []


def test_ferramenta_zera_os_lembretes_seguidos(base):
    b = _briefing(base, Usuario())
    for _ in range(mod.MAX_LEMBRETES):
        assert b.ao_parar(Resposta(texto="?")) is not None
        b.executar_ferramenta("buscar_componente", {"termo": "lcd"})
    assert b.ao_parar(Resposta(texto="?")) is not None and b.lembretes == mod.MAX_LEMBRETES + 1


def test_lembrete_depois_do_limite_de_perguntas_manda_decidir(base):
    b = _briefing(base, Usuario(respostas=["x"] * MAX_PERGUNTAS))
    for _ in range(MAX_PERGUNTAS):
        b.executar_ferramenta("perguntar_usuario", {"pergunta": "?", "sobre": ["projeto"]})
    assert "limite de perguntas acabou" in b.ao_parar(Resposta(texto="?"))


def test_sem_lembrete_depois_de_aprovada(base):
    b = _briefing(base, Usuario(vereditos=[Veredito(True)]))
    b.executar_ferramenta("entregar_especificacao", {"especificacao": ENTREGA})
    assert b.aprovada and b.ao_parar(Resposta(texto="Pronto.")) is None


def test_limite_de_passos_do_briefing(base):
    provedor = ProvedorFalso([_pede(("buscar_componente", {"termo": "x"}))] * 4)
    resultado = conduzir_briefing("uma placa", provedor, _briefing(base, Usuario()),
                                  max_passos=3)
    assert resultado.especificacao is None and not resultado.execucao.terminou


# --- Gravação e integração com o agente do Marco 4 --------------------------------------------

def _aprovado(base, texto=ENTREGA):
    provedor = ProvedorFalso([_pede(("entregar_especificacao", {"especificacao": texto}))])
    return conduzir_briefing("quero um monitor", provedor,
                             _briefing(base, Usuario(vereditos=[Veredito(True)])))


def test_yaml_gravado_volta_igual(base):
    spec, _ = validar(ENTREGA, base, [])
    assert validar(para_yaml(spec), base, [])[0] == spec


def test_salvar_e_o_agente_do_m4_aceita(base, tmp_path):
    arquivo = salvar(_aprovado(base), tmp_path)
    assert arquivo == tmp_path / "monitor-umidade" / "spec.yaml"
    assert arquivo.read_text(encoding="utf-8").startswith("# Especificação gerada pelo briefing")
    spec = ler_especificacao(arquivo, base)
    assert spec == validar(ENTREGA, base, [])[0]
    conversa = yaml.safe_load((arquivo.parent / "briefing.yaml").read_text(encoding="utf-8"))
    assert conversa["pedido"] == "quero um monitor" and conversa["correcoes"] == []
    assert conversa["versao_do_prompt"] == mod.VERSAO_DO_PROMPT

    # A especificação do briefing é a entrada do agente do Marco 4, como o spec.yaml.
    ferramentas = Ferramentas(base, spec)
    provedor = ProvedorFalso([
        _pede(("registrar_decisao", {"decisao": "conversor entre LCD e ESP32",
                                     "motivo": "níveis lógicos", "fonte": "especificacao:modulos.3"})),
        Resposta(texto="Pronto."),
    ])
    execucao = rodar_agente(pedido_do_agente(arquivo), provedor, ferramentas, registrar=None)
    assert execucao.terminou and provedor.resultados[0][0][1]["ok"]
    assert "monitor-umidade" in provedor.inicio[2]


def test_so_grava_especificacao_aprovada(base, tmp_path):
    provedor = ProvedorFalso([Resposta(texto="desisto")] * (mod.MAX_LEMBRETES + 1))
    resultado = conduzir_briefing("x", provedor, _briefing(base, Usuario()))
    with pytest.raises(ValueError):
        salvar(resultado, tmp_path)
    assert list(tmp_path.iterdir()) == []


# --- Terminal (main) --------------------------------------------------------------------------

class Teclado:
    """O ``input`` do terminal: devolve as linhas dadas e depois o fim da entrada."""

    def __init__(self, linhas):
        self.linhas = list(linhas)
        self.prompts = []

    def __call__(self, prompt=""):
        self.prompts.append(prompt)
        if not self.linhas:
            raise EOFError
        return self.linhas.pop(0)


def _rodar_main(tmp_path, respostas, linhas, argumentos=("quero um monitor",)):
    saida = []
    codigo = main([*argumentos, "--saida", str(tmp_path)], provedor=ProvedorFalso(respostas),
                  ler=Teclado(linhas), escrever=saida.append)
    return codigo, "\n".join(saida)


def test_main_aprova_e_grava(tmp_path):
    respostas = [_pede(("perguntar_usuario", {"pergunta": "Que display?",
                                              "sobre": ["modulo:display"]})),
                 _pede(("entregar_especificacao", {"especificacao": ENTREGA}))]
    codigo, texto = _rodar_main(tmp_path, respostas, ["um LCD 16x2", "", "s"])
    assert codigo == 0
    assert "Pergunta 1 de 6: Que display?" in texto
    assert "Componentes escolhidos" in texto and "Especificação aprovada e gravada" in texto
    # Depois de cada resposta, o terminal avisa que está esperando o agente.
    assert texto.count(mod.AGUARDE) == 2              # no começo e depois da pergunta
    assert "AGE: perguntar_usuario" in (tmp_path / mod.REGISTRO).read_text(encoding="utf-8")
    assert (tmp_path / "monitor-umidade" / "spec.yaml").is_file()


def test_main_pede_o_pedido_quando_falta(tmp_path):
    respostas = [_pede(("entregar_especificacao", {"especificacao": ENTREGA}))]
    teclado = Teclado(["quero um monitor", "s"])
    codigo = main(["--saida", str(tmp_path)], provedor=ProvedorFalso(respostas), ler=teclado,
                  escrever=lambda _l: None)
    assert codigo == 0 and teclado.prompts[0].startswith("Descreva a placa")


def test_main_sem_pedido(tmp_path):
    codigo, texto = _rodar_main(tmp_path, [], ["  "], argumentos=())
    assert codigo == 1 and "Nenhum pedido" in texto


def test_main_cancelado_nao_grava(tmp_path):
    respostas = [_pede(("entregar_especificacao", {"especificacao": ENTREGA}))]
    codigo, texto = _rodar_main(tmp_path, respostas, [])     # fim da entrada na aprovação
    assert codigo == 130 and "cancelado" in texto
    assert [a.name for a in tmp_path.iterdir()] == [mod.REGISTRO]   # nenhuma especificação


def test_main_sem_aprovacao(tmp_path):
    codigo, texto = _rodar_main(tmp_path, [Resposta(texto="Não consigo.")] * 4, [])
    assert codigo == 1 and "sem uma especificação aprovada" in texto and "Não consigo." in texto
    assert [a.name for a in tmp_path.iterdir()] == [mod.REGISTRO]
    registro = (tmp_path / mod.REGISTRO).read_text(encoding="utf-8")
    assert registro.count("LEMBRETE:") == mod.MAX_LEMBRETES and "O registro completo" in texto


def test_contratos_do_briefing_viram_ferramentas_da_api():
    """O adaptador da Anthropic aceita os contratos do briefing sem mudança (ADR-011)."""
    pytest.importorskip("anthropic")
    from src.agente.provedores.claude import ProvedorClaude

    class Parar(Exception):
        pass

    pedidos = []

    class Mensagens:
        def create(self, **kwargs):
            pedidos.append(kwargs)
            raise Parar

    class Cliente:
        class beta:
            messages = Mensagens()

    with pytest.raises(Parar):
        ProvedorClaude(cliente=Cliente()).iniciar(SISTEMA, CONTRATOS, "pedido")
    ferramentas = pedidos[0]["tools"]
    assert [f["name"] for f in ferramentas] == list(FERRAMENTAS)
    assert all(f["input_schema"] == c["parameters"] for f, c in zip(ferramentas, CONTRATOS))
    assert pedidos[0]["system"] == SISTEMA


def test_main_falha_da_api_sem_traceback(tmp_path):
    from src.agente.laco import ErroProvedor

    class ProvedorQueFalha(ProvedorFalso):
        def continuar(self, resultados):
            raise ErroProvedor("APITimeoutError: Request timed out.")

    provedor = ProvedorQueFalha([_pede(("perguntar_usuario", {"pergunta": "Que display?",
                                                              "sobre": ["modulo:display"]}))])
    saida = []
    codigo = main(["placa", "--saida", str(tmp_path)], provedor=provedor,
                  ler=Teclado(["LCD"]), escrever=saida.append)
    texto = "\n".join(saida)
    assert codigo == 1 and "A API do modelo falhou: APITimeoutError" in texto
    assert [a.name for a in tmp_path.iterdir()] == [mod.REGISTRO]
    assert "OBSERVA: {'ok': True, 'resposta': 'LCD'" in (tmp_path / mod.REGISTRO).read_text(
        encoding="utf-8")
