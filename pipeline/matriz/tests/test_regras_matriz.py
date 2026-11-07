"""Regras puras da matriz: prazos, tarefas, risco e versões."""

import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import regras_matriz as r  # noqa: E402

HOJE = date(2026, 11, 7)


def obrig(**kw):
    base = {"cnpj": "KALMANTESTE100", "obrigacao_id": "OBR-1", "versao": 1, "titulo": "Entregar X",
            "recorrencia": "periodica", "periodicidade": "anual", "aplica_a": [], "area_responsavel": "COMP"}
    base.update(kw)
    return base


# ---------------------------------------------------------------- prazo_json

@pytest.mark.parametrize("bruto", [
    '[{"unidade": "semanas", "referencia": "x"}]',
    '[{"unidade": "data_fixa", "referencia": "mes_seguinte", "valor": "31/03"}]',
    '[{"unidade": "data_fixa", "referencia": "ano_corrente", "valor": "31/02"}]',
    '[{"unidade": "dia_do_mes", "referencia": "mes_seguinte", "valor": "quinze"}]',
    '"texto"',
    "{nao json",
])
def test_prazo_json_invalido(bruto):
    with pytest.raises(ValueError):
        r.ler_prazo_json(bruto)


def test_prazo_json_aceita_objeto_unico_e_vazio():
    assert r.ler_prazo_json('{"unidade": "dias_antes", "referencia": "validade_outorga"}')[0]["unidade"] == "dias_antes"
    assert r.ler_prazo_json("") == [] and r.ler_prazo_json(None) == []


# ---------------------------------------------------------------- geração de tarefas

def vencimentos(o, outorgas=()):
    return [t["vencimento"] for t in r.gerar_tarefas(o, list(outorgas), HOJE)]


def test_anual_ano_seguinte_ao_exercicio():
    o = obrig(prazo_json='[{"unidade": "data_fixa", "referencia": "ano_seguinte_exercicio", "valor": "30/04"}]')
    ts = r.gerar_tarefas(o, [], HOJE)
    assert [t["vencimento"] for t in ts] == [date(2027, 4, 30)]
    assert ts[0]["descricao"] == "Entregar X — exercício 2026"


def test_mensal_dia_do_mes_seguinte_dentro_do_horizonte():
    o = obrig(periodicidade="mensal",
              prazo_json='[{"unidade": "dia_do_mes", "referencia": "mes_seguinte", "valor": "15"}]')
    v = vencimentos(o)
    assert v[0] == date(2026, 11, 15) and v[-1] == date(2027, 10, 15) and len(v) == 12


def test_dia_31_cai_no_fim_do_mes_curto():
    o = obrig(periodicidade="mensal",
              prazo_json='[{"unidade": "dia_do_mes", "referencia": "mes_corrente", "valor": "31"}]')
    assert date(2027, 2, 28) in vencimentos(o)


def test_trimestral_dias_apos_fim_do_trimestre():
    o = obrig(periodicidade="trimestral",
              prazo_json='[{"unidade": "dias_apos", "referencia": "fim_trimestre", "valor": "60"}]')
    assert vencimentos(o) == [date(2026, 11, 29), date(2027, 3, 1), date(2027, 5, 30), date(2027, 8, 29)]


def test_bienal_respeita_ano_base():
    o = obrig(periodicidade="bienal",
              prazo_json='[{"unidade": "data_fixa", "referencia": "ano_corrente", "valor": "30/06", "ano_base": 2027}]')
    assert vencimentos(o) == [date(2027, 6, 30)]
    o["prazo_json"] = '[{"unidade": "data_fixa", "referencia": "ano_corrente", "valor": "30/06", "ano_base": 2026}]'
    assert vencimentos(o) == []  # 2026 já passou, 2028 fora do horizonte


def test_uma_tarefa_por_unidade():
    o = obrig(aplica_a=["UN-02", "UN-04"],
              prazo_json='[{"unidade": "data_fixa", "referencia": "ano_corrente", "valor": "30/06"}]')
    ts = r.gerar_tarefas(o, [], HOJE)
    assert sorted(t["unidade_id"] for t in ts) == ["UN-02", "UN-04"]
    assert len({t["tarefa_id"] for t in ts}) == 2


OUTORGAS = [
    {"outorga_id": "OUT-01", "tipo": "licenca_operacao", "numero": "LO 1", "unidade_id": "UN-02",
     "validade": date(2027, 3, 10), "antecedencia_renovacao_dias": 120},
    {"outorga_id": "OUT-04", "tipo": "avcb", "numero": "AVCB 1", "unidade_id": "UN-01",
     "validade": "2027-08-15", "antecedencia_renovacao_dias": 60},
    {"outorga_id": "OUT-02", "tipo": "contrato_concessao", "unidade_id": "UN-01",
     "validade": date(2042, 3, 14), "antecedencia_renovacao_dias": 1095},
]


def test_ligada_a_outorga_usa_validade_menos_antecedencia():
    o = obrig(prazo_json='[{"unidade": "dias_antes", "referencia": "validade_outorga", "tipo_outorga": "licenca_operacao"}]')
    ts = r.gerar_tarefas(o, OUTORGAS, HOJE)
    assert len(ts) == 1 and ts[0]["vencimento"] == date(2026, 11, 10)
    assert ts[0]["outorga_id"] == "OUT-01" and ts[0]["unidade_id"] == "UN-02"


def test_outorga_com_valor_fixo_e_fora_do_horizonte():
    o = obrig(prazo_json='[{"unidade": "dias_antes", "referencia": "validade_outorga", "valor": "30"}]')
    assert sorted(vencimentos(o, OUTORGAS)) == [date(2027, 2, 8), date(2027, 7, 16)]  # concessão fica de fora


def test_por_evento_e_continua_nao_geram():
    assert vencimentos(obrig(recorrencia="por_evento")) == []
    assert vencimentos(obrig(recorrencia="continua")) == []


def test_tarefa_id_deterministico():
    a = r.tarefa_id("C", "O", "U", None, date(2027, 1, 1))
    assert a == r.tarefa_id("C", "O", "U", None, date(2027, 1, 1))
    assert a != r.tarefa_id("C", "O", "U", None, date(2027, 1, 2))


def test_em_risco():
    assert r.em_risco(date(2026, 11, 14), "aberta", HOJE)
    assert not r.em_risco(date(2026, 11, 15), "aberta", HOJE)
    assert r.em_risco(date(2026, 11, 1), "em_andamento", HOJE)          # atrasada
    assert not r.em_risco(date(2026, 11, 10), "concluida", HOJE)
    assert r.em_risco(date(2027, 4, 30), "aberta", HOJE, proposta_pendente=True)


# ---------------------------------------------------------------- consolidação

def tarefa(tid, venc, versao=1, status="aberta", obrig_id="OBR-1"):
    return {"cnpj": "C", "tarefa_id": tid, "obrigacao_id": obrig_id, "obrigacao_versao": versao,
            "unidade_id": None, "outorga_id": None, "descricao": "x", "vencimento": venc,
            "area_responsavel": "COMP", "status": status}


def test_consolidar_mantem_concluidas_atrasadas_e_status():
    geradas = [tarefa("nova", date(2027, 1, 1), versao=2)]
    anteriores = [
        tarefa("feita", date(2026, 10, 1), status="concluida"),
        tarefa("atrasada", date(2026, 11, 1), versao=2),
        tarefa("versao-velha", date(2027, 4, 30), versao=1),
        tarefa("nova", date(2027, 1, 1), versao=2, status="em_andamento"),
    ]
    final = {t["tarefa_id"]: t for t in r.consolidar_tarefas(
        geradas, anteriores, {}, {("C", "OBR-1"): 2}, set(), HOJE)}
    assert set(final) == {"nova", "feita", "atrasada"}
    assert final["nova"]["status"] == "em_andamento"
    assert final["atrasada"]["em_risco"] and not final["feita"]["em_risco"]


def test_consolidar_aplica_decisao_de_status():
    geradas = [tarefa("t1", date(2026, 11, 10))]
    dec = {"t1": {"status": "concluida", "evidencia_url": "s3://e", "em": datetime(2026, 11, 7, 12)}}
    t = r.consolidar_tarefas(geradas, [], dec, {}, set(), HOJE)[0]
    assert t["status"] == "concluida" and t["evidencia_url"] == "s3://e" and not t["em_risco"]


# ---------------------------------------------------------------- versões

LINHA = {"obrigacao_id": "OBR-1", "titulo": "Entregar X", "recorrencia": "periodica", "periodicidade": "anual",
         "prazo_json": '[{"unidade": "data_fixa", "referencia": "ano_corrente", "valor": "30/04"}]',
         "aplica_a": ["UN-01"], "criticidade": "alta", "area_responsavel": "COMP"}


def test_importacao_idempotente_e_alteracao_gera_versao():
    m = r.Matriz()
    m.importacao("C", [LINHA], HOJE, "m.csv")
    m.importacao("C", [dict(LINHA)], HOJE, "m.csv")
    assert len(m.linhas()) == 1 and m.vigente("C", "OBR-1")["status"] == "aprovada"
    m.importacao("C", [{**LINHA, "criticidade": "media"}], HOJE, "m2.csv")
    v1, v2 = m.versoes[("C", "OBR-1")]
    assert (v1["vigente"], v2["vigente"]) == (False, True) and v2["mudanca"] == "alteracao"
    assert "criticidade" in m.historico[-1]["resumo"]


def proposta(mudanca, pid="ato#0", **kw):
    return {"cnpj": "C", "obrigacao_id": "OBR-1", "mudanca": mudanca, "proposta_id": pid, "origem": "llm",
            "fonte_ato": "ato", "confianca": 0.9, **kw}


def test_proposta_de_alteracao_aprovada_vira_vigente():
    m = r.Matriz()
    m.importacao("C", [LINHA], HOJE, "m.csv")
    v2 = m.proposta(proposta("alteracao", prazo_json='[{"unidade": "data_fixa", "referencia": "ano_corrente", "valor": "31/03"}]'), HOJE)
    assert v2["status"] == "proposta" and not v2["vigente"] and v2["titulo"] == "Entregar X"
    assert m.proposta(proposta("alteracao"), HOJE) is None  # mesma proposta_id: ignorada
    assert ("C", "OBR-1") in m.pendentes()
    m.decisao("C", "OBR-1", 2, "aprovar", "dono", datetime(2026, 11, 8, 10))
    assert m.vigente("C", "OBR-1")["versao"] == 2 and m.pendentes() == set()
    assert m.decisao("C", "OBR-1", 2, "rejeitar", "dono", datetime(2026, 11, 8)) is None  # já decidida
    assert [h["evento"] for h in m.historico] == ["inclusao", "alteracao", "aprovacao"]


def test_revogacao_aprovada_e_rejeicao():
    m = r.Matriz()
    m.importacao("C", [LINHA], HOJE, "m.csv")
    m.proposta(proposta("revogacao", pid="a#0"), HOJE)
    m.decisao("C", "OBR-1", 2, "aprovar", "dono", datetime(2026, 11, 8))
    assert m.vigente("C", "OBR-1") is None and m.versoes[("C", "OBR-1")][1]["status"] == "revogada"

    m = r.Matriz()
    m.importacao("C", [LINHA], HOJE, "m.csv")
    m.proposta(proposta("alteracao", pid="b#0", criticidade="baixa"), HOJE)
    m.decisao("C", "OBR-1", 2, "rejeitar", "dono", datetime(2026, 11, 8))
    assert m.vigente("C", "OBR-1")["versao"] == 1 and m.versoes[("C", "OBR-1")][1]["status"] == "rejeitada"


def test_alteracao_de_obrigacao_inexistente_e_ignorada():
    assert r.Matriz().proposta(proposta("alteracao"), HOJE) is None


# ---------------------------------------------------------------- linha do tempo e vigência

def test_alteracao_registra_antes_e_depois_e_o_ato():
    import json as _json
    m = r.Matriz()
    m.importacao("C", [LINHA], date(2026, 11, 1), "m.csv")
    m.proposta(proposta("alteracao", prazo_regra="Até 31/03", fonte_url="https://dou/1", data_ato=date(2026, 11, 7),
                        trecho_citado="até 31 de março",
                        prazo_json='[{"unidade": "data_fixa", "referencia": "ano_corrente", "valor": "31/03"}]'), HOJE)
    h = m.historico[-1]
    assert h["evento"] == "alteracao" and h["ato_id"] == "ato" and h["ato_url"] == "https://dou/1"
    assert h["data_ato"] == date(2026, 11, 7) and h["trecho_citado"] == "até 31 de março"
    alt = {a["campo"]: a for a in _json.loads(h["alteracoes"])}
    assert set(alt) == {"prazo_json", "prazo_regra", "trecho_citado", "fonte_url", "fonte_ato"}
    assert "30/04" in alt["prazo_json"]["antes"] and "31/03" in alt["prazo_json"]["depois"]
    assert alt["prazo_regra"] == {"campo": "prazo_regra", "antes": None, "depois": "Até 31/03"}


def test_vigencia_abre_e_fecha_com_as_decisoes():
    m = r.Matriz()
    m.importacao("C", [LINHA], date(2026, 11, 1), "m.csv")
    m.proposta(proposta("alteracao", criticidade="media"), HOJE)
    # 02:00 UTC de 10/11 ainda é 09/11 em Brasília
    m.decisao("C", "OBR-1", 2, "aprovar", "dono", datetime(2026, 11, 10, 2))
    v1, v2 = m.versoes[("C", "OBR-1")]
    assert (v1["vigente_de"], v1["vigente_ate"]) == (date(2026, 11, 1), date(2026, 11, 9))
    assert (v2["vigente_de"], v2["vigente_ate"]) == (date(2026, 11, 9), None)
    assert r.vigente_em(m.versoes[("C", "OBR-1")], date(2026, 11, 5)) is v1
    assert r.vigente_em(m.versoes[("C", "OBR-1")], date(2026, 11, 9)) is v2
    assert r.vigente_em(m.versoes[("C", "OBR-1")], date(2026, 10, 1)) is None
    m.proposta(proposta("revogacao", pid="rev#0"), HOJE)
    m.decisao("C", "OBR-1", 3, "aprovar", "dono", datetime(2026, 12, 1, 15))
    assert v2["vigente_ate"] == date(2026, 12, 1) and r.vigente_em(m.versoes[("C", "OBR-1")], date(2026, 12, 2)) is None
    assert [h["evento"] for h in m.historico] == ["inclusao", "alteracao", "aprovacao", "revogacao", "aprovacao"]


def test_rejeicao_nao_mexe_na_vigencia():
    m = r.Matriz()
    m.importacao("C", [LINHA], date(2026, 11, 1), "m.csv")
    m.proposta(proposta("alteracao", criticidade="media"), HOJE)
    m.decisao("C", "OBR-1", 2, "rejeitar", "dono", datetime(2026, 11, 8, 12))
    v1, v2 = m.versoes[("C", "OBR-1")]
    assert v1["vigente"] and v1["vigente_ate"] is None and v2["vigente_de"] is None
