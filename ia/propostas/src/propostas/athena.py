"""Consultas de leitura no Athena, com parâmetros (nunca valor colado no SQL)."""

from __future__ import annotations

import time


class ErroConsulta(Exception):
    pass


class TabelaInexistente(ErroConsulta):
    pass


class Athena:
    def __init__(self, cliente, workgroup: str, espera_max_s: float = 120.0):
        self.cliente, self.workgroup, self.espera_max_s = cliente, workgroup, espera_max_s

    def consultar(self, sql: str, params: list[str] | None = None) -> list[dict]:
        """Linhas como dicts de texto (None quando nulo). `params` são valores, não SQL: cada um vira
        um literal de texto entre aspas."""
        args = {"QueryString": sql, "WorkGroup": self.workgroup}
        if params:
            args["ExecutionParameters"] = ["'" + str(p).replace("'", "''") + "'" for p in params]
        qid = self.cliente.start_query_execution(**args)["QueryExecutionId"]
        limite, pausa = time.monotonic() + self.espera_max_s, 0.3
        while True:
            st = self.cliente.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
            if st["State"] == "SUCCEEDED":
                break
            if st["State"] in ("FAILED", "CANCELLED"):
                motivo = st.get("StateChangeReason", st["State"])
                if "TABLE_NOT_FOUND" in motivo or "does not exist" in motivo:
                    raise TabelaInexistente(motivo)
                raise ErroConsulta(motivo)
            if time.monotonic() > limite:
                self.cliente.stop_query_execution(QueryExecutionId=qid)
                raise ErroConsulta(f"consulta {qid} passou de {self.espera_max_s}s")
            time.sleep(pausa)
            pausa = min(pausa * 1.5, 2.0)
        linhas, cabecalho = [], None
        token = None
        while True:
            kw = {"QueryExecutionId": qid, "MaxResults": 1000}
            if token:
                kw["NextToken"] = token
            resp = self.cliente.get_query_results(**kw)
            for r in resp["ResultSet"]["Rows"]:
                valores = [c.get("VarCharValue") for c in r["Data"]]
                if cabecalho is None:
                    cabecalho = valores
                else:
                    linhas.append(dict(zip(cabecalho, valores)))
            token = resp.get("NextToken")
            if not token:
                return linhas
