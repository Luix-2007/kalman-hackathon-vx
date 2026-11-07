import http.server
import importlib
import json
import os
import sys
import threading

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

RESPONSES = {
    "00000000000191": (200, {"cnpj": "00000000000191", "razao_social": "BANCO DO BRASIL SA",
                             "situacao_cadastral": "Ativa", "capital_social": "120000000000,00",
                             "QSA": [{"nome_socio": "FULANO", "is_x": False}], "score": 1.5}),
    "11111111000111": (200, {"cnpj": "11111111000111", "situacao_cadastral": "Baixada"}),
    "22222222000122": (429, {"error": "too many"}),
}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        cnpj = self.path.strip("/").split("?")[0]
        code, body = RESPONSES.get(cnpj, (404, {"error": "not found"}))
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def app(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("OPENCNPJ_API_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}])
        import app as module
        yield importlib.reload(module)
    srv.shutdown()


def item(uid):
    return boto3.resource("dynamodb").Table("t").get_item(Key={"user_id": uid}).get("Item")


def ev(uid, cnpj):
    return {"source": "app.usuarios", "detail-type": "UsuarioCadastrado", "detail": {"user_id": uid, "cnpj": cnpj}}


def test_ativa(app):
    assert app.handler(ev("u1", "00.000.000/0001-91"))["status"] == "ativa"
    i = item("u1")
    assert i["cnpj"] == "00000000000191" and i["empresa"]["razao_social"] == "BANCO DO BRASIL SA"


def test_inativa_nao_encontrado_invalido(app):
    assert app.handler(ev("u2", "11111111000111"))["status"] == "inativa"
    assert app.handler(ev("u3", "99999999000199"))["status"] == "nao_encontrado"
    assert app.handler(ev("u4", "123"))["status"] == "cnpj_invalido"
    assert "empresa" not in item("u3")


def test_429_falha_para_retry(app):
    with pytest.raises(app.RetryableError):
        app.handler(ev("u5", "22222222000122"))
    assert item("u5") is None
