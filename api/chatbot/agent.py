"""
Agente da Kalman (Strands + Bedrock AgentCore). Responde só com dados do Athena (gold_db).

Contrato, no mesmo formato das outras APIs (respostas em JSON, chaves em português,
erros como {"erro": "mensagem"}):

    entrada  {"user_id": "<sub do Cognito>", "prompt": "texto", "session_id": "..."}
             session_id é obrigatório só quando MEMORY_ID está configurado
    saída    {"resposta": "texto"}
    erro     {"erro": "mensagem"}   user_id/prompt/session_id inválidos, ou falha interna

O motivo de uma falha (mensagem do Athena, exceção do modelo) fica só no log: nem o
cliente nem o modelo recebem o texto original, que pode ter nomes de tabela e trechos de SQL.
"""

import logging
import os
import re
import time

import boto3
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

REGION        = "us-east-1"
MODEL_ID      = os.environ["MODEL_ID"]
DATABASE      = "gold_db"
# O workgroup do lakehouse já tem local de resultados; o "primary" não tem (exigiria ATHENA_OUTPUT).
WORKGROUP     = os.environ.get("ATHENA_WORKGROUP", "lakehouse-pipeline-lakehouse")
ATHENA_OUTPUT = os.environ.get("ATHENA_OUTPUT")      # só se o workgroup não tiver local de saída
ESPERA_MAX_S  = float(os.environ.get("ATHENA_ESPERA_MAX_S", "25"))
MEMORY_ID     = os.environ.get("MEMORY_ID")          # opcional no protótipo

USER_ID = re.compile(r"[A-Za-z0-9-]{1,64}")
SESSION_ID = re.compile(r"[A-Za-z0-9_-]{1,100}")
PROMPT_MAX = 4000

ERRO_CONSULTA = "não foi possível consultar os dados agora"
ERRO_RESPOSTA = "não foi possível responder agora, tente de novo"

app = BedrockAgentCoreApp()
athena = boto3.client("athena", region_name=REGION)

SYSTEM_PROMPT = """Você é o assistente da Kalman. Responda em português, de forma objetiva,
usando SOMENTE os dados retornados pelas ferramentas. Se não houver dado, diga que não encontrou."""


def athena_query(sql, params):
    """Linhas do resultado como dicts. Falha: [{"erro": ERRO_CONSULTA}], com o motivo no log."""
    args = {"QueryString": sql, "WorkGroup": WORKGROUP,
            "QueryExecutionContext": {"Database": DATABASE}}
    if params:
        args["ExecutionParameters"] = params
    if ATHENA_OUTPUT:
        args["ResultConfiguration"] = {"OutputLocation": ATHENA_OUTPUT}
    qid = athena.start_query_execution(**args)["QueryExecutionId"]
    limite = time.monotonic() + ESPERA_MAX_S
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        if time.monotonic() > limite:
            athena.stop_query_execution(QueryExecutionId=qid)
            log.error("consulta %s passou de %ss", qid, ESPERA_MAX_S)
            return [{"erro": ERRO_CONSULTA}]
        time.sleep(0.5)
    if st["State"] != "SUCCEEDED":
        log.error("consulta %s %s: %s", qid, st["State"], st.get("StateChangeReason", ""))
        return [{"erro": ERRO_CONSULTA}]
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


def _validar(payload):
    """Devolve (user_id, prompt, session_id) ou levanta ValueError com a mensagem para o cliente."""
    if not isinstance(payload, dict):
        raise ValueError('envie {"user_id": "...", "prompt": "..."}')
    user_id = str(payload.get("user_id", ""))
    if not USER_ID.fullmatch(user_id):
        raise ValueError("user_id inválido")
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > PROMPT_MAX:
        raise ValueError(f"prompt é obrigatório (texto de até {PROMPT_MAX} caracteres)")
    session_id = payload.get("session_id")
    if MEMORY_ID and not (isinstance(session_id, str) and SESSION_ID.fullmatch(session_id)):
        raise ValueError("session_id é obrigatório e deve ter só letras, números, _ e -")
    return user_id, prompt, session_id


@app.entrypoint
def invoke(payload, context=None):
    try:
        user_id, prompt, session_id = _validar(payload)
    except ValueError as exc:
        return {"erro": str(exc)}
    try:
        session_manager = None
        if MEMORY_ID:
            from bedrock_agentcore.memory.integrations.strands.config import AgentCoreMemoryConfig
            from bedrock_agentcore.memory.integrations.strands.session_manager import AgentCoreMemorySessionManager
            session_manager = AgentCoreMemorySessionManager(
                AgentCoreMemoryConfig(memory_id=MEMORY_ID, session_id=session_id, actor_id=user_id),
                region_name=REGION)
        agent = Agent(model=MODEL_ID, system_prompt=SYSTEM_PROMPT,
                      tools=make_tools(user_id), session_manager=session_manager)
        return {"resposta": str(agent(prompt))}
    except Exception:
        log.exception("falha ao responder (user %s)", user_id)
        return {"erro": ERRO_RESPOSTA}


if __name__ == "__main__":
    app.run()
