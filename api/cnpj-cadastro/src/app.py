"""
Enriquece o cadastro de um usuário com os dados do CNPJ (OpenCNPJ -> DynamoDB).

Gatilho: evento no EventBridge publicado pelo seu backend no cadastro:

    {
      "Source": "app.usuarios",
      "DetailType": "UsuarioCadastrado",
      "Detail": "{\"user_id\": \"<sub>\", \"cnpj\": \"00000000000191\"}"
    }

A Lambda busca os dados do CNPJ (fontes_cnpj.py: OpenCNPJ ou, na stack de demo,
a fixture da empresa de teste) e grava o resultado no item da organização
(user_id = "CNPJ#<cnpj>", ver dados.py).

O POST /cadastro (cadastro.py) já criou a organização. Esta Lambda só grava se o
usuário do evento ainda é o dono desse CNPJ: um evento atrasado de um CNPJ trocado,
ou um evento sem organização, é ignorado.
"""

from __future__ import annotations

import logging
import os
import re
from datetime import datetime, timezone

import boto3
from botocore.exceptions import ClientError

import fontes_cnpj
from dados import org_key
from fontes_cnpj import RetryableError  # noqa: F401  (a Lambda falha e tenta de novo)

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ.get("TABLE_NAME", "usuarios-cnpj")

_table = boto3.resource("dynamodb").Table(TABLE_NAME)


def normalize_cnpj(value: str) -> str:
    """Remove máscara. Aceita o CNPJ alfanumérico novo (12 caracteres + 2 dígitos)."""
    cnpj = re.sub(r"[^0-9A-Za-z]", "", value or "").upper()
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", cnpj):
        raise ValueError(f"CNPJ inválido: {value!r}")
    return cnpj


def _save(cnpj: str, dono: str, attrs: dict, remove: tuple[str, ...] = ()) -> bool:
    """Grava só os campos do CNPJ na organização, se `dono` ainda for o dono. Usa
    update_item (e não put_item) para não apagar o formulário, os membros e os convites.
    Devolve False se a organização não existe mais ou mudou de dono (evento ignorado)."""
    names = {**{f"#{k}": k for k in (*attrs, *remove)}, "#dono": "dono"}  # "status" é palavra reservada
    expr = "SET " + ", ".join(f"#{k} = :{k}" for k in attrs)
    if remove:
        expr += " REMOVE " + ", ".join(f"#{k}" for k in remove)
    try:
        _table.update_item(
            Key={"user_id": org_key(cnpj)},
            UpdateExpression=expr,
            ConditionExpression="#dono = :dono",
            ExpressionAttributeNames=names,
            ExpressionAttributeValues={**{f":{k}": v for k, v in attrs.items()}, ":dono": dono},
        )
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            return False
        raise
    return True


def handler(event: dict, context=None) -> dict:
    detail = event.get("detail", event)  # aceita evento do EventBridge ou payload direto
    user_id = str(detail["user_id"])
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    try:
        cnpj = normalize_cnpj(detail["cnpj"])
    except ValueError:
        log.warning("user %s: evento com CNPJ inválido %r ignorado", user_id, detail.get("cnpj"))
        return {"user_id": user_id, "status": "ignorado"}

    empresa = fontes_cnpj.buscar(cnpj)
    if empresa is None:
        status = "nao_encontrado"
    else:
        status = "ativa" if str(empresa.get("situacao_cadastral", "")).lower() == "ativa" else "inativa"

    attrs = {"status": status, "consultado_em": now}
    if empresa is not None:
        attrs["empresa"] = empresa
    if not _save(cnpj, user_id, attrs, remove=() if empresa is not None else ("empresa",)):
        log.warning("user %s não é dono do CNPJ %s, resultado ignorado", user_id, cnpj)
        return {"user_id": user_id, "cnpj": cnpj, "status": "ignorado"}
    log.info("user %s: CNPJ %s -> %s", user_id, cnpj, status)
    return {"user_id": user_id, "cnpj": cnpj, "status": status}
