"""
Membros da organização e convites (modelo em dados.py).

O dono do CNPJ convida outras pessoas pelo e-mail. O convidado cria a conta
normalmente (com esse e-mail), vê o convite pendente ao entrar e aceita.
Membros só leem os dados da organização; só o dono edita, convida e remove.
Cada usuário participa de uma única organização.

Dono e membros:
  GET    /cadastro/membros            dono, membros e (só para o dono) convites pendentes
  DELETE /cadastro/membros/{id}       id = sub do membro: o dono remove, ou o próprio membro sai
                                      id = e-mail: o dono cancela o convite
Só o dono:
  POST   /cadastro/membros            {"email": "pessoa@empresa.com"} -> convite válido por 7 dias
Convidado (ainda sem organização):
  GET    /cadastro/convite            convite pendente para o e-mail do usuário
  POST   /cadastro/convite            aceita
  DELETE /cadastro/convite            recusa
"""

from __future__ import annotations

import json
import re
from urllib.parse import unquote

import auth
import dados as db
from dados import ErroApi, TransacaoCancelada, convite_key, org_key, resp

MAX_MEMBROS = 50
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ---------- quem está chamando ----------

def _minha_org(user_id: str) -> tuple[dict, dict]:
    usuario = db.get(user_id) or {}
    org = db.get(org_key(usuario["cnpj"])) if usuario.get("cnpj") else None
    if not org:
        raise ErroApi(404, "você ainda não participa de uma organização")
    return usuario, org


def _so_dono(usuario: dict) -> None:
    if usuario.get("papel") != "dono":
        raise ErroApi(403, "só o dono da organização pode fazer isso")


def _meu_email(user_id: str) -> str:
    email = auth.email_do_usuario(user_id)
    if not email:
        raise ErroApi(404, "nenhum convite pendente")
    return email


# ---------- membros ----------

def listar(user_id: str) -> dict:
    usuario, org = _minha_org(user_id)
    body = {
        "cnpj": org["cnpj"],
        "dono": {"user_id": org["dono"], "email": org.get("dono_email")},
        "membros": sorted(
            ({"user_id": sub, **m} for sub, m in (org.get("membros") or {}).items()),
            key=lambda m: m.get("desde", ""),
        ),
    }
    if usuario.get("papel") == "dono":
        body["convites"] = sorted(
            ({"email": e, **c} for e, c in db.convites_ativos(org).items()), key=lambda c: c["criado_em"])
    return resp(200, body)


def convidar(user_id: str, raw_body: str | None) -> dict:
    usuario, org = _minha_org(user_id)
    _so_dono(usuario)
    try:
        body = json.loads(raw_body or "{}")
    except ValueError:
        raise ErroApi(400, "JSON inválido")
    email = str((body if isinstance(body, dict) else {}).get("email") or "").strip().lower()
    if not EMAIL.match(email) or len(email) > 254:
        raise ErroApi(400, 'envie {"email": "pessoa@empresa.com"}')

    membros = org.get("membros") or {}
    if email == org.get("dono_email") or any(m.get("email") == email for m in membros.values()):
        raise ErroApi(409, "essa pessoa já faz parte da organização")
    ativos = db.convites_ativos(org)
    if len(membros) + len(ativos) >= MAX_MEMBROS and email not in ativos:
        raise ErroApi(409, f"limite de {MAX_MEMBROS} membros e convites atingido")

    agora, expira = db.agora_iso(), db.agora_epoch() + db.CONVITE_VALIDADE_S
    try:
        db.transacao([
            # um convite pendente por e-mail; pode renovar o da própria organização
            {"Put": {
                "Item": {"user_id": convite_key(email), "cnpj": org["cnpj"], "convidado_por": user_id,
                         "criado_em": agora, "expira_em": expira},
                "ConditionExpression": "attribute_not_exists(user_id) OR expira_em < :agora OR cnpj = :cnpj",
                "ExpressionAttributeValues": {":agora": db.agora_epoch(), ":cnpj": org["cnpj"]},
            }},
            {"Update": {
                "Key": {"user_id": org_key(org["cnpj"])},
                "UpdateExpression": "SET convites.#e = :c",
                "ConditionExpression": "dono = :uid",
                "ExpressionAttributeNames": {"#e": email},
                "ExpressionAttributeValues": {":c": {"criado_em": agora, "expira_em": expira}, ":uid": user_id},
            }},
        ])
    except TransacaoCancelada as exc:
        if exc.falhou(0):
            raise ErroApi(409, "esse e-mail já tem um convite pendente de outra organização") from exc
        raise ErroApi(403, "só o dono da organização pode fazer isso") from exc
    return resp(201, {"email": email, "criado_em": agora, "expira_em": expira})


def remover(user_id: str, alvo: str) -> dict:
    usuario, org = _minha_org(user_id)
    cnpj = org["cnpj"]
    alvo = unquote(alvo or "").strip()

    if "@" in alvo:  # cancelar convite
        _so_dono(usuario)
        email = alvo.lower()
        try:
            db._table.update_item(
                Key={"user_id": org_key(cnpj)}, UpdateExpression="REMOVE convites.#e",
                ConditionExpression="dono = :uid AND attribute_exists(convites.#e)",
                ExpressionAttributeNames={"#e": email}, ExpressionAttributeValues={":uid": user_id})
        except db.ClientError as exc:
            if db.condicao_falhou(exc):
                raise ErroApi(404, "convite não encontrado") from exc
            raise
        try:  # o item do convite pode já ter expirado e sido apagado pelo TTL
            db._table.delete_item(Key={"user_id": convite_key(email)}, ConditionExpression="cnpj = :cnpj",
                                  ExpressionAttributeValues={":cnpj": cnpj})
        except db.ClientError as exc:
            if not db.condicao_falhou(exc):
                raise
        return resp(200, {"convite_cancelado": email})

    if alvo == user_id:  # sair da organização
        if usuario.get("papel") == "dono":
            raise ErroApi(400, "o dono não pode sair da organização")
        cond_org, valores = "attribute_exists(membros.#m)", {}
    else:  # o dono remove um membro
        _so_dono(usuario)
        cond_org, valores = "attribute_exists(membros.#m) AND dono = :uid", {":uid": user_id}
    try:
        db.transacao([
            {"Update": {"Key": {"user_id": org_key(cnpj)}, "UpdateExpression": "REMOVE membros.#m",
                        "ConditionExpression": cond_org, "ExpressionAttributeNames": {"#m": alvo},
                        **({"ExpressionAttributeValues": valores} if valores else {})}},
            {"Delete": {"Key": {"user_id": alvo}, "ConditionExpression": "cnpj = :cnpj AND papel = :membro",
                        "ExpressionAttributeValues": {":cnpj": cnpj, ":membro": "membro"}}},
        ])
    except TransacaoCancelada as exc:
        raise ErroApi(404, "membro não encontrado") from exc
    return resp(200, {"removido": alvo})


# ---------- convite (visão do convidado) ----------

def _convite_valido(email: str) -> tuple[dict, dict]:
    convite = db.get(convite_key(email))
    if not convite or int(convite.get("expira_em", 0)) <= db.agora_epoch():
        raise ErroApi(404, "nenhum convite pendente")
    org = db.get(org_key(convite["cnpj"]))
    if not org or email not in (org.get("convites") or {}):
        raise ErroApi(404, "nenhum convite pendente")
    return convite, org


def ver_convite(user_id: str) -> dict:
    convite, org = _convite_valido(_meu_email(user_id))
    return resp(200, {
        "cnpj": org["cnpj"],
        "razao_social": (org.get("empresa") or {}).get("razao_social"),
        "convidado_por": org.get("dono_email"),
        "expira_em": convite["expira_em"],
    })


def aceitar(user_id: str) -> dict:
    email = _meu_email(user_id)
    convite, org = _convite_valido(email)
    cnpj = org["cnpj"]
    try:
        db.transacao([
            {"Delete": {"Key": {"user_id": convite_key(email)},
                        "ConditionExpression": "cnpj = :cnpj AND expira_em > :agora",
                        "ExpressionAttributeValues": {":cnpj": cnpj, ":agora": db.agora_epoch()}}},
            {"Put": {"Item": {"user_id": user_id, "cnpj": cnpj, "papel": "membro"},
                     "ConditionExpression": "attribute_not_exists(cnpj)"}},
            {"Update": {"Key": {"user_id": org_key(cnpj)},
                        "UpdateExpression": "SET membros.#m = :m REMOVE convites.#e",
                        "ConditionExpression": "attribute_exists(user_id)",
                        "ExpressionAttributeNames": {"#m": user_id, "#e": email},
                        "ExpressionAttributeValues": {":m": {"email": email, "desde": db.agora_iso()}}}},
        ])
    except TransacaoCancelada as exc:
        if exc.falhou(1):
            raise ErroApi(409, "você já participa de uma organização; saia dela antes de aceitar") from exc
        raise ErroApi(404, "nenhum convite pendente") from exc
    return resp(200, {"cnpj": cnpj, "papel": "membro"})


def recusar(user_id: str) -> dict:
    email = _meu_email(user_id)
    convite = db.get(convite_key(email))
    if not convite:
        raise ErroApi(404, "nenhum convite pendente")
    db._table.delete_item(Key={"user_id": convite_key(email)})
    try:
        db._table.update_item(
            Key={"user_id": org_key(convite["cnpj"])}, UpdateExpression="REMOVE convites.#e",
            ConditionExpression="attribute_exists(user_id)", ExpressionAttributeNames={"#e": email})
    except db.ClientError as exc:
        if not db.condicao_falhou(exc):
            raise
    return resp(200, {"convite_recusado": email})


# ---------- roteamento ----------

ROTAS = {
    "GET /cadastro/membros": lambda uid, ev: listar(uid),
    "POST /cadastro/membros": lambda uid, ev: convidar(uid, ev.get("body")),
    "DELETE /cadastro/membros/{id}": lambda uid, ev: remover(uid, (ev.get("pathParameters") or {}).get("id")),
    "GET /cadastro/convite": lambda uid, ev: ver_convite(uid),
    "POST /cadastro/convite": lambda uid, ev: aceitar(uid),
    "DELETE /cadastro/convite": lambda uid, ev: recusar(uid),
}


def handler(event, context=None):
    user_id = auth.user_id_from_event(event)
    if not user_id:
        return resp(401, {"erro": "não autenticado"})
    rota = ROTAS.get(event.get("routeKey", ""))
    if not rota:
        return resp(404, {"erro": "rota não encontrada"})
    try:
        return rota(user_id, event)
    except ErroApi as exc:
        return resp(exc.status, {"erro": exc.erro})
