"""Testes do laço do agente, dos contratos e do adaptador da Anthropic (Marco 4, Parte 3).

Nenhum teste chama um modelo de IA. O laço roda com um provedor falso, que devolve
respostas escritas à mão, como o modelo devolveria. O adaptador da Anthropic roda com um
cliente falso, e esses testes são pulados se a biblioteca anthropic não estiver instalada.
"""
import pytest

from src.agente import ferramentas as mod_ferramentas
from src.agente.__main__ import SPEC
from src.agente.contratos import CONTRATOS
from src.agente.ferramentas import FERRAMENTAS, Ferramentas
from src.agente.laco import SISTEMA, Chamada, Resposta, montar_pedido, rodar_agente
from src.componentes.carregar import carregar_todos

ENTRADAS = {
    "buscar_componente": mod_ferramentas._BuscarEntrada,
    "ler_dados_componente": mod_ferramentas._LerEntrada,
    "selecionar_componente": mod_ferramentas._SelecionarEntrada,
    "conectar": mod_ferramentas._ConectarEntrada,
    "registrar_decisao": mod_ferramentas._DecisaoEntrada,
    "registrar_pendencia": mod_ferramentas._PendenciaEntrada,
}


@pytest.fixture(scope="module")
def base():
    return carregar_todos()


class ProvedorFalso:
    """Devolve, em ordem, as respostas dadas; guarda o que o laço mandou."""

    def __init__(self, respostas: list[Resposta]):
        self.respostas = list(respostas)
        self.inicio = None
        self.resultados: list[list[tuple[Chamada, dict]]] = []

    def iniciar(self, sistema, contratos, pedido):
        self.inicio = (sistema, contratos, pedido)
        return self.respostas.pop(0)

    def continuar(self, resultados):
        self.resultados.append(resultados)
        return self.respostas.pop(0)


def _pede(*chamadas, **uso) -> Resposta:
    return Resposta(chamadas=tuple(Chamada(n, a) for n, a in chamadas), **uso)


# --- Contratos ------------------------------------------------------------------------------

def test_um_contrato_para_cada_ferramenta():
    assert [c["name"] for c in CONTRATOS] == list(FERRAMENTAS)


@pytest.mark.parametrize("contrato", CONTRATOS, ids=lambda c: c["name"])
def test_contrato_bate_com_os_argumentos_da_ferramenta(contrato):
    modelo = ENTRADAS[contrato["name"]]
    params = contrato["parameters"]
    assert params["type"] == "object"
    assert set(params["properties"]) == set(modelo.model_fields)
    obrigatorios = {n for n, campo in modelo.model_fields.items() if campo.is_required()}
    assert set(params["required"]) == obrigatorios
    assert contrato["description"].strip()


def test_contrato_da_decisao_lista_os_formatos_de_fonte():
    descricao = next(c for c in CONTRATOS if c["name"] == "registrar_decisao")["description"]
    assert all(f in descricao for f in mod_ferramentas.FORMATOS_DE_FONTE)


def test_prompt_proibe_inventar_e_manda_registrar_pendencia():
    assert "memória" in SISTEMA and "registrar_pendencia" in SISTEMA and "fonte" in SISTEMA


# --- Laço -------------------------------------------------------------------------------------

def test_laco_executa_as_ferramentas_e_termina(base):
    provedor = ProvedorFalso([
        _pede(("buscar_componente", {"termo": "umidade"}), tokens_entrada=10, tokens_saida=2),
        _pede(("selecionar_componente", {"id": "sensor-umidade-capacitivo", "ref": "U3"}),
              ("conectar", {"ref": "U3", "pino": "AOUT", "rede": "SENSOR"})),
        Resposta(texto="Pronto.", tokens_entrada=5, tokens_saida=1),
    ])
    execucao = rodar_agente("pedido", provedor, Ferramentas(base), registrar=None)
    assert execucao.terminou and execucao.texto_final == "Pronto."
    assert execucao.passos == 3 and len(execucao.chamadas) == 3
    assert execucao.estado["selecoes"] == {"U3": "sensor-umidade-capacitivo"}
    assert execucao.estado["redes"] == {"SENSOR": ["U3:3"]}
    assert (execucao.tokens_entrada, execucao.tokens_saida) == (15, 3)
    # O modelo recebeu o prompt, os contratos e o resultado de cada chamada.
    assert provedor.inicio == (SISTEMA, CONTRATOS, "pedido")
    assert provedor.resultados[0][0][1]["ok"] is True
    assert [s["ok"] for _, s in provedor.resultados[1]] == [True, True]


def test_erros_voltam_ao_modelo_sem_parar_o_laco(base):
    provedor = ProvedorFalso([
        _pede(("selecionar_componente", {"id": "CONVERSOR_NIVEL_I2C", "ref": "U4"}),
              ("criar_componente", {"id": "x"}),
              ("ler_dados_componente", {"nome": "LCD1602_I2C"})),
        _pede(("registrar_pendencia", {"necessidade": "conversor de nível",
                                       "motivo": "não está na base"})),
        Resposta(texto="Falta o conversor."),
    ])
    execucao = rodar_agente("pedido", provedor, Ferramentas(base), registrar=None)
    erros = [s["erro"] for _, s in provedor.resultados[0]]
    assert erros == ["componente_inexistente", "ferramenta_inexistente", "entrada_invalida"]
    assert execucao.terminou
    assert execucao.tentativas_inexistentes == ["CONVERSOR_NIVEL_I2C"]
    assert execucao.estado["selecoes"] == {}
    assert execucao.estado["pendencias"][0]["necessidade"] == "conversor de nível"


def test_limite_de_passos(base):
    pedido_sem_fim = [_pede(("buscar_componente", {"termo": "umidade"}))] * 5
    provedor = ProvedorFalso(pedido_sem_fim)
    execucao = rodar_agente("pedido", provedor, Ferramentas(base), max_passos=3,
                            registrar=None)
    assert not execucao.terminou
    assert execucao.passos == 3 and len(execucao.chamadas) == 3
    assert len(provedor.resultados) == 2      # não pede uma quarta resposta
    assert "Limite" in execucao.texto_final


def test_registro_do_laco(base):
    linhas = []
    provedor = ProvedorFalso([
        Resposta(texto="Vou buscar.", chamadas=(Chamada("buscar_componente", {"termo": "lcd"}),)),
        Resposta(texto="Fim."),
    ])
    rodar_agente("pedido", provedor, Ferramentas(base), registrar=linhas.append)
    assert linhas[0] == "[passo 1] PENSA: Vou buscar."
    assert linhas[1].startswith("[passo 1] AGE: buscar_componente(")
    assert linhas[2].startswith("[passo 1] OBSERVA: {'ok': True")
    assert linhas[3] == "[passo 2] PENSA: Fim."


def test_resposta_sem_texto_nem_chamadas(base):
    execucao = rodar_agente("pedido", ProvedorFalso([Resposta()]), Ferramentas(base),
                            registrar=None)
    assert execucao.terminou and execucao.texto_final


def test_pedido_leva_a_especificacao_inteira():
    pedido = montar_pedido(SPEC)
    assert SPEC.read_text(encoding="utf-8").strip() in pedido


# --- Adaptador da Anthropic (só a tradução e a conversa; nenhuma chamada à API) --------------

def _mensagem(conteudo, stop_reason="tool_use", **extra):
    beta = pytest.importorskip("anthropic.types.beta")
    return beta.BetaMessage.model_validate({
        "id": "msg_1", "type": "message", "role": "assistant", "model": "claude-opus-5-5",
        "content": conteudo, "stop_reason": stop_reason, "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 20, "cache_read_input_tokens": 50,
                  "cache_creation_input_tokens": 10}, **extra})


def test_claude_traduz_texto_chamadas_e_tokens():
    from src.agente.provedores.claude import traduzir
    r = traduzir(_mensagem([
        {"type": "thinking", "thinking": "", "signature": "x"},
        {"type": "text", "text": "Vou ligar o sensor."},
        {"type": "tool_use", "id": "toolu_1", "name": "conectar",
         "input": {"ref": "U3", "pino": 3, "rede": "SENSOR"}},
    ]))
    assert r.texto == "Vou ligar o sensor."
    assert r.chamadas == (Chamada("conectar", {"ref": "U3", "pino": 3, "rede": "SENSOR"},
                                  "toolu_1"),)
    assert (r.tokens_entrada, r.tokens_saida) == (160, 20)   # entrada inclui o cache


def test_claude_recusa_termina_sem_executar_ferramentas():
    from src.agente.provedores.claude import traduzir
    r = traduzir(_mensagem(
        [{"type": "tool_use", "id": "t", "name": "buscar_componente", "input": {"termo": "x"}}],
        stop_reason="refusal"))
    assert r.chamadas == () and "recusou" in r.texto


def test_claude_resposta_cortada_nao_executa_pedido_incompleto():
    from src.agente.provedores.claude import traduzir
    r = traduzir(_mensagem(
        [{"type": "tool_use", "id": "t", "name": "buscar_componente", "input": {}}],
        stop_reason="max_tokens"))
    assert r.chamadas == () and "limite" in r.texto


def test_claude_monta_a_conversa_sem_chamar_a_api():
    pytest.importorskip("anthropic")
    from src.agente.provedores.claude import MODELO, ProvedorClaude

    pedidos = []
    respostas = [
        _mensagem([{"type": "thinking", "thinking": "", "signature": "s"},
                   {"type": "tool_use", "id": "toolu_1", "name": "buscar_componente",
                    "input": {"termo": "umidade"}},
                   {"type": "tool_use", "id": "toolu_2", "name": "ler_dados_componente",
                    "input": {"id": "x"}}]),
        _mensagem([{"type": "text", "text": "Fim."}], stop_reason="end_turn"),
    ]

    class Mensagens:
        def create(self, **parametros):
            pedidos.append({**parametros, "messages": list(parametros["messages"])})
            return respostas.pop(0)

    class Cliente:
        class beta:
            messages = Mensagens()

    assert MODELO == "claude-haiku-5-5"                       # o padrão (ADR-014)
    provedor = ProvedorClaude("claude-opus-5-5", cliente=Cliente())
    primeira = provedor.iniciar(SISTEMA, CONTRATOS, "pedido")
    p = pedidos[0]
    assert p["model"] == "claude-opus-5-5"
    assert p["system"] == SISTEMA and p["thinking"] == {"type": "adaptive"}
    assert p["output_config"] == {"effort": "high"}
    assert p["fallbacks"] == "default" and p["betas"] == ["server-side-fallback-2026-07-01"]
    assert "temperature" not in p
    assert [f["name"] for f in p["tools"]] == list(FERRAMENTAS)
    assert p["tools"][0]["input_schema"] == CONTRATOS[0]["parameters"]
    assert p["messages"] == [{"role": "user", "content": "pedido"}]

    resultados = [(primeira.chamadas[0], {"ok": True, "encontrados": []}),
                  (primeira.chamadas[1], {"ok": False, "erro": "componente_inexistente"})]
    assert provedor.continuar(resultados).texto == "Fim."
    historico = pedidos[1]["messages"]
    # A resposta anterior volta inteira (com o bloco de raciocínio), e os dois resultados
    # voltam juntos, numa só mensagem, com is_error na recusa.
    assert historico[1]["role"] == "assistant"
    assert [b.type for b in historico[1]["content"]] == ["thinking", "tool_use", "tool_use"]
    blocos = historico[2]["content"]
    assert [b["tool_use_id"] for b in blocos] == ["toolu_1", "toolu_2"]
    assert [b["is_error"] for b in blocos] == [False, True]
    assert '"componente_inexistente"' in blocos[1]["content"]


def test_laco_com_o_adaptador_da_anthropic(base):
    """O laço inteiro com o adaptador real e um cliente falso."""
    pytest.importorskip("anthropic")
    from src.agente.provedores.claude import ProvedorClaude
    respostas = [
        _mensagem([{"type": "tool_use", "id": "t1", "name": "selecionar_componente",
                    "input": {"id": "sensor-umidade-capacitivo", "ref": "U3"}}]),
        _mensagem([{"type": "text", "text": "Selecionado."}], stop_reason="end_turn"),
    ]

    class Cliente:
        class beta:
            class messages:
                @staticmethod
                def create(**_):
                    return respostas.pop(0)

    execucao = rodar_agente("pedido", ProvedorClaude(cliente=Cliente()), Ferramentas(base),
                            registrar=None)
    assert execucao.terminou and execucao.texto_final == "Selecionado."
    assert execucao.estado["selecoes"] == {"U3": "sensor-umidade-capacitivo"}


def _cliente_que_guarda(pedidos):
    beta = pytest.importorskip("anthropic.types.beta")
    fim = beta.BetaMessage.model_validate({
        "id": "m", "type": "message", "role": "assistant", "model": "claude-haiku-5-5",
        "content": [{"type": "text", "text": "Fim."}], "stop_reason": "end_turn",
        "stop_sequence": None, "usage": {"input_tokens": 1, "output_tokens": 1}})

    class Mensagens:
        def create(self, **parametros):
            pedidos.append(parametros)
            return fim

    class Cliente:
        class beta:
            messages = Mensagens()
    return Cliente()


def test_haiku_vai_sem_modelo_reserva():
    # O Haiku 5.5 não tem modelo reserva no servidor: "fallbacks" no pedido dá erro 400.
    from src.agente.provedores.claude import ProvedorClaude
    pedidos = []
    ProvedorClaude("claude-haiku-5-5", _cliente_que_guarda(pedidos), "medium").iniciar(
        SISTEMA, CONTRATOS, "pedido")
    [p] = pedidos
    assert p["model"] == "claude-haiku-5-5" and p["output_config"] == {"effort": "medium"}
    assert "fallbacks" not in p and "betas" not in p
    assert p["thinking"] == {"type": "adaptive"}


def test_opus_e_sonnet_vao_com_modelo_reserva():
    from src.agente.provedores.claude import ProvedorClaude
    for modelo in ("claude-opus-5-5", "claude-sonnet-5-5"):
        pedidos = []
        ProvedorClaude(modelo, _cliente_que_guarda(pedidos)).iniciar(SISTEMA, CONTRATOS, "p")
        assert pedidos[0]["fallbacks"] == "default", modelo


def test_laco_avisa_cada_resposta_e_cada_chamada(base):
    from src.agente.laco import Evento
    provedor = ProvedorFalso([
        _pede(("buscar_componente", {"termo": "umidade"}),
              ("selecionar_componente", {"id": "nao-existe", "ref": "U9"}), custo_usd=0.01),
        Resposta(texto="Pronto.", custo_usd=0.02),
    ])
    eventos: list[Evento] = []
    rodar_agente("pedido", provedor, Ferramentas(base), registrar=None, eventos=eventos.append)
    assert [(e.tipo, e.passo) for e in eventos] == [
        ("resposta", 1), ("chamada", 1), ("chamada", 1), ("resposta", 2)]
    assert eventos[1].saida["ok"] and not eventos[2].saida["ok"]
    assert eventos[3].resposta.texto == "Pronto." and eventos[0].segundos >= 0


def test_main_do_agente_aceita_modelo_e_esforco(monkeypatch, capsys, tmp_path):
    import src.agente.provedores.claude as claude
    from src.agente import __main__ as principal
    criados = []

    def falso(modelo, esforco):
        criados.append((modelo, esforco))
        return ProvedorFalso([Resposta(texto="Nada a fazer.")])
    monkeypatch.setattr(claude, "ProvedorClaude", falso)
    assert principal.main(["--modelo", "claude-haiku-5-5", "--esforco", "low",
                           "--custos", str(tmp_path), "--saida", str(tmp_path)]) == 0
    assert criados == [("claude-haiku-5-5", "low")]
    from src.custos import ler
    resposta, motor = ler(tmp_path / "monitor-umidade.jsonl")
    assert (resposta.etapa, resposta.tipo, resposta.custo) == (
        "agente", "chamada_llm", "desconhecido")
    # O agente não ligou nada: o motor de regras não aprova um circuito vazio.
    assert (motor.etapa, motor.tipo, motor.custo) == ("motor_de_regras", "operacao", "sem_custo")
    assert (tmp_path / "monitor-umidade" / "estado.json").is_file()
    saida = capsys.readouterr().out
    assert "claude-haiku-5-5 · esforço low" in saida and "passo 1" in saida
    assert "=== RESPOSTA FINAL ===" in saida and "Nada a fazer." in saida
    assert "=== MOTOR DE REGRAS ===" in saida and "Nada verificado" in saida


# --- Laço genérico (conversar), usado também pelo briefing (Marco 5, ADR-016) ------------------

def test_conversar_com_outras_ferramentas_e_encerrar():
    from src.agente.laco import conversar
    feitas = []

    def executar(nome, argumentos):
        feitas.append(nome)
        return {"ok": True}

    provedor = ProvedorFalso([_pede(("a", {}), ("b", {})), _pede(("c", {})),
                              Resposta(texto="não deveria ser pedida")])
    execucao = conversar("pedido", provedor, "sistema", [{"name": "a"}], executar,
                         registrar=None, encerrar=lambda: "c" in feitas)
    assert provedor.inicio == ("sistema", [{"name": "a"}], "pedido")
    assert feitas == ["a", "b", "c"]
    assert execucao.terminou and execucao.passos == 2
    assert len(provedor.respostas) == 1            # parou sem pedir a terceira resposta
    assert execucao.estado == {}                   # quem conhece as ferramentas preenche


def test_conversar_sem_encerrar_segue_ate_o_modelo_parar():
    from src.agente.laco import conversar
    provedor = ProvedorFalso([_pede(("a", {})), Resposta(texto="Fim.")])
    execucao = conversar("p", provedor, "s", [], lambda n, a: {"ok": False}, registrar=None)
    assert execucao.terminou and execucao.texto_final == "Fim." and execucao.passos == 2


class ProvedorQueResponde(ProvedorFalso):
    """Também recebe texto (``responder``), como o adaptador da Anthropic."""

    def __init__(self, respostas):
        super().__init__(respostas)
        self.textos: list[str] = []

    def responder(self, texto):
        self.textos.append(texto)
        return self.respostas.pop(0)


def test_conversar_ao_parar_manda_lembrete_e_segue():
    from src.agente.laco import conversar
    feitas = []
    provedor = ProvedorQueResponde([Resposta(texto="Qual display?"), _pede(("a", {})),
                                    Resposta(texto="Fim.")])
    lembretes = iter(["use a ferramenta", None])
    execucao = conversar("p", provedor, "s", [], lambda n, a: feitas.append(n) or {"ok": True},
                         registrar=None, ao_parar=lambda _r: next(lembretes))
    assert provedor.textos == ["use a ferramenta"] and feitas == ["a"]
    assert execucao.terminou and execucao.texto_final == "Fim." and execucao.passos == 3


def test_conversar_ao_parar_respeita_o_limite_de_passos():
    from src.agente.laco import conversar
    provedor = ProvedorQueResponde([Resposta(texto="?")] * 5)
    execucao = conversar("p", provedor, "s", [], lambda n, a: {}, max_passos=3,
                         registrar=None, ao_parar=lambda _r: "lembrete")
    assert not execucao.terminou and execucao.passos == 3 and len(provedor.textos) == 2
    assert "Limite" in execucao.texto_final


def test_claude_responder_fecha_pedido_cortado_e_manda_o_texto():
    pytest.importorskip("anthropic")
    from src.agente.provedores.claude import ProvedorClaude

    pedidos = []
    respostas = [
        _mensagem([{"type": "tool_use", "id": "toolu_9", "name": "buscar_componente",
                    "input": {}}], stop_reason="max_tokens"),
        _mensagem([{"type": "text", "text": "Ok."}], stop_reason="end_turn"),
        _mensagem([{"type": "text", "text": "De novo."}], stop_reason="end_turn"),
    ]

    class Mensagens:
        def create(self, **parametros):
            pedidos.append({**parametros, "messages": list(parametros["messages"])})
            return respostas.pop(0)

    class Cliente:
        class beta:
            messages = Mensagens()

    provedor = ProvedorClaude(cliente=Cliente())
    assert provedor.iniciar("s", CONTRATOS, "pedido").chamadas == ()   # cortada
    assert provedor.responder("continue").texto == "Ok."
    ultima = pedidos[1]["messages"][-1]
    assert ultima["role"] == "user"
    assert [b["type"] for b in ultima["content"]] == ["tool_result", "text"]
    assert ultima["content"][0]["tool_use_id"] == "toolu_9" and ultima["content"][0]["is_error"]
    assert ultima["content"][1]["text"] == "continue"
    # Sem pedido pendente, vai só o texto.
    provedor.responder("mais uma")
    assert [b["type"] for b in pedidos[2]["messages"][-1]["content"]] == ["text"]


def test_claude_erro_da_api_vira_erro_provedor_e_tem_tempo_limite(monkeypatch):
    anthropic = pytest.importorskip("anthropic")
    from src.agente.laco import ErroProvedor
    from src.agente.provedores import claude

    class Mensagens:
        def create(self, **parametros):
            raise anthropic.APIConnectionError(message="Request timed out.", request=None)

    class Cliente:
        class beta:
            messages = Mensagens()

    with pytest.raises(ErroProvedor, match="APIConnectionError"):
        claude.ProvedorClaude(cliente=Cliente()).iniciar("s", CONTRATOS, "pedido")
    # O cliente de verdade sai com tempo limite e novas tentativas, não com o padrão de 10 min.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "chave-falsa-do-teste")
    real = claude.ProvedorClaude().cliente
    assert real.timeout == claude.TEMPO_LIMITE == 180.0
    assert real.max_retries == claude.TENTATIVAS


def test_claude_erro_que_nao_e_da_api_passa_direto():
    pytest.importorskip("anthropic")
    from src.agente.provedores.claude import ProvedorClaude

    class Mensagens:
        def create(self, **parametros):
            raise ValueError("bug nosso")

    class Cliente:
        class beta:
            messages = Mensagens()

    with pytest.raises(ValueError):
        ProvedorClaude(cliente=Cliente()).iniciar("s", CONTRATOS, "pedido")
