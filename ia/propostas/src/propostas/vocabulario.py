"""Frases de busca para os temas do perfil regulatório (temas_interesse) e tipos de outorga."""

from __future__ import annotations

TEMAS = {
    "contabilidade_regulatoria": "contabilidade regulatória, demonstrações contábeis regulatórias e prestação de contas ao regulador",
    "qualidade_do_servico": "qualidade do serviço, indicadores de continuidade e metas de desempenho",
    "licenciamento_ambiental": "licenciamento ambiental, licença de operação e condicionantes ambientais",
    "recursos_hidricos": "outorga de direito de uso de recursos hídricos e cobrança pelo uso da água",
    "seguranca_barragens": "segurança de barragens, plano de segurança e inspeções de barragem",
    "seguranca_do_trabalho": "segurança e saúde no trabalho e normas regulamentadoras",
    "tarifas": "tarifas, reajuste e revisão tarifária, encargos setoriais",
    "societario": "obrigações societárias, assembleias e publicação de demonstrações financeiras",
    "telecomunicacoes": "serviços de telecomunicações e outorgas da Anatel",
    "petroleo_e_gas": "petróleo, gás natural e combustíveis regulados pela ANP",
}

OUTORGAS = {
    "licenca_operacao": "licença de operação",
    "licenca_instalacao": "licença de instalação",
    "licenca_previa": "licença prévia",
    "outorga_recursos_hidricos": "outorga de direito de uso de recursos hídricos",
    "autorizacao_aneel": "autorização da ANEEL",
    "concessao": "contrato de concessão",
    "avcb": "auto de vistoria do corpo de bombeiros",
}


def frase_tema(tema: str) -> str:
    return TEMAS.get(tema) or tema.replace("_", " ")


def frase_outorga(tipo: str) -> str:
    return OUTORGAS.get(tipo) or (tipo or "").replace("_", " ")
