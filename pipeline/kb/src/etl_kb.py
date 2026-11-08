"""
Job de atualizacao da Bedrock Knowledge Base com documentos das empresas classificadas.

Etapas (--STAGE):
    docs   Gold (empresas + classificacao) -> kb_docs/empresas/<user_id>.md + .metadata.json
    sync   StartIngestionJob na KB e aguarda conclusao

Roda como job AWS Glue Python Shell (Python 3.9).
Os caminhos funcionam com s3:// (no Glue) e com pastas locais (nos testes).

Argumentos (formato do Glue: --CHAVE valor):
    --STAGE     docs | sync
    --LAKE_URI  s3://bucket-do-lake  (ou pasta local)
    --REGION    regiao AWS
    --KB_ID     ID da Bedrock Knowledge Base
    --DS_ID     ID do DataSource da KB
    --PREFIXOS  Prefixo S3 para os docs (default: kb_docs/empresas)
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
import time
from typing import Callable, Dict, List, Optional

import duckdb
import pyarrow as pa

log = logging.getLogger("etl_kb")

GOLD_EMPRESAS = "gold_db.empresas_clientes"
GOLD_CLASSIFICACAO = "gold_db.classificacao_empresas"

TS = pa.timestamp("us", tz="UTC")


# ---------------------------------------------------------------- caminhos

def kb_dir(lake: str, prefixo: str = "kb_docs/empresas") -> str:
    return "{}/{}".format(lake, prefixo.rstrip("/"))


def _q(uri: str) -> str:
    return "'" + uri.replace("'", "''") + "'"


def _prepara_destino(uri: str) -> None:
    if not uri.startswith("s3://"):
        os.makedirs(os.path.dirname(uri), exist_ok=True)


# ---------------------------------------------------------------- DuckDB

def connect(s3: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.sql("SET TimeZone = 'UTC'")
    tmp = os.environ.get("TMPDIR") or "/tmp"
    con.sql("SET home_directory = {}".format(_q(tmp)))
    con.sql("SET extension_directory = {}".format(_q(tmp + "/.duckdb/extensions")))
    if s3:
        con.sql("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
        con.sql("CREATE SECRET (TYPE s3, PROVIDER credential_chain)")
    return con


# ---------------------------------------------------------------- formatacao

def formata_cnpj(cnpj: Optional[str]) -> str:
    if not cnpj or len(cnpj) != 14:
        return cnpj or "nao informado"
    return "{}.{}.{}/{}-{}".format(cnpj[:2], cnpj[2:5], cnpj[5:8], cnpj[8:12], cnpj[12:])


def formata_reais(valor) -> str:
    if valor is None:
        return "nao informado"
    s = "{:,.2f}".format(valor)
    return "R$ " + s.replace(",", "_").replace(".", ",").replace("_", ".")


def nome_arquivo(user_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", user_id)


# ---------------------------------------------------------------- documentos

def documento_empresa(e: dict) -> str:
    """Texto .md para a Knowledge Base. Sem nomes de socios (LGPD)."""
    if e.get("consultado_em") and hasattr(e["consultado_em"], "strftime"):
        consultado = e["consultado_em"].strftime("%d/%m/%Y")
    else:
        consultado = "nao informado"

    linhas = [
        "# {}".format(e.get("razao_social") or "Empresa sem razao social informada"),
        "",
    ]
    tipo = e.get("tipo_empresa")
    if tipo:
        linhas.append("- Tipo de empresa: {}".format(tipo))
    linhas += [
        "- Usuario: {}".format(e.get("user_id", "")),
        "- CNPJ: {}".format(formata_cnpj(e.get("cnpj"))),
        "- Situacao cadastral na Receita: {}".format(e.get("situacao_cadastral") or "nao informada"),
        "- Status no cadastro: {}".format(e.get("status") or ""),
        "- Capital social: {}".format(formata_reais(e.get("capital_social"))),
        "- Quantidade de socios: {}".format(
            e["qtd_socios"] if e.get("qtd_socios") is not None else "nao informada"),
        "- Dados consultados no OpenCNPJ em: {}".format(consultado),
    ]
    if e.get("cnae_principal_descricao"):
        linhas.append("- Atividade principal: {}".format(e["cnae_principal_descricao"]))
    if e.get("cnaes_secundarios_descricao"):
        linhas.append("- Atividades secundarias: {}".format(e["cnaes_secundarios_descricao"]))
    if e.get("municipio") and e.get("uf"):
        linhas.append("- Localizacao: {} - {}".format(e["municipio"], e["uf"]))
    linhas.append("")
    return "\n".join(linhas)


def metadado_empresa(e: dict) -> dict:
    """Metadado filtravel pela KB. Max 1 KB. Sem nomes de socios."""
    meta: Dict[str, object] = {
        "user_id": e.get("user_id", ""),
        "status": e.get("status") or "",
        "situacao_cadastral": e.get("situacao_cadastral") or "",
    }
    if e.get("tipo_empresa"):
        meta["tipo_empresa"] = e["tipo_empresa"]
    if e.get("uf"):
        meta["uf"] = e["uf"]
    return {"metadataAttributes": meta}


def escreve_local(uri: str, texto: str) -> None:
    _prepara_destino(uri)
    with open(uri, "w", encoding="utf-8") as f:
        f.write(texto)


def escritor_s3(s3_client) -> Callable[[str, str], None]:
    def escreve(uri: str, texto: str) -> None:
        bucket, key = uri[len("s3://"):].split("/", 1)
        tipo = "application/json" if key.endswith(".json") else "text/markdown"
        s3_client.put_object(Bucket=bucket, Key=key, Body=texto.encode("utf-8"),
                             ContentType="{};charset=utf-8".format(tipo))
    return escreve


# ---------------------------------------------------------------- etapas

def docs(catalog, lake: str,
         escreve: Callable[[str, str], None] = escreve_local,
         prefixo: str = "kb_docs/empresas") -> int:
    """
    Junta empresas_clientes e classificacao_empresas por user_id (LEFT JOIN)
    e gera um .md + .metadata.json por empresa.
    """
    empresas = catalog.load_table(GOLD_EMPRESAS).scan().to_arrow().to_pylist()

    # Classificacao pode ainda nao existir (pipeline ainda nao rodou o stage classificar).
    # O join e em Python: ler timestamps com fuso pelo DuckDB exige pytz, que o job nao tem.
    try:
        classes = {c["user_id"]: c for c in catalog.load_table(GOLD_CLASSIFICACAO).scan().to_arrow().to_pylist()}
    except Exception:
        classes = {}

    rows = []
    for e in empresas:
        c = classes.get(e["user_id"]) or {}
        tipo = c.get("tipo_empresa")
        # "indefinido" (ou marcado para revisar) nao vai para o documento: seria informacao errada
        if tipo == "indefinido" or c.get("revisar"):
            tipo = None
        rows.append({**e, "tipo_empresa": tipo, "score": c.get("score"), "revisar": c.get("revisar")})

    pasta = kb_dir(lake, prefixo)
    count = 0
    for e in rows:
        base = "{}/{}.md".format(pasta, nome_arquivo(e["user_id"]))
        escreve(base, documento_empresa(e))
        meta_json = json.dumps(metadado_empresa(e), ensure_ascii=False)
        # Verificacao de limite de 1 KB
        if len(meta_json.encode("utf-8")) > 1024:
            log.warning("metadado de %s ultrapassou 1 KB, truncando", e.get("user_id"))
            meta_json = json.dumps(
                {"metadataAttributes": {"user_id": e.get("user_id", "")}},
                ensure_ascii=False)
        escreve(base + ".metadata.json", meta_json)
        count += 1

    log.info("docs: %d documentos gravados em %s", count, pasta)
    return count


def sync(kb_id: str, ds_id: str, region: str) -> None:
    """Aciona StartIngestionJob e aguarda conclusao. Falha se a ingestao falhar."""
    import boto3
    client = boto3.client("bedrock-agent", region_name=region)
    resp = client.start_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id)
    job_id = resp["ingestionJob"]["ingestionJobId"]
    log.info("sync: ingestao iniciada job_id=%s", job_id)

    while True:
        time.sleep(15)
        job = client.get_ingestion_job(knowledgeBaseId=kb_id, dataSourceId=ds_id,
                                       ingestionJobId=job_id)["ingestionJob"]
        status = job["status"]
        log.info("sync: job_id=%s status=%s", job_id, status)
        if status == "COMPLETE":
            stats = job.get("statistics", {})
            log.info("sync: concluido %s", stats)
            return
        if status in ("FAILED", "STOPPED"):
            raise RuntimeError(
                "Ingestao {} terminou com status {}: {}".format(
                    job_id, status, job.get("failureReasons", [])))


# ---------------------------------------------------------------- entrada do job

def parse_args(argv: List[str]) -> Dict[str, str]:
    args: Dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            args[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    for obrigatorio in ("STAGE", "LAKE_URI"):
        if obrigatorio not in args:
            raise SystemExit("faltou --{}".format(obrigatorio))
    return args


def main(argv: List[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    stage, lake = args["STAGE"], args["LAKE_URI"].rstrip("/")
    region = (args.get("REGION")
              or os.environ.get("AWS_REGION")
              or os.environ.get("AWS_DEFAULT_REGION"))
    prefixo = args.get("PREFIXOS", "kb_docs/empresas").split(",")[0].rstrip("/")

    import boto3
    from pyiceberg.catalog import load_catalog
    catalog = load_catalog("glue", **{"type": "glue", "glue.region": region,
                                      "client.region": region, "s3.region": region})

    if stage == "docs":
        docs(catalog, lake,
             escritor_s3(boto3.client("s3", region_name=region)), prefixo)
    elif stage == "sync":
        kb_id = args.get("KB_ID", "")
        ds_id = args.get("DS_ID", "")
        if not kb_id or not ds_id:
            raise SystemExit("--KB_ID e --DS_ID sao obrigatorios para --STAGE sync")
        sync(kb_id, ds_id, region)
    else:
        raise SystemExit("--STAGE desconhecido: {}".format(stage))


if __name__ == "__main__":
    main(sys.argv[1:])
