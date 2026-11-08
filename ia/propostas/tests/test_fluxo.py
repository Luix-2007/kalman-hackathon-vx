"""
O passo inteiro pelos handlers das Lambdas, na ordem da máquina de estados, com a AWS trocada por
peças falsas: Athena com as fixtures da Aurora, Bedrock com respostas fixas, índice em memória e o
bucket numa pasta. Confere também o contrato com o resto: a máquina de estados, o template e o
arquivo de proposta que o ETL da matriz lê (tests/fixtures/proposta_dcr.json).
"""

import importlib
import io
import json
import re
from pathlib import Path

import pytest

from apoio import (AQUI, ATO_DCR, ATO_OUTRO, ATO_SAUDE, CNPJ, RAIZ, TAXONOMIA, BedrockFalso, empresa_aurora,
                   extracao_dcr, triagem_dcr)

from propostas import dados, fluxo
from propostas.armazem import ArmazemPasta
from propostas.vetores import IndiceEmMemoria

FIXTURE_CONTRATO = AQUI / "fixtures" / "proposta_dcr.json"


class AthenaDados:
    """Responde às consultas de propostas.dados com a Aurora e três atos."""

    def __init__(self, atos=(ATO_DCR, ATO_OUTRO, ATO_SAUDE), classificacao=True):
        self.atos, self.classificacao = list(atos), classificacao
        self.e = empresa_aurora()

    def consultar(self, sql, params=None):
        e = self.e
        if "FROM silver_db.dou_atos WHERE id = ?" in sql:
            return [a for a in self.atos if a["id"] == params[0]]
        if "FROM silver_db.dou_atos" in sql:
            return [a for a in self.atos if a["data_publicacao"] >= params[0]]
        if "silver_db.matriz_perfis" in sql:
            return [{"cnpj": CNPJ, "razao_social": e["razao_social"], "setor": e["setor"], "cnae_principal": "3514000",
                     "cnaes": json.dumps(e["cnaes"]), "ufs_atuacao": json.dumps(e["ufs_atuacao"]),
                     "orgaos_fiscalizadores": json.dumps(e["orgaos_fiscalizadores"]),
                     "temas_interesse": json.dumps(e["temas_interesse"]),
                     "temas_fora_escopo": json.dumps(e["temas_fora_escopo"]), "area_padrao": "COMP"}]
        if "silver_db.matriz_unidades" in sql:
            return [{"cnpj": CNPJ, "unidade_id": u["id"], "nome": u["nome"], "tipo": u["tipo"], "tags": json.dumps(u["tags"])}
                    for u in e["unidades"]]
        if "silver_db.matriz_areas" in sql:
            return [{"cnpj": CNPJ, "area_id": a["id"], "nome": a["nome"]} for a in e["areas"]]
        if "silver_db.matriz_outorgas" in sql:
            return [{"cnpj": CNPJ, "outorga_id": o["id"], "tipo": o["tipo"], "orgao": o["orgao"], "objeto": o["objeto"],
                     "unidade_id": o["unidade_id"]} for o in e["outorgas"]]
        if "gold_db.matriz_obrigacoes" in sql:
            return [{"cnpj": CNPJ, **{k: v for k, v in o.items() if k != "aplica_a"}, "versao": "1",
                     "aplica_a": json.dumps(o["aplica_a"])} for o in e["vigentes"]]
        if "gold_db.empresas_clientes" in sql:
            return [{"user_id": f"CNPJ#{CNPJ}", "cnae_principal_descricao": e["atividade_principal"],
                     "cnaes_secundarios_descricao": e["atividades_secundarias"]}]
        if "gold_db.classificacao_empresas" in sql:
            if not self.classificacao:
                from propostas.athena import TabelaInexistente
                raise TabelaInexistente("TABLE_NOT_FOUND")
            return [{"user_id": f"CNPJ#{CNPJ}", "tipo_empresa": "distribuidora_energia", "revisar": "false"}]
        raise AssertionError(f"consulta inesperada: {sql}")


class S3Falso:
    def get_object(self, Bucket, Key):
        assert Key == "artefatos/cadastro/tipos_empresa.json"
        return {"Body": io.BytesIO(TAXONOMIA.read_bytes())}


@pytest.fixture
def lambdas(tmp_path, monkeypatch):
    for k, v in {"LAKE_BUCKET": "lake", "VECTOR_BUCKET": "vetores", "AWS_REGION": "us-east-1",
                 "LIMIAR_SIMILARIDADE": "0.2", "AWS_DEFAULT_REGION": "us-east-1"}.items():
        monkeypatch.setenv(k, v)
    import handlers
    h = importlib.reload(handlers)
    armazem, indice = ArmazemPasta(tmp_path / "lake"), IndiceEmMemoria()
    bedrock = BedrockFalso({"classificar_relevancia": triagem_dcr, "registrar_propostas": extracao_dcr})
    athena = AthenaDados()
    monkeypatch.setattr(h, "_armazem", lambda: armazem)
    monkeypatch.setattr(h, "_athena", lambda: athena)
    monkeypatch.setattr(h, "_indice", lambda: indice)
    monkeypatch.setattr(h, "_cliente", lambda nome: {"bedrock-runtime": bedrock, "s3": S3Falso()}[nome])
    h._contextos.clear()
    return {"h": h, "armazem": armazem, "indice": indice, "bedrock": bedrock, "athena": athena, "raiz": tmp_path / "lake"}


def roda(h, evento):
    """O que a máquina de estados faz: Indexar -> Recuperar -> Map(Processar) -> Resumir."""
    i = h.indexar(evento)
    r = h.recuperar({k: i[k] for k in ("run_id", "dia", "desde")})
    resultados = [h.processar(item) for item in r["itens"]]
    return i, r, resultados, h.resumir({"run_id": r["run_id"], "dia": r["dia"], "resultados": resultados})


def eventos(raiz):
    return [json.loads(l) for p in sorted(raiz.glob("audit/propostas/eventos/**/*.jsonl"))
            for l in p.read_text(encoding="utf-8").splitlines()]


def test_execucao_completa_grava_so_a_proposta_do_ato_que_importa(lambdas):
    h, raiz = lambdas["h"], lambdas["raiz"]
    i, r, resultados, resumo = roda(h, {"id": "evt-1", "dia": "2026-11-08", "dias": 7})

    assert i["run_id"] == "evt-1" and i["desde"] == "2026-11-01"
    assert i["indexacao"]["atos"] == 3 and i["indexacao"]["indexados"] == i["indexacao"]["trechos"] >= 3
    assert {it["ato_id"] for it in r["itens"]} >= {ATO_DCR["id"]}
    por_ato = {x["ato_id"]: x for x in resultados}
    assert por_ato[ATO_DCR["id"]]["resultado"] == "proposta"
    assert all(x["resultado"] == "irrelevante" for a, x in por_ato.items() if a != ATO_DCR["id"])
    assert resumo["por_resultado"]["proposta"] == 1

    arquivos = list(raiz.glob("landing/matriz/propostas_llm/2026-11-08/*.json"))
    assert [p.name for p in arquivos] == [f"{ATO_DCR['id']}__{CNPJ}.json"]
    doc = json.loads(arquivos[0].read_text(encoding="utf-8"))
    assert doc["ato_id"] == ATO_DCR["id"] and doc["orgao_emissor"] == "ANEEL"
    assert doc["propostas"][0]["cnpj"] == CNPJ and doc["propostas"][0]["tipo"] == "alteracao"

    # cada par tem a marca de processado, e cada etapa deixou eventos com os campos da tabela
    marcas = {p.stem for p in raiz.glob(f"audit/propostas/processados/{CNPJ}/*.json")}
    assert marcas == set(por_ato)
    ev = eventos(raiz)
    assert {e["etapa"] for e in ev} == {"indexar", "recuperar", "triar", "verificar", "gravar", "resumo"}
    from propostas.eventos import CAMPOS
    assert all(list(e) == list(CAMPOS) for e in ev)
    triagens = [e for e in ev if e["etapa"] == "triar"]
    assert all(e["motivo"] and e["modelo"] for e in triagens)

    # o tipo da classificação virou consultas (origem "tipo") na busca
    resumo_busca = next(e for e in ev if e["etapa"] == "recuperar" and e["resultado"] == "resumo")
    assert json.loads(resumo_busca["detalhes"])["por_origem"]["tipo"] >= 1

    # o arquivo é o contrato com o ETL da matriz: pipeline/matriz/tests lê esta fixture
    FIXTURE_CONTRATO.parent.mkdir(exist_ok=True)
    gerado = json.loads(arquivos[0].read_text(encoding="utf-8"))
    if not FIXTURE_CONTRATO.exists():
        FIXTURE_CONTRATO.write_text(json.dumps(gerado, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    assert json.loads(FIXTURE_CONTRATO.read_text(encoding="utf-8")) == gerado


def test_segunda_execucao_nao_reindexa_nem_reprocessa(lambdas):
    h = lambdas["h"]
    roda(h, {"id": "evt-1", "dia": "2026-11-08", "dias": 7})
    chamadas = len(lambdas["bedrock"].conversas)
    i, r, resultados, _ = roda(h, {"id": "evt-2", "dia": "2026-11-08", "dias": 7})
    assert i["indexacao"]["indexados"] == 0 and r["itens"] == [] and resultados == []
    assert len(lambdas["bedrock"].conversas) == chamadas


def test_arquivo_de_proposta_e_gravado_uma_vez_so(lambdas, tmp_path):
    h, armazem = lambdas["h"], lambdas["armazem"]
    i = h.indexar({"id": "evt-1", "dia": "2026-11-08", "dias": 7})
    r = h.recuperar({k: i[k] for k in ("run_id", "dia", "desde")})
    destino = fluxo.caminho_proposta("2026-11-08", ATO_DCR["id"], CNPJ)
    armazem.gravar(destino, '{"de": "outra execução"}')
    item = next(x for x in r["itens"] if x["ato_id"] == ATO_DCR["id"])
    assert h.processar(item)["resultado"] == "ja_existia"
    assert json.loads(armazem.ler(destino)) == {"de": "outra execução"}


def test_proposta_reprovada_vai_para_a_auditoria_e_nao_para_a_landing(lambdas):
    h, raiz = lambdas["h"], lambdas["raiz"]
    def inventada(texto):
        p = extracao_dcr(texto)
        p["propostas"][0]["trecho_citado"] = "As DCR deverão ser entregues até 30 de abril de cada ano."
        return p
    lambdas["bedrock"].respostas["registrar_propostas"] = inventada
    _, _, resultados, _ = roda(h, {"id": "evt-1", "dia": "2026-11-08", "dias": 7})
    assert next(x for x in resultados if x["ato_id"] == ATO_DCR["id"])["resultado"] == "sem_proposta"
    assert not list(raiz.glob("landing/matriz/propostas_llm/**/*.json"))
    rep = json.loads(next(raiz.glob("audit/propostas/reprovadas/2026-11-08/*.json")).read_text(encoding="utf-8"))
    assert "trecho_citado não está no texto do ato" in rep["propostas"][0]["_erros"]


def test_erro_do_modelo_sobe_para_a_maquina_de_estados_e_nao_marca_como_processado(lambdas):
    h, raiz = lambdas["h"], lambdas["raiz"]
    i = h.indexar({"id": "evt-1", "dia": "2026-11-08", "dias": 7})
    r = h.recuperar({k: i[k] for k in ("run_id", "dia", "desde")})
    from propostas.modelo import ModeloOcupado
    lambdas["bedrock"].erro = type("ClientError", (Exception,), {"response": {"Error": {"Code": "ThrottlingException"}}})()
    with pytest.raises(ModeloOcupado):
        h.processar(r["itens"][0])
    assert not list(raiz.glob("audit/propostas/processados/**/*.json"))   # tenta de novo na próxima
    assert any(e["resultado"] == "erro" for e in eventos(raiz))


def test_sem_classificacao_segue_sem_as_consultas_por_tipo():
    empresas = dados.carregar_empresas(AthenaDados(classificacao=False))
    assert empresas[0]["tipo_empresa"] is None and len(empresas[0]["vigentes"]) == 22
    assert empresas[0]["unidades"][0]["id"] == "UN-01" and empresas[0]["temas_fora_escopo"] == ["telecomunicacoes", "petroleo_e_gas"]


def test_maquina_de_estados_bate_com_o_template_e_com_o_codigo():
    asl = json.loads((AQUI.parent / "statemachine" / "propostas.asl.json").read_text(encoding="utf-8"))
    template = (AQUI.parent / "template.yaml").read_text(encoding="utf-8")
    bloco = template[template.index("DefinitionSubstitutions:"):template.index("Policies:", template.index("DefinitionSubstitutions:"))]
    assert set(re.findall(r"\$\{(\w+)\}", json.dumps(asl))) == set(re.findall(r"^        (\w+):", bloco, re.M))
    par = asl["States"]["Processar"]["ItemProcessor"]["States"]["Par"]
    from propostas.modelo import ModeloOcupado
    assert ModeloOcupado.__name__ in par["Retry"][0]["ErrorEquals"]       # o nome do erro que a Lambda levanta
    assert asl["States"]["Processar"]["ItemsPath"] == "$.itens"
    for nome in ("indexar", "recuperar", "processar", "resumir"):
        assert f"Handler: handlers.{nome}" in template


def test_copia_das_regras_e_igual_a_do_etl_da_matriz():
    assert (AQUI.parent / "src/regras_matriz.py").read_bytes() == (RAIZ / "pipeline/matriz/src/regras_matriz.py").read_bytes()
