import importlib
import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))


class FakeEvents:
    def __init__(self, failed=0):
        self.entries, self.failed = [], failed

    def put_events(self, Entries):
        self.entries.extend(Entries)
        return {"FailedEntryCount": self.failed}


@pytest.fixture
def cadastro(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    import cadastro as module
    module = importlib.reload(module)
    monkeypatch.setattr(module, "_events", FakeEvents())
    return module


def req(body, sub="sub-123"):
    event = {"body": body if isinstance(body, str) else json.dumps(body)}
    if sub is not None:
        event["requestContext"] = {"authorizer": {"jwt": {"claims": {"sub": sub}}}}
    return event


def call(cadastro, *args, **kw):
    r = cadastro.handler(req(*args, **kw))
    return r["statusCode"], json.loads(r["body"])


def test_publica_evento_com_user_id_do_token(cadastro):
    code, body = call(cadastro, {"cnpj": "00.000.000/0001-91"})
    assert code == 202 and body["user_id"] == "sub-123" and body["cnpj"] == "00000000000191"
    (entry,) = cadastro._events.entries
    assert entry["Source"] == "app.usuarios" and entry["DetailType"] == "UsuarioCadastrado"
    assert json.loads(entry["Detail"]) == {"user_id": "sub-123", "cnpj": "00000000000191"}


def test_ignora_user_id_do_body(cadastro):
    code, body = call(cadastro, {"user_id": "outra-pessoa", "cnpj": "00000000000191"})
    assert code == 202 and body["user_id"] == "sub-123"
    assert json.loads(cadastro._events.entries[0]["Detail"])["user_id"] == "sub-123"


def test_sem_token_401_e_nao_publica(cadastro):
    assert call(cadastro, {"cnpj": "00000000000191"}, sub=None)[0] == 401
    assert cadastro._events.entries == []


@pytest.mark.parametrize("body", ["{nao-json", "[1, 2]", {}, {"cnpj": "123"}, {"cnpj": None}])
def test_body_invalido_400_e_nao_publica(cadastro, body):
    assert call(cadastro, body)[0] == 400
    assert cadastro._events.entries == []


def test_falha_no_eventbridge_502(cadastro, monkeypatch):
    monkeypatch.setattr(cadastro, "_events", FakeEvents(failed=1))
    assert call(cadastro, {"cnpj": "00000000000191"})[0] == 502
