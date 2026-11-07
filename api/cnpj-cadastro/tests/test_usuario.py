import importlib

import pytest
from conftest import chamar, evento, item

ORG = "CNPJ#00000000000191"


@pytest.fixture
def usuario(tabela):
    tabela.put_item(Item={"user_id": "u1", "cnpj": "00000000000191", "papel": "dono"})
    tabela.put_item(Item={"user_id": "m1", "cnpj": "00000000000191", "papel": "membro"})
    tabela.put_item(Item={
        "user_id": ORG, "cnpj": "00000000000191", "dono": "u1", "status": "ativa",
        "consultado_em": "2026-01-01T00:00:00+00:00", "membros": {"m1": {"email": "m1@a.com"}}, "convites": {},
        "empresa": {"razao_social": "BANCO DO BRASIL SA", "QSA": [{"nome_socio": "FULANO"}]},
    })
    import usuario as module
    return importlib.reload(module)


def req(method, user_id, body=None):
    return evento(user_id, body, method=method)


def call(usuario, *args, **kw):
    return chamar(usuario, req(*args, **kw))


def test_get_devolve_cadastro_sem_socios(usuario):
    code, body = call(usuario, "GET", "u1")
    assert code == 200 and body["papel"] == "dono"
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


def test_patch_inexistente_404_e_nao_cria(usuario, tabela):
    assert call(usuario, "PATCH", "fantasma", {"dados": {"a": 1}})[0] == 404
    assert item(tabela, "fantasma") is None


def test_membro_ve_os_mesmos_dados_mas_nao_edita(usuario, tabela):
    call(usuario, "PATCH", "u1", {"dados": {"telefone": "1199"}})
    code, body = call(usuario, "GET", "m1")
    assert code == 200 and body["papel"] == "membro" and body["dados"] == {"telefone": "1199"}
    assert body["empresa"]["razao_social"] == "BANCO DO BRASIL SA" and "QSA" not in body["empresa"]
    code, body = call(usuario, "PATCH", "m1", {"dados": {"telefone": "000"}})
    assert code == 403
    assert item(tabela, ORG)["dados"] == {"telefone": "1199"}


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
