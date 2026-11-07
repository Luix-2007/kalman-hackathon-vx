"""
Confere o lake dos atos do DOU depois de uma execução, sem depender do Athena.

Lê o Parquet da Landing pelo DuckDB e as tabelas Iceberg da Bronze/Prata/Ouro
pelo PyIceberg no Glue Data Catalog.

    uv run python scripts/verificar.py --ano 2026 --mes 11
"""

from __future__ import annotations

import argparse
import sys

import boto3

sys.path.insert(0, "src")

import etl_dou  # noqa: E402


def saida_do_stack(cfn, stack: str, chave: str) -> str:
    for s in cfn.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]:
        if s["OutputKey"] == chave:
            return s["OutputValue"]
    raise SystemExit(f"o stack {stack} não tem o output {chave}")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--stack", default="lakehouse-pipeline",
                   help="stack que tem o bucket do lake")
    p.add_argument("--ano", required=True)
    p.add_argument("--mes", required=True)
    p.add_argument("--secao", default="1")
    p.add_argument("--region", default="us-east-1")
    args = p.parse_args()

    ano_mes = f"{int(args.ano)}-{int(args.mes):02d}"
    secao = int(args.secao)

    cfn = boto3.client("cloudformation", region_name=args.region)
    lake = "s3://" + saida_do_stack(cfn, args.stack, "LakeBucketName")
    print(f"lake: {lake}\nmês: {ano_mes}  seção: {secao}\n")

    con = etl_dou.connect(s3=True)
    from pyiceberg.catalog import load_catalog
    catalog = load_catalog("glue", **{"type": "glue", "glue.region": args.region,
                                      "client.region": args.region, "s3.region": args.region})

    problemas = []

    print("Landing (Parquet)")
    glob = f"{etl_dou.landing_dir(lake, ano_mes, secao)}/*.parquet"
    landing_n = -1
    try:
        landing_n = con.sql(
            f"SELECT count(*) FROM read_parquet({etl_dou._q(glob)})").fetchone()[0]
        print(f"  landing_db.dou_xml       {landing_n}")
    except Exception as e:  # noqa: BLE001
        print(f"  !! não deu para ler {glob}: {e}")
        problemas.append("a Landing do mês não foi lida")
    if landing_n == 0:
        problemas.append("a Landing está vazia")

    print("\nBronze, Prata e Ouro (Iceberg)")
    contagens = {}
    for ident in (etl_dou.BRONZE_XML, etl_dou.PRATA_ATOS, etl_dou.OURO_RESUMO):
        try:
            n = catalog.load_table(ident).scan().to_arrow().num_rows
            contagens[ident] = n
            print(f"  {ident:<28} {n}")
        except Exception as e:  # noqa: BLE001
            print(f"  {ident:<28} !! {e}")
            problemas.append(f"não deu para ler {ident}")

    bronze_n = contagens.get(etl_dou.BRONZE_XML)
    if landing_n > 0 and bronze_n is not None and bronze_n < landing_n:
        problemas.append(f"a Bronze ({bronze_n}) tem menos linhas que a Landing do mês ({landing_n})")
    if contagens.get(etl_dou.PRATA_ATOS) == 0:
        problemas.append("a Prata está vazia")

    print("\nResumo mensal da Ouro")
    try:
        resumo = catalog.load_table(etl_dou.OURO_RESUMO).scan().to_arrow().to_pylist()
        for r in sorted(resumo, key=lambda x: x["ano_mes"]):
            print(f"  {r['ano_mes']}  atos={r['atos']}  aneel={r['atos_aneel']}"
                  f"  de={r['de']}  ate={r['ate']}")
        if not any(r["ano_mes"] == ano_mes for r in resumo):
            problemas.append(f"a Ouro não tem linha para {ano_mes}")
    except Exception as e:  # noqa: BLE001
        print(f"  !! {e}")

    print("\nTipos de ato mais comuns na Prata")
    try:
        atos = catalog.load_table(etl_dou.PRATA_ATOS).scan(
            selected_fields=("tipo", "orgao", "ano_mes")).to_arrow()
        con.register("atos", atos)
        for tipo, n in con.sql("""
            SELECT coalesce(tipo, '(sem tipo)'), count(*) FROM atos
            GROUP BY 1 ORDER BY 2 DESC LIMIT 8
        """).fetchall():
            print(f"  {tipo:<40} {n}")
        con.unregister("atos")
    except Exception as e:  # noqa: BLE001
        print(f"  !! {e}")

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
