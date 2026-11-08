"""
API da matriz de obrigações (lê e decide sobre a gold do lakehouse, pelo Athena).

    GET   /obrigacoes[?em=AAAA-MM-DD]     versão vigente de cada obrigação + propostas pendentes
                                          (com `em`: as versões em vigor naquele dia)
    GET   /obrigacoes/{id}                todas as versões e o histórico de uma obrigação
    GET   /linha-do-tempo[?obrigacao_id=&ato_id=]   o que cada ato mudou, do mais recente ao mais antigo
    POST  /obrigacoes/{id}/decisao        {"versao": 2, "decisao": "aprovar"|"rejeitar", "comentario"?}
    GET   /tarefas[?em_risco=true&obrigacao_id=OBR-1]
    PATCH /tarefas/{id}                   {"status": "aberta"|"em_andamento"|"concluida", "evidencia_url"?}
    POST  /importacoes                    envia a planilha da matriz (CSV/XLSX) e dispara o job (importacao.py)
    GET   /importacoes                    arquivos enviados e estado do último processamento

Header: Authorization: Bearer <access token do Cognito> (o mesmo login do cadastro).
O CNPJ e o papel vêm da tabela do cadastro (item do usuário), nunca do front:
membros leem, só o dono decide e muda status (403).

Uma decisão grava em bronze_db.matriz_decisoes (fonte de verdade, o job refaz a gold a partir
dela) e já aplica na gold, para o front ver na hora: status e vigência das versões, histórico e
as tarefas da obrigação, recalculadas com regras_matriz (o mesmo código do job).

O Athena não tem transação entre tabelas, então a decisão segue uma ordem que não perde nada:
  1. trava (cnpj, obrigação, versão) no DynamoDB, condicional: duas decisões ao mesmo tempo
     (clique duplo, duas abas) não passam as duas, a segunda recebe 409;
  2. só começa a gravar se a Lambda ainda tem MIN_MS_PARA_GRAVAR pela frente (503 sem gravar nada);
  3. grava a decisão na bronze, sozinha. Se falhar, solta a trava: nada mudou, dá para repetir;
  4. aplica na gold. Se falhar aqui, a decisão já vale (está na bronze) e o próximo processamento
     da matriz refaz a gold; o cliente recebe 502 dizendo isso, e a trava fica.
"""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import time
import uuid
from datetime import date, datetime, timedelta, timezone

import boto3
from botocore.exceptions import ClientError

import athena
import importacao
import regras_matriz as regras
import sql_matriz as sql

log = logging.getLogger()
log.setLevel(os.environ.get("LOG_LEVEL", "INFO"))

TABLE_NAME = os.environ.get("TABLE_NAME", "usuarios-cnpj")
TRAVAS_TABLE = os.environ.get("TRAVAS_TABLE", "matriz-travas")
MIN_MS_PARA_GRAVAR = int(os.environ.get("MIN_MS_PARA_GRAVAR", "12000"))   # bronze + gold, com folga
TRAVA_DIAS = 7       # depois disso o job já refez a gold e a versão não está mais como proposta
BRASILIA = timezone(timedelta(hours=-3))
URL = re.compile(r"^https?://\S{1,1990}$")

_table = boto3.resource("dynamodb").Table(TABLE_NAME)
_travas = boto3.resource("dynamodb").Table(TRAVAS_TABLE)

SEM_MATRIZ = "a matriz desta empresa ainda não foi processada"
JA_DECIDIDA = "esta versão já foi decidida ou está sendo decidida agora"
SEM_TEMPO = "a matriz demorou para responder; nada foi gravado, tente de novo"
GOLD_PENDENTE = "a decisão foi registrada, mas a matriz ainda não mostra; ela se atualiza no próximo processamento"


class ErroApi(Exception):
    def __init__(self, status: int, erro: str):
        super().__init__(erro)
        self.status, self.erro = status, erro


def resp(status: int, body: dict) -> dict:
    return {"statusCode": status, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(body, ensure_ascii=False, default=str)}


def agora_utc() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def hoje_brasilia() -> date:
    return datetime.now(BRASILIA).date()


# ---------------------------------------------------------------- quem chama

def user_id_from_event(event: dict) -> str | None:
    claims = (event.get("requestContext") or {}).get("authorizer", {}).get("jwt", {}).get("claims", {})
    return str(claims.get("sub") or "").strip() or None


def organizacao_do_usuario(user_id: str) -> tuple[str, str]:
    """(cnpj, papel) do usuário. Só leitura na tabela do cadastro."""
    item = _table.get_item(Key={"user_id": user_id}).get("Item") or {}
    cnpj, papel = item.get("cnpj"), item.get("papel")
    if not cnpj or not sql.CNPJ.match(cnpj):
        raise ErroApi(404, "cadastro não encontrado: envie um CNPJ ou aceite um convite")
    return cnpj, papel


def outorgas_da_organizacao(cnpj: str) -> list[dict]:
    org = _table.get_item(Key={"user_id": f"CNPJ#{cnpj}"}).get("Item") or {}
    saida = []
    for o in (org.get("dados") or {}).get("outorgas") or []:
        if isinstance(o, dict) and o.get("id"):
            ante = o.get("antecedencia_renovacao_dias")
            saida.append({"cnpj": cnpj, "outorga_id": o["id"], "tipo": o.get("tipo"), "numero": o.get("numero"),
                          "unidade_id": o.get("unidade_id"), "validade": o.get("validade"),
                          "antecedencia_renovacao_dias": int(ante) if ante is not None else None})
    return saida


def so_dono(papel: str) -> None:
    if papel != "dono":
        raise ErroApi(403, "só o dono da organização pode decidir e alterar tarefas")


# ---------------------------------------------------------------- linhas do Athena

def _obrigacao(linha: dict) -> dict:
    o = dict(linha)
    o["aplica_a"] = json.loads(o["aplica_a"]) if isinstance(o.get("aplica_a"), str) else (o.get("aplica_a") or [])
    return o


def _evento(linha: dict) -> dict:
    e = dict(linha)
    e["alteracoes"] = json.loads(e["alteracoes"]) if e.get("alteracoes") else []
    return e


def _tarefa(linha: dict) -> dict:
    t = dict(linha)
    if isinstance(t.get("atualizada_em"), str):
        t["atualizada_em"] = datetime.fromisoformat(t["atualizada_em"])
    return t


def _json_tarefa(t: dict) -> dict:
    return {**t, "vencimento": str(t["vencimento"]),
            "atualizada_em": t["atualizada_em"].isoformat(sep=" ") if isinstance(t.get("atualizada_em"), datetime)
            else t.get("atualizada_em")}


def _consultar(q: str) -> list[dict] | None:
    """None = tabela ainda não existe (matriz não processada)."""
    try:
        return athena.consultar(q)
    except athena.TabelaInexistente:
        return None


# ---------------------------------------------------------------- rotas de leitura

def listar_obrigacoes(cnpj: str, em: str | None = None) -> dict:
    if em:
        try:
            dia = date.fromisoformat(em)
        except ValueError:
            raise ErroApi(400, "em deve ser AAAA-MM-DD") from None
        linhas = _consultar(sql.obrigacoes_em(cnpj, dia))
        return resp(200, {"cnpj": cnpj, "em": em, "obrigacoes": [_obrigacao(l) for l in linhas or []]})
    linhas = _consultar(sql.obrigacoes_atuais(cnpj))
    if linhas is None:
        return resp(200, {"cnpj": cnpj, "obrigacoes": [], "aviso": SEM_MATRIZ})
    obs = [_obrigacao(l) for l in linhas]
    return resp(200, {"cnpj": cnpj, "obrigacoes": obs,
                      "resumo": {"vigentes": sum(o["vigente"] for o in obs),
                                 "propostas": sum(o["status"] == "proposta" for o in obs)}})


def detalhar_obrigacao(cnpj: str, obrigacao_id: str) -> dict:
    versoes = _consultar(sql.versoes_da_obrigacao(cnpj, obrigacao_id)) or []
    if not versoes:
        raise ErroApi(404, "obrigação não encontrada")
    historico = _consultar(sql.historico_da_obrigacao(cnpj, obrigacao_id)) or []
    return resp(200, {"obrigacao_id": obrigacao_id, "versoes": [_obrigacao(v) for v in versoes],
                      "historico": [_evento(h) for h in historico]})


def linha_do_tempo(cnpj: str, params: dict) -> dict:
    ato_id = params.get("ato_id") or None
    if ato_id and (len(ato_id) > 200 or not re.fullmatch(r"[\w.:#/-]+", ato_id)):
        raise ErroApi(400, "ato_id inválido")
    linhas = _consultar(sql.linha_do_tempo(cnpj, params.get("obrigacao_id") or None, ato_id))
    if linhas is None:
        return resp(200, {"cnpj": cnpj, "eventos": [], "aviso": SEM_MATRIZ})
    return resp(200, {"cnpj": cnpj, "eventos": [_evento(l) for l in linhas]})


def listar_tarefas(cnpj: str, params: dict) -> dict:
    obrigacao_id = params.get("obrigacao_id") or None
    linhas = _consultar(sql.tarefas(cnpj, obrigacao_id, str(params.get("em_risco", "")).lower() == "true"))
    if linhas is None:
        return resp(200, {"cnpj": cnpj, "tarefas": [], "aviso": SEM_MATRIZ})
    tarefas = [_json_tarefa(_tarefa(l)) for l in linhas]
    return resp(200, {"cnpj": cnpj, "tarefas": tarefas,
                      "resumo": {"total": len(tarefas), "em_risco": sum(t["em_risco"] for t in tarefas),
                                 "concluidas": sum(t["status"] == "concluida" for t in tarefas)}})


# ---------------------------------------------------------------- decisões

def _corpo(event: dict) -> dict:
    try:
        corpo = json.loads(event.get("body") or "{}")
    except ValueError:
        raise ErroApi(400, "JSON inválido") from None
    if not isinstance(corpo, dict):
        raise ErroApi(400, "envie um objeto JSON")
    return corpo


def recalcular_tarefas(cnpj: str, obrigacao_id: str, versoes: list[dict], hoje: date, agora: datetime) -> list[dict]:
    """Tarefas da obrigação depois da decisão, com as mesmas regras do job."""
    vigente = next((v for v in versoes if v["vigente"] and v["status"] == "aprovada"), None)
    geradas = regras.gerar_tarefas(vigente, outorgas_da_organizacao(cnpj), hoje) if vigente else []
    anteriores = [_tarefa(t) for t in (_consultar(sql.tarefas(cnpj, obrigacao_id)) or [])]
    pendentes = {(cnpj, obrigacao_id)} if any(v["status"] == "proposta" for v in versoes) else set()
    vigentes = {(cnpj, obrigacao_id): vigente["versao"]} if vigente else {}
    return regras.consolidar_tarefas(geradas, anteriores, {}, vigentes, pendentes, hoje, agora)


def travar_decisao(cnpj: str, obrigacao_id: str, versao: int) -> str:
    """Só uma decisão por versão passa daqui (put condicional). 409 para a segunda."""
    chave = f"{cnpj}#{obrigacao_id}#v{versao}"
    try:
        _travas.put_item(Item={"chave": chave, "expira_em": int(time.time()) + TRAVA_DIAS * 86400},
                         ConditionExpression="attribute_not_exists(chave)")
    except ClientError as exc:
        if exc.response["Error"]["Code"] == "ConditionalCheckFailedException":
            raise ErroApi(409, JA_DECIDIDA) from None
        raise
    return chave


def tem_tempo_para_gravar(context) -> bool:
    """Sem contexto (testes, chamada direta) não há limite conhecido."""
    if context is None or not hasattr(context, "get_remaining_time_in_millis"):
        return True
    return context.get_remaining_time_in_millis() >= MIN_MS_PARA_GRAVAR


def decidir(user_id: str, cnpj: str, papel: str, obrigacao_id: str, corpo: dict, context=None) -> dict:
    so_dono(papel)
    decisao, versao = corpo.get("decisao"), corpo.get("versao")
    if decisao not in ("aprovar", "rejeitar"):
        raise ErroApi(400, 'decisao deve ser "aprovar" ou "rejeitar"')
    if isinstance(versao, bool) or not isinstance(versao, int):
        raise ErroApi(400, "versao deve ser um número inteiro")
    comentario = corpo.get("comentario")
    if comentario is not None and (not isinstance(comentario, str) or len(comentario) > 2000):
        raise ErroApi(400, "comentario deve ser texto de até 2000 caracteres")

    versoes = [_obrigacao(v) for v in (_consultar(sql.versoes_da_obrigacao(cnpj, obrigacao_id)) or [])]
    alvo = next((v for v in versoes if v["versao"] == versao), None)
    if alvo is None:
        raise ErroApi(404, "versão da obrigação não encontrada")
    if alvo["status"] != "proposta":
        raise ErroApi(409, f"esta versão já foi decidida (status {alvo['status']})")

    agora, hoje = agora_utc(), hoje_brasilia()
    antes = copy.deepcopy(versoes)
    regras.aplicar_decisao(versoes, alvo, decisao, user_id, agora)
    novas = recalcular_tarefas(cnpj, obrigacao_id, versoes, hoje, agora)

    if not tem_tempo_para_gravar(context):
        log.warning("cnpj %s: decisão de %s v%s recusada antes de gravar, pouco tempo restante", cnpj, obrigacao_id, versao)
        raise ErroApi(503, SEM_TEMPO)
    trava = travar_decisao(cnpj, obrigacao_id, versao)

    # 1. a decisão em si (fonte de verdade), sozinha: se falhar, nada mudou
    try:
        athena.executar(sql.inserir_decisao({
            "decisao_id": str(uuid.uuid4()), "tipo": "obrigacao", "cnpj": cnpj, "obrigacao_id": obrigacao_id,
            "versao": versao, "decisao": decisao, "usuario": user_id, "comentario": comentario,
            "decidida_em": agora}))
    except athena.ErroAthena:
        _travas.delete_item(Key={"chave": trava})
        raise

    # 2. a gold, para o front ver na hora. Daqui em diante a decisão vale mesmo se algo falhar.
    escritas = [
        sql.inserir_historico({"cnpj": cnpj, "obrigacao_id": obrigacao_id, "versao": versao,
                               "evento": "aprovacao" if decisao == "aprovar" else "rejeicao",
                               "status": alvo["status"], "origem": alvo.get("origem"), "ocorrido_em": hoje,
                               "por": user_id, "ato_id": alvo.get("alterada_por"), "ato_url": alvo.get("fonte_url"),
                               "data_ato": alvo.get("data_ato"), "trecho_citado": alvo.get("trecho_citado"),
                               "resumo": f"{'aprovada' if decisao == 'aprovar' else 'rejeitada'} pelo dono"}),
        sql.apagar_tarefas_da_obrigacao(cnpj, obrigacao_id),
    ]
    update = sql.atualizar_versoes(cnpj, obrigacao_id, antes, versoes)
    if update:
        escritas.append(update)
    try:
        athena.em_paralelo(*escritas)
        inserir = sql.inserir_tarefas(novas)
        if inserir:
            athena.executar(inserir)
    except athena.ErroAthena:
        log.exception("cnpj %s: %s %s v%s registrada na bronze, mas a gold ficou incompleta; "
                      "o próximo processamento da matriz corrige", cnpj, decisao, obrigacao_id, versao)
        raise ErroApi(502, GOLD_PENDENTE) from None
    log.info("cnpj %s: %s %s v%s por %s", cnpj, decisao, obrigacao_id, versao, user_id)
    return resp(200, {"obrigacao_id": obrigacao_id, "versoes": versoes,
                      "tarefas": [_json_tarefa(t) for t in novas]})


def mudar_tarefa(user_id: str, cnpj: str, papel: str, tarefa_id: str, corpo: dict) -> dict:
    so_dono(papel)
    status = corpo.get("status")
    if status not in sql.STATUS_TAREFA:
        raise ErroApi(400, f"status deve ser um de {', '.join(sql.STATUS_TAREFA)}")
    if "evidencia_url" in corpo and corpo["evidencia_url"] is not None and not URL.match(str(corpo["evidencia_url"])):
        raise ErroApi(400, "evidencia_url deve ser um link http(s)")

    linhas = _consultar(sql.tarefa(cnpj, tarefa_id)) or []
    if not linhas:
        raise ErroApi(404, "tarefa não encontrada")
    t = _tarefa(linhas[0])
    hoje, agora = hoje_brasilia(), agora_utc()
    venc = date.fromisoformat(str(t["vencimento"]))
    # em risco por proposta pendente (e não pelo prazo) continua em risco enquanto aberta
    pendente = bool(t["em_risco"]) and t["status"] != "concluida" and (venc - hoje).days > regras.DIAS_RISCO
    evidencia = corpo["evidencia_url"] if "evidencia_url" in corpo else t.get("evidencia_url")
    em_risco = regras.em_risco(venc, status, hoje, pendente)

    athena.em_paralelo(
        sql.inserir_decisao({"decisao_id": str(uuid.uuid4()), "tipo": "tarefa", "cnpj": cnpj,
                             "tarefa_id": tarefa_id, "decisao": status, "evidencia_url": evidencia,
                             "usuario": user_id, "decidida_em": agora}),
        sql.atualizar_tarefa(cnpj, tarefa_id, status, evidencia, em_risco, agora),
    )
    t.update({"status": status, "evidencia_url": evidencia, "em_risco": em_risco, "atualizada_em": agora})
    return resp(200, {"tarefa": _json_tarefa(t)})


# ---------------------------------------------------------------- entrada

def handler(event, context=None):
    user_id = user_id_from_event(event)
    if not user_id:
        return resp(401, {"erro": "não autenticado"})
    rota = event.get("routeKey", "")
    params = event.get("pathParameters") or {}
    query = event.get("queryStringParameters") or {}
    try:
        cnpj, papel = organizacao_do_usuario(user_id)
        if "id" in params and not (sql.ID.match(params["id"]) or sql.TAREFA_ID.match(params["id"])):
            raise ErroApi(400, "id inválido")
        if query.get("obrigacao_id") and not sql.ID.match(query["obrigacao_id"]):
            raise ErroApi(400, "obrigacao_id inválido")
        if rota == "GET /obrigacoes":
            return listar_obrigacoes(cnpj, query.get("em"))
        if rota == "GET /linha-do-tempo":
            return linha_do_tempo(cnpj, query)
        if rota == "GET /obrigacoes/{id}":
            return detalhar_obrigacao(cnpj, params["id"])
        if rota == "POST /obrigacoes/{id}/decisao":
            return decidir(user_id, cnpj, papel, params["id"], _corpo(event), context)
        if rota == "GET /tarefas":
            return listar_tarefas(cnpj, query)
        if rota == "PATCH /tarefas/{id}":
            if not sql.TAREFA_ID.match(params["id"]):
                raise ErroApi(400, "id de tarefa inválido")
            return mudar_tarefa(user_id, cnpj, papel, params["id"], _corpo(event))
        if rota == "GET /importacoes":
            return resp(*importacao.listar(cnpj))
        if rota == "POST /importacoes":
            if papel != "dono":
                raise ErroApi(403, "só o dono da organização pode enviar a matriz")
            return resp(*importacao.importar(cnpj, user_id, _corpo(event)))
        return resp(404, {"erro": "rota não encontrada"})
    except importacao.ErroImportacao as exc:
        return resp(exc.status, {"erro": exc.erro})
    except ErroApi as exc:
        return resp(exc.status, {"erro": exc.erro})
    except sql.ValorInvalido as exc:
        return resp(400, {"erro": str(exc)})
    except athena.ErroAthena as exc:
        # o motivo (nomes de tabela, trecho do SQL) fica só no log; o cliente recebe a mensagem genérica
        log.exception("erro no Athena")
        return resp(502, {"erro": "não foi possível consultar a matriz agora, tente de novo"})
