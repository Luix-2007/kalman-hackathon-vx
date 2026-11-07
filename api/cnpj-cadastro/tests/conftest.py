import importlib
import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def tabela(monkeypatch):
    """Tabela única no moto (DynamoDB falso, em memória). Recarrega dados.py dentro do mock."""
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "t")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}])
        import dados
        importlib.reload(dados)
        yield boto3.resource("dynamodb").Table("t")


@pytest.fixture
def emails(monkeypatch):
    """E-mail de cada usuário no Cognito, sem chamar o Cognito: {sub: email}."""
    import auth
    mapa: dict[str, str] = {}
    monkeypatch.setattr(auth, "email_do_usuario", lambda sub: mapa.get(sub))
    return mapa


def item(tabela, chave):
    return tabela.get_item(Key={"user_id": chave}).get("Item")


def evento(sub, body=None, method="GET", route=None, path_params=None):
    """Simula o evento do API Gateway depois do JWT authorizer (user_id = sub do token)."""
    ctx = {"http": {"method": method}}
    if sub is not None:
        ctx["authorizer"] = {"jwt": {"claims": {"sub": sub}}}
    ev = {"requestContext": ctx, "routeKey": route or "",
          "body": body if body is None or isinstance(body, str) else json.dumps(body)}
    if path_params:
        ev["pathParameters"] = path_params
    return ev


def chamar(module, ev):
    r = module.handler(ev)
    return r["statusCode"], json.loads(r["body"])
