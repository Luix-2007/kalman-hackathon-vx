"""
POST /cadastro  (chamado pelo front, com o token do Cognito)

Header: Authorization: Bearer <access token>
Body JSON: {"cnpj": "00.000.000/0001-91"}

Cria a organização do CNPJ com o usuário como dono (modelo em dados.py) e publica
o evento "UsuarioCadastrado" no EventBridge para a consulta em segundo plano (app.py).
O user_id vem do token (claim "sub"); qualquer user_id no body é ignorado.

Respostas:
  202  organização criada (ou consulta refeita); status "processando" até a consulta terminar
  409  o CNPJ já tem dono, o usuário é membro de outra organização, ou a organização
       tem membros/convites e por isso não pode trocar de CNPJ
  400  CNPJ ou JSON inválido
Reenviar o mesmo CNPJ só refaz a consulta. O dono pode trocar de CNPJ enquanto a
organização não tiver membros, convites pendentes nem perfil regulatório com unidades,
outorgas ou áreas: o CNPJ anterior fica livre. O perfil é copiado para o lake da matriz
chaveado pelo CNPJ, e as obrigações e tarefas são derivadas dele; trocar o CNPJ depois
disso deixaria a matriz presa ao CNPJ antigo.
"""

import json
import os

import boto3

import auth
import dados
import perfil
from app import normalize_cnpj
from dados import ErroApi, TransacaoCancelada, org_key, resp

EVENT_SOURCE = os.environ.get("EVENT_SOURCE", "app.usuarios")
EVENT_DETAIL_TYPE = os.environ.get("EVENT_DETAIL_TYPE", "UsuarioCadastrado")

_events = boto3.client("events")

CNPJ_EM_USO = "este CNPJ já está vinculado a outro usuário"


def _nova_org(cnpj: str, user_id: str, email: str | None, dados_form: dict) -> dict:
    return {"Put": {
        "Item": {
            "user_id": org_key(cnpj), "cnpj": cnpj, "dono": user_id, "dono_email": email,
            "status": "processando", "dados": dados_form, "membros": {}, "convites": {},
            "criado_em": dados.agora_iso(),
        },
        "ConditionExpression": "attribute_not_exists(user_id)",  # falha se o CNPJ já tem dono
    }}


def vincular(user_id: str, cnpj: str) -> None:
    usuario = dados.get(user_id) or {}
    atual = usuario.get("cnpj")
    if usuario.get("papel") == "membro":
        raise ErroApi(409, "você é membro de outra organização; saia dela para cadastrar um CNPJ")
    if atual == cnpj:
        return  # reenvio do mesmo CNPJ: só refaz a consulta

    if atual is None:  # primeira vez: cria a organização com o usuário como dono
        ops = [
            _nova_org(cnpj, user_id, auth.email_do_usuario(user_id), {}),
            {"Put": {"Item": {"user_id": user_id, "cnpj": cnpj, "papel": "dono"},
                     "ConditionExpression": "attribute_not_exists(cnpj)"}},
        ]
    else:  # troca de CNPJ: só sem membros e convites; leva o formulário junto
        org = dados.get(org_key(atual)) or {}
        if org.get("membros") or dados.convites_ativos(org):
            raise ErroApi(409, "remova os membros e cancele os convites antes de trocar o CNPJ")
        if perfil.tem_perfil_no_lake(org.get("dados")):
            raise ErroApi(409, "a organização já tem perfil regulatório (unidades, outorgas ou "
                               "áreas) e matriz de obrigações ligados a este CNPJ; não é possível trocá-lo")
        ops = [
            _nova_org(cnpj, user_id, org.get("dono_email"), org.get("dados") or {}),
            {"Update": {"Key": {"user_id": user_id}, "UpdateExpression": "SET cnpj = :novo",
                        "ConditionExpression": "cnpj = :atual AND papel = :dono",
                        "ExpressionAttributeValues": {":novo": cnpj, ":atual": atual, ":dono": "dono"}}},
            {"Delete": {"Key": {"user_id": org_key(atual)},
                        "ConditionExpression": "dono = :uid AND size(membros) = :zero",
                        "ExpressionAttributeValues": {":uid": user_id, ":zero": 0}}},
        ]

    try:
        dados.transacao(ops)
    except TransacaoCancelada as exc:
        if exc.falhou(0):
            raise ErroApi(409, CNPJ_EM_USO) from exc
        raise ErroApi(409, "o cadastro mudou durante o envio, tente de novo") from exc


def handler(event, context=None):
    user_id = auth.user_id_from_event(event)
    if not user_id:
        return resp(401, {"erro": "não autenticado"})

    try:
        body = json.loads(event.get("body") or "{}")
    except ValueError:
        return resp(400, {"erro": "JSON inválido"})
    if not isinstance(body, dict):
        return resp(400, {"erro": 'envie {"cnpj": "..."}'})

    try:
        cnpj = normalize_cnpj(body.get("cnpj", ""))
    except ValueError:
        return resp(400, {"erro": "CNPJ inválido"})

    try:
        vincular(user_id, cnpj)
    except ErroApi as exc:
        return resp(exc.status, {"erro": exc.erro})

    result = _events.put_events(Entries=[{
        "Source": EVENT_SOURCE,
        "DetailType": EVENT_DETAIL_TYPE,
        "Detail": json.dumps({"user_id": user_id, "cnpj": cnpj}),
    }])
    if result.get("FailedEntryCount"):
        # o vínculo fica; reenviar o mesmo CNPJ só publica o evento de novo
        return resp(502, {"erro": "não foi possível registrar o cadastro, tente de novo"})
    return resp(202, {"status": "recebido", "user_id": user_id, "cnpj": cnpj})
