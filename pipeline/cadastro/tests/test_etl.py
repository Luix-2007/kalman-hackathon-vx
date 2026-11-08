"""
Roda o pipeline inteiro em pastas locais, com um catálogo Iceberg em SQLite
no lugar do Glue Data Catalog. Os itens têm o mesmo formato que a Lambda
api/cnpj-cadastro grava (put_item), serializados como um export do DynamoDB.
"""

import gzip
import json
import os
import sys
from decimal import Decimal

import pytest
from boto3.dynamodb.types import TypeSerializer
from pyiceberg.catalog.sql import SqlCatalog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import etl  # noqa: E402

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))

DIA1, DIA2 = "2026-11-07", "2026-11-08"

BB = json.loads(json.dumps({
    "cnpj": "00000000000191", "razao_social": "BANCO DO BRASIL SA",
    "situacao_cadastral": "Ativa", "capital_social": "120000000000,00",
    "QSA": [{"nome_socio": "FULANO", "is_x": False}, {"nome_socio": "BELTRANO", "is_x": True}],
    "score": 1.5,
}), parse_float=Decimal)

ITENS_DIA1 = [
    {"user_id": "u1", "cnpj": "00000000000191", "status": "ativa",
     "consultado_em": "2026-11-07T10:00:00+00:00", "empresa": BB},
    {"user_id": "u2", "cnpj": "11111111000111", "status": "inativa",
     "consultado_em": "2026-11-07T10:01:00+00:00",
     "empresa": {"cnpj": "11111111000111", "situacao_cadastral": "Baixada"}},
    {"user_id": "u3", "cnpj": "99999999000199", "status": "nao_encontrado",
     "consultado_em": "2026-11-07T10:02:00+00:00"},
    {"user_id": "u4", "cnpj": None, "status": "cnpj_invalido",
     "consultado_em": "2026-11-07T10:03:00+00:00"},
]


def escreve_export(pasta, itens):
    """Mesmo layout de um export DynamoDB JSON: data/*.json.gz, uma linha {"Item": ...} por item."""
    ser = TypeSerializer()
    os.makedirs(pasta, exist_ok=True)
    with gzip.open(os.path.join(pasta, "part-0000.json.gz"), "wt") as f:
        for it in itens:
            f.write(json.dumps({"Item": {k: ser.serialize(v) for k, v in it.items()}}, default=str) + "\n")
    return pasta


@pytest.fixture
def amb(tmp_path):
    lake = str(tmp_path / "lake")
    catalog = SqlCatalog("teste", uri=f"sqlite:///{tmp_path}/catalogo.db",
                         warehouse=f"file://{tmp_path}/warehouse")
    return {"tmp": tmp_path, "lake": lake, "catalog": catalog, "con": etl.connect()}


def roda_dia(amb, dt, itens):
    data = escreve_export(str(amb["tmp"] / "export" / dt / "data"), itens)
    n_landing = etl.landing(amb["con"], data, amb["lake"], dt)
    n_bronze = etl.bronze(amb["con"], amb["lake"], dt)
    n_silver = etl.silver(amb["con"], amb["catalog"], amb["lake"], dt)
    n_gold = etl.gold(amb["con"], amb["catalog"], amb["lake"])
    return n_landing, n_bronze, n_silver, n_gold


def linhas(amb, ident):
    return amb["catalog"].load_table(ident).scan().to_arrow().to_pylist()


def por_usuario(amb, ident):
    return {r["user_id"]: r for r in linhas(amb, ident)}


def test_pipeline_completo(amb):
    n_landing, n_bronze, n_silver, n_gold = roda_dia(amb, DIA1, ITENS_DIA1)
    assert n_landing == 4
    assert n_bronze == {"usuarios_cnpj": 4, "socios": 2}
    assert n_silver == {"usuarios_cnpj": 4, "socios": 2}
    assert n_gold == {"empresas_clientes": 2, "cadastros_por_status": 4}

    u = por_usuario(amb, etl.SILVER_USUARIOS)
    assert u["u1"]["razao_social"] == "BANCO DO BRASIL SA"
    assert u["u1"]["capital_social"] == Decimal("120000000000.00")
    assert u["u1"]["qtd_socios"] == 2
    assert u["u2"]["situacao_cadastral"] == "Baixada" and u["u2"]["qtd_socios"] is None
    assert u["u3"]["empresa_raw"] is None
    assert u["u4"]["cnpj"] is None and u["u4"]["status"] == "cnpj_invalido"

    socios = sorted(r["nome_socio"] for r in linhas(amb, etl.SILVER_SOCIOS))
    assert socios == ["BELTRANO", "FULANO"]

    empresas = por_usuario(amb, etl.GOLD_EMPRESAS)
    assert set(empresas) == {"u1", "u2"}
    status = {r["status"]: r["cadastros"] for r in linhas(amb, etl.GOLD_STATUS)}
    assert status == {"ativa": 1, "inativa": 1, "nao_encontrado": 1, "cnpj_invalido": 1}


def test_segundo_dia_atualiza_sem_duplicar(amb):
    roda_dia(amb, DIA1, ITENS_DIA1)
    # u2 virou ativa com outra razão social; u1 trocou de sócios; u5 é novo.
    dia2 = [dict(i) for i in ITENS_DIA1]
    dia2[0] = dict(dia2[0], consultado_em="2026-11-08T09:00:00+00:00",
                   empresa=dict(BB, QSA=[{"nome_socio": "CICLANO", "is_x": False}]))
    dia2[1] = {"user_id": "u2", "cnpj": "11111111000111", "status": "ativa",
               "consultado_em": "2026-11-08T09:01:00+00:00",
               "empresa": {"cnpj": "11111111000111", "razao_social": "NOVA SA",
                           "situacao_cadastral": "Ativa", "capital_social": "1.500,50"}}
    dia2.append({"user_id": "u5", "cnpj": "22222222000122", "status": "nao_encontrado",
                 "consultado_em": "2026-11-08T09:02:00+00:00"})
    roda_dia(amb, DIA2, dia2)

    u = por_usuario(amb, etl.SILVER_USUARIOS)
    assert len(u) == 5
    assert u["u2"]["status"] == "ativa" and u["u2"]["razao_social"] == "NOVA SA"
    assert u["u2"]["capital_social"] == Decimal("1500.50")
    assert u["u2"]["_carga_dt"] == DIA2
    assert [r["nome_socio"] for r in linhas(amb, etl.SILVER_SOCIOS)] == ["CICLANO"]
    assert len(por_usuario(amb, etl.GOLD_EMPRESAS)) == 2


def test_reprocessar_o_mesmo_dia_e_idempotente(amb):
    roda_dia(amb, DIA1, ITENS_DIA1)
    roda_dia(amb, DIA1, ITENS_DIA1)
    assert len(por_usuario(amb, etl.SILVER_USUARIOS)) == 4
    assert len(linhas(amb, etl.SILVER_SOCIOS)) == 2


def test_qualidade_barra_status_desconhecido(amb):
    ruim = ITENS_DIA1 + [{"user_id": "u9", "cnpj": None, "status": "status_novo",
                          "consultado_em": "2026-11-07T11:00:00+00:00"}]
    data = escreve_export(str(amb["tmp"] / "export" / "ruim" / "data"), ruim)
    etl.landing(amb["con"], data, amb["lake"], DIA1)
    etl.bronze(amb["con"], amb["lake"], DIA1)
    with pytest.raises(etl.QualidadeError, match="status_invalido=1"):
        etl.silver(amb["con"], amb["catalog"], amb["lake"], DIA1)
    assert (("silver_db",) not in amb["catalog"].list_namespaces()
            or "usuarios_cnpj" not in [t[1] for t in amb["catalog"].list_tables("silver_db")])


def test_resolve_export_data_uri():
    class FakeDdb:
        def describe_export(self, ExportArn):
            return {"ExportDescription": {
                "ExportStatus": "COMPLETED", "S3Bucket": "empresa-ddb-export",
                "ExportManifest": "usuarios_cnpj/2026-11-07/AWSDynamoDB/0170-abc/manifest-summary.json"}}
    assert etl.resolve_export_data_uri(FakeDdb(), "arn:x") == \
        "s3://empresa-ddb-export/usuarios_cnpj/2026-11-07/AWSDynamoDB/0170-abc/data"


def test_parse_args_formato_glue():
    args = etl.parse_args(["--STAGE", "landing", "--LAKE_URI", "s3://lake", "--RUN_DATE", "2026-11-07",
                           "--EXPORT_ARN", "arn:x", "--job-bookmark-option", "job-bookmark-disable",
                           "--enable-metrics"])
    assert args["STAGE"] == "landing" and args["EXPORT_ARN"] == "arn:x"
    with pytest.raises(SystemExit):
        etl.parse_args(["--STAGE", "bronze", "--LAKE_URI", "s3://lake", "--RUN_DATE", "07/11/2026"])
    with pytest.raises(SystemExit):
        etl.parse_args(["--STAGE", "landing", "--LAKE_URI", "s3://lake", "--RUN_DATE", "2026-11-07"])


def test_modelo_de_organizacoes_le_so_o_item_da_empresa(amb):
    """Tabela com organizações: vínculo do usuário, organização (CNPJ#) e convite."""
    itens = [
        {"user_id": "sub-dono", "cnpj": "00000000000191", "papel": "dono"},
        {"user_id": "sub-membro", "cnpj": "00000000000191", "papel": "membro"},
        {"user_id": "CNPJ#00000000000191", "cnpj": "00000000000191", "dono": "sub-dono",
         "status": "ativa", "consultado_em": "2026-11-07T10:00:00+00:00", "empresa": BB,
         "dados": {"setor": "financeiro"}, "membros": {"sub-membro": {"email": "m@x"}}, "convites": {}},
        {"user_id": "CNPJ#33000167000101", "cnpj": "33000167000101", "dono": "outro",
         "status": "processando", "dados": {}, "membros": {}, "convites": {}},
        {"user_id": "CONVITE#x@a.com", "cnpj": "00000000000191", "convidado_por": "sub-dono",
         "expira_em": 9999999999},
    ]
    n_landing, n_bronze, n_silver, n_gold = roda_dia(amb, DIA1, itens)
    assert n_landing == 5 and n_bronze == {"usuarios_cnpj": 2, "socios": 2}
    u = por_usuario(amb, etl.SILVER_USUARIOS)
    assert set(u) == {"CNPJ#00000000000191", "CNPJ#33000167000101"}
    assert u["CNPJ#00000000000191"]["razao_social"] == "BANCO DO BRASIL SA"
    assert set(por_usuario(amb, etl.GOLD_EMPRESAS)) == {"CNPJ#00000000000191"}


def test_bronze_traz_atividade_porte_e_sede_da_empresa(amb):
    """Campos que a classificação usa, lidos do item do cadastro (fixture da Aurora)."""
    empresa = json.loads(open(os.path.join(RAIZ, "api/cnpj-cadastro/src/fixtures/KALMANTESTE100.json"),
                              encoding="utf-8").read(), parse_float=Decimal)
    itens = [{"user_id": "CNPJ#KALMANTESTE100", "cnpj": "KALMANTESTE100", "dono": "u1", "status": "ativa",
              "consultado_em": "2026-11-07T10:00:00+00:00", "empresa": empresa}]
    roda_dia(amb, DIA1, itens)
    e = por_usuario(amb, etl.GOLD_EMPRESAS)["CNPJ#KALMANTESTE100"]
    assert e["cnae_principal"] == "3514000"
    assert "Distribuição de energia elétrica" in e["cnae_principal_descricao"]
    assert "Geração de energia elétrica" in e["cnaes_secundarios_descricao"]
    assert e["uf"] == empresa["uf"] and e["porte_empresa"] == empresa.get("porte_empresa")
