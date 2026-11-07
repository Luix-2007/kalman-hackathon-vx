"""
Importação da matriz de obrigações pelo front (a planilha que a empresa já tem).

    POST /importacoes   {"nome": "matriz.csv", "conteudo": "<texto do CSV>"}
                        {"nome": "matriz.xlsx", "conteudo_base64": "<bytes em base64>"}
    GET  /importacoes   arquivos enviados (mais novos primeiro) + estado do último processamento

Só o dono envia (membros leem: 403). O arquivo vai para
s3://<lake>/landing/matriz/importada/<cnpj>/<AAAAMMDD-HHMMSS>-<nome>, a mesma pasta que o job da matriz
(pipeline/matriz, stack lakehouse-matriz) já lê, e a máquina de estados é disparada na hora (sem esperar a rodada de
hora em hora). O processamento leva de 7 a 15 minutos (Glue, 4 etapas). Linha inválida não derruba o arquivo: o job a
deixa em quarentena na silver (valida = false), e o front confere as mesmas regras antes de enviar.

O arquivo passa pela API (e não por URL pré-assinada direto no S3) porque o bucket do lake é de outro stack e não tem
CORS para o navegador. Uma matriz tem poucos KB; o limite aqui é 2 MB (o da Lambda é 6 MB).
"""

from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import uuid
from datetime import datetime, timezone

import boto3

log = logging.getLogger()

LAKE_BUCKET = os.environ.get("LAKE_BUCKET", "")
STATE_MACHINE_ARN = os.environ.get("MATRIZ_STATE_MACHINE_ARN", "")
PASTA = "landing/matriz/importada"
MAX_BYTES = 2 * 1024 * 1024
EXTENSOES = {"csv": "text/csv; charset=utf-8",
             "xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}
COLUNAS_MINIMAS = ("obrigacao_id", "titulo")
NOME_SEGURO = re.compile(r"[^A-Za-z0-9._-]+")

_s3 = None
_sfn = None


class ErroImportacao(Exception):
    def __init__(self, status: int, erro: str):
        super().__init__(erro)
        self.status, self.erro = status, erro


def s3():
    global _s3
    _s3 = _s3 or boto3.client("s3")
    return _s3


def sfn():
    global _sfn
    _sfn = _sfn or boto3.client("stepfunctions")
    return _sfn


def _arquivo(corpo: dict) -> tuple[str, str, bytes]:
    """(nome seguro, extensão, bytes) do corpo do POST, ou ErroImportacao."""
    nome = str(corpo.get("nome") or "").strip()
    ext = nome.rsplit(".", 1)[-1].lower() if "." in nome else ""
    if ext not in EXTENSOES:
        raise ErroImportacao(400, "envie um arquivo .csv ou .xlsx")
    if ext == "csv":
        texto = corpo.get("conteudo")
        if not isinstance(texto, str):
            raise ErroImportacao(400, 'envie o texto do CSV em "conteudo"')
        dados = texto.encode("utf-8")
        cabecalho = texto.lstrip("﻿").split("\n", 1)[0].lower()
        faltam = [c for c in COLUNAS_MINIMAS if c not in cabecalho]
        if faltam:
            raise ErroImportacao(400, f"o arquivo não parece a matriz: faltam as colunas {', '.join(faltam)}")
    else:
        try:
            dados = base64.b64decode(str(corpo.get("conteudo_base64") or ""), validate=True)
        except (binascii.Error, ValueError):
            raise ErroImportacao(400, 'envie o .xlsx em base64 em "conteudo_base64"') from None
    if not dados:
        raise ErroImportacao(400, "arquivo vazio")
    if len(dados) > MAX_BYTES:
        raise ErroImportacao(413, "arquivo maior que 2 MB")
    base = NOME_SEGURO.sub("-", nome.rsplit(".", 1)[0]).strip("-._")[:60] or "matriz"
    return f"{base}.{ext}", ext, dados


def _ultimo_processamento() -> dict | None:
    if not STATE_MACHINE_ARN:
        return None
    try:
        execs = sfn().list_executions(stateMachineArn=STATE_MACHINE_ARN, maxResults=1)["executions"]
    except Exception:  # noqa: BLE001 - o estado é informativo; a lista de arquivos ainda serve
        log.exception("não foi possível ler as execuções da matriz")
        return None
    if not execs:
        return None
    e = execs[0]
    return {"estado": e["status"], "inicio": e["startDate"].isoformat(),
            "fim": e["stopDate"].isoformat() if e.get("stopDate") else None}


def importar(cnpj: str, user_id: str, corpo: dict, agora: datetime | None = None) -> tuple[int, dict]:
    """Grava o arquivo na landing e dispara o processamento. O dono já foi conferido por quem chama."""
    nome, ext, dados = _arquivo(corpo)
    agora = agora or datetime.now(timezone.utc)
    chave = f"{PASTA}/{cnpj}/{agora:%Y%m%d-%H%M%S}-{nome}"
    s3().put_object(Bucket=LAKE_BUCKET, Key=chave, Body=dados, ContentType=EXTENSOES[ext],
                    Metadata={"enviado-por": user_id})

    processamento = None
    if STATE_MACHINE_ARN:
        try:
            r = sfn().start_execution(
                stateMachineArn=STATE_MACHINE_ARN,
                name=f"importacao-{cnpj}-{agora:%Y%m%d%H%M%S}-{uuid.uuid4().hex[:6]}"[:80],
                input="{}")
            processamento = {"estado": "RUNNING", "inicio": agora.isoformat(), "fim": None, "execucao": r["executionArn"]}
        except Exception:  # noqa: BLE001 - o arquivo já está na landing; a rodada de hora em hora o pega
            log.exception("não foi possível disparar a matriz; fica para a próxima rodada")
    return 201, {"arquivo": chave.rsplit("/", 1)[-1], "enviado_em": agora.isoformat(), "processamento": processamento}


def listar(cnpj: str) -> tuple[int, dict]:
    prefixo = f"{PASTA}/{cnpj}/"
    arquivos = []
    for pagina in s3().get_paginator("list_objects_v2").paginate(Bucket=LAKE_BUCKET, Prefix=prefixo):
        for o in pagina.get("Contents", []):
            arquivos.append({"arquivo": o["Key"][len(prefixo):], "tamanho": o["Size"],
                             "enviado_em": o["LastModified"].isoformat()})
    arquivos.sort(key=lambda a: a["enviado_em"], reverse=True)
    return 200, {"importacoes": arquivos, "processamento": _ultimo_processamento()}
