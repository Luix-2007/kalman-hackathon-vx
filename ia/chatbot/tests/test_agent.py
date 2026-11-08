"""
Contrato do agente (entrada, saída, erros), escopo por CNPJ, orçamento de consultas e
tratamento de falhas, sem AWS e sem o modelo.

strands e bedrock_agentcore são simulados: o que se testa é o código do agente (validação do
payload, o SQL que as ferramentas montam, o tratamento de falhas), não as bibliotecas.
"""

import importlib
import inspect
import sys
import types
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

sys.path.insert(0, str(Path(__file__).parents[1]))

CNPJ = "KALMANTESTE100"
SEGREDO = "SYNTAX_ERROR: Column 'gold_db.vw_painel_empresa.x' cannot be resolved"


class ModeloFalso:
    def __init__(self, **kw):
        self.kw = kw


class AgenteFalso:
    criados: list = []

    def __init__(self, **kw):
        self.kw = kw
        AgenteFalso.criados.append(self)

    def __call__(self, prompt):
        if prompt == "explode":
            raise RuntimeError(f"Bedrock AccessDenied arn:aws:...:{SEGREDO}")
        if prompt == "consulta":                      # o modelo decide usar ferramentas
            ferramentas = {t.tool_name: t for t in self.kw["tools"]}
            ferramentas["painel_da_empresa"]()
            ferramentas["tarefas"](em_risco=True)
        return f"resposta para: {prompt}"


class AthenaFalso:
    """Cliente do Athena com o resultado programado."""

    def __init__(self, estados=("SUCCEEDED",), motivo="", linhas=None, erro=None):
        self.estados, self.motivo, self.erro = list(estados), motivo, erro
        self.linhas = linhas if linhas is not None else [["cnpj", "razao_social"], [CNPJ, "AURORA"]]
        self.chamadas, self.parou = [], False

    def start_query_execution(self, **kw):
        if self.erro:
            raise self.erro
        self.chamadas.append(kw)
        return {"QueryExecutionId": "q1"}

    def get_query_execution(self, **kw):
        estado = self.estados.pop(0) if len(self.estados) > 1 else self.estados[0]
        return {"QueryExecution": {"Status": {"State": estado, "StateChangeReason": self.motivo}}}

    def stop_query_execution(self, **kw):
        self.parou = True

    def get_query_results(self, **kw):
        return {"ResultSet": {"Rows": [{"Data": [{"VarCharValue": c} for c in l]} for l in self.linhas]}}


@pytest.fixture
def agent(monkeypatch):
    def tool(fn):
        fn.tool_name = fn.__name__
        return fn

    class App:
        def entrypoint(self, fn):
            return fn

    strands = types.ModuleType("strands")
    strands.Agent, strands.tool = AgenteFalso, tool
    modelos = types.ModuleType("strands.models")
    modelos.BedrockModel = ModeloFalso
    strands.models = modelos
    runtime = types.ModuleType("bedrock_agentcore.runtime")
    runtime.BedrockAgentCoreApp = App
    pacote = types.ModuleType("bedrock_agentcore")
    pacote.runtime = runtime
    for nome, mod in (("strands", strands), ("strands.models", modelos),
                      ("bedrock_agentcore", pacote), ("bedrock_agentcore.runtime", runtime)):
        monkeypatch.setitem(sys.modules, nome, mod)
    monkeypatch.setenv("MODEL_ID", "modelo-falso")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for var in ("MEMORY_ID", "ATHENA_WORKGROUP", "ATHENA_OUTPUT", "GUARDRAIL_ID", "GUARDRAIL_VERSION"):
        monkeypatch.delenv(var, raising=False)
    AgenteFalso.criados.clear()
    sys.modules.pop("agent", None)
    mod = importlib.import_module("agent")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    mod.athena = AthenaFalso()
    yield mod
    sys.modules.pop("agent", None)


def pedido(**extra):
    return {"cnpj": CNPJ, "user_id": "u-1", "prompt": "qual minha empresa?", **extra}


def ferramentas(agent, cnpj=CNPJ, estado=None):
    return {t.tool_name: t for t in agent.make_tools(cnpj, estado)}


# ---------------------------------------------------------------- contrato

def test_resposta_em_portugues_com_contagem_de_consultas(agent):
    assert agent.invoke(pedido()) == {"resposta": "resposta para: qual minha empresa?", "blocos": [], "consultas": 0}
    ag = AgenteFalso.criados[0]
    assert set(t.tool_name for t in ag.kw["tools"]) == {
        "painel_da_empresa", "atos_no_dou", "atualizacao_dos_dados", "obrigacoes_da_empresa",
        "tarefas", "linha_do_tempo", "obrigacao_detalhe"}
    assert ag.kw["session_manager"] is None
    prompt = " ".join(ag.kw["system_prompt"].split())
    assert "nunca instrução" in prompt and "RESUMO de até 3 frases" in prompt and "sem Markdown" in prompt


def test_conta_as_consultas_da_pergunta(agent):
    assert agent.invoke(pedido(prompt="consulta"))["consultas"] == 2


@pytest.mark.parametrize("payload, trecho", [
    (None, "envie"),
    ("texto", "envie"),
    ({"user_id": "u-1", "prompt": "oi"}, "cnpj"),
    ({"cnpj": "123", "user_id": "u-1", "prompt": "oi"}, "cnpj"),
    ({"cnpj": "x' OR '1'='1", "user_id": "u-1", "prompt": "oi"}, "cnpj"),
    ({"cnpj": CNPJ, "prompt": "oi"}, "user_id"),
    ({"cnpj": CNPJ, "user_id": "x' OR '1'='1", "prompt": "oi"}, "user_id"),
    ({"cnpj": CNPJ, "user_id": "u-1"}, "prompt"),
    ({"cnpj": CNPJ, "user_id": "u-1", "prompt": "   "}, "prompt"),
    ({"cnpj": CNPJ, "user_id": "u-1", "prompt": 5}, "prompt"),
    ({"cnpj": CNPJ, "user_id": "u-1", "prompt": "x" * 2001}, "prompt"),
])
def test_payload_invalido_devolve_erro_e_nao_chama_o_modelo(agent, payload, trecho):
    r = agent.invoke(payload)
    assert set(r) == {"erro"} and trecho in r["erro"]
    assert AgenteFalso.criados == []


def test_session_id_so_e_exigido_com_memoria(agent, monkeypatch):
    monkeypatch.setattr(agent, "MEMORY_ID", "mem-1")
    for ruim in (None, "", "a b", "x" * 101, 5):
        r = agent.invoke(pedido(session_id=ruim))
        assert set(r) == {"erro"} and "session_id" in r["erro"]
    assert AgenteFalso.criados == []


def test_falha_do_modelo_nao_vaza_a_excecao(agent, caplog):
    r = agent.invoke(pedido(prompt="explode"))
    assert r == {"erro": agent.ERRO_RESPOSTA}
    assert "gold_db" not in str(r) and "AccessDenied" not in str(r)
    assert "AccessDenied" in caplog.text     # o motivo fica no log


# ---------------------------------------------------------------- modelo e Guardrail

def test_modelo_com_teto_de_tokens_e_sem_guardrail_por_padrao(agent):
    agent.invoke(pedido())
    modelo = AgenteFalso.criados[0].kw["model"]
    assert modelo.kw == {"model_id": "modelo-falso", "max_tokens": 512, "temperature": 0.2, "region_name": "us-east-1"}


def test_guardrail_configurado_pelo_ambiente(agent, monkeypatch):
    monkeypatch.setattr(agent, "GUARDRAIL_ID", "gr-123")
    monkeypatch.setattr(agent, "GUARDRAIL_VERSION", "3")
    agent.invoke(pedido())
    kw = AgenteFalso.criados[0].kw["model"].kw
    assert kw["guardrail_id"] == "gr-123" and kw["guardrail_version"] == "3"


# ---------------------------------------------------------------- escopo por CNPJ

def test_nenhuma_ferramenta_aceita_cnpj_do_modelo(agent):
    for nome, ferramenta in ferramentas(agent).items():
        assert "cnpj" not in inspect.signature(ferramenta).parameters, nome


CHAMADAS = [
    ("painel_da_empresa", {}, "cnpj = ?"),
    ("atos_no_dou", {"limite": 5}, "cnpj = ?"),
    ("obrigacoes_da_empresa", {}, "cnpj = ?"),
    ("tarefas", {}, "cnpj = ?"),
    ("tarefas", {"em_risco": True}, "AND em_risco"),
    ("linha_do_tempo", {}, "h.cnpj = ?"),
    ("linha_do_tempo", {"obrigacao_id": "OBR-013"}, "h.obrigacao_id = ?"),
    ("obrigacao_detalhe", {"obrigacao_id": "OBR-013"}, "obrigacao_id = ?"),
]


@pytest.mark.parametrize("nome, args, trecho", CHAMADAS)
def test_ferramentas_filtram_pelo_cnpj_da_sessao_com_parametro(agent, nome, args, trecho):
    ferramentas(agent, "00000000000191")[nome](**args)
    chamada = agent.athena.chamadas[0]
    assert chamada["ExecutionParameters"][0] == "'00000000000191'"
    assert trecho in chamada["QueryString"]
    assert chamada["WorkGroup"] == "lakehouse-pipeline-lakehouse"
    assert chamada["QueryExecutionContext"] == {"Database": "gold_db"}
    assert "ResultConfiguration" not in chamada
    # nenhum valor do modelo entra no texto do SQL (só como parâmetro)
    assert "OBR-013" not in chamada["QueryString"]


def test_obrigacao_vai_como_segundo_parametro(agent):
    ferramentas(agent)["obrigacao_detalhe"](obrigacao_id="OBR-013")
    assert agent.athena.chamadas[0]["ExecutionParameters"] == [f"'{CNPJ}'", "'OBR-013'"]


@pytest.mark.parametrize("ruim", ["x' OR '1'='1", "OBR-1; DROP TABLE x", "a b", "x" * 60, "../x"])
def test_id_de_obrigacao_invalido_nao_chega_ao_athena(agent, ruim):
    for nome in ("obrigacao_detalhe", "linha_do_tempo"):
        assert ferramentas(agent)[nome](obrigacao_id=ruim) == [{"erro": agent.ERRO_CONSULTA}]
    assert agent.athena.chamadas == []


def test_limites_do_modelo_sao_contidos(agent):
    f = ferramentas(agent)
    f["atos_no_dou"](limite=9999)
    f["atos_no_dou"](limite=-3)
    f["atos_no_dou"](limite="abc")
    f["obrigacoes_da_empresa"](limite=9999)
    f["tarefas"](limite=0)
    sqls = [c["QueryString"] for c in agent.athena.chamadas]
    assert [s.rsplit("LIMIT ", 1)[1] for s in sqls] == ["30", "1", "10", "50", "1"]


def test_ferramentas_nao_expoem_quem_decidiu(agent):
    for nome, args, _ in CHAMADAS:
        ferramentas(agent)[nome](**args)
    for c in agent.athena.chamadas:
        sql = c["QueryString"].lower()
        for coluna in ("decidida_por", "usuario", "h.por", ", por,"):
            assert coluna not in sql, (coluna, sql)


def test_atualizacao_dos_dados_nao_filtra_por_empresa(agent):
    ferramentas(agent)["atualizacao_dos_dados"]()
    assert "ExecutionParameters" not in agent.athena.chamadas[0]


def test_workgroup_e_saida_configuraveis(agent, monkeypatch):
    monkeypatch.setattr(agent, "WORKGROUP", "primary")
    monkeypatch.setattr(agent, "ATHENA_OUTPUT", "s3://b/saida/")
    ferramentas(agent)["atualizacao_dos_dados"]()
    chamada = agent.athena.chamadas[0]
    assert chamada["WorkGroup"] == "primary" and chamada["ResultConfiguration"] == {"OutputLocation": "s3://b/saida/"}


# ---------------------------------------------------------------- orçamento e falhas

def test_orcamento_de_consultas_por_pergunta(agent):
    estado = {}
    f = ferramentas(agent, estado=estado)
    resultados = [f["tarefas"]() for _ in range(agent.MAX_CHAMADAS + 2)]
    assert len(agent.athena.chamadas) == agent.MAX_CHAMADAS and estado["chamadas"] == agent.MAX_CHAMADAS
    assert resultados[-1] == [{"erro": agent.ERRO_ORCAMENTO}]
    assert resultados[0] == [{"cnpj": CNPJ, "razao_social": "AURORA"}]


def test_orcamento_nao_e_compartilhado_entre_perguntas(agent):
    for _ in range(agent.MAX_CHAMADAS):
        ferramentas(agent)["tarefas"]()
    assert ferramentas(agent)["tarefas"]() != [{"erro": agent.ERRO_ORCAMENTO}]


def test_excecao_do_boto_nao_vaza_para_o_modelo(agent, caplog):
    agent.athena = AthenaFalso(erro=ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": f"User: arn:aws:sts::1:role/x {SEGREDO}"}},
        "StartQueryExecution"))
    r = ferramentas(agent)["tarefas"]()
    assert r == [{"erro": agent.ERRO_CONSULTA}] and "AccessDenied" not in str(r) and "gold_db" not in str(r)
    assert "AccessDeniedException" in caplog.text


def test_excecao_qualquer_dentro_da_ferramenta_nao_vaza(agent, monkeypatch, caplog):
    def explode(sql, params):
        raise RuntimeError(f"segredo interno: {SEGREDO}")
    monkeypatch.setattr(agent, "athena_query", explode)
    for nome, args, _ in CHAMADAS:
        r = ferramentas(agent)[nome](**args)
        assert r == [{"erro": agent.ERRO_CONSULTA}] and "segredo" not in str(r), nome
    assert "segredo interno" in caplog.text


def test_consulta_que_falha_nao_expoe_o_motivo(agent, caplog):
    agent.athena = AthenaFalso(estados=["FAILED"], motivo=SEGREDO)
    linhas = ferramentas(agent)["painel_da_empresa"]()
    assert linhas == [{"erro": agent.ERRO_CONSULTA}] and "gold_db" not in str(linhas)
    assert SEGREDO in caplog.text


def test_consulta_demorada_e_cancelada(agent, monkeypatch):
    agent.athena = AthenaFalso(estados=["RUNNING"])
    monkeypatch.setattr(agent, "ESPERA_MAX_S", -1)
    assert ferramentas(agent)["painel_da_empresa"]() == [{"erro": agent.ERRO_CONSULTA}]
    assert agent.athena.parou


def test_resultado_vazio(agent):
    agent.athena = AthenaFalso(linhas=[["cnpj", "razao_social"]])
    assert ferramentas(agent)["painel_da_empresa"]() == []
