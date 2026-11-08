"""
Agente Bedrock AgentCore para o lakehouse cnpj-cadastro + DOU.

Memória em dois níveis:
    1. In-session  — instância do Agent mantida por session_id no dict _sessions.
                     O Strands mantém o conversation_history automaticamente.
                     Persiste enquanto o container AgentCore estiver vivo.
    2. Persistente — AgentCore Memory (SemanticMemory + SummaryMemory por actorId).
                     Carregada no início de cada sessão nova; salva ao final de cada troca.

Ferramentas:
    consultar_empresa  — Athena: Gold (empresas_clientes + vw_empresas_atos)
    buscar_documentos  — Bedrock Knowledge Base (kb_docs/empresas/)

Entrada (InvokeAgentRuntime payload):
    {
        "prompt":     "<pergunta do usuário>",      # obrigatório
        "user_id":    "<user_id do cadastro>",       # recomendado; filtra dados ao usuário
        "session_id": "<uuid da sessão>"             # recomendado; mantém histórico
    }

Saída:
    {"resposta": "<texto>", "user_id": "<user_id>"}

Variáveis de ambiente:
    KB_ID, MEMORY_ID, ATHENA_WORKGROUP, LAKE_BUCKET, MODEL_ID, AWS_REGION
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

import boto3
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from strands import Agent, tool
from strands.models import BedrockModel

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")

# ---------------------------------------------------------------- configuração

KB_ID            = os.environ.get("KB_ID", "")
MEMORY_ID        = os.environ.get("MEMORY_ID", "")
ATHENA_WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "lakehouse-pipeline-lakehouse")
MODEL_ID         = os.environ.get("MODEL_ID", "anthropic.claude-3-5-sonnet-20241022-v2:0")
REGION           = os.environ.get("AWS_REGION", "us-east-1")

# Limite de sessões em RAM (evita vazamento em containers de longa duração).
_MAX_SESSIONS = 100

# ---------------------------------------------------------------- clientes AWS

athena           = boto3.client("athena",                region_name=REGION)
br_agent_runtime = boto3.client("bedrock-agent-runtime", region_name=REGION)

# ---------------------------------------------------------------- helpers Athena

_ATHENA_POLL = 1
_ATHENA_MAX  = 60


def _executar_athena(sql: str) -> list[dict[str, Any]]:
    """Executa SQL no Athena e devolve lista de dicts (coluna → valor)."""
    resp     = athena.start_query_execution(QueryString=sql, WorkGroup=ATHENA_WORKGROUP)
    exec_id  = resp["QueryExecutionId"]
    deadline = time.time() + _ATHENA_MAX

    while time.time() < deadline:
        status = athena.get_query_execution(QueryExecutionId=exec_id)
        state  = status["QueryExecution"]["Status"]["State"]
        if state == "SUCCEEDED":
            break
        if state in ("FAILED", "CANCELLED"):
            reason = status["QueryExecution"]["Status"].get("StateChangeReason", "")
            raise RuntimeError(f"Athena {state}: {reason}")
        time.sleep(_ATHENA_POLL)
    else:
        athena.stop_query_execution(QueryExecutionId=exec_id)
        raise TimeoutError(f"Athena não terminou em {_ATHENA_MAX}s")

    rows = athena.get_query_results(QueryExecutionId=exec_id)["ResultSet"]["Rows"]
    if len(rows) < 2:
        return []
    headers = [c.get("VarCharValue", "") for c in rows[0]["Data"]]
    return [
        {h: c.get("VarCharValue", "") for h, c in zip(headers, row["Data"])}
        for row in rows[1:]
    ]


# ---------------------------------------------------------------- ferramentas

@tool
def consultar_empresa(user_id: str) -> str:
    """
    Consulta dados completos de uma empresa no lakehouse dado o user_id.
    Retorna situação cadastral, capital social, quantidade de sócios e os
    últimos atos publicados no DOU em que a empresa foi citada.
    Sempre filtre pelo user_id recebido do usuário.
    """
    out: dict[str, Any] = {}

    try:
        out["empresa"] = _executar_athena(f"""
            SELECT user_id, cnpj, razao_social, situacao_cadastral,
                   status, capital_social, qtd_socios, consultado_em
            FROM gold_db.empresas_clientes
            WHERE user_id = '{user_id}'
        """)
    except Exception as exc:
        log.warning("consultar_empresa/empresa: %s", exc)
        out["empresa"] = {"erro": str(exc)}

    try:
        out["atos_recentes"] = _executar_athena(f"""
            SELECT razao_social, data_publicacao, tipo, orgao,
                   identifica, ementa, casou_por, url_pdf
            FROM gold_db.vw_empresas_atos
            WHERE user_id = '{user_id}'
            ORDER BY data_publicacao DESC
            LIMIT 10
        """)
    except Exception as exc:
        log.warning("consultar_empresa/atos: %s", exc)
        out["atos_recentes"] = {"aviso": str(exc)}

    return json.dumps(out, ensure_ascii=False, default=str)


@tool
def buscar_documentos(consulta: str) -> str:
    """
    Busca documentos relevantes sobre empresas na Bedrock Knowledge Base.
    Use para obter contexto detalhado: tipo de atividade, localização,
    histórico de classificação. Retorna até 5 trechos mais relevantes.
    """
    if not KB_ID:
        return "Knowledge Base não configurada (KB_ID vazio)."
    try:
        resp   = br_agent_runtime.retrieve(
            knowledgeBaseId=KB_ID,
            retrievalQuery={"text": consulta},
            retrievalConfiguration={"vectorSearchConfiguration": {"numberOfResults": 5}},
        )
        chunks = []
        for r in resp.get("retrievalResults", []):
            texto = r.get("content", {}).get("text", "")
            score = r.get("score", 0)
            fonte = r.get("location", {}).get("s3Location", {}).get("uri", "")
            if texto:
                chunks.append(f"[score={score:.3f} | {fonte}]\n{texto}")
        return "\n\n---\n\n".join(chunks) if chunks else "Nenhum documento encontrado."
    except Exception as exc:
        log.error("buscar_documentos: %s", exc)
        return f"Erro ao buscar documentos: {exc}"


# ---------------------------------------------------------------- AgentCore Memory

def _recuperar_memoria(user_id: str) -> str:
    """Carrega contexto persistente da AgentCore Memory para este usuário."""
    if not MEMORY_ID or not user_id:
        return ""
    try:
        from bedrock_agentcore.memory import BedrockAgentCoreMemoryClient  # type: ignore
        cli  = BedrockAgentCoreMemoryClient(memory_id=MEMORY_ID, region_name=REGION)
        resp = cli.retrieve_memory_records(
            namespace=user_id,
            search_query={"text": "empresas consultadas e contexto recente do usuário"},
            max_results=5,
        )
        textos = [
            r.get("content", {}).get("text", "")
            for r in resp.get("memoryRecords", [])
            if r.get("content", {}).get("text")
        ]
        if textos:
            return "Memória anterior:\n" + "\n".join(f"- {t}" for t in textos)
    except ImportError:
        pass
    except Exception as exc:
        log.warning("_recuperar_memoria (ignorado): %s", exc)
    return ""


def _salvar_memoria(user_id: str, session_id: str,
                    user_msg: str, resp_text: str) -> None:
    """Persiste o par (mensagem, resposta) no AgentCore Memory."""
    if not MEMORY_ID or not user_id:
        return
    try:
        from bedrock_agentcore.memory import BedrockAgentCoreMemoryClient  # type: ignore
        cli = BedrockAgentCoreMemoryClient(memory_id=MEMORY_ID, region_name=REGION)
        cli.create_event(
            actor_id=user_id,
            session_id=session_id or "default",
            payload={
                "messages": [
                    {"role": "user",      "content": user_msg},
                    {"role": "assistant", "content": resp_text},
                ]
            },
        )
    except ImportError:
        pass
    except Exception as exc:
        log.warning("_salvar_memoria (ignorado): %s", exc)


# ---------------------------------------------------------------- sessões in-memory
# Cada session_id mantém sua própria instância de Agent com o conversation_history
# completo do Strands. Isso garante memória dentro da sessão sem custo extra.

SYSTEM_PROMPT = """
Você é um assistente especializado na análise de empresas cadastradas no sistema.
Você tem acesso a:
  1. Dados de cadastro: CNPJ, razão social, situação cadastral, sócios, capital social.
  2. Publicações no Diário Oficial da União (DOU) que citam cada empresa.
  3. Documentos detalhados das empresas na Knowledge Base.

Regras:
  - Sempre filtre pelo user_id informado no início da conversa.
  - Use consultar_empresa para dados em tempo real do Athena.
  - Use buscar_documentos para contexto adicional da Knowledge Base.
  - Responda em português, de forma clara e objetiva.
  - Nunca invente dados: se não encontrar, diga isso explicitamente.
  - Não exponha nomes de sócios individualmente (LGPD).
"""

# Dict session_id → Agent. Reutilizado entre chamadas do mesmo session_id.
_sessions: dict[str, Agent] = {}


def _get_or_create_agent(session_id: str, user_id: str) -> Agent:
    """Retorna o agente da sessão existente ou cria um novo."""
    if session_id not in _sessions:
        # Evita vazamento: descarta metade das sessões mais antigas se cheio.
        if len(_sessions) >= _MAX_SESSIONS:
            para_remover = list(_sessions.keys())[: _MAX_SESSIONS // 2]
            for k in para_remover:
                del _sessions[k]
            log.info("Cache de sessões limpo (%d removidas)", len(para_remover))

        # Carrega memória persistente do usuário para o system prompt desta sessão.
        mem_ctx = _recuperar_memoria(user_id)
        system  = SYSTEM_PROMPT + (f"\n\n{mem_ctx}" if mem_ctx else "")

        model = BedrockModel(model_id=MODEL_ID, region_name=REGION)
        _sessions[session_id] = Agent(
            model=model,
            system_prompt=system,
            tools=[consultar_empresa, buscar_documentos],
        )
        log.info("Nova sessão: session_id=%s user_id=%s", session_id, user_id)

    return _sessions[session_id]


# ---------------------------------------------------------------- app

app = BedrockAgentCoreApp()


@app.entrypoint
def invoke(payload: dict) -> str:
    """Ponto de entrada chamado pelo InvokeAgentRuntime."""
    user_message: str = payload.get("prompt", "")
    user_id:      str = payload.get("user_id", "")
    session_id:   str = payload.get("session_id", "") or f"anon-{user_id}"

    if not user_message:
        return json.dumps({"erro": "Campo 'prompt' é obrigatório."}, ensure_ascii=False)

    # Inclui o user_id no prompt para o agente saber quem está consultando.
    prompt = f"[user_id: {user_id}] {user_message}" if user_id else user_message

    agent    = _get_or_create_agent(session_id, user_id)
    response = agent(prompt)

    try:
        content   = response.message.get("content", [])  # type: ignore[union-attr]
        resp_text = content[0].get("text", "") if content else str(response)
    except Exception:
        resp_text = str(response)

    _salvar_memoria(user_id, session_id, user_message, resp_text)

    return json.dumps({"resposta": resp_text, "user_id": user_id}, ensure_ascii=False)


if __name__ == "__main__":
    app.run()
