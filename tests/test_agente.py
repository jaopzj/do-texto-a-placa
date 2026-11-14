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

    provedor = ProvedorClaude(cliente=Cliente())
    primeira = provedor.iniciar(SISTEMA, CONTRATOS, "pedido")
    p = pedidos[0]
    assert p["model"] == MODELO == "claude-opus-5-5"
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
