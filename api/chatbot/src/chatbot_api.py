"""
API do chatbot: a única porta de entrada para o agente (agent.py, no AgentCore).

    POST /chatbot/mensagens    {"prompt": "texto", "session_id": "opcional"}
    200  {"resposta": "resumo curto (texto puro)", "blocos": [...]}
         blocos = os dados que a tela desenha (tarefas, linha do tempo...), montados em código
         a partir das consultas do agente; formato em ia/chatbot/contrato/schema.json
    400  corpo inválido     401 sem token     404 usuário sem organização
    429  limite de mensagens (header Retry-After)
    502  o agente falhou (mensagem genérica; o motivo fica só no log)
    504  o agente demorou demais

Header: Authorization: Bearer <access token do Cognito> (o mesmo login do cadastro).

O agente não autentica ninguém. Quem garante a identidade é esta Lambda:
  - o `sub` vem do token (JWT authorizer do API Gateway), nunca do corpo;
  - o CNPJ e o papel vêm do item do usuário na tabela do cadastro (só leitura);
  - só a role desta Lambda pode invocar o runtime do agente;
  - o session id do runtime é sha256(sub:session_id): um usuário não entra na conversa de outro.
Dono e membros conversam (é leitura); nenhuma ferramenta do agente escreve.

Limite por usuário: LIMITE_HORA e LIMITE_DIA mensagens (contador atômico no DynamoDB, uma
transação para as duas janelas). Conta a tentativa, não o sucesso: o custo está no modelo.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time
from datetime import datetime, timezone

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError, ReadTimeoutError

import blocos as modelo_de_blocos  # cópia de ia/chatbot/blocos.py (make ia-chatbot-sync-blocos); um teste confere

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ.get("TABLE_NAME", "usuarios-cnpj")           # cadastro (só leitura)
LIMITES_TABLE = os.environ.get("LIMITES_TABLE", "chatbot-limites")
AGENT_RUNTIME_ARN = os.environ.get("AGENT_RUNTIME_ARN", "")
LIMITE_HORA = int(os.environ.get("LIMITE_HORA", "20"))
LIMITE_DIA = int(os.environ.get("LIMITE_DIA", "100"))
ESPERA_AGENTE_S = int(os.environ.get("ESPERA_AGENTE_S", "26"))
PROMPT_MAX = 2000

CNPJ = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
SESSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")

ERRO_AGENTE = "não foi possível responder agora, tente de novo"

_cadastro = boto3.resource("dynamodb").Table(TABLE_NAME)
_limites = boto3.resource("dynamodb").Table(LIMITES_TABLE)
_agente = None


def _cliente_agente():
    global _agente
    if _agente is None:
        _agente = boto3.client("bedrock-agentcore", config=Config(
            read_timeout=ESPERA_AGENTE_S, connect_timeout=3, retries={"max_attempts": 1}))
    return _agente


class ErroApi(Exception):
    def __init__(self, status: int, erro: str, headers: dict | None = None):
        super().__init__(erro)
        self.status, self.erro, self.headers = status, erro, headers or {}


def resp(status: int, body: dict, headers: dict | None = None) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json", **(headers or {})},
            "body": json.dumps(body, ensure_ascii=False)}


def agora() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- quem chama

def user_id_from_event(event: dict) -> str | None:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    return str(claims.get("sub") or "").strip() or None


def organizacao_do_usuario(user_id: str) -> tuple[str, str]:
    """(cnpj, papel) do usuário. Só leitura na tabela do cadastro."""
    item = _cadastro.get_item(Key={"user_id": user_id}).get("Item") or {}
    cnpj, papel = item.get("cnpj"), item.get("papel")
    if not cnpj or not CNPJ.match(cnpj):
        raise ErroApi(404, "cadastro não encontrado: envie um CNPJ ou aceite um convite")
    return cnpj, papel


def anonimo(user_id: str) -> str:
    """Identificador curto para correlacionar linhas de log sem registrar o `sub`."""
    return hashlib.sha256(user_id.encode()).hexdigest()[:8]


# ---------------------------------------------------------------- limite por usuário

def _janelas(t: datetime) -> tuple[tuple[str, int, int], tuple[str, int, int]]:
    """(sufixo da chave, limite, expira_em) da hora e do dia corrente (UTC)."""
    fim_hora = t.replace(minute=0, second=0, microsecond=0).timestamp() + 3600
    fim_dia = t.replace(hour=0, minute=0, second=0, microsecond=0).timestamp() + 86400
    return ((f"h{t:%Y%m%d%H}", LIMITE_HORA, int(fim_hora)), (f"d{t:%Y%m%d}", LIMITE_DIA, int(fim_dia)))


def contar_mensagem(user_id: str) -> None:
    """Conta a mensagem nas duas janelas, ou levanta 429 sem contar em nenhuma."""
    t = agora()
    janelas = _janelas(t)
    ops = [{"Update": {
        "TableName": LIMITES_TABLE,
        "Key": {"chave": f"{user_id}#{sufixo}"},
        "UpdateExpression": "SET n = if_not_exists(n, :zero) + :um, expira_em = :ttl",
        "ConditionExpression": "attribute_not_exists(n) OR n < :limite",
        "ExpressionAttributeValues": {":zero": 0, ":um": 1, ":limite": limite, ":ttl": fim + 86400},
    }} for sufixo, limite, fim in janelas]
    try:
        _limites.meta.client.transact_write_items(TransactItems=ops)   # valores Python, como em cnpj-cadastro
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        motivos = [m.get("Code") for m in exc.response.get("CancellationReasons") or []]
        (_, _, fim_hora), (_, _, fim_dia) = janelas
        if motivos and motivos[0] == "ConditionalCheckFailed":
            raise ErroApi(429, f"limite de {LIMITE_HORA} mensagens por hora atingido, tente mais tarde",
                          {"Retry-After": str(max(1, fim_hora - int(t.timestamp())))}) from exc
        raise ErroApi(429, f"limite de {LIMITE_DIA} mensagens por dia atingido, tente amanhã",
                      {"Retry-After": str(max(1, fim_dia - int(t.timestamp())))}) from exc


# ---------------------------------------------------------------- pedido

def _corpo(event: dict) -> tuple[str, str]:
    try:
        corpo = json.loads(event.get("body") or "{}")
    except ValueError:
        raise ErroApi(400, "JSON inválido") from None
    if not isinstance(corpo, dict):
        raise ErroApi(400, 'envie {"prompt": "..."}')
    prompt = corpo.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > PROMPT_MAX:
        raise ErroApi(400, f"prompt é obrigatório (texto de até {PROMPT_MAX} caracteres)")
    session_id = corpo.get("session_id", "padrao")
    if not isinstance(session_id, str) or not SESSION_ID.match(session_id):
        raise ErroApi(400, "session_id deve ter só letras, números, _ e - (até 100 caracteres)")
    return prompt.strip(), session_id


def sessao(user_id: str, session_id: str) -> str:
    """64 caracteres (o runtime exige 33 ou mais). Depende do usuário: não dá para entrar na de outro."""
    return hashlib.sha256(f"{user_id}:{session_id}".encode()).hexdigest()


def perguntar(cnpj: str, user_id: str, prompt: str, session_id: str) -> dict:
    payload = {"cnpj": cnpj, "user_id": user_id, "prompt": prompt, "session_id": session_id}
    try:
        r = _cliente_agente().invoke_agent_runtime(
            agentRuntimeArn=AGENT_RUNTIME_ARN, runtimeSessionId=session_id,
            contentType="application/json", accept="application/json",
            payload=json.dumps(payload).encode())
        corpo = r["response"].read()
    except ReadTimeoutError as exc:
        raise ErroApi(504, "o assistente demorou demais para responder, tente de novo") from exc
    except (ClientError, BotoCoreError):
        log.exception("falha ao invocar o agente")
        raise ErroApi(502, ERRO_AGENTE) from None
    try:
        saida = json.loads(corpo)
    except ValueError:
        log.error("o agente devolveu algo que não é JSON: %r", corpo[:200])
        raise ErroApi(502, ERRO_AGENTE) from None
    if not isinstance(saida, dict) or not isinstance(saida.get("resposta"), str):
        # inclui {"erro": ...}: o texto do agente é para o log, não para o cliente
        log.error("o agente devolveu erro ou formato inesperado: %r", str(saida)[:300])
        raise ErroApi(502, ERRO_AGENTE)
    return saida


def handler(event, context=None):
    inicio = time.monotonic()
    user_id = user_id_from_event(event)
    if not user_id:
        return resp(401, {"erro": "não autenticado"})
    if event.get("routeKey") != "POST /chatbot/mensagens":
        return resp(404, {"erro": "rota não encontrada"})
    registro = {"evento": "mensagem", "usuario": anonimo(user_id)}
    try:
        cnpj, papel = organizacao_do_usuario(user_id)
        registro.update(cnpj=cnpj, papel=papel)
        prompt, session_id = _corpo(event)
        contar_mensagem(user_id)
        saida = perguntar(cnpj, user_id, prompt, sessao(user_id, session_id))
        bruto = saida.get("blocos")
        dados = modelo_de_blocos.validos(bruto)   # o front só recebe blocos com a forma do contrato
        if bruto is not None and (not isinstance(bruto, list) or len(dados) != len(bruto)):
            log.warning("blocos do agente descartados por forma inválida")
        registro.update(resultado="ok", consultas=saida.get("consultas"), blocos=[b["tipo"] for b in dados])
        return resp(200, {"resposta": saida["resposta"], "blocos": dados})
    except ErroApi as exc:
        registro["resultado"] = exc.status
        return resp(exc.status, {"erro": exc.erro}, exc.headers)
    finally:
        registro["ms"] = int((time.monotonic() - inicio) * 1000)
        log.info(json.dumps(registro, ensure_ascii=False))   # nunca o texto da pergunta ou da resposta
