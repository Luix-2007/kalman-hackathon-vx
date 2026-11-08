"""
Embeddings e classificação das empresas, sem AWS: um embedder falso (saco de palavras com
hash, então textos com palavras em comum ficam próximos) e um S3 Vectors em memória.

Usa o config/tipos_empresa.json de verdade: se a taxonomia ficar ambígua para as empresas
de teste (a Aurora, distribuidora, e o Banco do Brasil), o teste avisa.
"""

import hashlib
import json
import math
import os
import re
import sys
import unicodedata
from decimal import Decimal

import pytest
from pyiceberg.catalog.sql import SqlCatalog

AQUI = os.path.dirname(__file__)
sys.path.insert(0, os.path.join(AQUI, "..", "src"))
import etl  # noqa: E402

RAIZ = os.path.abspath(os.path.join(AQUI, "..", "..", ".."))
TAXONOMIA = os.path.join(AQUI, "..", "config", "tipos_empresa.json")


class EmbedderFalso:
    DIM = 256

    def __init__(self):
        self.chamadas = 0

    def embed(self, texto):
        self.chamadas += 1
        v = [0.0] * self.DIM
        sem_acento = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
        for palavra in re.findall(r"[a-z]{4,}", sem_acento):
            v[int(hashlib.md5(palavra.encode()).hexdigest(), 16) % self.DIM] += 1.0
        n = math.sqrt(sum(x * x for x in v)) or 1.0
        return [x / n for x in v]


class StoreFalso:
    """Mesmo contrato do S3VectorsStore; distância de cosseno como o índice usa."""

    def __init__(self):
        self.vetores = {}

    def get_vectors(self, keys):
        return {k: ({"metadata": self.vetores[k]["metadata"]} if k in self.vetores else None) for k in keys}

    def get_vector_data(self, key):
        return list(self.vetores[key]["data"]) if key in self.vetores else None

    def put_vectors(self, itens):
        for it in itens:
            self.vetores[it["key"]] = {"data": it["data"], "metadata": it.get("metadata", {})}

    def delete_vectors(self, keys):
        for k in keys:
            self.vetores.pop(k, None)

    def list_keys(self):
        return list(self.vetores)

    def query(self, vetor, top_k, index_name=None):
        sims = sorted(((sum(a * b for a, b in zip(vetor, v["data"])), k) for k, v in self.vetores.items()),
                      reverse=True)[:top_k]
        return [{"key": k, "distance": 1.0 - s, "metadata": self.vetores[k]["metadata"]} for s, k in sims]


def empresa(user_id, cnae, descricao, secundarios="", razao="EMPRESA SA", uf="SP"):
    return {"user_id": user_id, "cnpj": user_id[-14:], "razao_social": razao, "situacao_cadastral": "Ativa",
            "status": "ativa", "capital_social": Decimal("1.00"), "qtd_socios": 1, "consultado_em": None,
            "cnae_principal": cnae, "cnae_principal_descricao": descricao,
            "cnaes_secundarios_descricao": secundarios, "nome_fantasia": None,
            "natureza_juridica": "Sociedade Anônima Fechada", "porte_empresa": "Demais", "uf": uf, "municipio": None}


@pytest.fixture
def amb(tmp_path):
    catalog = SqlCatalog("teste", uri=f"sqlite:///{tmp_path}/c.db", warehouse=f"file://{tmp_path}/wh")
    catalog.create_namespace("gold_db")

    def gold(empresas):
        tabela = etl.ensure_table(catalog, etl.GOLD_EMPRESAS, str(tmp_path / "lake"))
        tabela.overwrite(etl.pa.Table.from_pylist(empresas, schema=etl.SCHEMAS[etl.GOLD_EMPRESAS]))

    return {"catalog": catalog, "lake": str(tmp_path / "lake"), "gold": gold,
            "taxonomia": etl.carregar_taxonomia(TAXONOMIA)}


AURORA = empresa("CNPJ#KALMANTESTE100", "3514000", "Distribuição de energia elétrica",
                 "Geração de energia elétrica; Comércio atacadista de energia elétrica; "
                 "Construção de estações e redes de distribuição de energia elétrica", "AURORA ENERGIA SA")
BB = empresa("CNPJ#00000000000191", "6422100", "Bancos múltiplos, com carteira comercial", "",
             "BANCO DO BRASIL SA", "DF")


# ---------------------------------------------------------------- taxonomia

def test_taxonomia_do_repositorio_e_valida_e_serve_as_propostas():
    t = etl.carregar_taxonomia(TAXONOMIA)
    assert len(t["tipos"]) >= 10
    for tipo in t["tipos"]:
        assert len(tipo["exemplos"]) >= 2, tipo["id"]
        # campos que o passo de propostas (ia/propostas) usa
        assert tipo["consultas"] and all(isinstance(c, str) and len(c) > 15 for c in tipo["consultas"]), tipo["id"]
        assert isinstance(tipo["orgaos"], list) and isinstance(tipo["temas"], list)


@pytest.mark.parametrize("ruim, trecho", [
    ({"tipos": [{"id": "a", "descricao": "x"}]}, "versao"),
    ({"versao": "1", "tipos": []}, "sem tipos"),
    ({"versao": "1", "tipos": [{"id": "A-1", "descricao": "x"}]}, "minúsculas"),
    ({"versao": "1", "tipos": [{"id": "a", "descricao": "x"}, {"id": "a", "descricao": "y"}]}, "repetidos"),
    ({"versao": "1", "tipos": [{"id": "indefinido", "descricao": "x"}]}, "reservado"),
    ({"versao": "1", "tipos": [{"id": "a", "descricao": " "}]}, "sem descricao"),
])
def test_taxonomia_invalida(ruim, trecho):
    with pytest.raises(ValueError, match=trecho):
        etl.validar_taxonomia(ruim)


def test_taxonomia_lida_do_s3():
    class S3:
        def get_object(self, Bucket, Key):
            assert (Bucket, Key) == ("lake", "artefatos/cadastro/tipos_empresa.json")
            corpo = open(TAXONOMIA, "rb").read()
            return {"Body": type("B", (), {"read": lambda self: corpo})()}
    assert etl.carregar_taxonomia("s3://lake/artefatos/cadastro/tipos_empresa.json", S3())["versao"]


# ---------------------------------------------------------------- texto e decisão

def test_texto_para_embedding_sem_campos_vazios():
    texto = etl.texto_para_embedding(AURORA)
    assert texto.startswith("Atividade principal: Distribuição de energia elétrica.")
    assert "Estado: SP." in texto and "Nome fantasia" not in texto
    assert len(etl.texto_para_embedding({**AURORA, "cnaes_secundarios_descricao": "x" * 20000})) == 8000


def test_decidir_tipo_media_dos_tres_melhores_com_limiar_e_margem():
    viz = [{"key": "a#0", "distance": 0.2}, {"key": "a#d", "distance": 0.25}, {"key": "a#1", "distance": 0.3},
           {"key": "a#2", "distance": 0.95}, {"key": "b#0", "distance": 0.4}, {"key": "__versao__", "distance": 0.0}]
    d = etl.decidir_tipo(viz, 0.30, 0.02)
    assert d["tipo_empresa"] == "a" and d["segundo_tipo"] == "b" and not d["revisar"]
    assert d["score"] == pytest.approx((0.8 + 0.75 + 0.7) / 3)   # o 4º vizinho de "a" não conta
    assert etl.decidir_tipo(viz, 0.90, 0.02)["tipo_empresa"] == "indefinido"      # abaixo do limiar
    perto = [{"key": "a#0", "distance": 0.30}, {"key": "b#0", "distance": 0.31}]
    assert etl.decidir_tipo(perto, 0.30, 0.02)["revisar"]                          # margem pequena
    assert etl.decidir_tipo([], 0.3, 0.02) == {"tipo_empresa": "indefinido", "score": 0.0, "segundo_tipo": "",
                                               "margem": 0.0, "revisar": True}


# ---------------------------------------------------------------- etapas

def test_embeddings_reaproveita_o_que_nao_mudou_e_apaga_quem_saiu(amb):
    emb, store, ref = EmbedderFalso(), StoreFalso(), StoreFalso()
    amb["gold"]([AURORA, BB])
    r1 = etl.embeddings(amb["catalog"], amb["lake"], emb, store, ref, amb["taxonomia"])
    n_ref = sum(1 + len(t["exemplos"]) for t in amb["taxonomia"]["tipos"]) + 1      # + o marcador de versão
    assert r1["embedados"] == 2 and len(ref.vetores) == n_ref
    assert store.vetores["CNPJ#KALMANTESTE100"]["metadata"]["cnae_principal"] == "3514000"

    chamadas = emb.chamadas
    amb["gold"]([AURORA])                       # BB saiu, Aurora igual, taxonomia igual
    r2 = etl.embeddings(amb["catalog"], amb["lake"], emb, store, ref, amb["taxonomia"])
    assert r2 == {"embedados": 0, "reaproveitados": 1, "apagados": 1, "referencias": 0}
    assert emb.chamadas == chamadas and set(store.vetores) == {"CNPJ#KALMANTESTE100"}

    nova = {**amb["taxonomia"], "versao": "outra"}
    etl.embeddings(amb["catalog"], amb["lake"], emb, store, ref, nova)
    assert ref.vetores["__versao__"]["metadata"]["versao"] == "outra"


def test_classificar_aurora_distribuidora_e_bb_banco(amb):
    emb, store, ref = EmbedderFalso(), StoreFalso(), StoreFalso()
    amb["gold"]([AURORA, BB])
    etl.embeddings(amb["catalog"], amb["lake"], emb, store, ref, amb["taxonomia"])
    # o embedder falso dá notas menores que o Titan: aqui se testa a ordem dos tipos, não o limiar
    # calibrado (0.30), que a simulação com o Titan de verdade confere (ia/propostas/simular.py)
    assert etl.classificar(amb["catalog"], amb["lake"], store, ref, amb["taxonomia"], 0.20, 0.02) == 2
    linhas = {r["user_id"]: r for r in amb["catalog"].load_table(etl.GOLD_CLASSIFICACAO).scan().to_arrow().to_pylist()}
    assert linhas["CNPJ#KALMANTESTE100"]["tipo_empresa"] == "distribuidora_energia"
    assert linhas["CNPJ#00000000000191"]["tipo_empresa"] == "instituicao_financeira"
    assert linhas["CNPJ#KALMANTESTE100"]["versao_taxonomia"] == amb["taxonomia"]["versao"]
    assert linhas["CNPJ#KALMANTESTE100"]["metodo"] == "s3vectors_cosine"


def test_empresa_sem_vetor_fica_indefinida_para_revisao(amb):
    amb["gold"]([AURORA])
    etl.classificar(amb["catalog"], amb["lake"], StoreFalso(), StoreFalso(), amb["taxonomia"])
    linha = amb["catalog"].load_table(etl.GOLD_CLASSIFICACAO).scan().to_arrow().to_pylist()[0]
    assert linha["tipo_empresa"] == "indefinido" and linha["revisar"]


def test_classificar_sem_empresas_grava_tabela_vazia(amb):
    amb["gold"]([])
    assert etl.classificar(amb["catalog"], amb["lake"], StoreFalso(), StoreFalso(), amb["taxonomia"]) == 0
    assert amb["catalog"].load_table(etl.GOLD_CLASSIFICACAO).scan().to_arrow().num_rows == 0


def test_maquina_de_estados_termina_em_classificar_e_nao_sincroniza_kb():
    d = json.load(open(os.path.join(AQUI, "..", "statemachine", "pipeline.asl.json"), encoding="utf-8"))
    s = d["States"]
    assert s["Gold"]["Next"] == "Embeddings" and s["Embeddings"]["Next"] == "Classificar"
    assert s["Classificar"]["Next"] == "Sucesso"
    assert s["Classificar"]["Parameters"]["Arguments"]["--STAGE"] == "classificar"
    assert not {"DocsDaKB", "SincronizarKB", "TemKnowledgeBase"} & set(s)
    placeholders = set(re.findall(r"\$\{(\w+)\}", json.dumps(d)))
    template = open(os.path.join(AQUI, "..", "template.yaml"), encoding="utf-8").read()
    bloco = template[template.index("DefinitionSubstitutions:"):template.index("Policies:", template.index("DefinitionSubstitutions:"))]
    assert placeholders == set(re.findall(r"^        (\w+):", bloco, re.M))


def test_s3vectors_store_chama_a_api_no_formato_certo():
    """O Stubber valida cada chamada contra o modelo do serviço (o mesmo boto3 do job: 1.42.97)."""
    import boto3
    from botocore.stub import Stubber

    cliente = boto3.client("s3vectors", region_name="us-east-1", aws_access_key_id="x", aws_secret_access_key="x")
    store = etl.S3VectorsStore.__new__(etl.S3VectorsStore)
    store._client, store._bucket, store._index = cliente, "lakehouse-pipeline-vectors", "empresas-v1"
    base = {"vectorBucketName": "lakehouse-pipeline-vectors", "indexName": "empresas-v1"}
    with Stubber(cliente) as st:
        st.add_response("get_vectors", {"vectors": [{"key": "u1", "metadata": {"texto_hash": "h"}}]},
                        {**base, "keys": ["u1", "u2"], "returnData": False, "returnMetadata": True})
        st.add_response("get_vectors", {"vectors": [{"key": "u1", "data": {"float32": [0.5, 0.5]}}]},
                        {**base, "keys": ["u1"], "returnData": True, "returnMetadata": False})
        st.add_response("put_vectors", {}, {**base, "vectors": [
            {"key": "u3", "data": {"float32": [0.1, 0.2]}, "metadata": {"uf": "SP"}}]})
        st.add_response("delete_vectors", {}, {**base, "keys": ["u2"]})
        st.add_response("list_vectors", {"vectors": [{"key": "u1"}], "nextToken": "t"}, base)
        st.add_response("list_vectors", {"vectors": [{"key": "u3"}]}, {**base, "nextToken": "t"})
        st.add_response("query_vectors", {"vectors": [{"key": "a#0", "distance": 0.1, "metadata": {"tipo_id": "a"}}],
                                          "distanceMetric": "cosine"},
                        {**base, "queryVector": {"float32": [0.1, 0.2]}, "topK": 30,
                         "returnMetadata": True, "returnDistance": True})
        assert store.get_vectors(["u1", "u2"]) == {"u1": {"metadata": {"texto_hash": "h"}}, "u2": None}
        assert store.get_vector_data("u1") == [0.5, 0.5]
        store.put_vectors([{"key": "u3", "data": [0.1, 0.2], "metadata": {"uf": "SP"}}])
        store.delete_vectors(["u2"])
        assert store.list_keys() == ["u1", "u3"]
        assert store.query([0.1, 0.2], top_k=30) == [{"key": "a#0", "distance": 0.1, "metadata": {"tipo_id": "a"}}]
        st.assert_no_pending_responses()
