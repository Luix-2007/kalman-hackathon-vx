"""
Consultas no Athena (workgroup do lakehouse, que já tem local de resultados configurado).

    consultar(sql) -> lista de dicts com tipos Python (int, float, bool, str)
    executar(sql)  -> roda um INSERT/UPDATE/DELETE e espera terminar
    em_paralelo(*sqls) -> roda vários ao mesmo tempo (tabelas diferentes)

Datas e timestamps voltam como texto ISO. Colunas de lista são lidas com
json_format(CAST(col AS JSON)) no SELECT e voltam como texto JSON.

TabelaInexistente: a matriz ainda não foi processada (o job cria as tabelas).
"""

from __future__ import annotations

import os
import time
from concurrent.futures import ThreadPoolExecutor

import boto3

WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "lakehouse-pipeline-lakehouse")
ESPERA_MAX_S = float(os.environ.get("ATHENA_ESPERA_MAX_S", "25"))

_client = None


class ErroAthena(Exception):
    pass


class TabelaInexistente(ErroAthena):
    pass


class CommitConcorrente(ErroAthena):
    """Outro commit no Iceberg ao mesmo tempo (ex.: o job da gold). Pode tentar de novo."""


def _athena():
    global _client
    _client = _client or boto3.client("athena")
    return _client


def _esperar(qid: str) -> None:
    inicio, pausa = time.monotonic(), 0.2
    while True:
        st = _athena().get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        estado = st["State"]
        if estado == "SUCCEEDED":
            return
        if estado in ("FAILED", "CANCELLED"):
            motivo = st.get("StateChangeReason", estado)
            if "TABLE_NOT_FOUND" in motivo or "does not exist" in motivo:
                raise TabelaInexistente(motivo)
            if "ICEBERG_COMMIT_ERROR" in motivo or "CONCURRENT" in motivo.upper():
                raise CommitConcorrente(motivo)
            raise ErroAthena(motivo)
        if time.monotonic() - inicio > ESPERA_MAX_S:
            _athena().stop_query_execution(QueryExecutionId=qid)
            raise ErroAthena(f"consulta {qid} passou de {ESPERA_MAX_S}s")
        time.sleep(pausa)
        pausa = min(pausa * 1.5, 1.0)


def _iniciar(sql: str) -> str:
    return _athena().start_query_execution(QueryString=sql, WorkGroup=WORKGROUP)["QueryExecutionId"]


def _converter(valor: str | None, tipo: str):
    if valor is None:
        return None
    if tipo in ("integer", "bigint", "smallint", "tinyint"):
        return int(valor)
    if tipo in ("double", "float", "real", "decimal"):
        return float(valor)
    if tipo == "boolean":
        return valor == "true"
    return valor


def consultar(sql: str) -> list[dict]:
    qid = _iniciar(sql)
    _esperar(qid)
    linhas, colunas, token, primeira = [], None, None, True
    while True:
        kwargs = {"QueryExecutionId": qid, "MaxResults": 1000}
        if token:
            kwargs["NextToken"] = token
        resp = _athena().get_query_results(**kwargs)
        if colunas is None:
            colunas = [(c["Name"], c["Type"]) for c in resp["ResultSet"]["ResultSetMetadata"]["ColumnInfo"]]
        rows = resp["ResultSet"]["Rows"]
        if primeira:
            rows, primeira = rows[1:], False   # a primeira linha é o cabeçalho
        for r in rows:
            dados = [d.get("VarCharValue") for d in r["Data"]]
            linhas.append({nome: _converter(v, tipo) for (nome, tipo), v in zip(colunas, dados)})
        token = resp.get("NextToken")
        if not token:
            return linhas


def executar(sql: str, tentativas: int = 3) -> None:
    for tentativa in range(1, tentativas + 1):
        try:
            _esperar(_iniciar(sql))
            return
        except CommitConcorrente:
            if tentativa == tentativas:
                raise
            time.sleep(0.5 * tentativa)


def em_paralelo(*sqls: str) -> None:
    with ThreadPoolExecutor(max_workers=len(sqls) or 1) as pool:
        for f in [pool.submit(executar, s) for s in sqls]:
            f.result()
