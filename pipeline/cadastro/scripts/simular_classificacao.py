"""
Roda as etapas embeddings e classificar do ETL com o Titan de verdade, sem gravar nada na AWS:
as empresas vêm do cadastro (DynamoDB, só leitura), a gold e os índices ficam em memória/pasta local.

    uv run python cadastro/scripts/simular_classificacao.py --saida /tmp/classificacao.json

Serve para conferir a taxonomia (config/tipos_empresa.json) e os limiares antes do deploy.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from decimal import Decimal

import boto3
from pyiceberg.catalog.sql import SqlCatalog

AQUI = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(AQUI, "..", "src"))
import etl  # noqa: E402


class StoreMemoria:
    def __init__(self):
        self.v = {}

    def get_vectors(self, keys):
        return {k: ({"metadata": self.v[k]["metadata"]} if k in self.v else None) for k in keys}

    def get_vector_data(self, key):
        return self.v[key]["data"] if key in self.v else None

    def put_vectors(self, itens):
        for it in itens:
            self.v[it["key"]] = it

    def delete_vectors(self, keys):
        for k in keys:
            self.v.pop(k, None)

    def list_keys(self):
        return list(self.v)

    def query(self, vetor, top_k, index_name=None):
        sims = sorted(((sum(a * b for a, b in zip(vetor, x["data"])), k) for k, x in self.v.items()), reverse=True)
        return [{"key": k, "distance": 1 - s, "metadata": self.v[k].get("metadata", {})} for s, k in sims[:top_k]]


def empresa_do_item(item: dict) -> dict:
    """O que o bronze e a gold tiram do item da organização (mesmos campos do etl.bronze)."""
    e = item.get("empresa") or {}
    cnaes = e.get("cnaes") or []
    principal = next((c for c in cnaes if c.get("is_principal")), {})
    secundarias = "; ".join(c.get("descricao", "") for c in cnaes if not c.get("is_principal"))
    return {"user_id": item["user_id"], "cnpj": item.get("cnpj"), "razao_social": e.get("razao_social"),
            "situacao_cadastral": e.get("situacao_cadastral"), "status": item.get("status"),
            "capital_social": None, "qtd_socios": None, "consultado_em": None,
            "cnae_principal": principal.get("codigo"), "cnae_principal_descricao": principal.get("descricao"),
            "cnaes_secundarios_descricao": secundarias or None, "nome_fantasia": e.get("nome_fantasia"),
            "natureza_juridica": e.get("natureza_juridica"), "porte_empresa": e.get("porte_empresa"),
            "uf": e.get("uf"), "municipio": e.get("municipio")}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--saida", required=True)
    p.add_argument("--tabela", default="cnpj-cadastro-UsuariosCnpjTable-14MB1HKZY61SQ")
    p.add_argument("--limiar", type=float, default=0.30)
    p.add_argument("--margem", type=float, default=0.02)
    p.add_argument("--regiao", default="us-east-1")
    args = p.parse_args()

    itens = boto3.resource("dynamodb", region_name=args.regiao).Table(args.tabela).scan()["Items"]
    itens = json.loads(json.dumps(itens, default=lambda x: float(x) if isinstance(x, Decimal) else str(x)))
    empresas = [empresa_do_item(i) for i in itens if str(i.get("user_id", "")).startswith("CNPJ#") and i.get("empresa")]

    tmp = tempfile.mkdtemp()
    catalog = SqlCatalog("sim", uri=f"sqlite:///{tmp}/c.db", warehouse=f"file://{tmp}/wh")
    catalog.create_namespace("gold_db")
    etl.ensure_table(catalog, etl.GOLD_EMPRESAS, tmp).overwrite(
        etl.pa.Table.from_pylist(empresas, schema=etl.SCHEMAS[etl.GOLD_EMPRESAS]))

    taxonomia = etl.carregar_taxonomia(os.path.join(AQUI, "..", "config", "tipos_empresa.json"))
    store, ref = StoreMemoria(), StoreMemoria()
    print("embeddings:", etl.embeddings(catalog, tmp, etl.BedrockTitanEmbedder(args.regiao), store, ref, taxonomia))
    etl.classificar(catalog, tmp, store, ref, taxonomia, args.limiar, args.margem)
    linhas = catalog.load_table(etl.GOLD_CLASSIFICACAO).scan().to_arrow().to_pylist()
    resultado = []
    for r in linhas:
        e = next(x for x in empresas if x["user_id"] == r["user_id"])
        resultado.append({"cnpj": e["cnpj"], "razao_social": e["razao_social"], "cnae": e["cnae_principal_descricao"],
                          "tipo_empresa": r["tipo_empresa"], "score": round(r["score"], 3),
                          "segundo_tipo": r["segundo_tipo"], "margem": round(r["margem"], 3), "revisar": r["revisar"]})
        print(json.dumps(resultado[-1], ensure_ascii=False))
    with open(args.saida, "w", encoding="utf-8") as f:
        json.dump(resultado, f, ensure_ascii=False, indent=2)


if __name__ == "__main__":
    main()
