"""
Quem está chamando a API.

O API Gateway valida o token do Cognito antes de chamar a Lambda (JWT authorizer
no template.yaml) e repassa os dados do token em requestContext.authorizer.jwt.claims.
O `sub` é o ID fixo e único do usuário no Cognito: é ele que usamos como user_id.
Nunca use um user_id vindo do body ou da URL.
"""

from __future__ import annotations

import os
import re

import boto3

USER_POOL_ID = os.environ.get("USER_POOL_ID", "")
_SUB = re.compile(r"^[0-9a-f-]{36}$")

_cognito = None


def user_id_from_event(event: dict) -> str | None:
    claims = (
        (event.get("requestContext") or {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    sub = str(claims.get("sub") or "").strip()
    return sub or None


def email_do_usuario(sub: str) -> str | None:
    """E-mail verificado do usuário, lido do Cognito (o access token não traz o e-mail)."""
    global _cognito
    if not _SUB.match(sub):
        return None
    _cognito = _cognito or boto3.client("cognito-idp")
    users = _cognito.list_users(UserPoolId=USER_POOL_ID, Filter=f'sub = "{sub}"', Limit=1)["Users"]
    if not users:
        return None
    attrs = {a["Name"]: a["Value"] for a in users[0]["Attributes"]}
    if attrs.get("email_verified") != "true":
        return None
    return attrs.get("email", "").strip().lower() or None
