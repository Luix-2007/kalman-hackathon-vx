import importlib

import boto3
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
    code, body = call(usuario, "PATCH", "u1", {"dados": {"setor": "energia", "nome_fantasia": "BB", "ufs_atuacao": ["DF"]}})
    assert code == 200 and body["dados"] == {"setor": "energia", "nome_fantasia": "BB", "ufs_atuacao": ["DF"]}
    code, body = call(usuario, "PATCH", "u1", {"dados": {"setor": "financeiro", "nome_fantasia": None}})
    assert body["dados"] == {"setor": "financeiro", "ufs_atuacao": ["DF"]}
    assert body["status"] == "ativa" and body["cnpj"] == "00000000000191"  # intocados


def test_patch_so_remove_campo(usuario):
    call(usuario, "PATCH", "u1", {"dados": {"setor": "energia"}})
    code, body = call(usuario, "PATCH", "u1", {"dados": {"setor": None}})
    assert code == 200 and body["dados"] == {}


def test_patch_inexistente_404_e_nao_cria(usuario, tabela):
    assert call(usuario, "PATCH", "fantasma", {"dados": {"setor": "energia"}})[0] == 404
    assert item(tabela, "fantasma") is None


def test_membro_ve_os_mesmos_dados_mas_nao_edita(usuario, tabela):
    call(usuario, "PATCH", "u1", {"dados": {"setor": "energia"}})
    code, body = call(usuario, "GET", "m1")
    assert code == 200 and body["papel"] == "membro" and body["dados"] == {"setor": "energia"}
    assert body["empresa"]["razao_social"] == "BANCO DO BRASIL SA" and "QSA" not in body["empresa"]
    code, body = call(usuario, "PATCH", "m1", {"dados": {"setor": "outro"}})
    assert code == 403
    assert item(tabela, ORG)["dados"] == {"setor": "energia"}


@pytest.mark.parametrize("body", [{}, {"dados": {}}, {"dados": "x"}, {"dados": {"Status": 1}},
                                  {"dados": {"status; drop": 1}}, {"dados": {f"c{i}": 1 for i in range(51)}},
                                  {"dados": {"telefone": "1199"}}])  # campo fora do perfil
def test_patch_invalido_400(usuario, body):
    assert call(usuario, "PATCH", "u1", body)[0] == 400


def test_patch_json_quebrado_400(usuario):
    r = usuario.handler({**req("PATCH", "u1"), "body": "{nao-json"})
    assert r["statusCode"] == 400


def test_campos_permitidos(usuario):
    code, body = call(usuario, "PATCH", "u1", {"dados": {"site": "a.com", "setor": "energia"}})
    assert code == 400 and body["campos"] == ["site"]
    assert item(usuario_tabela(), ORG).get("dados") is None  # nada foi gravado


def test_metodo_nao_permitido(usuario):
    assert call(usuario, "DELETE", "u1")[0] == 405


def test_sem_token_401(usuario):
    assert call(usuario, "GET", None)[0] == 401
    assert call(usuario, "PATCH", None, {"dados": {"setor": "x"}})[0] == 401


def test_usuario_so_acessa_o_proprio_cadastro(usuario):
    # o "intruso" está logado, mas não tem cadastro: não vê nem altera o de u1
    r = usuario.handler({**req("GET", "intruso"), "pathParameters": {"user_id": "u1"}})
    assert r["statusCode"] == 404
    r = usuario.handler({**req("PATCH", "intruso", {"dados": {"setor": "x"}}), "pathParameters": {"user_id": "u1"}})
    assert r["statusCode"] == 404
    assert call(usuario, "GET", "u1")[1]["dados"] == {}


def usuario_tabela():
    return boto3.resource("dynamodb").Table("t")


# ---------------------------------------------------------------- perfil regulatório

PERFIL = {
    "nome_fantasia": "Aurora Energia",
    "email_alertas": "compliance@aurora.example",
    "faixa_funcionarios": "501-1000",
    "setor": "energia_eletrica",
    "ufs_atuacao": ["SP", "MG"],
    "municipios_atuacao": ["3509502"],
    "orgaos_fiscalizadores": ["ANEEL", "CETESB"],
    "unidades": [{"id": "UN-01", "nome": "SE Pedra Branca", "tipo": "subestacao", "tags": ["alta_tensao"]}],
    "outorgas": [{"id": "OUT-01", "tipo": "licenca_operacao", "numero": "LO 123", "orgao": "CETESB",
                  "objeto": "Operação da SE", "unidade_id": "UN-01", "validade": "2027-03-10",
                  "antecedencia_renovacao_dias": 120}],
    "areas": [{"id": "GCTR", "nome": "Contabilidade Regulatória", "responsavel": "Ana",
               "email": "ana@aurora.example"}],
    "temas_interesse": ["contabilidade_regulatoria"],
    "temas_fora_escopo": ["telecom"],
    "certificacoes": ["ISO 14001"],
}


def test_patch_perfil_completo(usuario):
    code, body = call(usuario, "PATCH", "u1", {"dados": PERFIL})
    assert code == 200
    assert body["dados"]["outorgas"][0]["antecedencia_renovacao_dias"] == 120
    assert body["dados"] == PERFIL
    code, body = call(usuario, "GET", "m1")  # membro lê o perfil
    assert code == 200 and body["dados"]["unidades"][0]["nome"] == "SE Pedra Branca"


@pytest.mark.parametrize("dados, campo", [
    ({"email_alertas": "sem-arroba"}, "email_alertas"),
    ({"ufs_atuacao": ["XX"]}, "ufs_atuacao"),
    ({"ufs_atuacao": "SP"}, "ufs_atuacao"),
    ({"ufs_atuacao": ["SP", "SP"]}, "ufs_atuacao"),
    ({"municipios_atuacao": ["35"]}, "municipios_atuacao"),
    ({"setor": 3}, "setor"),
    ({"setor": "  "}, "setor"),
    ({"unidades": [{"nome": "sem id"}]}, "unidades"),
    ({"unidades": [{"id": "A", "nome": "x"}, {"id": "A", "nome": "y"}]}, "unidades"),
    ({"unidades": [{"id": "A", "nome": "x", "cor": "azul"}]}, "unidades"),
    ({"outorgas": [{"id": "O", "tipo": "LO", "orgao": "X", "validade": "10/11/2026"}]}, "outorgas"),
    ({"outorgas": [{"id": "O", "tipo": "LO", "orgao": "X", "antecedencia_renovacao_dias": "120"}]}, "outorgas"),
    ({"outorgas": [{"id": "O", "tipo": "LO", "orgao": "X", "antecedencia_renovacao_dias": 1.5}]}, "outorgas"),
    ({"areas": [{"id": "A", "nome": "x", "email": "ruim"}]}, "areas"),
    ({"areas": "GCTR"}, "areas"),
])
def test_patch_perfil_tipo_errado_400(usuario, dados, campo):
    code, body = call(usuario, "PATCH", "u1", {"dados": dados})
    assert code == 400 and campo in body["campos"]
    assert item(usuario_tabela(), ORG).get("dados") is None


def test_patch_perfil_null_apaga_lista(usuario):
    call(usuario, "PATCH", "u1", {"dados": {"unidades": PERFIL["unidades"]}})
    code, body = call(usuario, "PATCH", "u1", {"dados": {"unidades": None}})
    assert code == 200 and "unidades" not in body["dados"]


def test_perfil_da_aurora_e_valido():
    import json
    from pathlib import Path

    import perfil
    dados = json.loads((Path(__file__).parent / "aurora_dados.json").read_text(encoding="utf-8"))
    assert set(dados) <= set(perfil.CAMPOS)
    assert perfil.validar(dados) == {}
