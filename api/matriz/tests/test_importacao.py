"""POST/GET /importacoes: a planilha vai para a landing da matriz e o job é disparado (S3 e Step Functions no moto)."""

import base64
import importlib
import json
import sys
from pathlib import Path

import boto3
import pytest
from moto import mock_aws

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

CNPJ = "KALMANTESTE100"
BUCKET = "lake-teste"
CSV = (
    "obrigacao_id,titulo,orgao_sigla,recorrencia,periodicidade,prazo_regra,prazo_json,criticidade\n"
    'OBR-001,Enviar DEC e FEC,ANEEL,periodica,mensal,Até o dia 25,"[{""unidade"": ""dia_do_mes"", '
    '""referencia"": ""mes_seguinte"", ""valor"": ""25""}]",alta\n'
)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "t")
    monkeypatch.setenv("LAKE_BUCKET", BUCKET)
    with mock_aws():
        ddb = boto3.client("dynamodb")
        ddb.create_table(TableName="t", BillingMode="PAY_PER_REQUEST",
                         AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
                         KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}])
        t = boto3.resource("dynamodb").Table("t")
        t.put_item(Item={"user_id": "dono", "cnpj": CNPJ, "papel": "dono"})
        t.put_item(Item={"user_id": "membro", "cnpj": CNPJ, "papel": "membro"})
        boto3.client("s3").create_bucket(Bucket=BUCKET)
        iam = boto3.client("iam")
        papel = iam.create_role(RoleName="sfn", AssumeRolePolicyDocument="{}")["Role"]["Arn"]
        arn = boto3.client("stepfunctions").create_state_machine(
            name="matriz", definition=json.dumps({"StartAt": "A", "States": {"A": {"Type": "Pass", "End": True}}}),
            roleArn=papel)["stateMachineArn"]
        monkeypatch.setenv("MATRIZ_STATE_MACHINE_ARN", arn)
        import importacao
        import matriz_api
        importlib.reload(importacao)
        mod = importlib.reload(matriz_api)
        mod.arn = arn
        yield mod


def chamar(api, sub, rota, corpo=None):
    ev = {"routeKey": rota, "requestContext": {"http": {"method": rota.split()[0]},
                                               "authorizer": {"jwt": {"claims": {"sub": sub}}}}}
    if corpo is not None:
        ev["body"] = json.dumps(corpo)
    r = api.handler(ev)
    return r["statusCode"], json.loads(r["body"])


def test_csv_vai_para_a_landing_e_dispara_o_job(api):
    status, corpo = chamar(api, "dono", "POST /importacoes", {"nome": "Matriz da Aurora.csv", "conteudo": CSV})
    assert status == 201
    assert corpo["arquivo"].endswith("-Matriz-da-Aurora.csv")
    assert corpo["processamento"]["estado"] == "RUNNING"
    objetos = boto3.client("s3").list_objects_v2(Bucket=BUCKET)["Contents"]
    assert [o["Key"] for o in objetos] == [f"landing/matriz/importada/{CNPJ}/{corpo['arquivo']}"]
    assert boto3.client("stepfunctions").list_executions(stateMachineArn=api.arn)["executions"]

    status, lista = chamar(api, "membro", "GET /importacoes")
    assert status == 200
    assert lista["importacoes"][0]["arquivo"] == corpo["arquivo"]
    assert lista["processamento"]["estado"] in ("RUNNING", "SUCCEEDED")


def test_xlsx_em_base64(api):
    corpo = {"nome": "matriz.xlsx", "conteudo_base64": base64.b64encode(b"PK\x03\x04 planilha").decode()}
    assert chamar(api, "dono", "POST /importacoes", corpo)[0] == 201


def test_membro_nao_envia(api):
    assert chamar(api, "membro", "POST /importacoes", {"nome": "m.csv", "conteudo": CSV})[0] == 403


@pytest.mark.parametrize("corpo, status", [
    ({"nome": "matriz.pdf", "conteudo": CSV}, 400),
    ({"nome": "matriz.csv"}, 400),
    ({"nome": "matriz.csv", "conteudo": "a,b\n1,2\n"}, 400),           # não tem obrigacao_id nem titulo
    ({"nome": "matriz.xlsx", "conteudo_base64": "isto não é base64!"}, 400),
    ({"nome": "matriz.csv", "conteudo": "obrigacao_id,titulo\n" + "x" * (2 * 1024 * 1024)}, 413),
])
def test_arquivo_invalido(api, corpo, status):
    assert chamar(api, "dono", "POST /importacoes", corpo)[0] == status
    assert "Contents" not in boto3.client("s3").list_objects_v2(Bucket=BUCKET)
