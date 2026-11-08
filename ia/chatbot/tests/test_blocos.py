"""
Blocos de dados da resposta: conversão das linhas do Athena (tudo texto) em tipos de verdade,
só colunas conhecidas, link só http(s), e o agente montando os blocos a partir das ferramentas.
"""

import json
import sys
from pathlib import Path

import pytest

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI.parent / "evals"))

import blocos as bl  # noqa: E402
import dados_fixture as fx  # noqa: E402
from test_agent import agent, AgenteFalso, CNPJ  # noqa: E402,F401  (a fixture simula strands e bedrock_agentcore)


# ---------------------------------------------------------------- conversão

def test_tarefas_viram_tipos_de_verdade():
    b = bl.montar("tarefas", {"em_risco": True, "limite": 30}, fx.TAREFAS)
    assert b["tipo"] == "tarefas" and b["parametros"] == {"em_risco": True}
    t = b["itens"][0]
    assert t["em_risco"] is True and t["obrigacao_versao"] == 1 and t["vencimento"] == "2026-11-10"
    assert set(t) == set(bl.COLUNAS["tarefas"])


def test_vazio_vira_none_e_falso_e_preservado():
    b = bl.montar("obrigacoes_da_empresa", {}, fx.OBRIGACOES)
    proposta = next(i for i in b["itens"] if i["status"] == "proposta")
    assert proposta["vigente"] is False and proposta["vigente_de"] is None and proposta["data_ato"] == "2026-11-07"
    vigente = next(i for i in b["itens"] if i["obrigacao_id"] == "OBR-001")
    assert vigente["vigente"] is True and vigente["vigente_ate"] is None and vigente["periodicidade"] == "mensal"
    assert next(i for i in b["itens"] if i["obrigacao_id"] == "OBR-009")["periodicidade"] is None


def test_linha_do_tempo_traz_o_antes_e_o_depois():
    b = bl.montar("linha_do_tempo", {"obrigacao_id": "OBR-013"}, fx.LINHA_DO_TEMPO)
    assert b["parametros"] == {"obrigacao_id": "OBR-013"}
    mudanca = b["itens"][0]
    assert mudanca["evento"] == "alteracao" and mudanca["versao"] == 2 and mudanca["data_ato"] == "2026-11-07"
    campos = {a["campo"]: a for a in mudanca["alteracoes"]}
    assert campos["prazo_regra"] == {"campo": "prazo_regra", "antes": "Até 30 de abril do ano seguinte ao exercício",
                                     "depois": "Até 31 de março do ano seguinte ao exercício"}
    assert campos["fonte_ato"]["antes"] is None
    assert b["itens"][1]["alteracoes"] is None          # inclusão não tem antes e depois


def test_versoes_com_lista_de_unidades():
    linhas = [{"obrigacao_id": "OBR-018", "versao": "1", "titulo": "RAPP", "status": "aprovada", "vigente": "true",
               "aplica_a": '["UN-02","UN-03"]', "prazo_regra": "Até 31/03"}]
    b = bl.montar("obrigacao_detalhe", {"obrigacao_id": "OBR-018"}, linhas)
    assert b["tipo"] == "versoes" and b["parametros"] == {"obrigacao_id": "OBR-018"}
    assert b["itens"][0]["aplica_a"] == ["UN-02", "UN-03"]


def test_empresa_com_inteiros():
    item = bl.montar("painel_da_empresa", {}, fx.PAINEL)["itens"][0]
    assert item["razao_social"] == "AURORA ENERGIA S.A." and item["atos_no_dou"] == 2 and item["qtd_socios"] == 0


@pytest.mark.parametrize("url, esperado", [
    ("https://www.in.gov.br/ato", "https://www.in.gov.br/ato"),
    ("HTTP://exemplo.gov.br/x", "HTTP://exemplo.gov.br/x"),
    ("javascript:alert(1)", None),
    ("data:text/html,<script>", None),
    ("//evil.example/x", None),
    ("", None),
])
def test_so_link_http_passa(url, esperado):
    b = bl.montar("atos_no_dou", {}, [{"data_publicacao": "2026-11-05", "identifica": "ATO", "url_pdf": url}])
    assert b["itens"][0]["url_pdf"] == esperado


def test_colunas_desconhecidas_nao_passam():
    linha = {"descricao": "x", "vencimento": "2026-11-10", "decidida_por": "sub-secreto", "usuario": "u", "por": "p"}
    item = bl.montar("tarefas", {}, [linha])["itens"][0]
    assert "decidida_por" not in item and "usuario" not in item and "por" not in item
    assert "sub-secreto" not in json.dumps(item)


def test_sem_bloco_para_erro_vazio_ou_ferramenta_sem_bloco():
    assert bl.montar("tarefas", {}, [{"erro": "x"}]) is None
    assert bl.montar("tarefas", {}, []) is None
    assert bl.montar("tarefas", {}, [{"outra": "coisa"}]) is None            # nenhuma coluna conhecida
    assert bl.montar("atualizacao_dos_dados", {}, fx.FRESCOR) is None
    assert bl.montar("ferramenta_que_nao_existe", {}, fx.TAREFAS) is None


def test_limites_de_tamanho():
    linhas = [{"descricao": "x" * 5000, "vencimento": "2026-11-10"}] * 80
    b = bl.montar("tarefas", {}, linhas)
    assert len(b["itens"]) == bl.MAX_ITENS and len(b["itens"][0]["descricao"]) == bl.MAX_TEXTO


def test_json_quebrado_vira_none():
    item = bl.montar("linha_do_tempo", {}, [{"ocorrido_em": "2026-11-07", "alteracoes": "{nao json"}])["itens"][0]
    assert item["alteracoes"] is None


def test_validos_descarta_o_que_nao_tem_a_forma():
    ok = {"tipo": "tarefas", "parametros": {"em_risco": True, "x": 5}, "itens": [{"descricao": "a"}]}
    assert bl.validos([ok]) == [{"tipo": "tarefas", "parametros": {"em_risco": True}, "itens": [{"descricao": "a"}]}]
    ruins = [{"tipo": "outro", "itens": [{"a": 1}]}, {"tipo": "tarefas", "itens": "x"}, {"tipo": "tarefas", "itens": []},
             {"tipo": "tarefas", "itens": [{"a": {"objeto": "aninhado"}}]}, "texto", None]
    assert bl.validos(ruins) == [] and bl.validos("x") == [] and bl.validos(None) == []
    assert len(bl.validos([ok] * 20)) == 8


# ---------------------------------------------------------------- o agente monta os blocos

class AgenteQueConsulta:
    """O modelo decide as ferramentas; o que ele escreve é só o resumo."""
    chamadas = []

    def __init__(self, **kw):
        self.tools = {t.tool_name: t for t in kw["tools"]}

    def __call__(self, prompt):
        for nome, args in AgenteQueConsulta.chamadas:
            self.tools[nome](**args)
        return "Resumo curto."


@pytest.fixture
def consultando(agent, monkeypatch):
    monkeypatch.setattr(agent, "Agent", AgenteQueConsulta)
    monkeypatch.setattr(agent, "athena_query", lambda sql, params: fx.responder(sql, params))
    return agent


def invocar(agent, chamadas):
    AgenteQueConsulta.chamadas = chamadas
    return agent.invoke({"cnpj": CNPJ, "user_id": "u-1", "prompt": "oi"})


def test_agente_devolve_resumo_e_blocos_das_ferramentas(consultando):
    r = invocar(consultando, [("tarefas", {"em_risco": True}), ("linha_do_tempo", {"obrigacao_id": "OBR-013"})])
    assert r["resposta"] == "Resumo curto." and r["consultas"] == 2
    assert [b["tipo"] for b in r["blocos"]] == ["tarefas", "linha_do_tempo"]
    assert r["blocos"][0]["parametros"] == {"em_risco": True}
    assert {t["obrigacao_id"] for t in r["blocos"][0]["itens"]} == {"OBR-009", "OBR-013"}
    assert r["blocos"][1]["parametros"] == {"obrigacao_id": "OBR-013"}


def test_mesma_ferramenta_com_os_mesmos_parametros_vale_uma_vez(consultando):
    r = invocar(consultando, [("tarefas", {"em_risco": True, "limite": 5}), ("tarefas", {"em_risco": True, "limite": 30})])
    assert r["consultas"] == 2 and [b["tipo"] for b in r["blocos"]] == ["tarefas"]


def test_parametros_diferentes_geram_blocos_diferentes(consultando):
    r = invocar(consultando, [("tarefas", {"em_risco": True}), ("tarefas", {})])
    assert [b["parametros"] for b in r["blocos"]] == [{"em_risco": True}, {}]
    assert len(r["blocos"][0]["itens"]) < len(r["blocos"][1]["itens"])


def test_ferramenta_com_erro_nao_gera_bloco(agent, monkeypatch):
    monkeypatch.setattr(agent, "Agent", AgenteQueConsulta)
    monkeypatch.setattr(agent, "athena_query", lambda sql, params: [{"erro": agent.ERRO_CONSULTA}])
    r = invocar(agent, [("tarefas", {})])
    assert r["blocos"] == [] and r["consultas"] == 1


def test_sem_ferramenta_sem_blocos(consultando):
    assert invocar(consultando, [])["blocos"] == []


def test_falha_ao_montar_o_bloco_nao_tira_os_dados_do_modelo(consultando, monkeypatch, caplog):
    def explode(*a, **k):
        raise RuntimeError("bug no bloco")
    monkeypatch.setattr(consultando.blocos, "montar", explode)
    ferramentas = {t.tool_name: t for t in consultando.make_tools(CNPJ)}
    linhas = ferramentas["tarefas"]()
    assert len(linhas) == 3 and linhas[0]["obrigacao_id"] == "OBR-009"      # o modelo recebe os dados
    assert "bug no bloco" in caplog.text


def test_o_modelo_recebe_as_linhas_originais_nao_os_blocos(consultando):
    ferramentas = {t.tool_name: t for t in consultando.make_tools(CNPJ)}
    assert ferramentas["tarefas"](em_risco=True)[0]["em_risco"] == "true"     # texto do Athena, como antes


def test_blocos_nao_trazem_quem_decidiu(consultando):
    r = invocar(consultando, [(n, {}) for n in ("painel_da_empresa", "atos_no_dou", "obrigacoes_da_empresa",
                                                 "tarefas", "linha_do_tempo")])
    texto = json.dumps(r["blocos"])
    for proibido in ("decidida_por", "usuario", '"por"', "sub-"):
        assert proibido not in texto
