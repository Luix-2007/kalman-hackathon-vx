"""
GET   /cadastro/me   -> dados da organização do usuário, para preencher o formulário
PATCH /cadastro/me   -> salva os campos do formulário (só o dono)

Header: Authorization: Bearer <access token do Cognito>
O usuário só enxerga a própria organização: o user_id vem do token ("sub").
A organização é o CNPJ (ver dados.py): dono e membros veem os mesmos dados.

GET devolve:
  user_id, papel ("dono" | "membro"), cnpj, status, consultado_em
           status "processando" logo depois do POST, até a consulta terminar
  empresa  dados da Receita (sem a lista de sócios, por causa da LGPD)
  dados    campos do formulário (vazio até o primeiro PATCH)
  404 se o usuário ainda não tem organização

PATCH body: {"dados": {"email_alertas": "compliance@empresa.com", "setor": null}}
  - só o dono edita (membros só leem: 403)
  - só mexe em `dados`; cnpj/status/empresa nunca são alterados por aqui
  - merge campo a campo: o que não foi enviado fica como está (uma lista é
    substituída inteira)
  - valor null apaga o campo
  - só os campos do perfil regulatório (perfil.py); campo fora da lista ou com
    tipo errado volta 400
"""

import json
import re
from decimal import Decimal

from botocore.exceptions import ClientError

import dados as db
import perfil
from auth import user_id_from_event
from dados import org_key, resp

# Campos do perfil regulatório (tipos e regras em perfil.py). None = aceita qualquer campo.
CAMPOS_PERMITIDOS: set[str] | None = set(perfil.CAMPOS)

MAX_CAMPOS = 50
NOME_CAMPO = re.compile(r"^[a-z][a-z0-9_]{0,49}$")
# Dados dos sócios (pessoas físicas): não são devolvidos ao front.
CAMPOS_SENSIVEIS = {"QSA"}

SEM_ORGANIZACAO = "cadastro não encontrado: envie um CNPJ ou aceite um convite"


def get_usuario(user_id: str) -> dict:
    usuario = db.get(user_id) or {}
    org = db.get(org_key(usuario["cnpj"])) if usuario.get("cnpj") else None
    if not org:
        return resp(404, {"erro": SEM_ORGANIZACAO})
    empresa = {k: v for k, v in (org.get("empresa") or {}).items() if k not in CAMPOS_SENSIVEIS}
    return resp(200, {
        "user_id": user_id,
        "papel": usuario.get("papel"),
        "cnpj": org.get("cnpj"),
        "status": org.get("status"),
        "consultado_em": org.get("consultado_em"),
        "empresa": empresa,
        "dados": org.get("dados", {}),
    })


def patch_usuario(user_id: str, raw_body: str | None) -> dict:
    try:
        body = json.loads(raw_body or "{}", parse_float=Decimal)
    except ValueError:
        return resp(400, {"erro": "JSON inválido"})
    dados = body.get("dados") if isinstance(body, dict) else None
    if not isinstance(dados, dict) or not dados:
        return resp(400, {"erro": 'envie {"dados": {"campo": "valor"}}'})
    if len(dados) > MAX_CAMPOS:
        return resp(400, {"erro": f"no máximo {MAX_CAMPOS} campos por vez"})
    invalidos = [k for k in dados if not NOME_CAMPO.match(k)]
    if invalidos:
        return resp(400, {"erro": "nome de campo inválido (use snake_case minúsculo)", "campos": invalidos})
    if CAMPOS_PERMITIDOS is not None:
        fora = [k for k in dados if k not in CAMPOS_PERMITIDOS]
        if fora:
            return resp(400, {"erro": "campo não permitido", "campos": fora})
    erros = perfil.validar(dados)
    if erros:
        return resp(400, {"erro": "valor inválido", "campos": erros})

    usuario = db.get(user_id) or {}
    if not usuario.get("cnpj"):
        return resp(404, {"erro": SEM_ORGANIZACAO})
    if usuario.get("papel") != "dono":
        return resp(403, {"erro": "só o dono da organização pode editar o cadastro"})
    chave = {"user_id": org_key(usuario["cnpj"])}

    # 1) garante que o mapa `dados` existe (e que o usuário ainda é o dono)
    try:
        db._table.update_item(
            Key=chave,
            UpdateExpression="SET dados = if_not_exists(dados, :vazio)",
            ConditionExpression="dono = :uid",
            ExpressionAttributeValues={":vazio": {}, ":uid": user_id},
        )
    except ClientError as exc:
        if db.condicao_falhou(exc):
            return resp(403, {"erro": "só o dono da organização pode editar o cadastro"})
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
    db._table.update_item(
        Key=chave,
        UpdateExpression=expr.strip(),
        ExpressionAttributeNames=names,
        **kwargs,
    )
    return get_usuario(user_id)


def handler(event, context=None):
    user_id = user_id_from_event(event)
    if not user_id:
        return resp(401, {"erro": "não autenticado"})
    method = event.get("requestContext", {}).get("http", {}).get("method", "").upper()
    if method == "GET":
        return get_usuario(user_id)
    if method == "PATCH":
        return patch_usuario(user_id, event.get("body"))
    return resp(405, {"erro": "método não permitido"})
