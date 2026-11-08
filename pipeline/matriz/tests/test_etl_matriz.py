"""
Pipeline da matriz ponta a ponta, em pastas locais e catálogo Iceberg em SQLite.

O cenário é o da demo: a Aurora (fixture do CNPJ e perfil de api/cnpj-cadastro) com as
22 obrigações de fixtures/aurora/matriz.csv, depois a proposta do DOU que altera a OBR-013,
a aprovação pela API (simulada com a linha que ela grava em bronze_db.matriz_decisoes) e
a conclusão de uma tarefa.
"""

import json
import os
import shutil
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from pyiceberg.catalog.sql import SqlCatalog

AQUI = Path(__file__).parent
sys.path.insert(0, str(AQUI.parent / "src"))
import etl_matriz as etl  # noqa: E402

RAIZ = AQUI.parents[2]
FIXTURES = AQUI.parent / "fixtures" / "aurora"
CNPJ = "KALMANTESTE100"
HOJE = date(2026, 11, 7)


def item_aurora():
    """Item CNPJ#KALMANTESTE100 como a API grava depois do seed (Decimal, como o boto3 lê)."""
    empresa = json.loads((RAIZ / "api/cnpj-cadastro/src/fixtures/KALMANTESTE100.json").read_text(), parse_float=Decimal)
    empresa["QSA"] = [{"nome_socio": "FULANO"}]
    dados = json.loads((RAIZ / "api/cnpj-cadastro/tests/aurora_dados.json").read_text(), parse_float=Decimal)
    return {"user_id": f"CNPJ#{CNPJ}", "cnpj": CNPJ, "dono": "u1", "status": "ativa", "empresa": empresa,
            "dados": dados, "membros": {"m1": {"email": "m@x"}}, "convites": {}}


@pytest.fixture
def amb(tmp_path):
    lake = str(tmp_path / "lake")
    catalog = SqlCatalog("teste", uri=f"sqlite:///{tmp_path}/catalogo.db", warehouse=f"file://{tmp_path}/wh")
    return {"lake": lake, "catalog": catalog, "con": etl.connect()}


def copia(amb, origem: Path, *destino: str):
    alvo = Path(etl.landing(amb["lake"], *destino))
    alvo.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(origem, alvo)


def roda(amb, agora=datetime(2026, 11, 7, 12), hoje=HOJE):
    nb = etl.bronze(amb["con"], amb["catalog"], amb["lake"], agora)
    ns = etl.silver(amb["catalog"], amb["lake"])
    ng = etl.gold(amb["catalog"], amb["lake"], hoje)
    return nb, ns, ng


def linhas(amb, ident):
    return amb["catalog"].load_table(ident).scan().to_arrow().to_pylist()


def obrigacoes(amb):
    return {(o["obrigacao_id"], o["versao"]): o for o in linhas(amb, etl.GOLD_OBRIGACOES)}


def tarefas(amb, obrigacao_id=None):
    return [t for t in linhas(amb, etl.GOLD_TAREFAS) if obrigacao_id in (None, t["obrigacao_id"])]


def decisao(amb, **kw):
    """A linha que a API grava com INSERT no Athena."""
    linha = {"decisao_id": kw.pop("decisao_id", "d1"), "cnpj": CNPJ, "usuario": "u1",
             "decidida_em": datetime(2026, 11, 7, 15), **kw}
    tabela = amb["catalog"].load_table(etl.BRONZE_DECISOES)
    tabela.append(etl.tabela_arrow(etl.BRONZE_DECISOES, [linha]))


@pytest.fixture
def aurora(amb):
    etl.exportar_perfis([item_aurora()], amb["lake"], "2026-11-07")
    copia(amb, FIXTURES / "matriz.csv", "importada", CNPJ, "matriz.csv")
    amb["primeira"] = roda(amb)
    return amb


# ---------------------------------------------------------------- etapa 3

def test_perfil_exportado_sem_socios_membros_e_com_cnpj():
    doc = etl.documento_perfil(item_aurora())
    assert doc["cnpj"] == CNPJ and "QSA" not in doc["empresa"] and "membros" not in doc
    assert doc["dados"]["outorgas"][0]["antecedencia_renovacao_dias"] == 120  # Decimal -> int
    assert etl.documento_perfil({"user_id": "CNPJ#123"}) is None


def test_matriz_da_aurora_vira_22_obrigacoes_aprovadas(aurora):
    nb, ns, ng = aurora["primeira"]
    assert nb == {"matriz_importada": 22, "matriz_propostas_llm": 0, "matriz_perfis": 1}
    assert ns["quarentena"] == 0
    obs = obrigacoes(aurora)
    assert len(obs) == 22
    assert all(o["status"] == "aprovada" and o["vigente"] and o["versao"] == 1 for o in obs.values())
    assert obs[("OBR-018", 1)]["aplica_a"] == ["UN-02", "UN-03"]
    perfil = linhas(aurora, etl.SILVER_PERFIS)[0]
    assert perfil["cnae_principal"] == "3514000" and perfil["area_padrao"] == "COMP"
    assert len(linhas(aurora, etl.SILVER_OUTORGAS)) == 4


def test_renovacao_da_licenca_vence_em_10_11_e_esta_em_risco(aurora):
    lo = tarefas(aurora, "OBR-009")
    assert len(lo) == 1
    assert lo[0]["vencimento"] == date(2026, 11, 10) and lo[0]["em_risco"]
    assert lo[0]["outorga_id"] == "OUT-01" and lo[0]["unidade_id"] == "UN-02"
    assert lo[0]["status"] == "aberta" and lo[0]["area_responsavel"] == "GMA"


def test_tarefas_geradas_por_tipo(aurora):
    assert tarefas(aurora, "OBR-021") == [] and tarefas(aurora, "OBR-022") == []   # por evento, contínua
    assert tarefas(aurora, "OBR-010") == []                                       # renovação fora do horizonte
    assert len(tarefas(aurora, "OBR-001")) == 12                                  # mensal
    assert len(tarefas(aurora, "OBR-020")) == 2                                   # bienal, 2 unidades
    dcr = tarefas(aurora, "OBR-013")
    assert [t["vencimento"] for t in dcr] == [date(2027, 4, 30)] and not dcr[0]["em_risco"]


def test_rodar_de_novo_nao_muda_nada(aurora):
    antes = (linhas(aurora, etl.GOLD_OBRIGACOES), linhas(aurora, etl.GOLD_TAREFAS), linhas(aurora, etl.GOLD_VERSOES))
    etl.exportar_perfis([item_aurora()], aurora["lake"], "2026-11-07")   # mesmo perfil regravado
    nb, _, _ = roda(aurora, agora=datetime(2026, 11, 7, 13))
    assert nb == {"matriz_importada": 0, "matriz_propostas_llm": 0, "matriz_perfis": 0}
    depois = (linhas(aurora, etl.GOLD_OBRIGACOES), linhas(aurora, etl.GOLD_TAREFAS), linhas(aurora, etl.GOLD_VERSOES))
    assert depois == antes


# ---------------------------------------------------------------- etapa 5 (demo)

@pytest.fixture
def com_proposta(aurora):
    copia(aurora, FIXTURES / "proposta_obr013.json", "propostas_llm", "2026-11-07", "dou-2026-11-07-s1-000013.json")
    aurora["segunda"] = roda(aurora, agora=datetime(2026, 11, 7, 14))
    return aurora


def test_proposta_cria_versao_2_e_poe_tarefa_em_risco(com_proposta):
    obs = obrigacoes(com_proposta)
    v1, v2 = obs[("OBR-013", 1)], obs[("OBR-013", 2)]
    assert v2["status"] == "proposta" and not v2["vigente"] and v1["vigente"]
    assert v2["origem"] == "llm" and v2["alterada_por"] == "dou-2026-11-07-s1-000013" and v2["confianca"] == 0.86
    assert "31/03" in v2["prazo_json"] and v2["titulo"] == v1["titulo"]
    dcr = tarefas(com_proposta, "OBR-013")
    assert [t["vencimento"] for t in dcr] == [date(2027, 4, 30)] and dcr[0]["em_risco"]
    versoes = [v for v in linhas(com_proposta, etl.GOLD_VERSOES) if v["obrigacao_id"] == "OBR-013"]
    assert [v["evento"] for v in versoes] == ["inclusao", "alteracao"]
    assert "prazo_json" in versoes[-1]["resumo"]


def test_aprovacao_move_a_tarefa_para_31_03(com_proposta):
    decisao(com_proposta, tipo="obrigacao", obrigacao_id="OBR-013", versao=2, decisao="aprovar")
    roda(com_proposta, agora=datetime(2026, 11, 7, 16))
    obs = obrigacoes(com_proposta)
    assert obs[("OBR-013", 2)]["status"] == "aprovada" and obs[("OBR-013", 2)]["vigente"]
    assert not obs[("OBR-013", 1)]["vigente"] and obs[("OBR-013", 2)]["decidida_por"] == "u1"
    dcr = tarefas(com_proposta, "OBR-013")
    assert [(t["vencimento"], t["obrigacao_versao"]) for t in dcr] == [(date(2027, 3, 31), 2)]
    assert not dcr[0]["em_risco"]
    eventos = [v["evento"] for v in linhas(com_proposta, etl.GOLD_VERSOES) if v["obrigacao_id"] == "OBR-013"]
    assert eventos == ["inclusao", "alteracao", "aprovacao"]
    v1, v2 = obs[("OBR-013", 1)], obs[("OBR-013", 2)]
    assert (v1["vigente_de"], v1["vigente_ate"]) == (HOJE, HOJE) and (v2["vigente_de"], v2["vigente_ate"]) == (HOJE, None)


def test_snapshots_do_iceberg_guardam_a_versao_anterior(com_proposta):
    tabela = com_proposta["catalog"].load_table(etl.GOLD_OBRIGACOES)
    antes = tabela.current_snapshot().snapshot_id
    decisao(com_proposta, tipo="obrigacao", obrigacao_id="OBR-013", versao=2, decisao="aprovar")
    roda(com_proposta, agora=datetime(2026, 11, 7, 16))
    passado = com_proposta["catalog"].load_table(etl.GOLD_OBRIGACOES).scan(snapshot_id=antes).to_arrow().to_pylist()
    v2_antes = next(o for o in passado if (o["obrigacao_id"], o["versao"]) == ("OBR-013", 2))
    assert v2_antes["status"] == "proposta"


def test_rejeicao_tira_o_risco(com_proposta):
    decisao(com_proposta, tipo="obrigacao", obrigacao_id="OBR-013", versao=2, decisao="rejeitar")
    roda(com_proposta, agora=datetime(2026, 11, 7, 16))
    assert obrigacoes(com_proposta)[("OBR-013", 2)]["status"] == "rejeitada"
    dcr = tarefas(com_proposta, "OBR-013")
    assert [t["vencimento"] for t in dcr] == [date(2027, 4, 30)] and not dcr[0]["em_risco"]


def test_status_da_tarefa_vem_das_decisoes(aurora):
    lo = tarefas(aurora, "OBR-009")[0]
    decisao(aurora, tipo="tarefa", tarefa_id=lo["tarefa_id"], decisao="concluida", evidencia_url="https://x/protocolo.pdf")
    roda(aurora, agora=datetime(2026, 11, 7, 16))
    lo = tarefas(aurora, "OBR-009")[0]
    assert lo["status"] == "concluida" and not lo["em_risco"] and lo["evidencia_url"] == "https://x/protocolo.pdf"
    # dias depois, a tarefa concluída continua lá, mesmo vencida
    roda(aurora, agora=datetime(2026, 11, 20, 12), hoje=date(2026, 11, 20))
    assert tarefas(aurora, "OBR-009")[0]["status"] == "concluida"


def test_tarefa_aberta_vencida_continua_como_atrasada(aurora):
    roda(aurora, agora=datetime(2026, 11, 12, 12), hoje=date(2026, 11, 12))
    lo = tarefas(aurora, "OBR-009")
    assert [t["vencimento"] for t in lo] == [date(2026, 11, 10)] and lo[0]["em_risco"]


# ---------------------------------------------------------------- quarentena

def escreve_proposta(amb, nome, propostas, bruto=None):
    alvo = Path(etl.landing(amb["lake"], "propostas_llm", "2026-11-07", f"{nome}.json"))
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(bruto if bruto is not None else json.dumps(
        {"ato_id": nome, "ato_url": "u", "data_publicacao": "2026-11-07", "orgao_emissor": "ANEEL", "propostas": propostas}))


def test_propostas_ruins_vao_para_a_quarentena(aurora):
    boa = {"cnpj": CNPJ, "tipo": "nova", "titulo": "Nova obrigação", "trecho_citado": "art. 1º ...",
           "recorrencia": "por_evento", "criticidade": "media", "area_sugerida": "XYZ"}
    escreve_proposta(aurora, "a1", [
        boa,
        {**boa, "trecho_citado": ""},                                               # sem trecho
        {**boa, "tipo": "alteracao", "obrigacao_id_alvo": "OBR-999"},              # alvo inexistente
        {**boa, "aplica_a": ["UN-77"]},                                             # unidade inexistente
        {**boa, "tipo": "talvez"},                                                  # tipo inválido
        {**boa, "cnpj": "00000000000191"},                                          # sem perfil
        {**boa, "recorrencia": "periodica", "periodicidade": "anual", "prazo_json": [{"unidade": "x"}]},
    ])
    escreve_proposta(aurora, "a2", None, bruto="{isto não é json")
    _, ns, _ = roda(aurora, agora=datetime(2026, 11, 7, 14))
    cands = [c for c in linhas(aurora, etl.SILVER_CANDIDATAS) if c["origem"] == "llm"]
    assert ns["quarentena"] == 7 and sum(c["valida"] for c in cands) == 1
    valida = next(c for c in cands if c["valida"])
    assert valida["area_responsavel"] == "COMP"   # área desconhecida -> área padrão
    erros = " | ".join(e for c in cands for e in c["erros"])
    for trecho in ("trecho_citado", "OBR-999", "UN-77", "tipo deve ser", "sem perfil", "unidade desconhecida", "arquivo inválido"):
        assert trecho in erros
    novas = [o for o in linhas(aurora, etl.GOLD_OBRIGACOES) if o["origem"] == "llm"]
    assert len(novas) == 1 and novas[0]["status"] == "proposta" and novas[0]["obrigacao_id"].startswith("LLM-")


def test_linha_ruim_da_matriz_importada_nao_derruba_as_outras(amb):
    etl.exportar_perfis([item_aurora()], amb["lake"], "2026-11-07")
    alvo = Path(etl.landing(amb["lake"], "importada", CNPJ, "pequena.csv"))
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_text(
        "obrigacao_id;titulo;recorrencia;periodicidade;prazo_json;aplica_a\n"
        'X-1;Boa;periodica;anual;"[{""unidade"": ""data_fixa"", ""referencia"": ""ano_corrente"", ""valor"": ""01/12""}]";UN-01\n'
        "X-2;Sem prazo;periodica;anual;;\n", encoding="utf-8")
    _, ns, _ = roda(amb)
    assert ns["quarentena"] == 1
    assert [o["obrigacao_id"] for o in linhas(amb, etl.GOLD_OBRIGACOES)] == ["X-1"]
    assert tarefas(amb, "X-1")[0]["vencimento"] == date(2026, 12, 1)


def test_parse_args():
    assert etl.parse_args(["--STAGE", "gold", "--LAKE_URI", "s3://b", "--HOJE", "2026-11-07"])["HOJE"] == "2026-11-07"
    assert "HOJE" not in etl.parse_args(["--STAGE", "gold", "--LAKE_URI", "s3://b", "--HOJE", "hoje"])
    with pytest.raises(SystemExit):
        etl.parse_args(["--STAGE", "perfis", "--LAKE_URI", "s3://b"])
    with pytest.raises(SystemExit):
        etl.parse_args(["--STAGE", "gold", "--LAKE_URI", "s3://b", "--HOJE", "07/11/2026"])


# ---------------------------------------------------------------- linha do tempo

def test_linha_do_tempo_traz_ato_e_antes_depois(com_proposta):
    h = [v for v in linhas(com_proposta, etl.GOLD_VERSOES) if v["obrigacao_id"] == "OBR-013"][-1]
    assert h["evento"] == "alteracao" and h["ato_id"] == "dou-2026-11-07-s1-000013"
    assert h["data_ato"] == date(2026, 11, 7) and h["ato_url"] == "https://www.in.gov.br/"
    assert "31 de março" in h["trecho_citado"]
    alt = {a["campo"]: a for a in json.loads(h["alteracoes"])}
    assert alt["prazo_regra"]["antes"] == "Até 30 de abril do ano seguinte ao exercício"
    assert alt["prazo_regra"]["depois"] == "Até 31 de março do ano seguinte ao exercício"
    assert obrigacoes(com_proposta)[("OBR-013", 2)]["data_ato"] == date(2026, 11, 7)


def test_gold_antiga_ganha_as_colunas_novas(amb):
    """A gold já existe na AWS sem as colunas da linha do tempo: o job evolui o schema."""
    import pyarrow as pa
    novas = {"data_ato", "vigente_de", "vigente_ate", "ato_id", "ato_url", "trecho_citado", "alteracoes"}
    for ident in (etl.GOLD_OBRIGACOES, etl.GOLD_VERSOES):
        antigo = pa.schema([f for f in etl.SCHEMAS[ident] if f.name not in novas])
        amb["catalog"].create_namespace_if_not_exists("gold_db")
        amb["catalog"].create_table(ident, schema=antigo)
    etl.exportar_perfis([item_aurora()], amb["lake"], "2026-11-07")
    copia(amb, FIXTURES / "matriz.csv", "importada", CNPJ, "matriz.csv")
    roda(amb)
    cols = {f.name for f in amb["catalog"].load_table(etl.GOLD_VERSOES).schema().fields}
    assert novas - {"vigente_de", "vigente_ate"} <= cols
    assert obrigacoes(amb)[("OBR-001", 1)]["vigente_de"] == HOJE


def test_data_publicacao_invalida_vai_para_quarentena(aurora):
    escreve_proposta(aurora, "d1", [{"cnpj": CNPJ, "tipo": "nova", "titulo": "X", "trecho_citado": "t",
                                     "recorrencia": "por_evento"}])
    alvo = Path(etl.landing(aurora["lake"], "propostas_llm", "2026-11-07", "d1.json"))
    doc = json.loads(alvo.read_text()); doc["data_publicacao"] = "07/11/2026"; alvo.write_text(json.dumps(doc))
    roda(aurora, agora=datetime(2026, 11, 7, 14))
    c = [c for c in linhas(aurora, etl.SILVER_CANDIDATAS) if c["origem"] == "llm"][0]
    assert not c["valida"] and any("data_publicacao" in e for e in c["erros"])


# ---------------------------------------------------------------- contrato com ia/propostas

def test_arquivo_gerado_pelo_passo_de_propostas_entra_valido(aurora):
    """O passo de propostas do DOU (ia/propostas) grava este formato; o teste de lá confere que a
    fixture é exatamente o que ele gera. Aqui, o ETL tem de aceitá-lo sem quarentena."""
    gerado = RAIZ / "ia/propostas/tests/fixtures/proposta_dcr.json"
    copia(aurora, gerado, "propostas_llm", "2026-11-08", "dou-2026-11-07-s1-000013__KALMANTESTE100.json")
    nb, ns, _ = roda(aurora, agora=datetime(2026, 11, 8, 6))
    assert nb["matriz_propostas_llm"] == 1 and ns["quarentena"] == 0
    cand = [c for c in linhas(aurora, etl.SILVER_CANDIDATAS) if c["origem"] == "llm"]
    assert len(cand) == 1 and cand[0]["valida"], cand[0]["erros"]
    v2 = obrigacoes(aurora)[("OBR-013", 2)]
    assert v2["status"] == "proposta" and "31/03" in v2["prazo_json"] and v2["area_responsavel"] == "GCTR"
