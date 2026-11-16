"""Testes do registro de custos (Marco 5; ADR-017). Não chamam o modelo."""
import json
from datetime import datetime, timezone

import pytest

from src import custos as modulo
from src.agente.laco import Chamada, Evento, Resposta, conversar
from src.agente.provedores.claude import FONTE_DOS_PRECOS, custo
from src.custos import Custos, ErroCustos, ler, resumir

HAIKU = "claude-haiku-5-5"


def _resposta(modelo=HAIKU, entrada=1000, saida=200, chamadas=()):
    valor = custo(modelo, entrada, saida, 0, 0)
    return Resposta(chamadas=tuple(chamadas), tokens_entrada=entrada, tokens_saida=saida,
                    custo_usd=valor, modelo=modelo,
                    custo_fonte=FONTE_DOS_PRECOS if valor is not None else None)


def _relogio():
    return datetime(2026, 11, 16, 12, 0, tzinfo=timezone.utc)


def test_chamada_com_preco_conhecido_e_calculada():
    c = Custos("monitor-umidade", "exec1", agora=_relogio)
    l = c.chamada("briefing", _resposta(), segundos=1.23456, passo=1)
    assert (l.tipo, l.custo, l.modelo, l.passo) == ("chamada_llm", "calculado", HAIKU, 1)
    assert l.custo_usd == custo(HAIKU, 1000, 200, 0, 0) and l.custo_usd > 0
    assert l.tabela_de_precos == FONTE_DOS_PRECOS and l.segundos == 1.235
    assert l.custo_acumulado_usd == l.custo_usd
    assert l.momento == "2026-11-16T12:00:00+00:00"


def test_modelo_sem_preco_fica_desconhecido_sem_valor_chutado():
    c = Custos("p")
    l = c.chamada("agente", _resposta(modelo="modelo-novo"))
    assert l.custo == "desconhecido" and l.custo_usd is None and l.tabela_de_precos is None
    assert l.tokens_entrada == 1000 and "modelo-novo" in l.detalhe
    r = c.resumo()["total"]
    assert r["chamadas_sem_preco"] == 1 and r["custo_completo"] is False


def test_operacao_nao_tem_custo_de_api():
    l = Custos("p").operacao("motor_de_regras", "verificar", 0.01, "aprovado")
    assert (l.tipo, l.custo, l.custo_usd, l.modelo) == ("operacao", "sem_custo", None, None)


def test_acumulado_e_resumo_por_etapa():
    c = Custos("p", "e")
    a = c.chamada("briefing", _resposta(entrada=1000))
    c.operacao("briefing", "perguntar_usuario", 2.0)
    b = c.chamada("agente", _resposta(entrada=3000, saida=500))
    c.chamada("agente", _resposta(modelo="sem-preco"))
    assert b.custo_acumulado_usd == pytest.approx(a.custo_usd + b.custo_usd)
    r = c.resumo()
    assert r["execucoes"] == 1 and list(r["etapas"]) == ["briefing", "agente"]
    assert r["etapas"]["briefing"]["chamadas_llm"] == 1
    assert r["etapas"]["briefing"]["operacoes"] == 1
    assert r["etapas"]["briefing"]["custo_completo"] is True
    assert r["etapas"]["agente"]["custo_completo"] is False
    assert r["total"]["tokens_entrada"] == 1000 + 3000 + 1000
    assert r["total"]["custo_calculado_usd"] == pytest.approx(a.custo_usd + b.custo_usd)
    assert r["total"]["modelos"] == sorted({HAIKU, "sem-preco"})


def test_gravar_acrescenta_e_ler_volta_igual(tmp_path):
    primeira = Custos("monitor-umidade", "um")
    primeira.chamada("briefing", _resposta())
    arquivo = primeira.gravar(tmp_path)
    segunda = Custos("monitor-umidade", "dois")
    segunda.operacao("motor_de_regras", "verificar")
    assert segunda.gravar(tmp_path) == arquivo == tmp_path / "monitor-umidade.jsonl"
    lidos = ler(arquivo)
    assert lidos == primeira.lancamentos + segunda.lancamentos
    assert resumir(lidos)["execucoes"] == 2


def test_sem_projeto_vai_para_arquivo_proprio(tmp_path):
    c = Custos()
    c.operacao("x", "y")
    assert c.gravar(tmp_path).name == "sem-projeto.jsonl"


@pytest.mark.parametrize("linha", ["não é json", "[]", '{"momento": "x"}',
                                   json.dumps({"campo_estranho": 1})])
def test_ler_arquivo_estragado(tmp_path, linha):
    arquivo = tmp_path / "p.jsonl"
    arquivo.write_text(linha + "\n", encoding="utf-8")
    with pytest.raises(ErroCustos, match="p.jsonl:1"):
        ler(arquivo)


def test_ouvinte_no_laco_anota_respostas_e_ferramentas_e_repassa():
    class Falso:
        def __init__(self):
            self.respostas = [_resposta(chamadas=[Chamada("buscar", {}, "1")]),
                              _resposta(entrada=50, saida=5)]

        def iniciar(self, *a):
            return self.respostas.pop(0)

        def continuar(self, resultados):
            return self.respostas.pop(0)

        def responder(self, texto):
            raise AssertionError

    c, vistos = Custos("p"), []
    conversar("pedido", Falso(), "sistema", [], lambda nome, args: {"ok": False},
              eventos=c.ouvinte("agente", vistos.append))
    assert [(l.tipo, l.nome, l.passo) for l in c.lancamentos] == [
        ("chamada_llm", "resposta do modelo", 1), ("operacao", "buscar", 1),
        ("chamada_llm", "resposta do modelo", 2)]
    assert c.lancamentos[1].detalhe == "a ferramenta recusou"
    assert c.lancamentos[1].segundos >= 0
    assert [e.tipo for e in vistos] == ["resposta", "chamada", "resposta"]


def test_ouvinte_ignora_evento_incompleto():
    c = Custos("p")
    c.ouvinte("x")(Evento("resposta", 1))
    assert c.lancamentos == []


def test_terminal_resumo_e_detalhe(tmp_path):
    c = Custos("monitor-umidade", "abc")
    c.chamada("briefing", _resposta())
    c.chamada("briefing", _resposta(modelo="sem-preco"))
    c.operacao("motor_de_regras", "verificar", 0.002, "reprovado")
    c.gravar(tmp_path)
    saida = []
    assert modulo.main(["monitor-umidade", "--pasta", str(tmp_path), "--detalhe"],
                       saida.append) == 0
    texto = "\n".join(saida)
    assert "abc briefing" in texto and "desconhecido" in texto and "sem_custo" in texto
    assert "TOTAL: 2 chamada(s) ao modelo, 1 operação(ões)" in texto
    assert "chamadas sem preço conhecido" in texto


def test_terminal_json_e_filtro_por_execucao(tmp_path):
    for execucao in ("um", "dois"):
        c = Custos("p", execucao)
        c.chamada("agente", _resposta())
        c.gravar(tmp_path)
    saida = []
    assert modulo.main([str(tmp_path / "p.jsonl"), "--execucao", "um", "--json"],
                       saida.append) == 0
    assert json.loads(saida[0])["execucoes"] == 1


def test_terminal_sem_arquivo(tmp_path):
    saida = []
    assert modulo.main(["nada", "--pasta", str(tmp_path)], saida.append) == 2


def test_resposta_do_adaptador_diz_modelo_e_fonte_do_preco():
    from types import SimpleNamespace
    from src.agente.provedores.claude import traduzir as _traduzir
    uso = SimpleNamespace(input_tokens=10, output_tokens=2, cache_read_input_tokens=0,
                          cache_creation_input_tokens=0)
    api = SimpleNamespace(content=[], stop_reason="end_turn", usage=uso, model=HAIKU)
    r = _traduzir(api)
    assert (r.modelo, r.custo_fonte) == (HAIKU, FONTE_DOS_PRECOS) and r.custo_usd > 0
    r = _traduzir(SimpleNamespace(content=[], stop_reason="end_turn", usage=uso, model="x"))
    assert (r.modelo, r.custo_fonte, r.custo_usd) == ("x", None, None)
