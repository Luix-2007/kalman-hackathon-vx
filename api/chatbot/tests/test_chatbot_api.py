"""
Lambda de entrada do chatbot, com o DynamoDB no moto e um cliente do AgentCore simulado:
identidade (token -> CNPJ pela tabela do cadastro), validação, sessão, limite por usuário
e tratamento de falhas do agente.
"""

import importlib
import io
import json
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

import boto3
import pytest
from botocore.exceptions import ClientError, ReadTimeoutError
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

CNPJ = "KALMANTESTE100"
OUTRO = "00000000000191"
SEGREDO = "gold_db.matriz_tarefas AccessDenied arn:aws:iam::1:role/x"


class AgenteFalso:
    """Cliente bedrock-agentcore: devolve `saida` (dict, bytes ou exceção) a cada invocação."""

    def __init__(self):
        self.chamadas, self.saida = [], {"resposta": "A renovação da LO vence em 10/11/2026.", "consultas": 2}

    def invoke_agent_runtime(self, **kw):
        self.chamadas.append(kw)
        if isinstance(self.saida, Exception):
            raise self.saida
        corpo = self.saida if isinstance(self.saida, bytes) else json.dumps(self.saida).encode()
        return {"response": io.BytesIO(corpo), "statusCode": 200}

    def payload(self, i=-1):
        return json.loads(self.chamadas[i]["payload"])


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "cad")
    monkeypatch.setenv("LIMITES_TABLE", "lim")
    monkeypatch.setenv("AGENT_RUNTIME_ARN", "arn:aws:bedrock-agentcore:us-east-1:1:runtime/kalman-x")
    with mock_aws():
        ddb = boto3.client("dynamodb")
        for nome, chave in (("cad", "user_id"), ("lim", "chave")):
            ddb.create_table(TableName=nome, BillingMode="PAY_PER_REQUEST",
                             AttributeDefinitions=[{"AttributeName": chave, "AttributeType": "S"}],
                             KeySchema=[{"AttributeName": chave, "KeyType": "HASH"}])
        cad = boto3.resource("dynamodb").Table("cad")
        cad.put_item(Item={"user_id": "dono", "cnpj": CNPJ, "papel": "dono"})
        cad.put_item(Item={"user_id": "membro", "cnpj": CNPJ, "papel": "membro"})
        cad.put_item(Item={"user_id": "outro-dono", "cnpj": OUTRO, "papel": "dono"})
        cad.put_item(Item={"user_id": "sem-cnpj", "papel": "dono"})
        import chatbot_api
        mod = importlib.reload(chatbot_api)
        mod._agente = AgenteFalso()
        mod.fake = mod._agente
        mod.relogio = [datetime(2026, 11, 7, 12, 30, tzinfo=timezone.utc)]
        monkeypatch.setattr(mod, "agora", lambda: mod.relogio[0])
        yield mod


def evento(sub, corpo=None, rota="POST /chatbot/mensagens"):
    ev = {"routeKey": rota, "requestContext": {"http": {"method": rota.split()[0]}}}
    if sub:
        ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": sub}}}
    if corpo is not None:
        ev["body"] = corpo if isinstance(corpo, str) else json.dumps(corpo)
    return ev


def enviar(api, sub, corpo=None, **kw):
    r = api.handler(evento(sub, {"prompt": "quais tarefas estão em risco?"} if corpo is None else corpo, **kw))
    return r["statusCode"], json.loads(r["body"]), r["headers"]


def contador(chave):
    item = boto3.resource("dynamodb").Table("lim").get_item(Key={"chave": chave}).get("Item")
    return int(item["n"]) if item else 0


# ---------------------------------------------------------------- identidade

def test_sem_token_401_e_nao_chama_o_agente(api):
    assert enviar(api, None)[0] == 401
    assert api.fake.chamadas == []


def test_rota_desconhecida_404(api):
    assert enviar(api, "dono", rota="GET /chatbot/mensagens")[0] == 404


@pytest.mark.parametrize("sub", ["estranho", "sem-cnpj"])
def test_usuario_sem_organizacao_404_sem_chamar_nem_contar(api, sub):
    code, body, _ = enviar(api, sub)
    assert code == 404 and "cadastro não encontrado" in body["erro"]
    assert api.fake.chamadas == [] and contador(f"{sub}#h2026110712") == 0


def test_cnpj_e_usuario_vem_do_token_e_da_tabela_nunca_do_corpo(api):
    code, body, _ = enviar(api, "dono", {"prompt": "oi", "cnpj": OUTRO, "user_id": "outro-dono", "papel": "dono"})
    assert code == 200 and body == {"resposta": "A renovação da LO vence em 10/11/2026.", "blocos": []}
    p = api.fake.payload()
    assert p["cnpj"] == CNPJ and p["user_id"] == "dono" and p["prompt"] == "oi"
    assert set(p) == {"cnpj", "user_id", "prompt", "session_id"}
    chamada = api.fake.chamadas[0]
    assert chamada["agentRuntimeArn"].endswith("runtime/kalman-x")
    assert chamada["contentType"] == "application/json"


def test_membro_tambem_conversa(api):
    assert enviar(api, "membro")[0] == 200
    assert api.fake.payload()["cnpj"] == CNPJ and api.fake.payload()["user_id"] == "membro"


def test_usuarios_de_organizacoes_diferentes_recebem_cnpjs_diferentes(api):
    enviar(api, "dono")
    enviar(api, "outro-dono")
    assert [json.loads(c["payload"])["cnpj"] for c in api.fake.chamadas] == [CNPJ, OUTRO]


# ---------------------------------------------------------------- validação

@pytest.mark.parametrize("corpo, trecho", [
    ("{nao json", "JSON"),
    ("[1]", "prompt"),
    ({}, "prompt"),
    ({"prompt": ""}, "prompt"),
    ({"prompt": "   "}, "prompt"),
    ({"prompt": 5}, "prompt"),
    ({"prompt": "x" * 2001}, "prompt"),
    ({"prompt": "oi", "session_id": "a b"}, "session_id"),
    ({"prompt": "oi", "session_id": "x" * 101}, "session_id"),
    ({"prompt": "oi", "session_id": 7}, "session_id"),
])
def test_corpo_invalido_400_sem_chamar_nem_contar(api, corpo, trecho):
    code, body, _ = enviar(api, "dono", corpo)
    assert code == 400 and trecho in body["erro"]
    assert api.fake.chamadas == [] and contador("dono#h2026110712") == 0


# ---------------------------------------------------------------- sessão

def test_sessao_tem_64_caracteres_e_depende_do_usuario(api):
    enviar(api, "dono", {"prompt": "oi", "session_id": "conversa-1"})
    enviar(api, "dono", {"prompt": "oi", "session_id": "conversa-1"})
    enviar(api, "membro", {"prompt": "oi", "session_id": "conversa-1"})
    enviar(api, "dono", {"prompt": "oi", "session_id": "conversa-2"})
    runtime = [c["runtimeSessionId"] for c in api.fake.chamadas]
    assert all(re.fullmatch(r"[0-9a-f]{64}", s) for s in runtime)
    assert runtime[0] == runtime[1]                    # mesma conversa
    assert len({runtime[0], runtime[2], runtime[3]}) == 3   # outro usuário ou outra conversa
    assert [json.loads(c["payload"])["session_id"] for c in api.fake.chamadas] == runtime


def test_quem_muda_de_organizacao_comeca_outra_conversa(api):
    enviar(api, "dono", {"prompt": "oi", "session_id": "conversa-1"})
    api._cadastro.put_item(Item={"user_id": "dono", "cnpj": OUTRO, "papel": "membro"})   # aceitou convite de outra
    enviar(api, "dono", {"prompt": "oi", "session_id": "conversa-1"})
    antes, depois = (c["runtimeSessionId"] for c in api.fake.chamadas)
    assert antes != depois
    assert json.loads(api.fake.chamadas[1]["payload"])["cnpj"] == OUTRO


def test_sem_session_id_usa_uma_conversa_por_usuario(api):
    enviar(api, "dono")
    enviar(api, "dono")
    assert api.fake.chamadas[0]["runtimeSessionId"] == api.fake.chamadas[1]["runtimeSessionId"]


# ---------------------------------------------------------------- limite por usuário

def test_limite_por_hora_429_com_retry_after(api, monkeypatch):
    monkeypatch.setattr(api, "LIMITE_HORA", 2)
    assert [enviar(api, "dono")[0] for _ in range(2)] == [200, 200]
    code, body, headers = enviar(api, "dono")
    assert code == 429 and "2 mensagens por hora" in body["erro"]
    assert headers["Retry-After"] == str(30 * 60)       # 12:30 -> 13:00
    assert len(api.fake.chamadas) == 2                  # o agente não foi chamado
    assert enviar(api, "membro")[0] == 200              # outro usuário não é afetado
    api.relogio[0] = datetime(2026, 11, 7, 13, 0, 1, tzinfo=timezone.utc)
    assert enviar(api, "dono")[0] == 200                # nova hora, nova janela


def test_limite_por_dia_nao_consome_a_hora(api, monkeypatch):
    monkeypatch.setattr(api, "LIMITE_DIA", 3)
    for _ in range(3):
        assert enviar(api, "dono")[0] == 200
    code, body, headers = enviar(api, "dono")
    assert code == 429 and "3 mensagens por dia" in body["erro"] and int(headers["Retry-After"]) > 3600
    assert contador("dono#h2026110712") == 3 and contador("dono#d20261107") == 3   # transação: nada a mais
    api.relogio[0] = datetime(2026, 11, 8, 0, 0, 5, tzinfo=timezone.utc)
    assert enviar(api, "dono")[0] == 200


def test_o_limite_conta_a_tentativa_mesmo_se_o_agente_falhar(api):
    api.fake.saida = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "InvokeAgentRuntime")
    assert enviar(api, "dono")[0] == 502
    assert contador("dono#h2026110712") == 1


def test_contador_tem_expiracao(api):
    enviar(api, "dono")
    item = boto3.resource("dynamodb").Table("lim").get_item(Key={"chave": "dono#h2026110712"})["Item"]
    assert int(item["expira_em"]) > int(datetime(2026, 11, 7, 13, tzinfo=timezone.utc).timestamp())


# ---------------------------------------------------------------- falhas do agente

@pytest.mark.parametrize("saida", [
    {"erro": f"consulta falhou: {SEGREDO}"},
    {"resposta": 5},
    {"outra": "coisa"},
    [1, 2],
    b"<html>502</html>",
])
def test_resposta_estranha_do_agente_vira_502_generico(api, saida, caplog):
    api.fake.saida = saida
    code, body, _ = enviar(api, "dono")
    assert code == 502 and body == {"erro": api.ERRO_AGENTE}
    assert "gold_db" not in json.dumps(body)


def test_o_texto_de_erro_do_agente_fica_no_log(api, caplog):
    api.fake.saida = {"erro": f"falhou: {SEGREDO}"}
    enviar(api, "dono")
    assert SEGREDO in caplog.text


def test_excecao_do_runtime_vira_502_generico(api, caplog):
    api.fake.saida = ClientError({"Error": {"Code": "AccessDeniedException", "Message": SEGREDO}}, "InvokeAgentRuntime")
    code, body, _ = enviar(api, "dono")
    assert code == 502 and body == {"erro": api.ERRO_AGENTE}
    assert "AccessDeniedException" in caplog.text


def test_demora_do_agente_vira_504(api):
    api.fake.saida = ReadTimeoutError(endpoint_url="https://bedrock-agentcore")
    code, body, _ = enviar(api, "dono")
    assert code == 504 and "demorou" in body["erro"]


# ---------------------------------------------------------------- log

def test_log_estruturado_sem_pergunta_nem_resposta_nem_sub(api, caplog):
    import logging
    caplog.set_level(logging.INFO)
    sub = "sub-9f2c1d7e-secreto"
    boto3.resource("dynamodb").Table("cad").put_item(Item={"user_id": sub, "cnpj": CNPJ, "papel": "dono"})
    enviar(api, sub, {"prompt": "segredo-da-pergunta-123"})
    linhas = [json.loads(r.message) for r in caplog.records if r.message.startswith("{")]
    assert len(linhas) == 1
    reg = linhas[0]
    assert reg["evento"] == "mensagem" and reg["resultado"] == "ok" and reg["consultas"] == 2
    assert reg["cnpj"] == CNPJ and reg["papel"] == "dono" and reg["ms"] >= 0
    assert reg["usuario"] == api.anonimo(sub) and len(reg["usuario"]) == 8
    for proibido in (sub, "segredo-da-pergunta-123", "renovação da LO"):
        assert proibido not in caplog.text, proibido


# ---------------------------------------------------------------- blocos de dados

BLOCO = {"tipo": "tarefas", "parametros": {"em_risco": True},
         "itens": [{"descricao": "Renovar a LO", "vencimento": "2026-11-10", "em_risco": True, "obrigacao_versao": 1}]}


def test_blocos_do_agente_chegam_ao_front_sem_o_resto(api):
    api.fake.saida = {"resposta": "Uma tarefa em risco.", "blocos": [BLOCO], "consultas": 1}
    code, body, _ = enviar(api, "dono")
    assert code == 200 and body == {"resposta": "Uma tarefa em risco.", "blocos": [BLOCO]}    # sem "consultas"


def test_blocos_com_forma_invalida_sao_descartados(api, caplog):
    ruim = {"tipo": "inventado", "itens": [{"a": 1}]}
    aninhado = {"tipo": "tarefas", "itens": [{"descricao": {"objeto": "aninhado"}}]}
    api.fake.saida = {"resposta": "ok", "blocos": [BLOCO, ruim, aninhado, "texto"], "consultas": 1}
    code, body, _ = enviar(api, "dono")
    assert code == 200 and body["blocos"] == [BLOCO]
    assert "descartados" in caplog.text


@pytest.mark.parametrize("blocos", [None, "x", {"tipo": "tarefas"}, 5])
def test_blocos_ausentes_ou_de_tipo_errado_viram_lista_vazia(api, blocos):
    api.fake.saida = {"resposta": "ok", "blocos": blocos}
    code, body, _ = enviar(api, "dono")
    assert code == 200 and body == {"resposta": "ok", "blocos": []}


def test_agente_antigo_sem_blocos_continua_funcionando(api):
    api.fake.saida = {"resposta": "ok", "consultas": 0}
    assert enviar(api, "dono")[1] == {"resposta": "ok", "blocos": []}


def test_log_registra_os_tipos_de_bloco_nao_o_conteudo(api, caplog):
    import logging
    caplog.set_level(logging.INFO)
    api.fake.saida = {"resposta": "ok", "blocos": [BLOCO], "consultas": 1}
    enviar(api, "dono")
    reg = next(json.loads(r.message) for r in caplog.records if r.message.startswith("{"))
    assert reg["blocos"] == ["tarefas"] and "Renovar a LO" not in caplog.text


def test_copia_dos_blocos_e_igual_a_do_agente():
    import filecmp
    agente = Path(__file__).parents[3] / "ia" / "chatbot" / "blocos.py"
    assert filecmp.cmp(Path(__file__).parents[1] / "src" / "blocos.py", agente, shallow=False), \
        "rode make ia-chatbot-sync-blocos"
