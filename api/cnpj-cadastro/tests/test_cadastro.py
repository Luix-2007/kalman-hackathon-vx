import importlib
import json

import pytest
from conftest import chamar, evento, item


class FakeEvents:
    def __init__(self, failed=0):
        self.entries, self.failed = [], failed

    def put_events(self, Entries):
        self.entries.extend(Entries)
        return {"FailedEntryCount": self.failed}


@pytest.fixture
def cadastro(tabela, emails, monkeypatch):
    import cadastro as module
    module = importlib.reload(module)
    monkeypatch.setattr(module, "_events", FakeEvents())
    emails.update({"sub-123": "dono@a.com", "u1": "u1@a.com", "u2": "u2@a.com"})
    return module


def call(cadastro, body, sub="sub-123"):
    return chamar(cadastro, evento(sub, body, method="POST"))


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


def test_sem_token_401_e_nao_publica(cadastro, tabela):
    assert call(cadastro, {"cnpj": "00000000000191"}, sub=None)[0] == 401
    assert cadastro._events.entries == [] and item(tabela, "CNPJ#00000000000191") is None


@pytest.mark.parametrize("body", ["{nao-json", "[1, 2]", {}, {"cnpj": "123"}, {"cnpj": None}])
def test_body_invalido_400_e_nao_publica(cadastro, tabela, body):
    assert call(cadastro, body)[0] == 400
    assert cadastro._events.entries == [] and item(tabela, "sub-123") is None


# ---------- organização: um dono por CNPJ ----------

def test_cria_organizacao_com_o_usuario_como_dono(cadastro, tabela):
    assert call(cadastro, {"cnpj": "00000000000191"})[0] == 202
    assert item(tabela, "sub-123") == {"user_id": "sub-123", "cnpj": "00000000000191", "papel": "dono"}
    org = item(tabela, "CNPJ#00000000000191")
    assert org["dono"] == "sub-123" and org["dono_email"] == "dono@a.com"
    assert org["status"] == "processando" and org["dados"] == {} and org["membros"] == {}


def test_cnpj_de_outro_usuario_409_e_nao_publica(cadastro, tabela):
    assert call(cadastro, {"cnpj": "00000000000191"}, sub="u1")[0] == 202
    code, body = call(cadastro, {"cnpj": "00.000.000/0001-91"}, sub="u2")
    assert code == 409 and "outro usuário" in body["erro"]
    assert item(tabela, "u2") is None and item(tabela, "CNPJ#00000000000191")["dono"] == "u1"
    assert len(cadastro._events.entries) == 1


def test_reenvio_do_mesmo_cnpj_refaz_a_consulta(cadastro, tabela):
    assert call(cadastro, {"cnpj": "00000000000191"})[0] == 202
    tabela.update_item(Key={"user_id": "CNPJ#00000000000191"}, UpdateExpression="SET #s = :s, dados = :d",
                       ExpressionAttributeNames={"#s": "status"},
                       ExpressionAttributeValues={":s": "ativa", ":d": {"x": 1}})
    assert call(cadastro, {"cnpj": "00000000000191"})[0] == 202
    assert len(cadastro._events.entries) == 2
    org = item(tabela, "CNPJ#00000000000191")
    assert org["status"] == "ativa" and org["dados"] == {"x": 1}  # nada muda até a consulta terminar


def test_troca_de_cnpj_sem_membros_libera_o_anterior(cadastro, tabela):
    assert call(cadastro, {"cnpj": "00000000000191"}, sub="u1")[0] == 202
    tabela.update_item(Key={"user_id": "CNPJ#00000000000191"}, UpdateExpression="SET empresa = :e, dados = :d",
                       ExpressionAttributeValues={":e": {"razao_social": "X"}, ":d": {"setor": "energia"}})
    assert call(cadastro, {"cnpj": "33000167000101"}, sub="u1")[0] == 202
    assert item(tabela, "u1")["cnpj"] == "33000167000101"
    assert item(tabela, "CNPJ#00000000000191") is None
    org = item(tabela, "CNPJ#33000167000101")
    assert org["dono"] == "u1" and org["status"] == "processando"
    assert "empresa" not in org and org["dados"] == {"setor": "energia"}  # o formulário vai junto
    # o CNPJ liberado pode ser usado por outra pessoa; o novo, não
    assert call(cadastro, {"cnpj": "00000000000191"}, sub="u2")[0] == 202
    assert call(cadastro, {"cnpj": "33000167000101"}, sub="u2")[0] == 409


def test_troca_com_membros_ou_convites_409(cadastro, tabela):
    assert call(cadastro, {"cnpj": "00000000000191"}, sub="u1")[0] == 202
    tabela.update_item(Key={"user_id": "CNPJ#00000000000191"}, UpdateExpression="SET membros.#m = :m",
                       ExpressionAttributeNames={"#m": "u9"}, ExpressionAttributeValues={":m": {"email": "x@a.com"}})
    code, body = call(cadastro, {"cnpj": "33000167000101"}, sub="u1")
    assert code == 409 and "membros" in body["erro"]
    tabela.update_item(Key={"user_id": "CNPJ#00000000000191"},
                       UpdateExpression="REMOVE membros.#m SET convites.#e = :c",
                       ExpressionAttributeNames={"#m": "u9", "#e": "y@a.com"},
                       ExpressionAttributeValues={":c": {"criado_em": "x", "expira_em": 9999999999}})
    assert call(cadastro, {"cnpj": "33000167000101"}, sub="u1")[0] == 409
    assert item(tabela, "u1")["cnpj"] == "00000000000191"


def test_membro_nao_cria_organizacao(cadastro, tabela):
    tabela.put_item(Item={"user_id": "u2", "cnpj": "00000000000191", "papel": "membro"})
    code, body = call(cadastro, {"cnpj": "33000167000101"}, sub="u2")
    assert code == 409 and "membro" in body["erro"]
    assert item(tabela, "CNPJ#33000167000101") is None and cadastro._events.entries == []


def test_falha_no_eventbridge_mantem_vinculo_e_reenvio_funciona(cadastro, monkeypatch):
    monkeypatch.setattr(cadastro, "_events", FakeEvents(failed=1))
    assert call(cadastro, {"cnpj": "00000000000191"})[0] == 502
    monkeypatch.setattr(cadastro, "_events", FakeEvents())
    assert call(cadastro, {"cnpj": "00000000000191"})[0] == 202
    assert len(cadastro._events.entries) == 1


@pytest.mark.parametrize("lista", ["unidades", "outorgas", "areas"])
def test_troca_com_perfil_regulatorio_409(cadastro, tabela, lista):
    assert call(cadastro, {"cnpj": "00000000000191"}, sub="u1")[0] == 202
    tabela.update_item(Key={"user_id": "CNPJ#00000000000191"}, UpdateExpression="SET dados = :d",
                       ExpressionAttributeValues={":d": {"setor": "energia", lista: [{"id": "X"}]}})
    code, body = call(cadastro, {"cnpj": "33000167000101"}, sub="u1")
    assert code == 409 and "perfil regulatório" in body["erro"]
    assert item(tabela, "u1")["cnpj"] == "00000000000191"
    assert item(tabela, "CNPJ#33000167000101") is None


def test_troca_com_listas_vazias_e_permitida(cadastro, tabela):
    assert call(cadastro, {"cnpj": "00000000000191"}, sub="u1")[0] == 202
    tabela.update_item(Key={"user_id": "CNPJ#00000000000191"}, UpdateExpression="SET dados = :d",
                       ExpressionAttributeValues={":d": {"unidades": [], "setor": "energia"}})
    assert call(cadastro, {"cnpj": "33000167000101"}, sub="u1")[0] == 202
