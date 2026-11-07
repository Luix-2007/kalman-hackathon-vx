"""
Modelo de dados: tabela única, chave `user_id` (string).

    user_id = <sub>              cnpj, papel ("dono" | "membro")
        A organização do usuário. Cada usuário participa de no máximo uma.

    user_id = CNPJ#<cnpj>        a organização (empresa), um item por CNPJ
        dono, dono_email               quem cadastrou o CNPJ (único por CNPJ)
        status, consultado_em, empresa dados do OpenCNPJ (app.py)
        dados                          formulário (só o dono edita)
        membros   {sub: {email, desde}}           quem foi convidado e aceitou (só leem)
        convites  {email: {criado_em, expira_em}} convites pendentes

    user_id = CONVITE#<email>    cnpj, convidado_por, criado_em, expira_em (TTL)
        Convite pendente para um e-mail. Um por e-mail, porque cada usuário
        participa de uma única organização.

O DynamoDB só garante unicidade pela chave. Por isso o vínculo usuário <-> CNPJ
usa dois itens gravados juntos numa transação (transact_write_items): ou grava
tudo, ou nada.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from botocore.exceptions import ClientError

TABLE_NAME = os.environ.get("TABLE_NAME", "usuarios-cnpj")
CONVITE_VALIDADE_S = 7 * 24 * 3600

_table = boto3.resource("dynamodb").Table(TABLE_NAME)


def org_key(cnpj: str) -> str:
    return f"CNPJ#{cnpj}"


def convite_key(email: str) -> str:
    return f"CONVITE#{email}"


def agora_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def agora_epoch() -> int:
    return int(time.time())


def get(chave: str) -> dict | None:
    return _table.get_item(Key={"user_id": chave}, ConsistentRead=True).get("Item")


def convites_ativos(org: dict) -> dict:
    agora = agora_epoch()
    return {e: c for e, c in (org.get("convites") or {}).items() if int(c.get("expira_em", 0)) > agora}


class TransacaoCancelada(Exception):
    """Alguma condição da transação falhou. `falhou(i)` diz se foi a operação i."""

    def __init__(self, motivos: list[str]):
        super().__init__(motivos)
        self.motivos = motivos

    def falhou(self, i: int) -> bool:
        return i < len(self.motivos) and self.motivos[i] == "ConditionalCheckFailed"


def transacao(ops: list[dict]) -> None:
    """Grava várias operações de uma vez (tudo ou nada). Os valores são tipos Python normais."""
    for op in ops:
        next(iter(op.values())).setdefault("TableName", TABLE_NAME)
    try:
        _table.meta.client.transact_write_items(TransactItems=ops)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "TransactionCanceledException":
            raise
        motivos = [m.get("Code", "None") for m in exc.response.get("CancellationReasons") or []]
        raise TransacaoCancelada(motivos) from exc


def condicao_falhou(exc: ClientError) -> bool:
    return exc.response["Error"]["Code"] == "ConditionalCheckFailedException"


class ErroApi(Exception):
    """Erro com status HTTP e mensagem para o front."""

    def __init__(self, status: int, erro: str):
        super().__init__(erro)
        self.status, self.erro = status, erro


def _default(o):
    if isinstance(o, Decimal):
        return int(o) if o == o.to_integral_value() else float(o)
    raise TypeError(f"{type(o)} não serializável")


def resp(status: int, body: dict) -> dict:
    return {
        "statusCode": status,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(body, default=_default, ensure_ascii=False),
    }
