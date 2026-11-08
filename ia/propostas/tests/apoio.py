"""Peças falsas e fixtures para os testes do passo de propostas (sem AWS)."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import sys
import unicodedata
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[2]
sys.path.insert(0, str(AQUI.parent / "src"))

TAXONOMIA = RAIZ / "pipeline/cadastro/config/tipos_empresa.json"
CNPJ = "KALMANTESTE100"

# O ato da demo (fixtures/aurora/proposta_obr013.json): a ANEEL antecipa a entrega das DCR.
TRECHO_DCR = ("As Demonstrações Contábeis Regulatórias auditadas deverão ser entregues até 31 de março "
              "do ano seguinte ao exercício a que se referem.")
ATO_DCR = {
    "id": "dou-2026-11-07-s1-000013", "data_publicacao": "2026-11-07", "tipo": "Resolução Normativa",
    "orgao": "Ministério de Minas e Energia/Agência Nacional de Energia Elétrica/Diretoria",
    "identifica": "RESOLUÇÃO NORMATIVA ANEEL Nº 1.200, DE 5 DE NOVEMBRO DE 2026",
    "ementa": "Altera o prazo de entrega das Demonstrações Contábeis Regulatórias.",
    "url_pdf": "https://www.in.gov.br/dou-1",
    "texto": ("RESOLUÇÃO NORMATIVA ANEEL Nº 1.200 A DIRETORA-GERAL DA AGÊNCIA NACIONAL DE ENERGIA ELÉTRICA resolve: "
              "Art. 1º Esta Resolução altera o Manual de Contabilidade do Setor Elétrico. "
              f"Art. 2º {TRECHO_DCR} Art. 3º Esta Resolução entra em vigor na data de sua publicação."),
}
ATO_OUTRO = {
    "id": "52044471", "data_publicacao": "2026-11-05", "tipo": "Despacho",
    "orgao": "Ministério de Minas e Energia/Agência Nacional de Energia Elétrica/Superintendência de Fiscalização",
    "identifica": "DESPACHO Nº 4.130, DE 28 DE OUTUBRO DE 2026", "ementa": None, "url_pdf": "http://x",
    "texto": ("DESPACHO Nº 4.130 Processo nº 48500.024499/2025-01. Interessado: Mauê S.A. - Geradora. Decisão: Não "
              "reconhecer excludentes de responsabilidade no processo de implantação da PCH Alto Alegre."),
}
ATO_SAUDE = {
    "id": "52000001", "data_publicacao": "2026-11-04", "tipo": "Portaria",
    "orgao": "Ministério da Saúde/Gabinete do Ministro", "identifica": "PORTARIA Nº 9", "ementa": None,
    "url_pdf": "http://y", "texto": "Art. 1º Habilita o hospital municipal a receber recursos do fundo de saúde."
}


def empresa_aurora(tipo_empresa: str | None = "distribuidora_energia") -> dict:
    """A Aurora como dados.carregar_empresas a monta, a partir das fixtures do repositório."""
    dados = json.loads((RAIZ / "api/cnpj-cadastro/tests/aurora_dados.json").read_text(encoding="utf-8"))
    vigentes = []
    with open(RAIZ / "pipeline/matriz/fixtures/aurora/matriz.csv", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            vigentes.append({"obrigacao_id": r["obrigacao_id"], "titulo": r["titulo"], "orgao_sigla": r["orgao_sigla"],
                             "tema": r["tema"], "fonte_ato": r["fonte_ato"], "fonte_dispositivo": r["fonte_dispositivo"],
                             "trecho_citado": r["trecho_citado"], "prazo_regra": r["prazo_regra"],
                             "recorrencia": r["recorrencia"], "periodicidade": r["periodicidade"],
                             "aplica_a": [u.strip() for u in r["aplica_a"].replace(";", ",").split(",") if u.strip()],
                             "area_responsavel": r["area_responsavel"], "criticidade": r["criticidade"]})
    return {
        "cnpj": CNPJ, "razao_social": "AURORA ENERGIA SA", "setor": dados.get("setor"), "cnae_principal": "3514000",
        "cnaes": ["3514000", "3511501"], "ufs_atuacao": dados["ufs_atuacao"],
        "orgaos_fiscalizadores": dados["orgaos_fiscalizadores"], "temas_interesse": dados["temas_interesse"],
        "temas_fora_escopo": dados["temas_fora_escopo"], "area_padrao": "COMP",
        "atividade_principal": "Distribuição de energia elétrica",
        "atividades_secundarias": "Geração de energia elétrica", "tipo_empresa": tipo_empresa,
        "unidades": [{"id": u["id"], "nome": u["nome"], "tipo": u["tipo"], "tags": u.get("tags", [])} for u in dados["unidades"]],
        "areas": [{"id": a["id"], "nome": a["nome"]} for a in dados["areas"]],
        "outorgas": [{"id": o["id"], "tipo": o.get("tipo"), "orgao": o.get("orgao"), "objeto": o.get("objeto"),
                      "unidade_id": o.get("unidade_id")} for o in dados["outorgas"]],
        "vigentes": vigentes,
    }


def taxonomia() -> dict:
    return json.loads(TAXONOMIA.read_text(encoding="utf-8"))


def vetor_de(texto: str, dim: int = 1024) -> list[float]:
    """Saco de palavras com hash: textos com palavras em comum ficam próximos."""
    v = [0.0] * dim
    t = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode().lower()
    for palavra in re.findall(r"[a-z]{4,}", t):
        v[int(hashlib.md5(palavra.encode()).hexdigest(), 16) % dim] += 1.0
    n = math.sqrt(sum(x * x for x in v)) or 1.0
    return [x / n for x in v]


class EmbedderFalso:
    def __init__(self):
        self.textos: list[str] = []

    def embed(self, texto):
        self.textos.append(texto)
        return vetor_de(texto)

    def embed_varios(self, textos, paralelo=8):
        return [self.embed(t) for t in textos]


class BedrockFalso:
    """invoke_model (Titan) e converse (Claude com ferramenta). `respostas` decide o que cada
    ferramenta devolve: função (texto da mensagem) -> input da ferramenta."""

    def __init__(self, respostas: dict | None = None, erro: Exception | None = None):
        self.respostas = respostas or {}
        self.erro = erro
        self.conversas: list[dict] = []

    def invoke_model(self, modelId, body, contentType, accept):
        texto = json.loads(body)["inputText"]
        dado = json.dumps({"embedding": vetor_de(texto)}).encode()
        return {"body": io.BytesIO(dado)}

    def converse(self, **kw):
        if self.erro:
            raise self.erro
        self.conversas.append(kw)
        nome = kw["toolConfig"]["toolChoice"]["tool"]["name"]
        texto = kw["messages"][0]["content"][0]["text"]
        resposta = self.respostas.get(nome)
        if resposta is None:
            return {"output": {"message": {"content": [{"text": "não sei"}]}}, "stopReason": "end_turn"}
        return {"output": {"message": {"content": [{"toolUse": {"toolUseId": "t1", "name": nome,
                                                                "input": resposta(texto)}}]}},
                "stopReason": "tool_use", "usage": {"inputTokens": 10, "outputTokens": 5}}


def triagem_dcr(texto: str) -> dict:
    """Relevante só o ato das DCR; o despacho de outra empresa não."""
    dado = json.loads(texto)
    if "Contábeis Regulatórias" in (dado["ato"].get("ementa") or ""):
        return {"relevante": True, "motivo": "Muda o prazo das DCR, obrigação OBR-013 da empresa.",
                "tipo_mudanca": "alteracao", "obrigacao_alvo": "OBR-013", "confianca": 0.9}
    return {"relevante": False, "motivo": "Decisão sobre outra empresa.", "tipo_mudanca": "nenhuma", "confianca": 0.95}


def extracao_dcr(texto: str) -> dict:
    return {"propostas": [{
        "tipo": "alteracao", "obrigacao_id_alvo": "OBR-013", "fonte_dispositivo": "art. 2º",
        "trecho_citado": TRECHO_DCR, "orgao_sigla": "ANEEL", "tema": "contabilidade_regulatoria",
        "recorrencia": "periodica", "periodicidade": "anual", "prazo_regra": "Até 31 de março do ano seguinte ao exercício",
        "prazo_json": [{"unidade": "data_fixa", "referencia": "ano_seguinte_exercicio", "valor": "31/03"}],
        "area_sugerida": "GCTR", "criticidade": "alta", "confianca": 0.86}]}
