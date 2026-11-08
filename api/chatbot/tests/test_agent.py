"""
Contrato do agente (entrada, saída, erros) e consultas ao Athena, sem AWS e sem o modelo.

strands e bedrock_agentcore são simulados: o que se testa é o código do agente (validação do
payload, o SQL que as ferramentas montam, o tratamento de falhas), não as bibliotecas.
"""

import importlib
import sys
import types
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[1]))

SEGREDO = "SYNTAX_ERROR: Column 'gold_db.vw_painel_empresa.x' cannot be resolved"


class AgenteFalso:
    criados: list = []

    def __init__(self, **kw):
        self.kw = kw
        AgenteFalso.criados.append(self)

    def __call__(self, prompt):
        if prompt == "explode":
            raise RuntimeError(f"Bedrock AccessDenied arn:aws:...:{SEGREDO}")
        return f"resposta para: {prompt}"


class AthenaFalso:
    """Cliente do Athena com o resultado programado."""

    def __init__(self, estados=("SUCCEEDED",), motivo="", linhas=None):
        self.estados, self.motivo = list(estados), motivo
        self.linhas = linhas if linhas is not None else [["cnpj", "razao_social"], ["00000000000191", "BB"]]
        self.chamadas, self.parou = [], False

    def start_query_execution(self, **kw):
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
    runtime = types.ModuleType("bedrock_agentcore.runtime")
    runtime.BedrockAgentCoreApp = App
    pacote = types.ModuleType("bedrock_agentcore")
    pacote.runtime = runtime
    for nome, mod in (("strands", strands), ("bedrock_agentcore", pacote), ("bedrock_agentcore.runtime", runtime)):
        monkeypatch.setitem(sys.modules, nome, mod)
    monkeypatch.setenv("MODEL_ID", "modelo-falso")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    for var in ("MEMORY_ID", "ATHENA_WORKGROUP", "ATHENA_OUTPUT"):
        monkeypatch.delenv(var, raising=False)
    AgenteFalso.criados.clear()
    sys.modules.pop("agent", None)
    mod = importlib.import_module("agent")
    monkeypatch.setattr(mod.time, "sleep", lambda s: None)
    mod.athena = AthenaFalso()
    yield mod
    sys.modules.pop("agent", None)


# ---------------------------------------------------------------- contrato

def test_resposta_em_portugues(agent):
    assert agent.invoke({"user_id": "u-1", "prompt": "qual minha empresa?"}) == {
        "resposta": "resposta para: qual minha empresa?"}
    ag = AgenteFalso.criados[0]
    assert [t.tool_name for t in ag.kw["tools"]] == ["painel_da_empresa", "atos_no_dou", "atualizacao_dos_dados"]
    assert ag.kw["session_manager"] is None


@pytest.mark.parametrize("payload, trecho", [
    (None, "envie"),
    ("texto", "envie"),
    ({"prompt": "oi"}, "user_id"),
    ({"user_id": "x' OR '1'='1", "prompt": "oi"}, "user_id"),
    ({"user_id": "CNPJ#00000000000191", "prompt": "oi"}, "user_id"),
    ({"user_id": "u-1"}, "prompt"),
    ({"user_id": "u-1", "prompt": "   "}, "prompt"),
    ({"user_id": "u-1", "prompt": 5}, "prompt"),
    ({"user_id": "u-1", "prompt": "x" * 4001}, "prompt"),
])
def test_payload_invalido_devolve_erro_e_nao_chama_o_modelo(agent, payload, trecho):
    r = agent.invoke(payload)
    assert set(r) == {"erro"} and trecho in r["erro"]
    assert AgenteFalso.criados == []


def test_session_id_so_e_exigido_com_memoria(agent, monkeypatch):
    monkeypatch.setattr(agent, "MEMORY_ID", "mem-1")
    for ruim in (None, "", "a b", "x" * 101, 5):
        r = agent.invoke({"user_id": "u-1", "prompt": "oi", "session_id": ruim})
        assert set(r) == {"erro"} and "session_id" in r["erro"]
    assert AgenteFalso.criados == []


def test_falha_do_modelo_nao_vaza_a_excecao(agent, caplog):
    r = agent.invoke({"user_id": "u-1", "prompt": "explode"})
    assert r == {"erro": agent.ERRO_RESPOSTA}
    assert "gold_db" not in str(r) and "AccessDenied" not in str(r)
    assert "AccessDenied" in caplog.text     # o motivo fica no log


# ---------------------------------------------------------------- Athena e ferramentas

def ferramentas(agent, user="u-1"):
    return {t.tool_name: t for t in agent.make_tools(user)}


def test_ferramentas_filtram_pelo_usuario_com_parametro(agent):
    linhas = ferramentas(agent)["painel_da_empresa"]()
    assert linhas == [{"cnpj": "00000000000191", "razao_social": "BB"}]
    chamada = agent.athena.chamadas[0]
    assert chamada["ExecutionParameters"] == ["'u-1'"] and "user_id = ?" in chamada["QueryString"]
    assert chamada["WorkGroup"] == "lakehouse-pipeline-lakehouse"
    assert chamada["QueryExecutionContext"] == {"Database": "gold_db"}
    assert "ResultConfiguration" not in chamada


def test_atos_limita_o_tamanho_da_lista(agent):
    ferramentas(agent)["atos_no_dou"](limite=9999)
    assert agent.athena.chamadas[0]["QueryString"].endswith("LIMIT 30")
    ferramentas(agent)["atos_no_dou"](limite=-3)
    assert agent.athena.chamadas[1]["QueryString"].endswith("LIMIT 1")


def test_atualizacao_dos_dados_nao_filtra_por_usuario(agent):
    ferramentas(agent)["atualizacao_dos_dados"]()
    assert "ExecutionParameters" not in agent.athena.chamadas[0]


def test_workgroup_e_saida_configuraveis(agent, monkeypatch):
    monkeypatch.setattr(agent, "WORKGROUP", "primary")
    monkeypatch.setattr(agent, "ATHENA_OUTPUT", "s3://b/saida/")
    ferramentas(agent)["atualizacao_dos_dados"]()
    chamada = agent.athena.chamadas[0]
    assert chamada["WorkGroup"] == "primary" and chamada["ResultConfiguration"] == {"OutputLocation": "s3://b/saida/"}


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
