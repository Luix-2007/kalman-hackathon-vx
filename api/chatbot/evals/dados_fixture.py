"""
Respostas fixas do Athena para as avaliações (a Aurora no dia da demo, antes de aprovar a
proposta que antecipa a entrega das DCR). Permitem medir o modelo sem depender do pipeline:
os mesmos dados em toda execução. Com --dados-reais o runner consulta o lake de verdade.

`responder(sql, params, extra)` escolhe as linhas pelo texto do SQL; `extra` (do caso) troca
as linhas de uma consulta, por exemplo para plantar uma instrução num texto de ato.
"""

from __future__ import annotations

import json

CNPJ = "KALMANTESTE100"

PAINEL = [{"cnpj": CNPJ, "razao_social": "AURORA ENERGIA S.A.", "situacao_cadastral": "Ativa",
           "status_cadastro": "ativa", "capital_social": "850000000.00", "qtd_socios": "0",
           "atos_no_dou": "2", "tipos_de_ato": "2", "ato_mais_recente": "2026-11-05"}]

ATOS = [
    {"data_publicacao": "2026-11-05", "tipo": "Resolução Normativa", "orgao": "ANEEL",
     "identifica": "RESOLUÇÃO NORMATIVA ANEEL Nº 1.200", "url_pdf": "https://www.in.gov.br/ato-1200",
     "ementa": "Altera prazos de envio das demonstrações contábeis regulatórias das concessionárias."},
    {"data_publicacao": "2026-10-20", "tipo": "Portaria", "orgao": "MTE",
     "identifica": "PORTARIA MTE Nº 88", "url_pdf": "https://www.in.gov.br/portaria-88",
     "ementa": "Atualiza a Norma Regulamentadora nº 10 sobre segurança em instalações elétricas."},
]

FRESCOR = [
    {"origem": "cadastro (DynamoDB)", "registros": "1", "mais_recente": "2026-11-07T21:00:00"},
    {"origem": "atos do DOU", "registros": "52310", "mais_recente": "2026-11-07"},
]

OBRIGACOES = [
    {"obrigacao_id": "OBR-001", "versao": "1", "titulo": "Enviar à ANEEL os indicadores de continuidade DEC e FEC",
     "orgao_sigla": "ANEEL", "tema": "qualidade_do_servico", "recorrencia": "periodica", "periodicidade": "mensal",
     "prazo_regra": "Até o dia 25 do mês seguinte", "area_responsavel": "GOPR", "criticidade": "alta",
     "status": "aprovada", "vigente": "true", "data_ato": "", "vigente_de": "2026-11-01", "vigente_ate": ""},
    {"obrigacao_id": "OBR-009", "versao": "1", "titulo": "Pedir a renovação da Licença de Operação",
     "orgao_sigla": "CETESB", "tema": "licenciamento_ambiental", "recorrencia": "periodica", "periodicidade": "",
     "prazo_regra": "120 dias antes do vencimento da licença", "area_responsavel": "GMA", "criticidade": "alta",
     "status": "aprovada", "vigente": "true", "data_ato": "", "vigente_de": "2026-11-01", "vigente_ate": ""},
    {"obrigacao_id": "OBR-013", "versao": "1",
     "titulo": "Entregar à ANEEL as Demonstrações Contábeis Regulatórias (DCR) auditadas",
     "orgao_sigla": "ANEEL", "tema": "contabilidade_regulatoria", "recorrencia": "periodica", "periodicidade": "anual",
     "prazo_regra": "Até 30 de abril do ano seguinte ao exercício", "area_responsavel": "GCTR", "criticidade": "alta",
     "status": "aprovada", "vigente": "true", "data_ato": "", "vigente_de": "2026-11-01", "vigente_ate": ""},
    {"obrigacao_id": "OBR-013", "versao": "2",
     "titulo": "Entregar à ANEEL as Demonstrações Contábeis Regulatórias (DCR) auditadas",
     "orgao_sigla": "ANEEL", "tema": "contabilidade_regulatoria", "recorrencia": "periodica", "periodicidade": "anual",
     "prazo_regra": "Até 31 de março do ano seguinte ao exercício", "area_responsavel": "GCTR", "criticidade": "alta",
     "status": "proposta", "vigente": "false", "data_ato": "2026-11-07", "vigente_de": "", "vigente_ate": ""},
    {"obrigacao_id": "OBR-019", "versao": "1", "titulo": "Realizar a eleição da CIPA",
     "orgao_sigla": "MTE", "tema": "seguranca_do_trabalho", "recorrencia": "periodica", "periodicidade": "anual",
     "prazo_regra": "Até 15 de setembro de cada ano", "area_responsavel": "GSST", "criticidade": "media",
     "status": "aprovada", "vigente": "true", "data_ato": "", "vigente_de": "2026-11-01", "vigente_ate": ""},
]

TAREFAS = [
    {"descricao": "Pedir a renovação da Licença de Operação — LO 31004567 (validade 10/03/2027)",
     "vencimento": "2026-11-10", "status": "aberta", "em_risco": "true", "area_responsavel": "GMA",
     "obrigacao_id": "OBR-009", "obrigacao_versao": "1"},
    {"descricao": "Enviar os indicadores de continuidade DEC e FEC — competência 11/2026",
     "vencimento": "2026-12-25", "status": "aberta", "em_risco": "false", "area_responsavel": "GOPR",
     "obrigacao_id": "OBR-001", "obrigacao_versao": "1"},
    {"descricao": "Entregar as DCR auditadas — exercício 2026", "vencimento": "2027-04-30", "status": "aberta",
     "em_risco": "true", "area_responsavel": "GCTR", "obrigacao_id": "OBR-013", "obrigacao_versao": "1"},
]

ALTERACOES_OBR013 = json.dumps([
    {"campo": "prazo_regra", "antes": "Até 30 de abril do ano seguinte ao exercício",
     "depois": "Até 31 de março do ano seguinte ao exercício"},
    {"campo": "fonte_ato", "antes": None, "depois": "dou-2026-11-07-s1-000013"},
], ensure_ascii=False)

LINHA_DO_TEMPO = [
    {"ocorrido_em": "2026-11-07", "obrigacao_id": "OBR-013",
     "titulo": "Entregar à ANEEL as Demonstrações Contábeis Regulatórias (DCR) auditadas", "versao": "2",
     "evento": "alteracao", "resumo": "alteração proposta pelo LLM: prazo_regra, fonte_ato",
     "ato_id": "dou-2026-11-07-s1-000013", "data_ato": "2026-11-07",
     "trecho_citado": "As Demonstrações Contábeis Regulatórias auditadas deverão ser entregues até 31 de março do ano seguinte ao exercício a que se referem.",
     "alteracoes": ALTERACOES_OBR013},
    {"ocorrido_em": "2026-11-01", "obrigacao_id": "OBR-013",
     "titulo": "Entregar à ANEEL as Demonstrações Contábeis Regulatórias (DCR) auditadas", "versao": "1",
     "evento": "inclusao", "resumo": "incluída pela matriz do cliente", "ato_id": "matriz_importada:matriz.csv",
     "data_ato": "", "trecho_citado": "", "alteracoes": ""},
    {"ocorrido_em": "2026-11-01", "obrigacao_id": "OBR-009", "titulo": "Pedir a renovação da Licença de Operação",
     "versao": "1", "evento": "inclusao", "resumo": "incluída pela matriz do cliente",
     "ato_id": "matriz_importada:matriz.csv", "data_ato": "", "trecho_citado": "", "alteracoes": ""},
]


def _param(params, i):
    return params[i].strip("'") if params and len(params) > i else None


def responder(sql: str, params: list, extra: dict | None = None) -> list[dict]:
    """Linhas que o Athena devolveria. `extra`: {"vw_empresas_atos": [...]} troca as de uma consulta."""
    s = " ".join(sql.lower().split())
    chaves = {
        "vw_painel_empresa": PAINEL, "vw_empresas_atos": ATOS, "vw_frescor": FRESCOR,
    }
    for chave, linhas in chaves.items():
        if chave in s:
            return (extra or {}).get(chave, linhas)
    if "from matriz_versoes" in s:
        alvo = _param(params, 1)
        base = (extra or {}).get("matriz_versoes", LINHA_DO_TEMPO)
        return [l for l in base if alvo is None or l["obrigacao_id"] == alvo]
    if "from matriz_tarefas" in s:
        base = (extra or {}).get("matriz_tarefas", TAREFAS)
        return [l for l in base if " and em_risco" not in s or l["em_risco"] == "true"]
    if "from matriz_obrigacoes" in s:
        base = (extra or {}).get("matriz_obrigacoes", OBRIGACOES)
        if "obrigacao_id = ?" in s:                       # obrigacao_detalhe
            return [l for l in base if l["obrigacao_id"] == _param(params, 1)]
        return [l for l in base if l["vigente"] == "true" or l["status"] == "proposta"]
    raise KeyError(f"consulta sem dados de fixture: {sql[:80]}")
