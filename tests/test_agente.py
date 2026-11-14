"""Testes do laço do agente, dos contratos e do adaptador do Gemini (Marco 4, Parte 3).

Nenhum teste chama um modelo de IA. O laço roda com um provedor falso, que devolve
respostas escritas à mão, como o modelo devolveria. O adaptador do Gemini só é testado na
tradução das respostas, e o teste é pulado se a biblioteca google-genai não estiver
instalada.
"""
import pytest

from src.agente import ferramentas as mod_ferramentas
from src.agente.__main__ import SPEC, montar_pedido
from src.agente.contratos import CONTRATOS
from src.agente.ferramentas import FERRAMENTAS, Ferramentas
from src.agente.laco import SISTEMA, Chamada, Resposta, rodar_agente
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


# --- Adaptador do Gemini (só a tradução; nenhuma chamada à API) ---------------------------------

def test_gemini_traduz_texto_chamadas_e_tokens():
    types = pytest.importorskip("google.genai.types")
    from src.agente.provedores.gemini import traduzir
    resposta = types.GenerateContentResponse(
        candidates=[types.Candidate(content=types.Content(role="model", parts=[
            types.Part(text="Vou ligar o sensor."),
            types.Part(function_call=types.FunctionCall(
                name="conectar", args={"ref": "U3", "pino": 3, "rede": "SENSOR"})),
        ]))],
        usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=120, candidates_token_count=30))
    r = traduzir(resposta)
    assert r.texto == "Vou ligar o sensor."
    assert r.chamadas == (Chamada("conectar", {"ref": "U3", "pino": 3, "rede": "SENSOR"}),)
    assert (r.tokens_entrada, r.tokens_saida) == (120, 30)


def test_gemini_aceita_os_seis_contratos():
    types = pytest.importorskip("google.genai.types")
    declaracoes = [types.FunctionDeclaration(name=c["name"], description=c["description"],
                                             parameters_json_schema=c["parameters"])
                   for c in CONTRATOS]
    assert [d.name for d in declaracoes] == list(FERRAMENTAS)


def test_gemini_monta_a_conversa_sem_chamar_a_api():
    types = pytest.importorskip("google.genai.types")
    from src.agente.provedores.gemini import ProvedorGemini

    class Modelos:
        def __init__(self):
            self.pedidos = []

        def generate_content(self, model, contents, config):
            self.pedidos.append((model, list(contents), config))
            return types.GenerateContentResponse(candidates=[types.Candidate(
                content=types.Content(role="model", parts=[types.Part(text="ok")]))])

    class Cliente:
        models = Modelos()

    provedor = ProvedorGemini(cliente=Cliente())
    assert provedor.iniciar(SISTEMA, CONTRATOS, "pedido").texto == "ok"
    model, contents, config = Cliente.models.pedidos[0]
    assert config.system_instruction == SISTEMA
    assert config.automatic_function_calling.disable is True
    assert [d.name for d in config.tools[0].function_declarations] == list(FERRAMENTAS)
    provedor.continuar([(Chamada("buscar_componente", {"termo": "x"}), {"ok": False})])
    _, contents, _ = Cliente.models.pedidos[1]
    assert contents[-1].parts[0].function_response.name == "buscar_componente"
    assert contents[-1].parts[0].function_response.response == {"ok": False}
