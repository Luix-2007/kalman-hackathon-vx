import importlib
import json
import os
import sys

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


@pytest.fixture
def usuario(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "t")
    with mock_aws():
        db = boto3.resource("dynamodb")
        db.create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}])
        db.Table("t").put_item(Item={
            "user_id": "u1", "cnpj": "00000000000191", "status": "ativa",
            "consultado_em": "2026-01-01T00:00:00+00:00",
            "empresa": {"razao_social": "BANCO DO BRASIL SA", "QSA": [{"nome_socio": "FULANO"}]},
        })
        import usuario as module
        yield importlib.reload(module)


def req(method, user_id, body=None):
    """Simula o evento do API Gateway depois do JWT authorizer (user_id = sub do token)."""
    ctx = {"http": {"method": method}}
    if user_id is not None:
        ctx["authorizer"] = {"jwt": {"claims": {"sub": user_id}}}
    return {"requestContext": ctx, "body": json.dumps(body) if body is not None else None}


def call(usuario, *args, **kw):
    r = usuario.handler(req(*args, **kw))
    return r["statusCode"], json.loads(r["body"])


def test_get_devolve_cadastro_sem_socios(usuario):
    code, body = call(usuario, "GET", "u1")
    assert code == 200
    assert body["status"] == "ativa" and body["empresa"]["razao_social"] == "BANCO DO BRASIL SA"
    assert "QSA" not in body["empresa"]
    assert body["dados"] == {}


def test_get_inexistente_404(usuario):
    assert call(usuario, "GET", "nao-existe")[0] == 404


def test_patch_faz_merge_e_null_remove(usuario):
    code, body = call(usuario, "PATCH", "u1", {"dados": {"telefone": "1199", "site": "a.com", "idade": 3}})
    assert code == 200 and body["dados"] == {"telefone": "1199", "site": "a.com", "idade": 3}
    code, body = call(usuario, "PATCH", "u1", {"dados": {"telefone": "2288", "site": None}})
    assert body["dados"] == {"telefone": "2288", "idade": 3}
    assert body["status"] == "ativa" and body["cnpj"] == "00000000000191"  # intocados


def test_patch_so_remove_campo(usuario):
    call(usuario, "PATCH", "u1", {"dados": {"a": 1}})
    code, body = call(usuario, "PATCH", "u1", {"dados": {"a": None}})
    assert code == 200 and body["dados"] == {}


def test_patch_inexistente_404_e_nao_cria(usuario):
    assert call(usuario, "PATCH", "fantasma", {"dados": {"a": 1}})[0] == 404
    assert boto3.resource("dynamodb").Table("t").get_item(Key={"user_id": "fantasma"}).get("Item") is None


@pytest.mark.parametrize("body", [{}, {"dados": {}}, {"dados": "x"}, {"dados": {"Status": 1}},
                                  {"dados": {"status; drop": 1}}, {"dados": {f"c{i}": 1 for i in range(51)}}])
def test_patch_invalido_400(usuario, body):
    assert call(usuario, "PATCH", "u1", body)[0] == 400


def test_patch_json_quebrado_400(usuario):
    r = usuario.handler({**req("PATCH", "u1"), "body": "{nao-json"})
    assert r["statusCode"] == 400


def test_campos_permitidos(usuario, monkeypatch):
    monkeypatch.setattr(usuario, "CAMPOS_PERMITIDOS", {"telefone"})
    assert call(usuario, "PATCH", "u1", {"dados": {"telefone": "1"}})[0] == 200
    assert call(usuario, "PATCH", "u1", {"dados": {"outro": "1"}})[0] == 400


def test_metodo_nao_permitido(usuario):
    assert call(usuario, "DELETE", "u1")[0] == 405


def test_sem_token_401(usuario):
    assert call(usuario, "GET", None)[0] == 401
    assert call(usuario, "PATCH", None, {"dados": {"a": 1}})[0] == 401


def test_usuario_so_acessa_o_proprio_cadastro(usuario):
    # o "intruso" está logado, mas não tem cadastro: não vê nem altera o de u1
    r = usuario.handler({**req("GET", "intruso"), "pathParameters": {"user_id": "u1"}})
    assert r["statusCode"] == 404
    r = usuario.handler({**req("PATCH", "intruso", {"dados": {"a": 1}}), "pathParameters": {"user_id": "u1"}})
    assert r["statusCode"] == 404
    assert call(usuario, "GET", "u1")[1]["dados"] == {}
