import importlib

import pytest
from conftest import chamar, evento, item

CNPJ = "00000000000191"
ORG = f"CNPJ#{CNPJ}"


@pytest.fixture
def membros(tabela, emails):
    """Organização do "dono"; "ana" e "beto" têm conta, mas ainda não participam de nenhuma."""
    emails.update({"dono": "dono@empresa.com", "ana": "ana@empresa.com", "beto": "beto@empresa.com"})
    tabela.put_item(Item={"user_id": "dono", "cnpj": CNPJ, "papel": "dono"})
    tabela.put_item(Item={"user_id": ORG, "cnpj": CNPJ, "dono": "dono", "dono_email": "dono@empresa.com",
                          "status": "ativa", "empresa": {"razao_social": "BANCO DO BRASIL SA"},
                          "dados": {}, "membros": {}, "convites": {}})
    import membros as module
    return importlib.reload(module)


def call(m, sub, route, body=None, id=None):
    method = route.split()[0]
    return chamar(m, evento(sub, body, method=method, route=route, path_params={"id": id} if id else None))


def convidar(m, email, sub="dono"):
    return call(m, sub, "POST /cadastro/membros", {"email": email})


def aceitar(m, sub):
    return call(m, sub, "POST /cadastro/convite")


def test_fluxo_convite_aceito(membros, tabela):
    code, body = convidar(membros, " Ana@Empresa.com ")
    assert code == 201 and body["email"] == "ana@empresa.com"
    assert item(tabela, "CONVITE#ana@empresa.com")["cnpj"] == CNPJ

    code, body = call(membros, "ana", "GET /cadastro/convite")
    assert code == 200 and body["razao_social"] == "BANCO DO BRASIL SA" and body["convidado_por"] == "dono@empresa.com"

    code, body = aceitar(membros, "ana")
    assert code == 200 and body == {"cnpj": CNPJ, "papel": "membro"}
    assert item(tabela, "ana") == {"user_id": "ana", "cnpj": CNPJ, "papel": "membro"}
    assert item(tabela, "CONVITE#ana@empresa.com") is None
    org = item(tabela, ORG)
    assert org["membros"]["ana"]["email"] == "ana@empresa.com" and org["convites"] == {}

    code, body = call(membros, "ana", "GET /cadastro/membros")
    assert code == 200 and body["dono"]["email"] == "dono@empresa.com"
    assert [m["user_id"] for m in body["membros"]] == ["ana"] and "convites" not in body  # membro não vê convites


def test_so_o_dono_convida_e_remove(membros):
    convidar(membros, "ana@empresa.com")
    aceitar(membros, "ana")
    assert convidar(membros, "beto@empresa.com", sub="ana")[0] == 403
    assert call(membros, "ana", "DELETE /cadastro/membros/{id}", id="dono")[0] == 403
    assert call(membros, "ana", "DELETE /cadastro/membros/{id}", id="beto@empresa.com")[0] == 403


def test_quem_nao_participa_nao_ve_nada(membros):
    assert call(membros, "beto", "GET /cadastro/membros")[0] == 404
    assert convidar(membros, "x@empresa.com", sub="beto")[0] == 404


@pytest.mark.parametrize("body", [{}, {"email": "sem-arroba"}, {"email": ""}, "{quebrado", [1]])
def test_convite_invalido_400(membros, body):
    assert call(membros, "dono", "POST /cadastro/membros", body)[0] == 400


def test_nao_convida_quem_ja_faz_parte(membros):
    assert convidar(membros, "dono@empresa.com")[0] == 409
    convidar(membros, "ana@empresa.com")
    aceitar(membros, "ana")
    assert convidar(membros, "ana@empresa.com")[0] == 409


def test_um_convite_pendente_por_email(membros, tabela):
    tabela.put_item(Item={"user_id": "CNPJ#33000167000101", "cnpj": "33000167000101", "dono": "outro",
                          "membros": {}, "convites": {}})
    tabela.put_item(Item={"user_id": "outro", "cnpj": "33000167000101", "papel": "dono"})
    assert convidar(membros, "ana@empresa.com")[0] == 201
    assert convidar(membros, "ana@empresa.com")[0] == 201  # o mesmo dono pode renovar
    code, body = convidar(membros, "ana@empresa.com", sub="outro")
    assert code == 409 and "outra organização" in body["erro"]


def test_convite_vencido(membros, tabela):
    convidar(membros, "ana@empresa.com")
    tabela.update_item(Key={"user_id": "CONVITE#ana@empresa.com"}, UpdateExpression="SET expira_em = :e",
                       ExpressionAttributeValues={":e": 1})
    assert call(membros, "ana", "GET /cadastro/convite")[0] == 404
    assert aceitar(membros, "ana")[0] == 404
    assert item(tabela, "ana") is None


def test_quem_ja_tem_organizacao_nao_aceita(membros, tabela):
    tabela.put_item(Item={"user_id": "ana", "cnpj": "33000167000101", "papel": "dono"})
    convidar(membros, "ana@empresa.com")
    code, body = aceitar(membros, "ana")
    assert code == 409 and "já participa" in body["erro"]
    assert item(tabela, "ana")["cnpj"] == "33000167000101"
    assert item(tabela, "CONVITE#ana@empresa.com") is not None  # nada mudou


def test_recusar_convite(membros, tabela):
    convidar(membros, "ana@empresa.com")
    assert call(membros, "ana", "DELETE /cadastro/convite")[0] == 200
    assert item(tabela, "CONVITE#ana@empresa.com") is None and item(tabela, ORG)["convites"] == {}
    assert call(membros, "ana", "DELETE /cadastro/convite")[0] == 404


def test_dono_cancela_convite(membros, tabela):
    convidar(membros, "ana@empresa.com")
    code, body = call(membros, "dono", "GET /cadastro/membros")
    assert [c["email"] for c in body["convites"]] == ["ana@empresa.com"]
    assert call(membros, "dono", "DELETE /cadastro/membros/{id}", id="ana%40empresa.com")[0] == 200
    assert item(tabela, "CONVITE#ana@empresa.com") is None and item(tabela, ORG)["convites"] == {}
    assert aceitar(membros, "ana")[0] == 404


def test_dono_remove_membro_e_membro_sai(membros, tabela):
    for nome in ("ana", "beto"):
        convidar(membros, f"{nome}@empresa.com")
        aceitar(membros, nome)
    assert call(membros, "dono", "DELETE /cadastro/membros/{id}", id="ana")[0] == 200
    assert item(tabela, "ana") is None and "ana" not in item(tabela, ORG)["membros"]
    assert call(membros, "dono", "DELETE /cadastro/membros/{id}", id="ana")[0] == 404
    assert call(membros, "beto", "DELETE /cadastro/membros/{id}", id="beto")[0] == 200  # sair
    assert item(tabela, "beto") is None and item(tabela, ORG)["membros"] == {}


def test_dono_nao_sai_nem_se_remove(membros, tabela):
    assert call(membros, "dono", "DELETE /cadastro/membros/{id}", id="dono")[0] == 400
    assert item(tabela, "dono")["papel"] == "dono"


def test_sem_token_e_rota_desconhecida(membros):
    assert call(membros, None, "GET /cadastro/membros")[0] == 401
    assert call(membros, "dono", "PUT /cadastro/membros")[0] == 404
