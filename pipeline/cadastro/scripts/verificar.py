"""
Confere o lake depois de uma execução do pipeline, sem depender do Athena.

Lê as mesmas fontes que o Athena leria: os Parquet da Landing/Bronze pelo DuckDB
e as tabelas Iceberg da Silver/Gold pelo PyIceberg no Glue Data Catalog. Serve
para validar a primeira execução e para conferir um reprocessamento.

    uv run python scripts/verificar.py --stack lakehouse-pipeline --data 2026-11-07

Compara também a contagem da Silver com a da tabela DynamoDB de origem, que é a
checagem que o CONTEXTO.md pede.
"""

from __future__ import annotations

import argparse
import sys

import boto3

sys.path.insert(0, "src")

import etl  # noqa: E402


def saida_do_stack(cfn, stack: str, chave: str) -> str:
    saidas = cfn.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]
    for s in saidas:
        if s["OutputKey"] == chave:
            return s["OutputValue"]
    raise SystemExit(f"o stack {stack} não tem o output {chave}")


def conta_parquet(con, uri: str) -> int:
    try:
        return con.sql(f"SELECT count(*) FROM read_parquet({etl._q(uri)})").fetchone()[0]
    except Exception as e:  # noqa: BLE001
        print(f"  !! não deu para ler {uri}: {e}")
        return -1


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stack", default="lakehouse-pipeline")
    p.add_argument("--data", required=True, help="AAAA-MM-DD da execução")
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--tabela-dynamo", default=None,
                   help="nome da tabela de origem, para comparar a contagem")
    args = p.parse_args()

    cfn = boto3.client("cloudformation", region_name=args.region)
    lake = "s3://" + saida_do_stack(cfn, args.stack, "LakeBucketName")
    dt = args.data
    print(f"lake: {lake}\ndata: {dt}\n")

    con = etl.connect(s3=True)
    from pyiceberg.catalog import load_catalog
    catalog = load_catalog("glue", **{"type": "glue", "glue.region": args.region,
                                      "client.region": args.region, "s3.region": args.region})

    problemas = []

    print("Landing e Bronze (Parquet)")
    landing_n = conta_parquet(con, etl.landing_uri(lake, dt))
    bronze_u = conta_parquet(con, etl.bronze_uri(lake, "usuarios_cnpj", dt))
    bronze_s = conta_parquet(con, etl.bronze_uri(lake, "socios", dt))
    print(f"  landing.usuarios_cnpj   {landing_n}")
    print(f"  bronze.usuarios_cnpj    {bronze_u}")
    print(f"  bronze.socios           {bronze_s}")
    if landing_n <= 0:
        problemas.append("a Landing está vazia")
    if landing_n != bronze_u:
        problemas.append(f"Landing ({landing_n}) e Bronze ({bronze_u}) têm contagens diferentes")

    print("\nSilver e Gold (Iceberg)")
    contagens = {}
    for ident in (etl.SILVER_USUARIOS, etl.SILVER_SOCIOS, etl.GOLD_EMPRESAS, etl.GOLD_STATUS):
        try:
            t = catalog.load_table(ident).scan().to_arrow()
            contagens[ident] = t.num_rows
            print(f"  {ident:<32} {t.num_rows}")
        except Exception as e:  # noqa: BLE001
            print(f"  {ident:<32} !! {e}")
            problemas.append(f"não deu para ler {ident}")

    silver_n = contagens.get(etl.SILVER_USUARIOS)
    if silver_n == 0:
        problemas.append("a Silver está vazia")

    print("\nStatus na Bronze do dia")
    try:
        for status, n in con.sql(f"""
            SELECT status, count(*) FROM read_parquet({etl._q(etl.bronze_uri(lake, 'usuarios_cnpj', dt))})
            GROUP BY 1 ORDER BY 1
        """).fetchall():
            print(f"  {status:<20} {n}")
    except Exception as e:  # noqa: BLE001
        print(f"  !! {e}")

    print("\nDocumentos da Knowledge Base")
    s3 = boto3.client("s3", region_name=args.region)
    bucket = lake[len("s3://"):]
    pagina = s3.list_objects_v2(Bucket=bucket, Prefix="kb_docs/empresas/")
    md = [o["Key"] for o in pagina.get("Contents", []) if o["Key"].endswith(".md")]
    meta = [o["Key"] for o in pagina.get("Contents", []) if o["Key"].endswith(".metadata.json")]
    print(f"  {len(md)} .md e {len(meta)} .metadata.json em s3://{bucket}/kb_docs/empresas/")
    empresas_n = contagens.get(etl.GOLD_EMPRESAS)
    if empresas_n is not None and len(md) != empresas_n:
        problemas.append(f"gold.empresas_clientes tem {empresas_n} linhas mas há {len(md)} documentos")
    if md:
        corpo = s3.get_object(Bucket=bucket, Key=md[0])["Body"].read().decode("utf-8")
        print(f"\n  exemplo ({md[0]}):")
        for linha in corpo.splitlines():
            print(f"    {linha}")

    if args.tabela_dynamo:
        print("\nComparação com o DynamoDB")
        ddb = boto3.client("dynamodb", region_name=args.region)
        origem = ddb.scan(TableName=args.tabela_dynamo, Select="COUNT")["Count"]
        print(f"  origem {origem}  x  silver {silver_n}")
        if silver_n is not None and origem != silver_n:
            problemas.append(f"DynamoDB tem {origem} itens e a Silver tem {silver_n}")

    print()
    if problemas:
        print("PROBLEMAS:")
        for pr in problemas:
            print(f"  - {pr}")
        return 1
    print("Tudo conferido.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
