"""
GET   /cadastro/me   -> dados para preencher o formulário
PATCH /cadastro/me   -> salva os campos que o usuário preencheu

Header: Authorization: Bearer <access token do Cognito>
O usuário só enxerga e altera o próprio cadastro: o user_id vem do token ("sub").

GET devolve:
  user_id, cnpj, status, consultado_em
  empresa  dados da Receita (sem a lista de sócios, por causa da LGPD)
  dados    campos preenchidos pelo usuário (vazio até o primeiro PATCH)

PATCH body: {"dados": {"telefone": "1199999-0000", "site": null}}
  - só mexe em `dados`; cnpj/status/empresa nunca são alterados por aqui
  - merge campo a campo: o que não foi enviado fica como está
  - valor null apaga o campo
  - os campos são livres (nome em snake_case); quando o formulário estiver
    definido, valide-os em CAMPOS_PERMITIDOS abaixo
"""

import json
import os
import re
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from auth import user_id_from_event

TABLE_NAME = os.environ.get("TABLE_NAME", "usuarios-cnpj")

# None = aceita qualquer campo. Depois de definir o formulário, troque por um
# conjunto, ex.: {"telefone", "email_contato", "site"}.
CAMPOS_PERMITIDOS: set[str] | None = None

MAX_CAMPOS = 50
NOME_CAMPO = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
# Dados dos sócios (pessoas físicas): não são devolvidos ao front.
CAMPOS_SENSIVEIS = {"QSA"}

_table = boto3.resource("dynamodb").Table(TABLE_NAME)


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"{type(o)} não serializável")


def _resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default, ensure_ascii=False),
    }


def get_usuario(user_id: str) -> dict:
    item = _table.get_item(Key={"user_id": user_id}).get("Item")
    if not item:
        return _resp(404, {"erro": "cadastro não encontrado (ainda pode estar sendo processado)"})
    empresa = {k: v for k, v in (item.get("empresa") or {}).items() if k not in CAMPOS_SENSIVEIS}
    return _resp(200, {
        "user_id": item["user_id"],
        "cnpj": item.get("cnpj"),
        "status": item.get("status"),
        "consultado_em": item.get("consultado_em"),
        "empresa": empresa,
        "dados": item.get("dados", {}),
    })


def patch_usuario(user_id: str, raw_body: str | None) -> dict:
    try:
        body = json.loads(raw_body or "{}", parse_float=Decimal)
    except ValueError:
        return _resp(400, {"erro": "JSON inválido"})
    dados = body.get("dados") if isinstance(body, dict) else None
    if not isinstance(dados, dict) or not dados:
        return _resp(400, {"erro": 'envie {"dados": {"campo": "valor"}}'})
    if len(dados) > MAX_CAMPOS:
        return _resp(400, {"erro": f"no máximo {MAX_CAMPOS} campos por vez"})
    invalidos = [k for k in dados if not NOME_CAMPO.match(k)]
    if invalidos:
        return _resp(400, {"erro": "nome de campo inválido (use snake_case minúsculo)", "campos": invalidos})
    if CAMPOS_PERMITIDOS is not None:
        fora = [k for k in dados if k not in CAMPOS_PERMITIDOS]
        if fora:
            return _resp(400, {"erro": "campo não permitido", "campos": fora})

    # 1) garante que o mapa `dados` existe (e que o cadastro existe)
    try:
        _table.update_item(
            Key={"user_id": user_id},
            UpdateExpression="SET dados = if_not_exists(dados, :vazio)",
            ConditionExpression="attribute_exists(user_id)",
            ExpressionAttributeValues={":vazio": {}},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return _resp(404, {"erro": "cadastro não encontrado"})
        raise

    # 2) merge campo a campo (null remove o campo)
    names, values, sets, removes = {}, {}, [], []
    for i, (campo, valor) in enumerate(dados.items()):
        names[f"#c{i}"] = campo
        if valor is None:
            removes.append(f"dados.#c{i}")
        else:
            values[f":v{i}"] = valor
            sets.append(f"dados.#c{i} = :v{i}")
    expr = ""
    if sets:
        expr += "SET " + ", ".join(sets)
    if removes:
        expr += " REMOVE " + ", ".join(removes)
    kwargs = {"ExpressionAttributeValues": values} if values else {}
    _table.update_item(
        Key={"user_id": user_id},
        UpdateExpression=expr.strip(),
        ExpressionAttributeNames=names,
        **kwargs,
    )
    return get_usuario(user_id)


def handler(event, context=None):
    user_id = user_id_from_event(event)
    if not user_id:
        return _resp(401, {"erro": "não autenticado"})
    method = event.get("requestContext", {}).get("http", {}).get("method", "").upper()
    if method == "GET":
        return get_usuario(user_id)
    if method == "PATCH":
        return patch_usuario(user_id, event.get("body"))
    return _resp(405, {"erro": "método não permitido"})
