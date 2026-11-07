import os, re, time
import boto3
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

REGION        = "us-east-1"
MODEL_ID      = os.environ["MODEL_ID"]
DATABASE      = "gold_db"
WORKGROUP     = os.environ.get("ATHENA_WORKGROUP", "primary")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT")      # ex.: s3://.../athena-results/
MEMORY_ID     = os.environ.get("MEMORY_ID")          # opcional no protótipo

app = BedrockAgentCoreApp()
athena = boto3.client("athena", region_name=REGION)

SYSTEM_PROMPT = """Você é o assistente da Kalman. Responda em português, de forma objetiva,
usando SOMENTE os dados retornados pelas ferramentas. Se não houver dado, diga que não encontrou."""

def athena_query(sql, params):
    args = {"QueryString": sql, "WorkGroup": WORKGROUP,
            "QueryExecutionContext": {"Database": DATABASE}}
    if params:
        args["ExecutionParameters"] = params
    if ATHENA_OUTPUT:
        args["ResultConfiguration"] = {"OutputLocation": ATHENA_OUTPUT}
    qid = athena.start_query_execution(**args)["QueryExecutionId"]
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(0.5)
    if st["State"] != "SUCCEEDED":
        return [{"erro": st.get("StateChangeReason", st["State"])}]
    rows = athena.get_query_results(QueryExecutionId=qid, MaxResults=50)["ResultSet"]["Rows"]
    header = [c.get("VarCharValue") for c in rows[0]["Data"]]
    return [dict(zip(header, [c.get("VarCharValue") for c in r["Data"]])) for r in rows[1:]]

def make_tools(user_id):
    uid = f"'{user_id}'"

    @tool
    def painel_da_empresa() -> list[dict]:
        """Resumo da empresa do usuário: razão social, situação cadastral, capital social,
        quantidade de sócios, número de atos no DOU e data do ato mais recente."""
        return athena_query(
            "SELECT cnpj, razao_social, situacao_cadastral, status_cadastro, capital_social, "
            "qtd_socios, atos_no_dou, tipos_de_ato, ato_mais_recente "
            "FROM vw_painel_empresa WHERE user_id = ? LIMIT 1", [uid])

    @tool
    def atos_no_dou(limite: int = 10) -> list[dict]:
        """Atos publicados no Diário Oficial da União sobre a empresa do usuário,
        do mais recente para o mais antigo (data, tipo, órgão, ementa e link do PDF)."""
        limite = max(1, min(int(limite), 30))
        return athena_query(
            "SELECT data_publicacao, tipo, orgao, identifica, ementa, url_pdf "
            "FROM vw_empresas_atos WHERE user_id = ? "
            f"ORDER BY data_publicacao DESC LIMIT {limite}", [uid])

    @tool
    def atualizacao_dos_dados() -> list[dict]:
        """Até quando os dados de cada fonte estão atualizados."""
        return athena_query("SELECT origem, registros, mais_recente FROM vw_frescor", [])

    return [painel_da_empresa, atos_no_dou, atualizacao_dos_dados]

@app.entrypoint
def invoke(payload, context=None):
    user_id = str(payload.get("user_id", ""))
    if not re.fullmatch(r"[A-Za-z0-9-]{1,64}", user_id):
        return {"erro": "user_id inválido"}
    session_manager = None
    if MEMORY_ID:
        from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
        from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
        session_manager = AgentCoreMemorySessionManager(
            AgentCoreMemoryConfig(memory_id=MEMORY_ID, session_id=payload["session_id"], actor_id=user_id),
            region_name=REGION)
    agent = Agent(model=MODEL_ID, system_prompt=SYSTEM_PROMPT,
                  tools=make_tools(user_id), session_manager=session_manager)
    return {"answer": str(agent(payload["prompt"]))}

if __name__ == "__main__":
    app.run()