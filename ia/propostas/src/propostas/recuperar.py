"""Etapa 1: dos vetores das consultas da empresa aos atos candidatos."""

from __future__ import annotations

from .atos import ato_da_chave


def recuperar(empresa: dict, consultas: list[dict], vetores: list[list[float]], indice, desde: int,
              top_k: int, limiar: float, maximo: int, ja_processados: set[str] | None = None) -> list[dict]:
    """Atos com trechos parecidos com alguma consulta. A nota do ato é a maior semelhança entre os
    seus trechos (1 - distância de cosseno); guarda também quais consultas o acharam."""
    ja = ja_processados or set()
    por_ato: dict[str, dict] = {}
    for consulta, vetor in zip(consultas, vetores):
        for r in indice.consultar(vetor, top_k, {"data": {"$gte": desde}}):
            sim = 1.0 - r["distancia"]
            if sim < limiar:
                continue
            meta = r.get("metadata") or {}
            ato_id = meta.get("ato_id") or ato_da_chave(r["key"])
            if ato_id in ja:
                continue
            a = por_ato.setdefault(ato_id, {"ato_id": ato_id, "score": 0.0, "trechos": {}, "consultas": []})
            a["score"] = max(a["score"], sim)
            t = a["trechos"].get(r["key"])
            if t is None or sim > t["sim"]:
                a["trechos"][r["key"]] = {"chave": r["key"], "sim": round(sim, 4), "texto": meta.get("texto", "")}
            a["consultas"].append({"origem": consulta["origem"], "sim": round(sim, 4),
                                   **{k: consulta[k] for k in ("obrigacao_id", "tema", "tipo") if k in consulta}})
    candidatos = sorted(por_ato.values(), key=lambda a: (-a["score"], a["ato_id"]))[:maximo]
    for a in candidatos:
        a["score"] = round(a["score"], 4)
        a["trechos"] = sorted(a["trechos"].values(), key=lambda t: -t["sim"])[:5]
        a["origens"] = sorted({c["origem"] for c in a["consultas"]})
    return candidatos


def limitar_pares(candidatos_por_cnpj: dict[str, list[dict]], maximo: int) -> list[tuple[str, dict]]:
    """Até `maximo` pares (empresa, ato), alternando entre as empresas pela ordem de nota: uma
    empresa com muitos candidatos não deixa as outras sem nenhum."""
    filas = {cnpj: list(c) for cnpj, c in sorted(candidatos_por_cnpj.items())}
    pares: list[tuple[str, dict]] = []
    while len(pares) < maximo and any(filas.values()):
        for cnpj, fila in filas.items():
            if fila and len(pares) < maximo:
                pares.append((cnpj, fila.pop(0)))
    return pares
