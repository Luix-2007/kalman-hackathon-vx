"""Configuração do passo de propostas, lida do ambiente da Lambda (ou passada na simulação)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

# Muda quando os prompts ou o formato pedido ao modelo mudam: vai em cada evento, para comparar.
VERSAO_PROMPT = "2026-11-08.3"

MODELO_EMBEDDING = "amazon.titan-embed-text-v2:0"
DIMENSAO = 1024
INDICE_ATOS = "dou-atos-v1"

PREFIXO_PROPOSTAS = "landing/matriz/propostas_llm"
PREFIXO_AUDITORIA = "audit/propostas"


@dataclass
class Config:
    lake_bucket: str = ""
    vector_bucket: str = ""
    indice_atos: str = INDICE_ATOS
    athena_workgroup: str = "lakehouse-pipeline-lakehouse"
    taxonomia_uri: str = ""
    modelo_triagem: str = "us.anthropic.claude-haiku-4-5-20251001-v1:0"
    modelo_extracao: str = "us.anthropic.claude-sonnet-5"
    regiao: str = "us-east-1"
    dias_indexar: int = 7               # atos publicados nos últimos N dias entram no índice
    max_trechos_por_execucao: int = 6000
    top_k: int = 8                      # trechos por consulta
    limiar_similaridade: float = 0.35   # abaixo disto o trecho não conta (1 - distância de cosseno)
    max_atos_por_empresa: int = 20
    max_pares: int = 300                # teto de (empresa, ato) por execução, para limitar custo
    limiar_confianca: float = 0.6       # proposta abaixo disto nem é gravada
    max_texto_extracao: int = 40000     # caracteres do ato que vão para a extração
    extras: dict = field(default_factory=dict)


def de_ambiente(env=os.environ) -> Config:
    c = Config(
        lake_bucket=env.get("LAKE_BUCKET", ""),
        vector_bucket=env.get("VECTOR_BUCKET", ""),
        indice_atos=env.get("INDICE_ATOS", INDICE_ATOS),
        athena_workgroup=env.get("ATHENA_WORKGROUP", "lakehouse-pipeline-lakehouse"),
        taxonomia_uri=env.get("TAXONOMIA_URI", ""),
        modelo_triagem=env.get("MODELO_TRIAGEM", Config.modelo_triagem),
        modelo_extracao=env.get("MODELO_EXTRACAO", Config.modelo_extracao),
        regiao=env.get("AWS_REGION", "us-east-1"),
    )
    for nome, tipo in (("dias_indexar", int), ("max_trechos_por_execucao", int), ("top_k", int),
                       ("limiar_similaridade", float), ("max_atos_por_empresa", int), ("max_pares", int),
                       ("limiar_confianca", float), ("max_texto_extracao", int)):
        valor = env.get(nome.upper())
        if valor not in (None, ""):
            setattr(c, nome, tipo(valor))
    if not c.taxonomia_uri and c.lake_bucket:
        c.taxonomia_uri = f"s3://{c.lake_bucket}/artefatos/cadastro/tipos_empresa.json"
    return c
