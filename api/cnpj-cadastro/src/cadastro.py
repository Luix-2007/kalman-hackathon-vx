"""
POST /cadastro  (chamado pelo front, com o token do Cognito)

Header: Authorization: Bearer <access token>
Body JSON: {"cnpj": "00.000.000/0001-91"}

O user_id vem do token (claim "sub"); qualquer user_id no body é ignorado.
Valida e publica o evento "UsuarioCadastrado" no EventBridge.
Responde 202 na hora; a consulta do CNPJ acontece em segundo plano (app.py).
"""

import json
import os

import boto3

from app import normalize_cnpj
from auth import user_id_from_event

EVENT_SOURCE = os.environ.get("EVENT_SOURCE", "app.usuarios")
EVENT_DETAIL_TYPE = os.environ.get("EVENT_DETAIL_TYPE", "UsuarioCadastrado")

_events = boto3.client("events")


def _resp(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"}, "body": json.dumps(body)}


def handler(event, context=None):
    user_id = user_id_from_event(event)
    if not user_id:
        return _resp(401, {"erro": "não autenticado"})

    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return _resp(400, {"erro": "JSON inválido"})
    if not isinstance(body, dict):
        return _resp(400, {"erro": 'envie {"cnpj": "..."}'})

    try:
        cnpj = normalize_cnpj(body.get("cnpj", ""))
    except ValueError:
        return _resp(400, {"erro": "CNPJ inválido"})

    result = _events.put_events(Entries=[{
        "Source": EVENT_SOURCE,
        "DetailType": EVENT_DETAIL_TYPE,
        "Detail": json.dumps({"user_id": user_id, "cnpj": cnpj}),
    }])
    if result.get("FailedEntryCount"):
        return _resp(502, {"erro": "não foi possível registrar o cadastro, tente de novo"})
    return _resp(202, {"status": "recebido", "user_id": user_id, "cnpj": cnpj})
