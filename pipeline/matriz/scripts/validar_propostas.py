"""
Passa arquivos de proposta (ex.: a saída de ia/propostas/simular.py) pelo bronze e pelo silver do
ETL da matriz, localmente, e mostra o que entraria válido e o que iria para a quarentena.

    uv run python matriz/scripts/validar_propostas.py /tmp/sim/landing/matriz/propostas_llm

Os perfis vêm do cadastro (DynamoDB, só leitura); a matriz da Aurora (fixtures/aurora/matriz.csv)
entra como importada do KALMANTESTE100, para as alterações terem alvo. Nada é gravado na AWS.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sys
import tempfile
from datetime import datetime
from decimal import Decimal
from pathlib import Path

import boto3
from pyiceberg.catalog.sql import SqlCatalog

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "src"))
import etl_matriz as etl  # noqa: E402


def main():
    p = argparse.ArgumentParser()
    p.add_argument("pasta", type=Path, help="pasta com <data>/<arquivo>.json (como landing/matriz/propostas_llm)")
    p.add_argument("--tabela", default="cnpj-cadastro-UsuariosCnpjTable-14MB1HKZY61SQ")
    p.add_argument("--regiao", default="us-east-1")
    args = p.parse_args()

    tmp = Path(tempfile.mkdtemp())
    lake = str(tmp / "lake")
    catalog = SqlCatalog("v", uri=f"sqlite:///{tmp}/c.db", warehouse=f"file://{tmp}/wh")
    itens = boto3.resource("dynamodb", region_name=args.regiao).Table(args.tabela).scan()["Items"]
    itens = json.loads(json.dumps(itens, default=lambda x: int(x) if isinstance(x, Decimal) and x == int(x) else float(x)),
                       parse_float=Decimal)
    print("perfis exportados:", etl.exportar_perfis([i for i in itens if str(i.get("user_id", "")).startswith("CNPJ#")],
                                                    lake, "2026-11-08"))
    alvo = Path(etl.landing(lake, "importada", "KALMANTESTE100", "matriz.csv"))
    alvo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(AQUI.parent / "fixtures/aurora/matriz.csv", alvo)
    for arq in sorted(args.pasta.glob("*/*.json")):
        destino = Path(etl.landing(lake, "propostas_llm", arq.parent.name, arq.name))
        destino.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy(arq, destino)

    con = etl.connect()
    print("bronze:", etl.bronze(con, catalog, lake, datetime(2026, 11, 8, 6)))
    print("silver:", etl.silver(catalog, lake))
    cands = [c for c in catalog.load_table(etl.SILVER_CANDIDATAS).scan().to_arrow().to_pylist() if c["origem"] == "llm"]
    validas = [c for c in cands if c["valida"]]
    print(f"\npropostas do LLM: {len(cands)}  válidas: {len(validas)}  quarentena: {len(cands) - len(validas)}")
    for c in cands:
        print(f"  {'OK ' if c['valida'] else 'QUARENTENA'} {c['cnpj']:15s} {c['mudanca']:9s} {c['obrigacao_id']:12s} "
              f"{(c['titulo'] or '')[:60]:60s} {'; '.join(c['erros'] or [])}")
    print("gold:", etl.gold(catalog, lake))
    obs = [o for o in catalog.load_table(etl.GOLD_OBRIGACOES).scan().to_arrow().to_pylist() if o["status"] == "proposta"]
    print(f"obrigações com status proposta na gold: {len(obs)}")


if __name__ == "__main__":
    main()
