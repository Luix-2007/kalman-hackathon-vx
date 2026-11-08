"""
Gera o preview do aviso de mudanças com dados fictícios: aviso-mudancas.html e aviso-mudancas.txt nesta pasta.

    python api/alertas/preview/gerar_preview.py      (ou, de api/: uv run python alertas/preview/gerar_preview.py)

Os casos saem de front/cadastro-teste/src/dash/dados.ts e da leitura real da semana (1.931 atos do DOU de 03 a
06/11/2026, 13 relevantes). A empresa, as pessoas, as tarefas e a decisão sobre a REN 1.175 são exemplo.
Data fixa (08/11/2026) para o preview não mudar de um dia para o outro.
"""

import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent / "src"))

import email_alerta  # noqa: E402

PAINEL = "http://localhost:5173/painel"  # o front ainda não tem endereço público

DADOS = {
    "empresa": "Light SESA",
    "hoje": "2026-11-08",
    "painel_url": PAINEL,
    "alertas_url": PAINEL + "?aba=alertas",
    "leitura": {"atos": 1931, "relevantes": 13, "periodo": "03 a 06/11"},
    "propostas": [
        {
            "obrigacao_id": "OBR-006", "versao": 2, "mudanca": "alteracao",
            "titulo": "Responder o pedido de migração ao mercado livre",
            "prazo_regra": "Até 5 dias úteis do recebimento da comunicação",
            "fonte_ato": "REN ANEEL nº 1.174/2026", "fonte_dispositivo": "art. 166-A da REN 1.000/2021",
            "data_ato": "2026-11-04", "pagina": "68",
            "fonte_url": "http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=04/11/2026&jornal=515&pagina=68",
            "area_responsavel": "Comercial",
            "trecho_citado": "A distribuidora tem o prazo de até 5 dias úteis, contados a partir do recebimento da "
                             "comunicação da migração prevista no art. 166, para verificar os requisitos técnicos e a "
                             "existência de motivos que impeçam a migração",
            "alteracoes": [
                {"campo": "prazo_regra", "antes": "Até 10 dias úteis do recebimento da comunicação",
                 "depois": "Até 5 dias úteis do recebimento da comunicação"},
                {"campo": "fonte_ato", "antes": "REN ANEEL nº 1.000/2021", "depois": "REN ANEEL nº 1.174/2026"},
                {"campo": "fonte_dispositivo", "antes": "art. 166", "depois": "art. 166-A da REN 1.000/2021"},
            ],
        },
        {
            "obrigacao_id": "OBR-014", "versao": 1, "mudanca": "inclusao",
            "titulo": "Destinar aos consumidores os créditos de PIS/Cofins restituídos",
            "prazo_regra": "10 anos da restituição do indébito ou da homologação da compensação",
            "fonte_ato": "STF · embargos na ADI 7324", "data_ato": "2026-11-04", "pagina": "1",
            "area_responsavel": "Financeiro",
        },
    ],
    "aprovadas": [
        {
            "obrigacao_id": "OBR-012", "versao": 1, "mudanca": "inclusao",
            "titulo": "Dar ao consumidor acesso aos próprios dados por interface padronizada",
            "fonte_ato": "REN ANEEL nº 1.175/2026", "fonte_dispositivo": "art. 22, I",
            "data_ato": "2026-11-04", "pagina": "91",
            "fonte_url": "http://pesquisa.in.gov.br/imprensa/jsp/visualiza/index.jsp?data=04/11/2026&jornal=515&pagina=91",
            "vigente_de": "2026-11-07", "aprovada_por": "Ana Ribeiro", "tarefas_criadas": 1,
        },
    ],
    # todas as tarefas abertas: o módulo separa as que estão em risco (atrasadas ou vencendo em até 3 dias)
    "tarefas": [
        {"tarefa_id": "T-001", "obrigacao_id": "OBR-005", "descricao": "Recolher o PROINFA de outubro",
         "vencimento": "2026-11-07", "area_responsavel": "Financeiro", "status": "aberta"},
        {"tarefa_id": "T-003", "obrigacao_id": "OBR-004", "descricao": "Pagar a quota da CDE de novembro",
         "vencimento": "2026-11-10", "area_responsavel": "Financeiro", "status": "aberta"},
        {"tarefa_id": "T-005", "obrigacao_id": "OBR-008", "descricao": "Liquidar a Conta Bandeiras de setembro na CCEE",
         "vencimento": "2026-11-12", "area_responsavel": "Financeiro", "status": "aberta"},
        {"tarefa_id": "T-007", "obrigacao_id": "OBR-005", "descricao": "Recolher o PROINFA de novembro",
         "vencimento": "2026-11-20", "area_responsavel": "Financeiro", "status": "aberta"},
        {"tarefa_id": "T-013", "obrigacao_id": "OBR-004", "descricao": "Pagar a quota da CDE de outubro",
         "vencimento": "2026-10-19", "area_responsavel": "Financeiro", "status": "concluida"},
    ],
}


def main() -> None:
    email = email_alerta.montar(DADOS)
    (AQUI / "aviso-mudancas.html").write_text(email["html"], encoding="utf-8")
    (AQUI / "aviso-mudancas.txt").write_text(f"Assunto: {email['assunto']}\n\n{email['texto']}", encoding="utf-8")
    print(f"Assunto: {email['assunto']}")
    print(f"HTML: {AQUI / 'aviso-mudancas.html'} ({len(email['html']):,} caracteres)")
    print(f"Texto: {AQUI / 'aviso-mudancas.txt'}")


if __name__ == "__main__":
    main()
