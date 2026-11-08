"""Aviso de mudanças por e-mail: escape, seções que somem e o caso sem nada para avisar."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "src"))

import email_alerta  # noqa: E402

HOJE = "2026-11-08"

PROPOSTA = {
    "obrigacao_id": "OBR-006", "versao": 2, "mudanca": "alteracao",
    "titulo": "Responder o pedido de migração ao mercado livre",
    "fonte_ato": "REN ANEEL nº 1.174/2026", "fonte_dispositivo": "art. 166-A", "data_ato": "2026-11-04", "pagina": "68",
    "area_responsavel": "Comercial",
    "alteracoes": [{"campo": "prazo_regra", "antes": "10 dias úteis", "depois": "5 dias úteis"},
                   {"campo": "fonte_ato", "antes": "REN ANEEL nº 1.000/2021", "depois": "REN ANEEL nº 1.174/2026"}],
}
APROVADA = {"titulo": "Dar ao consumidor acesso aos próprios dados", "mudanca": "inclusao", "vigente_de": "2026-11-07"}
ATRASADA = {"descricao": "Recolher o PROINFA de outubro", "vencimento": "2026-11-07", "area_responsavel": "Financeiro",
            "status": "aberta"}
EM_2_DIAS = {"descricao": "Pagar a quota da CDE de novembro", "vencimento": "2026-11-10", "area_responsavel": "Financeiro",
             "status": "aberta"}


def test_sem_nada_nao_ha_email():
    assert email_alerta.montar({}) is None
    # a leitura do DOU sozinha e tarefas fora da janela de risco não geram aviso
    assert email_alerta.montar({
        "hoje": HOJE, "leitura": {"atos": 1931, "relevantes": 13},
        "tarefas": [{**EM_2_DIAS, "vencimento": "2026-11-20"}, {**ATRASADA, "status": "concluida"}],
    }) is None


def test_completo_tem_as_tres_secoes_e_o_antes_depois():
    e = email_alerta.montar({"empresa": "Light SESA", "hoje": HOJE, "painel_url": "https://kalman.example/painel",
                             "leitura": {"atos": 1931, "relevantes": 13},
                             "propostas": [PROPOSTA], "aprovadas": [APROVADA], "tarefas": [EM_2_DIAS, ATRASADA]})
    assert e["assunto"] == "Light SESA: 1 mudança para decidir · 2 tarefas em risco · 1 mudança aprovada"
    for parte in (e["html"], e["texto"]):
        assert "Para decidir" in parte or "PARA DECIDIR" in parte
        assert "1.931 atos lidos no DOU · 13 relevantes" in parte
        assert "REN ANEEL nº 1.174/2026 · art. 166-A · DOU 04/11/2026, p. 68" in parte
        assert "Atrasada há 1 dia" in parte and "Vence em 2 dias" in parte
    assert "10 dias úteis → 5 dias úteis" in e["texto"]
    assert "Revisar no painel" in e["html"] and 'href="https://kalman.example/painel"' in e["html"]
    # a fonte já aparece na linha da fonte: o antes/depois do ato não se repete
    assert "REN ANEEL nº 1.000/2021" not in e["texto"]
    # tarefa atrasada vem antes da que vence depois
    assert e["texto"].index("PROINFA") < e["texto"].index("CDE")
    assert "<title" not in e["html"] and "<h1" not in e["html"]


def test_secao_vazia_some():
    e = email_alerta.montar({"hoje": HOJE, "tarefas": [ATRASADA]})
    assert e["assunto"] == "Kalman: 1 tarefa em risco"
    assert "Tarefas em risco" in e["html"]
    for ausente in ("Para decidir", "Mudanças aprovadas", "Revisar no painel", "atos lidos"):
        assert ausente not in e["html"]
    assert "PARA DECIDIR" not in e["texto"] and "MUDANÇAS APROVADAS" not in e["texto"]

    so_aprovada = email_alerta.montar({"hoje": HOJE, "aprovadas": [APROVADA]})
    assert "Mudanças aprovadas" in so_aprovada["html"] and "Tarefas em risco" not in so_aprovada["html"]


def test_escapa_html_de_todo_dado():
    ataque = '<script>alert("x")</script>'
    e = email_alerta.montar({
        "empresa": ataque, "hoje": HOJE,
        "propostas": [{**PROPOSTA, "titulo": ataque, "trecho_citado": ataque, "fonte_ato": ataque,
                       "alteracoes": [{"campo": "prazo_regra", "antes": ataque, "depois": "<b>5</b>"}]}],
        "aprovadas": [{**APROVADA, "titulo": ataque, "aprovada_por": ataque}],
        "tarefas": [{**ATRASADA, "descricao": ataque, "area_responsavel": ataque}],
    })
    html = e["html"]
    assert "<script>" not in html and "<b>5</b>" not in html
    assert "&lt;script&gt;alert(&quot;x&quot;)&lt;/script&gt;" in html
    # texto puro não é HTML: vai como veio
    assert ataque in e["texto"]


def test_link_que_nao_e_http_some():
    e = email_alerta.montar({"hoje": HOJE, "painel_url": "javascript:alert(1)", "alertas_url": "https://x.example/a?b=1&c=2",
                             "propostas": [{**PROPOSTA, "fonte_url": 'https://dou.example/"onmouseover="x'}]})
    assert "javascript:" not in e["html"]
    assert "Revisar no painel" not in e["html"]  # sem painel válido, sem botão
    assert 'href="https://x.example/a?b=1&amp;c=2"' in e["html"]
    assert '"onmouseover="' not in e["html"]
