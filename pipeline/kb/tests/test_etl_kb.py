"""
Documentos da Knowledge Base (stack lakehouse-kb), em pastas locais e catálogo em SQLite.

Os documentos saíram do ETL do cadastro (etapa kb_docs) para este job, que também junta a
classificação das empresas. As regras de antes continuam: nada de nomes de sócios (LGPD).
"""

import json
import os
import sys
from datetime import datetime, timezone
from decimal import Decimal

import pyarrow as pa
import pytest
from pyiceberg.catalog.sql import SqlCatalog

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "src"))
import etl_kb  # noqa: E402

SCHEMA_EMPRESAS = pa.schema([
    ("user_id", pa.string()), ("cnpj", pa.string()), ("razao_social", pa.string()),
    ("situacao_cadastral", pa.string()), ("status", pa.string()), ("capital_social", pa.decimal128(20, 2)),
    ("qtd_socios", pa.int32()), ("consultado_em", pa.timestamp("us", tz="UTC")),
    ("cnae_principal", pa.string()), ("cnae_principal_descricao", pa.string()),
    ("cnaes_secundarios_descricao", pa.string()), ("nome_fantasia", pa.string()),
    ("natureza_juridica", pa.string()), ("porte_empresa", pa.string()), ("uf", pa.string()), ("municipio", pa.string()),
])
SCHEMA_CLASSIFICACAO = pa.schema([
    ("user_id", pa.string()), ("tipo_empresa", pa.string()), ("score", pa.float32()), ("segundo_tipo", pa.string()),
    ("margem", pa.float32()), ("revisar", pa.bool_()), ("metodo", pa.string()), ("modelo_embedding", pa.string()),
    ("versao_taxonomia", pa.string()), ("classificado_em", pa.timestamp("us", tz="UTC")),
])

BB = {"user_id": "CNPJ#00000000000191", "cnpj": "00000000000191", "razao_social": "BANCO DO BRASIL SA",
      "situacao_cadastral": "Ativa", "status": "ativa", "capital_social": Decimal("120000000000.00"),
      "qtd_socios": 41, "consultado_em": datetime(2026, 11, 7, 10, tzinfo=timezone.utc),
      "cnae_principal": "6422100", "cnae_principal_descricao": "Bancos múltiplos, com carteira comercial",
      "cnaes_secundarios_descricao": None, "nome_fantasia": None, "natureza_juridica": None,
      "porte_empresa": "Demais", "uf": "DF", "municipio": "BRASILIA"}


@pytest.fixture
def amb(tmp_path):
    catalog = SqlCatalog("teste", uri=f"sqlite:///{tmp_path}/c.db", warehouse=f"file://{tmp_path}/wh")
    catalog.create_namespace("gold_db")
    catalog.create_table(etl_kb.GOLD_EMPRESAS, schema=SCHEMA_EMPRESAS).append(
        pa.Table.from_pylist([BB], schema=SCHEMA_EMPRESAS))
    return {"catalog": catalog, "lake": str(tmp_path / "lake")}


def ler(amb, nome):
    return open(os.path.join(etl_kb.kb_dir(amb["lake"]), nome), encoding="utf-8").read()


def test_documento_sem_classificacao_e_sem_socios(amb):
    assert etl_kb.docs(amb["catalog"], amb["lake"]) == 1
    doc = ler(amb, "CNPJ_00000000000191.md")
    assert doc.startswith("# BANCO DO BRASIL SA")
    assert "00.000.000/0001-91" in doc and "R$ 120.000.000.000,00" in doc
    assert "Atividade principal: Bancos múltiplos" in doc and "Localizacao: BRASILIA - DF" in doc
    assert "Tipo de empresa" not in doc            # a classificação ainda não rodou
    meta = json.loads(ler(amb, "CNPJ_00000000000191.md.metadata.json"))
    assert meta == {"metadataAttributes": {"user_id": "CNPJ#00000000000191", "status": "ativa",
                                           "situacao_cadastral": "Ativa", "uf": "DF"}}


def test_documento_traz_o_tipo_quando_a_classificacao_existe(amb):
    amb["catalog"].create_table(etl_kb.GOLD_CLASSIFICACAO, schema=SCHEMA_CLASSIFICACAO).append(pa.Table.from_pylist([{
        "user_id": BB["user_id"], "tipo_empresa": "instituicao_financeira", "score": 0.7, "segundo_tipo": "industria",
        "margem": 0.2, "revisar": False, "metodo": "s3vectors_cosine", "modelo_embedding": "amazon.titan-embed-text-v2:0",
        "versao_taxonomia": "1", "classificado_em": datetime(2026, 11, 8, tzinfo=timezone.utc)}], schema=SCHEMA_CLASSIFICACAO))
    etl_kb.docs(amb["catalog"], amb["lake"])
    assert "- Tipo de empresa: instituicao_financeira" in ler(amb, "CNPJ_00000000000191.md")
    meta = json.loads(ler(amb, "CNPJ_00000000000191.md.metadata.json"))
    assert meta["metadataAttributes"]["tipo_empresa"] == "instituicao_financeira"


def test_nome_de_arquivo_seguro_e_formatos():
    assert etl_kb.nome_arquivo("CNPJ#123/x") == "CNPJ_123_x"
    assert etl_kb.formata_cnpj("123") == "123" and etl_kb.formata_reais(None) == "nao informado"


def test_parse_args_e_maquina_de_estados():
    with pytest.raises(SystemExit):
        etl_kb.parse_args(["--STAGE", "docs"])
    d = json.load(open(os.path.join(AQUI, "..", "statemachine", "kb.asl.json"), encoding="utf-8"))
    assert d["StartAt"] == "Docs" and d["States"]["Docs"]["Next"] == "Sync"
    assert "${GlueJobName}" in json.dumps(d) and "${AlertTopicArn}" in json.dumps(d)


def test_classificacao_indefinida_nao_vai_para_o_documento(amb):
    amb["catalog"].create_table(etl_kb.GOLD_CLASSIFICACAO, schema=SCHEMA_CLASSIFICACAO).append(pa.Table.from_pylist([{
        "user_id": BB["user_id"], "tipo_empresa": "indefinido", "score": 0.1, "segundo_tipo": "", "margem": 0.0,
        "revisar": True, "metodo": "s3vectors_cosine", "modelo_embedding": "m", "versao_taxonomia": "1",
        "classificado_em": datetime(2026, 11, 8, tzinfo=timezone.utc)}], schema=SCHEMA_CLASSIFICACAO))
    etl_kb.docs(amb["catalog"], amb["lake"])
    assert "Tipo de empresa" not in ler(amb, "CNPJ_00000000000191.md")
