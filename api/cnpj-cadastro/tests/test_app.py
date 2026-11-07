import http.server
import importlib
import json
import os
import sys
import threading

import boto3
import pytest

RESPONSES = {
    "00000000000191": (200, {"cnpj": "00000000000191", "razao_social": "BANCO DO BRASIL SA",
                             "situacao_cadastral": "Ativa", "capital_social": "120000000000,00",
                             "QSA": [{"nome_socio": "FULANO", "is_x": False}], "score": 1.5}),
    "11111111000111": (200, {"cnpj": "11111111000111", "situacao_cadastral": "Baixada"}),
    "22222222000122": (429, {"error": "too many"}),
}


CHAMADAS: list[str] = []  # CNPJs pedidos ao OpenCNPJ falso


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        cnpj = self.path.strip("/").split("?")[0]
        CHAMADAS.append(cnpj)
        code, body = RESPONSES.get(cnpj, (404, {"error": "not found"}))
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def app(tabela, monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    for k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("OPENCNPJ_API_URL", f"http://127.0.0.1:{srv.server_address[1]}")
    monkeypatch.delenv("FIXTURES_ENABLED", raising=False)
    CHAMADAS.clear()
    import app as module
    yield importlib.reload(module)
    srv.shutdown()


def item(uid):
    return boto3.resource("dynamodb").Table("t").get_item(Key={"user_id": uid}).get("Item")


def org(cnpj):
    return item(f"CNPJ#{cnpj}")


def vincular(uid, cnpj):
    """Simula o POST /cadastro, que cria a organização (com o dono) antes do evento."""
    boto3.resource("dynamodb").Table("t").put_item(Item={
        "user_id": f"CNPJ#{cnpj}", "cnpj": cnpj, "dono": uid, "status": "processando",
        "dados": {}, "membros": {}, "convites": {}})


def ev(uid, cnpj, vinculado=True):
    if vinculado:
        vincular(uid, "".join(c for c in cnpj if c.isalnum()))  # o POST grava sem máscara
    return {"source": "app.usuarios", "detail-type": "UsuarioCadastrado", "detail": {"user_id": uid, "cnpj": cnpj}}


def test_ativa(app):
    assert app.handler(ev("u1", "00.000.000/0001-91"))["status"] == "ativa"
    o = org("00000000000191")
    assert o["status"] == "ativa" and o["empresa"]["razao_social"] == "BANCO DO BRASIL SA"
    assert o["dono"] == "u1" and o["membros"] == {}  # o resto da organização fica intacto


def test_inativa_nao_encontrado(app):
    assert app.handler(ev("u2", "11111111000111"))["status"] == "inativa"
    assert app.handler(ev("u3", "99999999000199"))["status"] == "nao_encontrado"
    assert "empresa" not in org("99999999000199")


def test_evento_sem_organizacao_ou_invalido_e_ignorado(app):
    assert app.handler(ev("u4", "00000000000191", vinculado=False))["status"] == "ignorado"
    assert app.handler(ev("u4", "123", vinculado=False))["status"] == "ignorado"
    assert org("00000000000191") is None  # não cria a organização


def test_evento_de_quem_nao_e_dono_e_ignorado(app):
    vincular("dono", "00000000000191")  # ex.: o usuário trocou de CNPJ e outra pessoa pegou este
    assert app.handler(ev("antigo", "00000000000191", vinculado=False))["status"] == "ignorado"
    o = org("00000000000191")
    assert o["dono"] == "dono" and o["status"] == "processando" and "empresa" not in o


def test_429_falha_para_retry(app):
    with pytest.raises(app.RetryableError):
        app.handler(ev("u5", "22222222000122"))
    assert org("22222222000122")["status"] == "processando"


def test_nova_consulta_preserva_dados_do_formulario(app):
    app.handler(ev("u6", "00000000000191"))
    boto3.resource("dynamodb").Table("t").update_item(
        Key={"user_id": "CNPJ#00000000000191"}, UpdateExpression="SET dados = :d",
        ExpressionAttributeValues={":d": {"telefone": "1199"}})
    assert app.handler(ev("u6", "00000000000191", vinculado=False))["status"] == "ativa"  # reconsulta
    assert org("00000000000191")["dados"] == {"telefone": "1199"}


# ---------------------------------------------------------------- empresa de teste (fixture)

def test_fixture_ligada_le_arquivo_sem_chamar_opencnpj(app, monkeypatch):
    monkeypatch.setenv("FIXTURES_ENABLED", "true")
    assert app.handler(ev("u7", "KALMANTESTE100"))["status"] == "ativa"
    o = org("KALMANTESTE100")
    assert o["empresa"]["razao_social"] == "AURORA ENERGIA S.A."
    assert o["empresa"]["cnae_principal"] == "3514000" and o["empresa"]["uf"] == "SP"
    assert CHAMADAS == []


def test_fixture_ligada_nao_afeta_cnpj_real(app, monkeypatch):
    monkeypatch.setenv("FIXTURES_ENABLED", "true")
    assert app.handler(ev("u8", "00000000000191"))["status"] == "ativa"
    assert CHAMADAS == ["00000000000191"]


def test_fixture_ligada_sem_arquivo_e_nao_encontrado(app, monkeypatch):
    monkeypatch.setenv("FIXTURES_ENABLED", "true")
    assert app.handler(ev("u9", "KALMANTESTE999"))["status"] == "nao_encontrado"
    assert CHAMADAS == []


def test_fixture_desligada_vai_ao_opencnpj(app):
    assert app.handler(ev("u10", "KALMANTESTE100"))["status"] == "nao_encontrado"
    assert CHAMADAS == ["KALMANTESTE100"]


def test_fixture_reenviar_preserva_dados(app, monkeypatch):
    monkeypatch.setenv("FIXTURES_ENABLED", "true")
    app.handler(ev("u11", "KALMANTESTE100"))
    boto3.resource("dynamodb").Table("t").update_item(
        Key={"user_id": "CNPJ#KALMANTESTE100"}, UpdateExpression="SET dados = :d",
        ExpressionAttributeValues={":d": {"nome_fantasia": "Aurora"}})
    assert app.handler(ev("u11", "KALMANTESTE100", vinculado=False))["status"] == "ativa"
    assert org("KALMANTESTE100")["dados"] == {"nome_fantasia": "Aurora"}
