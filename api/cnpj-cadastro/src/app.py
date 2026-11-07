"""
Enriquece o cadastro de um usuário com os dados do CNPJ (OpenCNPJ -> DynamoDB).

Gatilho: evento no EventBridge publicado pelo seu backend no cadastro:

    {
      "Source": "app.usuarios",
      "DetailType": "UsuarioCadastrado",
      "Detail": "{\"user_id\": \"<sub>\", \"cnpj\": \"00000000000191\"}"
    }

A Lambda consulta https://api.opencnpj.org/{cnpj}?datasets=receita e grava
o resultado no item da organização (user_id = "CNPJ#<cnpj>", ver dados.py).

O POST /cadastro (cadastro.py) já criou a organização. Esta Lambda só grava se o
usuário do evento ainda é o dono desse CNPJ: um evento atrasado de um CNPJ trocado,
ou um evento sem organização, é ignorado.
"""

from __future__ import annotations

import json
import logging
import os
import re
import urllib.error
import urllib.request
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

from dados import org_key

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ.get("TABLE_NAME", "usuarios-cnpj")
API_URL = os.environ.get("OPENCNPJ_API_URL", "https://api.opencnpj.org")

_table = boto3.resource("dynamodb").Table(TABLE_NAME)


class RetryableError(Exception):
    """Erro temporário (429/5xx/rede): a Lambda falha e o EventBridge/Lambda tenta de novo."""


def normalize_cnpj(value: str) -> str:
    """Remove máscara. Aceita o CNPJ alfanumérico novo (12 caracteres + 2 dígitos)."""
    cnpj = re.sub(r"[^0-9A-Za-z]", "", value or "").upper()
    if not re.fullmatch(r"[0-9A-Z]{12}[0-9]{2}", cnpj):
        raise ValueError(f"CNPJ inválido: {value!r}")
    return cnpj


def fetch_cnpj(cnpj: str) -> dict | None:
    """Retorna os dados do CNPJ, ou None se não existir na base."""
    req = urllib.request.Request(
        f"{API_URL}/{cnpj}?datasets=receita",
        headers={"User-Agent": "cadastro-usuarios", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read(), parse_float=Decimal)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 429 or exc.code >= 500:
            raise RetryableError(f"OpenCNPJ HTTP {exc.code}") from exc
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RetryableError(str(exc)) from exc


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

    empresa = fetch_cnpj(cnpj)
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
