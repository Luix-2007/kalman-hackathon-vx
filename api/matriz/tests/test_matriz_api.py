"""
API da matriz com o DynamoDB no moto e um DuckDB no lugar do Athena.

O SQL que a API gera roda de verdade no DuckDB, em tabelas com as colunas da gold. Os
dados de partida saem das mesmas regras do job (regras_matriz): a OBR-009 (renovar a LO,
vence 10/11/2026) e a OBR-013 (DCR até 30/04) com a proposta do DOU que antecipa para 31/03.
"""

import filecmp
import importlib
import json
import sys
from datetime import date, datetime
from pathlib import Path

import boto3
import duckdb
import pytest
from moto import mock_aws

SRC = Path(__file__).parents[1] / "src"
sys.path.insert(0, str(SRC))
import athena  # noqa: E402
import regras_matriz as regras  # noqa: E402
import sql_matriz as sql  # noqa: E402

CNPJ = "KALMANTESTE100"
HOJE = date(2026, 11, 7)
AGORA = datetime(2026, 11, 7, 12)

DDL = """
CREATE SCHEMA gold_db; CREATE SCHEMA bronze_db;
CREATE MACRO json_format(x) AS CAST(x AS VARCHAR);
CREATE TABLE gold_db.matriz_obrigacoes (
  cnpj VARCHAR, obrigacao_id VARCHAR, versao INTEGER, titulo VARCHAR, fonte_ato VARCHAR,
  fonte_dispositivo VARCHAR, fonte_url VARCHAR, trecho_citado VARCHAR, orgao_sigla VARCHAR, tema VARCHAR,
  aplica_a VARCHAR[], recorrencia VARCHAR, periodicidade VARCHAR, prazo_regra VARCHAR, prazo_json VARCHAR,
  area_responsavel VARCHAR, evidencia VARCHAR, criticidade VARCHAR, origem VARCHAR, status VARCHAR,
  confianca DOUBLE, incluida_em DATE, alterada_por VARCHAR, vigente BOOLEAN, mudanca VARCHAR,
  proposta_id VARCHAR, hash_conteudo VARCHAR, decidida_por VARCHAR, decidida_em TIMESTAMP,
  data_ato DATE, vigente_de DATE, vigente_ate DATE);
CREATE TABLE gold_db.matriz_tarefas (
  cnpj VARCHAR, tarefa_id VARCHAR, obrigacao_id VARCHAR, obrigacao_versao INTEGER, unidade_id VARCHAR,
  outorga_id VARCHAR, descricao VARCHAR, vencimento DATE, area_responsavel VARCHAR, status VARCHAR,
  evidencia_url VARCHAR, em_risco BOOLEAN, atualizada_em TIMESTAMP);
CREATE TABLE gold_db.matriz_versoes (
  cnpj VARCHAR, obrigacao_id VARCHAR, versao INTEGER, evento VARCHAR, status VARCHAR, origem VARCHAR,
  ocorrido_em DATE, por VARCHAR, resumo VARCHAR, ato_id VARCHAR, ato_url VARCHAR, data_ato DATE,
  trecho_citado VARCHAR, alteracoes VARCHAR);
CREATE TABLE bronze_db.matriz_decisoes (
  decisao_id VARCHAR, tipo VARCHAR, cnpj VARCHAR, obrigacao_id VARCHAR, versao INTEGER, tarefa_id VARCHAR,
  decisao VARCHAR, evidencia_url VARCHAR, usuario VARCHAR, comentario VARCHAR, decidida_em TIMESTAMP);
"""

OUTORGAS = [{"id": "OUT-01", "tipo": "licenca_operacao", "numero": "LO 31004567", "orgao": "CETESB",
             "unidade_id": "UN-02", "validade": "2027-03-10", "antecedencia_renovacao_dias": 120}]
OBR = [
    {"obrigacao_id": "OBR-009", "titulo": "Pedir a renovação da Licença de Operação", "recorrencia": "periodica",
     "prazo_json": '[{"unidade": "dias_antes", "referencia": "validade_outorga", "tipo_outorga": "licenca_operacao"}]',
     "aplica_a": ["UN-02"], "area_responsavel": "GMA", "criticidade": "alta"},
    {"obrigacao_id": "OBR-013", "titulo": "Entregar as DCR", "recorrencia": "periodica", "periodicidade": "anual",
     "prazo_json": '[{"unidade": "data_fixa", "referencia": "ano_seguinte_exercicio", "valor": "30/04"}]',
     "aplica_a": ["UN-01"], "area_responsavel": "GCTR", "criticidade": "alta"},
]
PROPOSTA = {"cnpj": CNPJ, "obrigacao_id": "OBR-013", "mudanca": "alteracao", "proposta_id": "dou-1#0",
            "origem": "llm", "fonte_ato": "dou-1", "confianca": 0.86, "trecho_citado": "até 31 de março",
            "fonte_url": "https://www.in.gov.br/dou-1", "data_ato": date(2026, 11, 6), "prazo_regra": "Até 31/03",
            "prazo_json": '[{"unidade": "data_fixa", "referencia": "ano_seguinte_exercicio", "valor": "31/03"}]'}


class AthenaFalso:
    """consultar/executar/em_paralelo do módulo athena, rodando no DuckDB."""

    def __init__(self):
        self.con = duckdb.connect()
        self.con.execute(DDL)
        self.sqls: list[str] = []

    def consultar(self, q):
        self.sqls.append(q)
        try:
            cur = self.con.execute(q)
        except duckdb.CatalogException as exc:
            raise athena.TabelaInexistente(str(exc)) from exc
        nomes = [d[0] for d in cur.description]
        saida = []
        for linha in cur.fetchall():
            d = {}
            for n, v in zip(nomes, linha):
                if isinstance(v, datetime):
                    v = v.isoformat(sep=" ")
                elif isinstance(v, date):
                    v = v.isoformat()
                d[n] = v
            saida.append(d)
        return saida

    def executar(self, q):
        self.sqls.append(q)
        self.con.execute(q)

    def em_paralelo(self, *qs):
        for q in qs:
            self.executar(q)

    def inserir(self, tabela, linhas, colunas):
        for l in linhas:
            valores = [l.get(c) for c in colunas]
            self.con.execute(f"INSERT INTO {tabela} ({', '.join(colunas)}) VALUES ({', '.join('?' * len(colunas))})",
                             valores)

    def linhas(self, q):
        return self.consultar(q)


def gold_inicial(fake):
    m = regras.Matriz()
    m.importacao(CNPJ, OBR, date(2026, 11, 1), "matriz.csv")
    m.proposta(PROPOSTA, HOJE)
    outorgas = [{"cnpj": CNPJ, "outorga_id": o["id"], **o} for o in OUTORGAS]
    geradas = [t for v in m.linhas() if v["vigente"] for t in regras.gerar_tarefas(v, outorgas, HOJE)]
    tarefas = regras.consolidar_tarefas(geradas, [], {}, m.versoes_vigentes(), m.pendentes(), HOJE, AGORA)
    fake.inserir(sql.GOLD_OBRIGACOES, m.linhas(), sql.COLUNAS_OBRIGACAO)
    fake.inserir(sql.GOLD_TAREFAS, tarefas, sql.COLUNAS_TAREFA)
    fake.inserir(sql.GOLD_VERSOES, m.historico, sql.COLUNAS_HISTORICO)


@pytest.fixture
def api(monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    monkeypatch.setenv("TABLE_NAME", "t")
    with mock_aws():
        boto3.client("dynamodb").create_table(
            TableName="t", BillingMode="PAY_PER_REQUEST",
            AttributeDefinitions=[{"AttributeName": "user_id", "AttributeType": "S"}],
            KeySchema=[{"AttributeName": "user_id", "KeyType": "HASH"}])
        t = boto3.resource("dynamodb").Table("t")
        t.put_item(Item={"user_id": "dono", "cnpj": CNPJ, "papel": "dono"})
        t.put_item(Item={"user_id": "membro", "cnpj": CNPJ, "papel": "membro"})
        t.put_item(Item={"user_id": f"CNPJ#{CNPJ}", "cnpj": CNPJ, "dono": "dono", "dados": {"outorgas": OUTORGAS}})
        fake = AthenaFalso()
        gold_inicial(fake)
        for nome in ("consultar", "executar", "em_paralelo"):
            monkeypatch.setattr(athena, nome, getattr(fake, nome))
        import matriz_api
        mod = importlib.reload(matriz_api)
        monkeypatch.setattr(mod, "hoje_brasilia", lambda: HOJE)
        monkeypatch.setattr(mod, "agora_utc", lambda: datetime(2026, 11, 7, 15))
        mod.fake = fake
        yield mod


def chamar(api, sub, rota, corpo=None, id=None, query=None):
    ev = {"routeKey": rota, "requestContext": {"http": {"method": rota.split()[0]}}}
    if sub:
        ev["requestContext"]["authorizer"] = {"jwt": {"claims": {"sub": sub}}}
    if id:
        ev["pathParameters"] = {"id": id}
    if query:
        ev["queryStringParameters"] = query
    if corpo is not None:
        ev["body"] = corpo if isinstance(corpo, str) else json.dumps(corpo)
    r = api.handler(ev)
    return r["statusCode"], json.loads(r["body"])


def lo(api):
    return next(t for t in chamar(api, "dono", "GET /tarefas")[1]["tarefas"] if t["obrigacao_id"] == "OBR-009")


# ---------------------------------------------------------------- acesso

def test_sem_token_401_e_sem_organizacao_404(api):
    assert chamar(api, None, "GET /obrigacoes")[0] == 401
    assert chamar(api, "estranho", "GET /obrigacoes")[0] == 404


def test_membro_le_mas_nao_decide(api):
    assert chamar(api, "membro", "GET /obrigacoes")[0] == 200
    assert chamar(api, "membro", "GET /tarefas")[0] == 200
    assert chamar(api, "membro", "POST /obrigacoes/{id}/decisao", {"versao": 2, "decisao": "aprovar"}, id="OBR-013")[0] == 403
    assert chamar(api, "membro", "PATCH /tarefas/{id}", {"status": "concluida"}, id=lo(api)["tarefa_id"])[0] == 403


def test_id_com_injecao_400(api):
    assert chamar(api, "dono", "GET /obrigacoes/{id}", id="x' OR '1'='1")[0] == 400
    assert chamar(api, "dono", "GET /tarefas", query={"obrigacao_id": "x'--"})[0] == 400


# ---------------------------------------------------------------- leitura

def test_lista_vigentes_e_propostas(api):
    code, body = chamar(api, "dono", "GET /obrigacoes")
    assert code == 200 and body["resumo"] == {"vigentes": 2, "propostas": 1}
    chaves = [(o["obrigacao_id"], o["versao"], o["status"]) for o in body["obrigacoes"]]
    assert chaves == [("OBR-009", 1, "aprovada"), ("OBR-013", 1, "aprovada"), ("OBR-013", 2, "proposta")]
    assert body["obrigacoes"][0]["aplica_a"] == ["UN-02"]


def test_detalhe_traz_versoes_e_historico(api):
    code, body = chamar(api, "dono", "GET /obrigacoes/{id}", id="OBR-013")
    assert code == 200 and [v["versao"] for v in body["versoes"]] == [1, 2]
    assert [h["evento"] for h in body["historico"]] == ["inclusao", "alteracao"]
    assert chamar(api, "dono", "GET /obrigacoes/{id}", id="OBR-404")[0] == 404


def test_tarefas_em_risco(api):
    code, body = chamar(api, "dono", "GET /tarefas", query={"em_risco": "true"})
    assert code == 200
    assert {(t["obrigacao_id"], t["vencimento"]) for t in body["tarefas"]} == {
        ("OBR-009", "2026-11-10"), ("OBR-013", "2027-04-30")}


def test_matriz_nao_processada(api):
    api.fake.con.execute("DROP TABLE gold_db.matriz_tarefas; DROP TABLE gold_db.matriz_obrigacoes")
    code, body = chamar(api, "dono", "GET /tarefas")
    assert code == 200 and body["tarefas"] == [] and "aviso" in body
    assert chamar(api, "dono", "GET /obrigacoes")[1]["aviso"]


# ---------------------------------------------------------------- decisões

def test_aprovar_move_a_tarefa_para_31_03_na_hora(api):
    code, body = chamar(api, "dono", "POST /obrigacoes/{id}/decisao",
                        {"versao": 2, "decisao": "aprovar", "comentario": "ok, conferido"}, id="OBR-013")
    assert code == 200, body
    assert [(v["versao"], v["status"], v["vigente"]) for v in body["versoes"]] == [(1, "aprovada", False), (2, "aprovada", True)]
    assert [(t["vencimento"], t["em_risco"]) for t in body["tarefas"]] == [("2027-03-31", False)]

    # o que ficou gravado (o mesmo que o front lê depois)
    obs = api.fake.linhas("SELECT versao, status, vigente, decidida_por FROM gold_db.matriz_obrigacoes "
                          "WHERE obrigacao_id = 'OBR-013' ORDER BY versao")
    assert obs == [{"versao": 1, "status": "aprovada", "vigente": False, "decidida_por": None},
                   {"versao": 2, "status": "aprovada", "vigente": True, "decidida_por": "dono"}]
    tarefas = chamar(api, "dono", "GET /tarefas", query={"obrigacao_id": "OBR-013"})[1]["tarefas"]
    assert [t["vencimento"] for t in tarefas] == ["2027-03-31"]
    dec = api.fake.linhas("SELECT tipo, decisao, usuario, comentario, versao FROM bronze_db.matriz_decisoes")
    assert dec == [{"tipo": "obrigacao", "decisao": "aprovar", "usuario": "dono", "comentario": "ok, conferido", "versao": 2}]
    hist = chamar(api, "dono", "GET /obrigacoes/{id}", id="OBR-013")[1]["historico"]
    assert [h["evento"] for h in hist] == ["inclusao", "alteracao", "aprovacao"]
    # a outra obrigação não foi tocada
    assert lo(api)["vencimento"] == "2026-11-10"

    code, body = chamar(api, "dono", "POST /obrigacoes/{id}/decisao", {"versao": 2, "decisao": "rejeitar"}, id="OBR-013")
    assert code == 409


def test_rejeitar_mantem_30_04_sem_risco(api):
    code, body = chamar(api, "dono", "POST /obrigacoes/{id}/decisao", {"versao": 2, "decisao": "rejeitar"}, id="OBR-013")
    assert code == 200
    assert body["versoes"][1]["status"] == "rejeitada" and body["versoes"][0]["vigente"]
    assert [(t["vencimento"], t["em_risco"]) for t in body["tarefas"]] == [("2027-04-30", False)]


@pytest.mark.parametrize("corpo, status", [
    ({"versao": 2, "decisao": "talvez"}, 400),
    ({"versao": "2", "decisao": "aprovar"}, 400),
    ({"versao": 2, "decisao": "aprovar", "comentario": 5}, 400),
    ("{nao json", 400),
    ({"versao": 9, "decisao": "aprovar"}, 404),
    ({"versao": 1, "decisao": "aprovar"}, 409),
])
def test_decisao_invalida(api, corpo, status):
    assert chamar(api, "dono", "POST /obrigacoes/{id}/decisao", corpo, id="OBR-013")[0] == status


def test_concluir_tarefa(api):
    tid = lo(api)["tarefa_id"]
    code, body = chamar(api, "dono", "PATCH /tarefas/{id}",
                        {"status": "concluida", "evidencia_url": "https://x.example/protocolo.pdf"}, id=tid)
    assert code == 200 and body["tarefa"]["status"] == "concluida" and not body["tarefa"]["em_risco"]
    t = lo(api)
    assert t["status"] == "concluida" and t["evidencia_url"] == "https://x.example/protocolo.pdf" and not t["em_risco"]
    dec = api.fake.linhas("SELECT tipo, tarefa_id, decisao FROM bronze_db.matriz_decisoes")
    assert dec == [{"tipo": "tarefa", "tarefa_id": tid, "decisao": "concluida"}]


def test_reabrir_tarefa_com_proposta_pendente_continua_em_risco(api):
    dcr = next(t for t in chamar(api, "dono", "GET /tarefas")[1]["tarefas"] if t["obrigacao_id"] == "OBR-013")
    code, body = chamar(api, "dono", "PATCH /tarefas/{id}", {"status": "em_andamento"}, id=dcr["tarefa_id"])
    assert code == 200 and body["tarefa"]["em_risco"]


@pytest.mark.parametrize("corpo, id, status", [
    ({"status": "feita"}, None, 400),
    ({"status": "concluida", "evidencia_url": "javascript:alert(1)"}, None, 400),
    ({"status": "concluida"}, "0000000000000000", 404),
    ({"status": "concluida"}, "OBR-009", 400),
])
def test_tarefa_invalida(api, corpo, id, status):
    assert chamar(api, "dono", "PATCH /tarefas/{id}", corpo, id=id or lo(api)["tarefa_id"])[0] == status


# ---------------------------------------------------------------- peças

def test_texto_escapa_aspas_e_recusa_controle():
    assert sql.texto("d'água") == "'d''água'"
    with pytest.raises(sql.ValorInvalido):
        sql.texto("a\x00b")
    with pytest.raises(sql.ValorInvalido):
        sql.ident("1' OR '1'='1")


def test_regras_iguais_as_do_pipeline():
    pipeline = Path(__file__).parents[3] / "pipeline" / "matriz" / "src" / "regras_matriz.py"
    assert filecmp.cmp(SRC / "regras_matriz.py", pipeline, shallow=False), \
        "rode make -C pipeline/matriz sync-regras"


class ClienteFalso:
    def __init__(self, estados, paginas):
        self.estados, self.paginas, self.parou = list(estados), list(paginas), False

    def start_query_execution(self, **kw):
        return {"QueryExecutionId": "q1"}

    def get_query_execution(self, **kw):
        estado, motivo = self.estados.pop(0)
        return {"QueryExecution": {"Status": {"State": estado, "StateChangeReason": motivo}}}

    def get_query_results(self, **kw):
        return self.paginas.pop(0)

    def stop_query_execution(self, **kw):
        self.parou = True


def pagina(linhas, token=None, cabecalho=False):
    meta = {"ColumnInfo": [{"Name": "n", "Type": "integer"}, {"Name": "ok", "Type": "boolean"},
                           {"Name": "d", "Type": "date"}, {"Name": "x", "Type": "double"}]}
    rows = ([{"Data": [{"VarCharValue": c} for c in ("n", "ok", "d", "x")]}] if cabecalho else []) + \
        [{"Data": [{"VarCharValue": v} if v is not None else {} for v in l]} for l in linhas]
    p = {"ResultSet": {"ResultSetMetadata": meta, "Rows": rows}}
    if token:
        p["NextToken"] = token
    return p


def test_athena_converte_tipos_e_pagina(monkeypatch):
    cli = ClienteFalso([("RUNNING", ""), ("SUCCEEDED", "")],
                       [pagina([("1", "true", "2027-03-31", "0.5")], token="t", cabecalho=True),
                        pagina([("2", "false", None, None)])])
    monkeypatch.setattr(athena, "_client", cli)
    monkeypatch.setattr(athena.time, "sleep", lambda s: None)
    assert athena.consultar("SELECT 1") == [{"n": 1, "ok": True, "d": "2027-03-31", "x": 0.5},
                                            {"n": 2, "ok": False, "d": None, "x": None}]


def test_athena_erros(monkeypatch):
    monkeypatch.setattr(athena.time, "sleep", lambda s: None)
    monkeypatch.setattr(athena, "_client", ClienteFalso([("FAILED", "TABLE_NOT_FOUND: gold_db.x")], []))
    with pytest.raises(athena.TabelaInexistente):
        athena.consultar("SELECT 1")
    cli = ClienteFalso([("FAILED", "ICEBERG_COMMIT_ERROR"), ("SUCCEEDED", "")], [])
    monkeypatch.setattr(athena, "_client", cli)
    athena.executar("UPDATE x")          # tenta de novo e passa
    monkeypatch.setattr(athena, "_client", ClienteFalso([("FAILED", "SYNTAX_ERROR")], []))
    with pytest.raises(athena.ErroAthena):
        athena.executar("UPDATE x")


# ---------------------------------------------------------------- linha do tempo

def test_linha_do_tempo_mostra_o_que_o_ato_mudou(api):
    code, body = chamar(api, "dono", "GET /linha-do-tempo")
    assert code == 200
    ev = body["eventos"][0]   # o mais recente
    assert ev["evento"] == "alteracao" and ev["obrigacao_id"] == "OBR-013" and ev["titulo"] == "Entregar as DCR"
    assert ev["ato_id"] == "dou-1" and ev["ato_url"] == "https://www.in.gov.br/dou-1" and ev["data_ato"] == "2026-11-06"
    alt = {a["campo"]: a for a in ev["alteracoes"]}
    assert alt["prazo_regra"] == {"campo": "prazo_regra", "antes": None, "depois": "Até 31/03"}
    assert "30/04" in alt["prazo_json"]["antes"] and "31/03" in alt["prazo_json"]["depois"]
    assert {e["obrigacao_id"] for e in body["eventos"]} == {"OBR-009", "OBR-013"}


def test_linha_do_tempo_filtra_por_ato_e_obrigacao(api):
    assert [e["evento"] for e in chamar(api, "dono", "GET /linha-do-tempo", query={"ato_id": "dou-1"})[1]["eventos"]] == ["alteracao"]
    assert {e["obrigacao_id"] for e in chamar(api, "dono", "GET /linha-do-tempo",
                                                query={"obrigacao_id": "OBR-009"})[1]["eventos"]} == {"OBR-009"}
    assert chamar(api, "dono", "GET /linha-do-tempo", query={"ato_id": "x' OR 1=1 --"})[0] == 400


def test_aprovacao_entra_na_linha_do_tempo_com_o_ato_e_fecha_a_vigencia(api):
    chamar(api, "dono", "POST /obrigacoes/{id}/decisao", {"versao": 2, "decisao": "aprovar"}, id="OBR-013")
    ev = chamar(api, "dono", "GET /linha-do-tempo", query={"obrigacao_id": "OBR-013"})[1]["eventos"]
    assert [e["evento"] for e in ev] == ["aprovacao", "alteracao", "inclusao"]
    assert ev[0]["ato_id"] == "dou-1" and ev[0]["data_ato"] == "2026-11-06" and ev[0]["por"] == "dono"
    vig = api.fake.linhas("SELECT versao, vigente_de, vigente_ate FROM gold_db.matriz_obrigacoes "
                          "WHERE obrigacao_id = 'OBR-013' ORDER BY versao")
    assert vig == [{"versao": 1, "vigente_de": "2026-11-01", "vigente_ate": "2026-11-07"},
                   {"versao": 2, "vigente_de": "2026-11-07", "vigente_ate": None}]
    # como a matriz estava antes e depois
    antes = chamar(api, "dono", "GET /obrigacoes", query={"em": "2026-11-05"})[1]["obrigacoes"]
    depois = chamar(api, "dono", "GET /obrigacoes", query={"em": "2026-11-07"})[1]["obrigacoes"]
    assert [(o["obrigacao_id"], o["versao"]) for o in antes] == [("OBR-009", 1), ("OBR-013", 1)]
    assert [(o["obrigacao_id"], o["versao"]) for o in depois] == [("OBR-009", 1), ("OBR-013", 2)]
    assert chamar(api, "dono", "GET /obrigacoes", query={"em": "05/11/2026"})[0] == 400


def test_erro_do_athena_nao_vaza_detalhe(api, monkeypatch, caplog):
    segredo = "SYNTAX_ERROR: line 1:8: Column 'gold_db.matriz_obrigacoes.x' cannot be resolved"
    def falha(q):
        raise athena.ErroAthena(segredo)
    monkeypatch.setattr(athena, "consultar", falha)
    code, body = chamar(api, "dono", "GET /tarefas")
    assert code == 502 and body == {"erro": "não foi possível consultar a matriz agora, tente de novo"}
    assert "gold_db" not in json.dumps(body)
    assert segredo in caplog.text   # o motivo continua no log, para quem opera
