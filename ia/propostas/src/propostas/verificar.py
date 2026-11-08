"""Etapa 4: o que o modelo propôs é conferido em código antes de virar arquivo.

As regras são as do ETL da matriz (etl_matriz._validar), mais duas que só dá para checar aqui:
o trecho citado tem de estar no ato, e a confiança tem de passar do limiar. Uma proposta que
passa aqui não deve cair na quarentena do ETL (há um teste de contrato para isso)."""

from __future__ import annotations

import json

import regras_matriz as regras

from .atos import citacao_esta_no_texto

CAMPOS = ("tipo", "obrigacao_id_alvo", "titulo", "fonte_dispositivo", "trecho_citado", "orgao_sigla", "tema",
          "aplica_a", "recorrencia", "periodicidade", "prazo_regra", "prazo_json", "area_sugerida", "evidencia",
          "criticidade", "confianca")


def limpar(proposta: dict, cnpj: str) -> dict:
    """Só os campos do formato, sem texto vazio, com o CNPJ da empresa (nunca o que o modelo disser)."""
    p = {k: proposta.get(k) for k in CAMPOS if proposta.get(k) not in (None, "", [])}
    if isinstance(p.get("prazo_json"), str):
        try:
            p["prazo_json"] = json.loads(p["prazo_json"])
        except ValueError:
            pass
    return {"cnpj": cnpj, **p}


def verificar(p: dict, texto_ato: str, empresa: dict, limiar_confianca: float) -> list[str]:
    erros: list[str] = []
    tipo = p.get("tipo")
    if tipo not in ("nova", "alteracao", "revogacao"):
        erros.append(f"tipo inválido ({tipo})")
    vigentes = {v["obrigacao_id"] for v in empresa.get("vigentes", [])}
    if tipo in ("alteracao", "revogacao") and p.get("obrigacao_id_alvo") not in vigentes:
        erros.append(f"obrigação alvo {p.get('obrigacao_id_alvo')} não é vigente na empresa")
    if not citacao_esta_no_texto(p.get("trecho_citado"), texto_ato):
        erros.append("trecho_citado não está no texto do ato")
    if tipo == "nova" and not (p.get("titulo") or "").strip():
        erros.append("titulo é obrigatório")
    prazo: list[dict] = []
    if tipo != "revogacao":
        try:
            prazo = regras.ler_prazo_json(p.get("prazo_json"))
            if tipo == "nova" and p.get("recorrencia") == "periodica" and not prazo:
                erros.append("prazo_json vazio em obrigação periódica")
        except ValueError as exc:
            erros.append(str(exc))
    so_outorga = bool(prazo) and all(r["unidade"] == "dias_antes" for r in prazo)
    periodicas = [r["unidade"] for r in prazo if r["unidade"] != "dias_antes"]
    if periodicas and p.get("recorrencia") in ("por_evento", "continua"):
        # ex.: "em até 12 meses" escrito como dias_apos fim_mes 365 viraria uma tarefa por mês
        erros.append(f"regra periódica ({periodicas[0]}) em obrigação {p['recorrencia']}")
    if tipo == "nova" or p.get("recorrencia"):
        if p.get("recorrencia") not in regras.RECORRENCIAS:
            erros.append(f"recorrencia inválida ({p.get('recorrencia')})")
        elif p["recorrencia"] == "periodica" and not so_outorga and p.get("periodicidade") not in regras.PERIODICIDADES:
            erros.append(f"periodicidade inválida ({p.get('periodicidade')})")
    if p.get("criticidade") and p["criticidade"] not in regras.CRITICIDADES:
        erros.append(f"criticidade inválida ({p['criticidade']})")
    unidades = {u["id"] for u in empresa.get("unidades", [])}
    fora = [u for u in p.get("aplica_a") or [] if u not in unidades]
    if fora:
        erros.append(f"aplica_a com unidade inexistente: {', '.join(fora)}")
    conf = p.get("confianca")
    if not isinstance(conf, (int, float)) or conf < limiar_confianca:
        erros.append(f"confianca abaixo de {limiar_confianca} ({conf})")
    return erros


def ajustar_area(p: dict, empresa: dict) -> dict:
    """Área que não existe na empresa sai (o ETL usaria a padrão)."""
    if p.get("area_sugerida") and p["area_sugerida"] not in {a["id"] for a in empresa.get("areas", [])}:
        p = {k: v for k, v in p.items() if k != "area_sugerida"}
    return p
