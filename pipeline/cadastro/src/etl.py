"""
Lakehouse da tabela usuarios-cnpj (DynamoDB do stack cnpj-cadastro).

Um script com várias etapas, escolhidas por --STAGE:

    landing  export do DynamoDB (.json.gz)  -> Parquet, item cru como JSON
    bronze   Landing                         -> Parquet tipado (usuarios_cnpj e socios)
    silver   Bronze                          -> Iceberg, upsert por user_id + checagens
    gold     Silver                          -> Iceberg (empresas_clientes, cadastros_por_status)
    kb_docs  Gold                            -> um .md por empresa para a Bedrock Knowledge Base

Roda como job AWS Glue Python Shell (Python 3.9). O DuckDB é a engine de
processamento e o PyIceberg grava as tabelas Iceberg no Glue Data Catalog.
Os caminhos funcionam com s3:// (no Glue) e com pastas locais (nos testes).

Argumentos (formato do Glue: --CHAVE valor):
    --STAGE       landing | bronze | silver | gold | kb_docs
    --LAKE_URI    s3://bucket-do-lake  (ou pasta local)
    --RUN_DATE    AAAA-MM-DD
    --EXPORT_ARN  ARN do export do DynamoDB (só na landing)
    --REGION      região AWS
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from typing import Callable, Dict, List, Optional

import duckdb
import pyarrow as pa

log = logging.getLogger("etl")

# "processando": organização criada pelo POST /cadastro, consulta ainda não terminou
STATUS_VALIDOS = ("ativa", "inativa", "nao_encontrado", "cnpj_invalido", "processando")

SILVER_USUARIOS = "silver_db.usuarios_cnpj"
SILVER_SOCIOS = "silver_db.socios"
GOLD_EMPRESAS = "gold_db.empresas_clientes"
GOLD_STATUS = "gold_db.cadastros_por_status"

TS = pa.timestamp("us", tz="UTC")

SCHEMAS: Dict[str, pa.Schema] = {
    SILVER_USUARIOS: pa.schema([
        ("user_id", pa.string()),
        ("cnpj", pa.string()),
        ("status", pa.string()),
        ("consultado_em", TS),
        ("razao_social", pa.string()),
        ("situacao_cadastral", pa.string()),
        ("capital_social", pa.decimal128(20, 2)),
        ("qtd_socios", pa.int32()),
        ("empresa_raw", pa.string()),
        ("_row_hash", pa.string()),
        ("_ingested_at", TS),
        ("_carga_dt", pa.string()),
    ]),
    SILVER_SOCIOS: pa.schema([
        ("user_id", pa.string()),
        ("cnpj", pa.string()),
        ("nome_socio", pa.string()),
        ("socio_raw", pa.string()),
        ("_carga_dt", pa.string()),
    ]),
    GOLD_EMPRESAS: pa.schema([
        ("user_id", pa.string()),
        ("cnpj", pa.string()),
        ("razao_social", pa.string()),
        ("situacao_cadastral", pa.string()),
        ("status", pa.string()),
        ("capital_social", pa.decimal128(20, 2)),
        ("qtd_socios", pa.int32()),
        ("consultado_em", TS),
    ]),
    GOLD_STATUS: pa.schema([
        ("dia", pa.date32()),
        ("status", pa.string()),
        ("cadastros", pa.int64()),
    ]),
}


class QualidadeError(Exception):
    """A carga não passou nas checagens da Silver. O job falha e a Gold não roda."""


# ---------------------------------------------------------------- caminhos

def landing_uri(lake: str, dt: str) -> str:
    return f"{lake}/landing/usuarios_cnpj/dt={dt}/data.parquet"


def bronze_uri(lake: str, tabela: str, dt: str) -> str:
    return f"{lake}/bronze/{tabela}/dt={dt}/data.parquet"


def kb_dir(lake: str) -> str:
    return f"{lake}/kb_docs/empresas"


def _q(uri: str) -> str:
    """Literal SQL seguro para um caminho."""
    return "'" + uri.replace("'", "''") + "'"


def _prepara_destino(uri: str) -> None:
    if not uri.startswith("s3://"):
        os.makedirs(os.path.dirname(uri), exist_ok=True)


# ---------------------------------------------------------------- DuckDB

def connect(s3: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.sql("SET TimeZone = 'UTC'")

    # No Glue Python Shell o HOME e "/", que nao e gravavel. O DuckDB guarda as
    # extensoes em $HOME/.duckdb e morreria com
    # 'IO Error: Failed to create directory "/.duckdb/"'. Aponta para o temporario.
    tmp = os.environ.get("TMPDIR") or "/tmp"
    con.sql(f"SET home_directory = {_q(tmp)}")
    con.sql(f"SET extension_directory = {_q(tmp + '/.duckdb/extensions')}")

    if s3:
        con.sql("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
        con.sql("CREATE SECRET (TYPE s3, PROVIDER credential_chain)")
    return con


def _arrow(con: duckdb.DuckDBPyConnection, sql: str, schema: pa.Schema) -> pa.Table:
    """Executa a consulta e devolve Arrow com exatamente o esquema da tabela Iceberg."""
    return con.sql(sql).fetch_arrow_table().select(schema.names).cast(schema)


# ---------------------------------------------------------------- etapas

def resolve_export_data_uri(ddb_client, export_arn: str) -> str:
    """Pasta data/ de um export DynamoDB concluído."""
    d = ddb_client.describe_export(ExportArn=export_arn)["ExportDescription"]
    if d["ExportStatus"] != "COMPLETED":
        raise RuntimeError(f"export {export_arn} está {d['ExportStatus']}")
    base = d["ExportManifest"].rsplit("/", 1)[0]  # .../AWSDynamoDB/<id>/manifest-summary.json
    return f"s3://{d['S3Bucket']}/{base}/data"


def landing(con: duckdb.DuckDBPyConnection, export_data_uri: str, lake: str, dt: str) -> int:
    """Item cru do DynamoDB como JSON. O campo empresa muda de item para item,
    então nada de inferir esquema aqui."""
    out = landing_uri(lake, dt)
    _prepara_destino(out)
    con.sql(f"""
        COPY (
          SELECT Item AS item,
                 now() AS _ingested_at,
                 'dynamodb:usuarios-cnpj' AS _source
          FROM read_json({_q(export_data_uri + '/*.json.gz')},
                         format = 'newline_delimited',
                         columns = {{'Item': 'JSON'}})
        ) TO {_q(out)} (FORMAT parquet, COMPRESSION snappy)
    """)
    n = con.sql(f"SELECT count(*) FROM read_parquet({_q(out)})").fetchone()[0]
    log.info("landing %s: %d itens", dt, n)
    return n


# Na tabela única do cadastro (api/cnpj-cadastro/src/dados.py) só a organização tem os
# dados da empresa: o vínculo do usuário (<sub>, com `papel`) e o convite (CONVITE#<email>)
# ficam de fora. Itens antigos, de antes das organizações, continuam entrando.
SO_EMPRESAS = ("(item->'$.papel') IS NULL "
               "AND NOT starts_with(coalesce((item->>'$.user_id.S'), ''), 'CONVITE#')")


def bronze(con: duckdb.DuckDBPyConnection, lake: str, dt: str) -> Dict[str, int]:
    src = _q(landing_uri(lake, dt))
    out_u = bronze_uri(lake, "usuarios_cnpj", dt)
    out_s = bronze_uri(lake, "socios", dt)
    _prepara_destino(out_u)
    _prepara_destino(out_s)

    con.sql(f"""
        COPY (
          SELECT
            item->>'$.user_id.S'                                  AS user_id,
            item->>'$.cnpj.S'                                     AS cnpj,
            item->>'$.status.S'                                   AS status,
            CAST(item->>'$.consultado_em.S' AS TIMESTAMPTZ)       AS consultado_em,
            item->>'$.empresa.M.razao_social.S'                   AS razao_social,
            item->>'$.empresa.M.situacao_cadastral.S'             AS situacao_cadastral,
            TRY_CAST(replace(replace(
              item->>'$.empresa.M.capital_social.S', '.', ''), ',', '.')
              AS DECIMAL(20,2))                                   AS capital_social,
            CAST(json_array_length(item->'$.empresa.M.QSA.L') AS INTEGER) AS qtd_socios,
            CAST(item->'$.empresa' AS VARCHAR)                    AS empresa_raw,
            md5(CAST(item AS VARCHAR))                            AS _row_hash,
            _ingested_at
          FROM read_parquet({src})
          WHERE {SO_EMPRESAS}
        ) TO {_q(out_u)} (FORMAT parquet, COMPRESSION zstd)
    """)
    con.sql(f"""
        COPY (
          SELECT item->>'$.user_id.S'           AS user_id,
                 item->>'$.cnpj.S'              AS cnpj,
                 socio->>'$.M.nome_socio.S'     AS nome_socio,
                 CAST(socio->'$.M' AS VARCHAR)  AS socio_raw
          FROM read_parquet({src}),
               UNNEST(CAST(item->'$.empresa.M.QSA.L' AS JSON[])) AS t(socio)
          WHERE {SO_EMPRESAS}
        ) TO {_q(out_s)} (FORMAT parquet, COMPRESSION zstd)
    """)
    n = {
        "usuarios_cnpj": con.sql(f"SELECT count(*) FROM read_parquet({_q(out_u)})").fetchone()[0],
        "socios": con.sql(f"SELECT count(*) FROM read_parquet({_q(out_s)})").fetchone()[0],
    }
    log.info("bronze %s: %s", dt, n)
    return n


def _location(lake: str, ident: str) -> Optional[str]:
    if not lake.startswith("s3://"):
        return None  # catálogo local decide a pasta
    db, tabela = ident.split(".")
    return f"{lake}/{db.replace('_db', '')}/{tabela}"


def ensure_table(catalog, ident: str, lake: str):
    ns = ident.split(".")[0]
    if (ns,) not in catalog.list_namespaces():
        catalog.create_namespace(ns)  # no Glue o database já vem do template
    return catalog.create_table_if_not_exists(
        ident, schema=SCHEMAS[ident], location=_location(lake, ident))


def checar_qualidade(con: duckdb.DuckDBPyConnection, novos: pa.Table) -> None:
    con.register("novos_q", novos)
    validos = ", ".join(f"'{s}'" for s in STATUS_VALIDOS)
    sem_chave, chave_dup, status_ruim, cnpj_ruim = con.sql(f"""
        SELECT count(*) FILTER (WHERE user_id IS NULL),
               count(*) - count(DISTINCT user_id),
               count(*) FILTER (WHERE status IS NULL OR status NOT IN ({validos})),
               count(*) FILTER (WHERE cnpj IS NOT NULL AND length(cnpj) <> 14)
        FROM novos_q
    """).fetchone()
    con.unregister("novos_q")
    if sem_chave or chave_dup or status_ruim or cnpj_ruim:
        raise QualidadeError(
            f"sem_chave={sem_chave} chave_duplicada={chave_dup} "
            f"status_invalido={status_ruim} cnpj_tamanho_errado={cnpj_ruim}")


def silver(con: duckdb.DuckDBPyConnection, catalog, lake: str, dt: str) -> Dict[str, int]:
    from pyiceberg.expressions import In

    novos = _arrow(con, f"""
        SELECT * EXCLUDE (rn), '{dt}' AS _carga_dt FROM (
          SELECT *, row_number() OVER (
                   PARTITION BY user_id ORDER BY consultado_em DESC) AS rn
          FROM read_parquet({_q(bronze_uri(lake, 'usuarios_cnpj', dt))})
        ) WHERE rn = 1
    """, SCHEMAS[SILVER_USUARIOS])
    checar_qualidade(con, novos)
    if novos.num_rows == 0:
        log.info("silver %s: carga vazia, nada a fazer", dt)
        return {"usuarios_cnpj": 0, "socios": 0}

    usuarios = ensure_table(catalog, SILVER_USUARIOS, lake)
    usuarios.upsert(novos, join_cols=["user_id"])

    # A lista de sócios de um usuário pode mudar inteira: apaga e insere de novo.
    socios_novos = _arrow(con, f"""
        SELECT *, '{dt}' AS _carga_dt
        FROM read_parquet({_q(bronze_uri(lake, 'socios', dt))})
    """, SCHEMAS[SILVER_SOCIOS])
    socios = ensure_table(catalog, SILVER_SOCIOS, lake)
    socios.delete(In("user_id", novos.column("user_id").to_pylist()))
    if socios_novos.num_rows:
        socios.append(socios_novos)

    n = {"usuarios_cnpj": novos.num_rows, "socios": socios_novos.num_rows}
    log.info("silver %s: %s", dt, n)
    return n


def gold(con: duckdb.DuckDBPyConnection, catalog, lake: str) -> Dict[str, int]:
    usuarios = catalog.load_table(SILVER_USUARIOS).scan().to_arrow()
    con.register("usuarios", usuarios)

    empresas = _arrow(con, """
        SELECT user_id, cnpj, razao_social, situacao_cadastral, status,
               capital_social, qtd_socios, consultado_em
        FROM usuarios
        WHERE status IN ('ativa', 'inativa')
        ORDER BY user_id
    """, SCHEMAS[GOLD_EMPRESAS])
    por_status = _arrow(con, """
        SELECT CAST(consultado_em AS DATE) AS dia, status, count(*) AS cadastros
        FROM usuarios
        GROUP BY ALL
        ORDER BY dia, status
    """, SCHEMAS[GOLD_STATUS])
    con.unregister("usuarios")

    # Volume pequeno (um item por usuário): recalcular tudo é mais simples e seguro.
    ensure_table(catalog, GOLD_EMPRESAS, lake).overwrite(empresas)
    ensure_table(catalog, GOLD_STATUS, lake).overwrite(por_status)

    n = {"empresas_clientes": empresas.num_rows, "cadastros_por_status": por_status.num_rows}
    log.info("gold: %s", n)
    return n


# ---------------------------------------------------------------- docs da KB

def formata_cnpj(cnpj: Optional[str]) -> str:
    if not cnpj or len(cnpj) != 14:
        return cnpj or "não informado"
    return f"{cnpj[:2]}.{cnpj[2:5]}.{cnpj[5:8]}/{cnpj[8:12]}-{cnpj[12:]}"


def formata_reais(valor) -> str:
    if valor is None:
        return "não informado"
    s = f"{valor:,.2f}"
    return "R$ " + s.replace(",", "_").replace(".", ",").replace("_", ".")


def nome_arquivo(user_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]", "_", user_id)


def documento_empresa(e: dict) -> str:
    """Texto que a Knowledge Base indexa. Sem nomes de sócios (LGPD)."""
    consultado = e["consultado_em"].strftime("%d/%m/%Y") if e["consultado_em"] else "não informado"
    linhas = [
        f"# {e['razao_social'] or 'Empresa sem razão social informada'}",
        "",
        f"- Usuário: {e['user_id']}",
        f"- CNPJ: {formata_cnpj(e['cnpj'])}",
        f"- Situação cadastral na Receita: {e['situacao_cadastral'] or 'não informada'}",
        f"- Status no cadastro: {e['status']}",
        f"- Capital social: {formata_reais(e['capital_social'])}",
        f"- Quantidade de sócios: {e['qtd_socios'] if e['qtd_socios'] is not None else 'não informada'}",
        f"- Dados consultados no OpenCNPJ em: {consultado}",
        "",
    ]
    return "\n".join(linhas)


def escreve_local(uri: str, texto: str) -> None:
    _prepara_destino(uri)
    with open(uri, "w", encoding="utf-8") as f:
        f.write(texto)


def escritor_s3(s3_client) -> Callable[[str, str], None]:
    def escreve(uri: str, texto: str) -> None:
        bucket, key = uri[len("s3://"):].split("/", 1)
        tipo = "application/json" if key.endswith(".json") else "text/markdown"
        s3_client.put_object(Bucket=bucket, Key=key, Body=texto.encode("utf-8"),
                             ContentType=f"{tipo}; charset=utf-8")
    return escreve


def kb_docs(catalog, lake: str, escreve: Callable[[str, str], None] = escreve_local) -> int:
    empresas = catalog.load_table(GOLD_EMPRESAS).scan().to_arrow().to_pylist()
    pasta = kb_dir(lake)
    for e in empresas:
        base = f"{pasta}/{nome_arquivo(e['user_id'])}.md"
        escreve(base, documento_empresa(e))
        escreve(base + ".metadata.json", json.dumps({"metadataAttributes": {
            "user_id": e["user_id"],
            "status": e["status"],
            "situacao_cadastral": e["situacao_cadastral"] or "",
        }}, ensure_ascii=False))
    log.info("kb_docs: %d documentos", len(empresas))
    return len(empresas)


# ---------------------------------------------------------------- entrada do job

def parse_args(argv: List[str]) -> Dict[str, str]:
    """Lê pares --CHAVE valor (formato que o Glue passa ao script)."""
    args, i = {}, 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            args[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    for obrigatorio in ("STAGE", "LAKE_URI"):
        if obrigatorio not in args:
            raise SystemExit(f"faltou --{obrigatorio}")
    if args["STAGE"] in ("landing", "bronze", "silver"):
        if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args.get("RUN_DATE", "")):
            raise SystemExit("--RUN_DATE precisa ser AAAA-MM-DD")
    if args["STAGE"] == "landing" and "EXPORT_ARN" not in args:
        raise SystemExit("faltou --EXPORT_ARN")
    return args


def main(argv: List[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    stage, lake = args["STAGE"], args["LAKE_URI"].rstrip("/")
    region = args.get("REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")

    import boto3
    from pyiceberg.catalog import load_catalog

    con = connect(s3=lake.startswith("s3://"))
    catalog = load_catalog("glue", **{"type": "glue", "glue.region": region,
                                      "client.region": region, "s3.region": region})

    if stage == "landing":
        data_uri = resolve_export_data_uri(boto3.client("dynamodb", region_name=region),
                                           args["EXPORT_ARN"])
        landing(con, data_uri, lake, args["RUN_DATE"])
    elif stage == "bronze":
        bronze(con, lake, args["RUN_DATE"])
    elif stage == "silver":
        silver(con, catalog, lake, args["RUN_DATE"])
    elif stage == "gold":
        gold(con, catalog, lake)
    elif stage == "kb_docs":
        kb_docs(catalog, lake, escritor_s3(boto3.client("s3", region_name=region)))
    else:
        raise SystemExit(f"--STAGE desconhecido: {stage}")


if __name__ == "__main__":
    main(sys.argv[1:])
