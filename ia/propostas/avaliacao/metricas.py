"""
Mede a busca e a triagem contra os atos rotulados à mão (rotulagem/amostra-*/rotulagem.csv).

    uv run python propostas/avaliacao/metricas.py \\
        --rotulos propostas/rotulagem/amostra-2026-11-08/rotulagem.csv \\
        --grupos propostas/rotulagem/amostra-2026-11-08/grupos.csv \\
        --simulacao /tmp/sim --cnpj KALMANTESTE100

A simulação (propostas/simular.py) deixa candidatos.json e os eventos da triagem. As perguntas:
  cobertura da busca   dos atos rotulados relevantes, quantos a busca trouxe? (o que ela perde)
                       separado por grupo: o "resto" mostra o que um filtro por órgão perderia
  precisão da busca    dos candidatos rotulados, quantos são relevantes?
  triagem              acertos e erros do modelo barato contra o rótulo
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def sim(valor: str | None) -> bool | None:
    v = (valor or "").strip().lower()
    if v in ("sim", "s", "1", "true", "relevante"):
        return True
    if v in ("nao", "não", "n", "0", "false", "irrelevante"):
        return False
    return None          # ainda não rotulado


def _taxa(a: int, b: int) -> float | None:
    return round(a / b, 3) if b else None


def calcular(rotulos: dict[str, bool], grupos: dict[str, str], candidatos: set[str],
             triagens: dict[str, bool]) -> dict:
    rotulados = {a: r for a, r in rotulos.items() if r is not None}
    relevantes = {a for a, r in rotulados.items() if r}
    por_grupo = {}
    for g in sorted(set(grupos.values()) | {"sem_grupo"}):
        rel_g = {a for a in relevantes if grupos.get(a, "sem_grupo") == g}
        if rel_g or g != "sem_grupo":
            por_grupo[g] = {"relevantes": len(rel_g), "achados": len(rel_g & candidatos),
                            "cobertura": _taxa(len(rel_g & candidatos), len(rel_g))}
    cand_rot = candidatos & set(rotulados)
    vp = sum(1 for a, t in triagens.items() if t and rotulados.get(a) is True)
    fp = sum(1 for a, t in triagens.items() if t and rotulados.get(a) is False)
    fn = sum(1 for a, t in triagens.items() if not t and rotulados.get(a) is True)
    vn = sum(1 for a, t in triagens.items() if not t and rotulados.get(a) is False)
    return {
        "rotulados": len(rotulados), "relevantes": len(relevantes),
        "busca": {"cobertura": _taxa(len(relevantes & candidatos), len(relevantes)),
                  "precisao": _taxa(len(cand_rot & relevantes), len(cand_rot)),
                  "por_grupo": por_grupo, "perdidos": sorted(relevantes - candidatos)},
        "triagem": {"verdadeiro_positivo": vp, "falso_positivo": fp, "falso_negativo": fn, "verdadeiro_negativo": vn,
                    "precisao": _taxa(vp, vp + fp), "cobertura": _taxa(vp, vp + fn),
                    "descartados_relevantes": sorted(a for a, t in triagens.items() if not t and rotulados.get(a) is True)},
    }


def ler_simulacao(pasta: Path, cnpj: str) -> tuple[set[str], dict[str, bool]]:
    candidatos = {c["ato_id"] for c in json.loads((pasta / "candidatos.json").read_text(encoding="utf-8")).get(cnpj, [])}
    triagens = {}
    for p in pasta.glob("audit/propostas/eventos/**/*.jsonl"):
        for linha in p.read_text(encoding="utf-8").splitlines():
            e = json.loads(linha)
            if e["etapa"] == "triar" and e["cnpj"] == cnpj:
                triagens[e["ato_id"]] = e["resultado"] == "relevante"
    return candidatos, triagens


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--rotulos", type=Path, required=True)
    p.add_argument("--grupos", type=Path, required=True)
    p.add_argument("--simulacao", type=Path, required=True)
    p.add_argument("--cnpj", default="KALMANTESTE100")
    args = p.parse_args()
    with open(args.rotulos, encoding="utf-8-sig") as f:
        rotulos = {r["ato_id"]: sim(r.get("relevante")) for r in csv.DictReader(f)}
    with open(args.grupos, encoding="utf-8") as f:
        grupos = {r["ato_id"]: r["grupo"] for r in csv.DictReader(f)}
    candidatos, triagens = ler_simulacao(args.simulacao, args.cnpj)
    resultado = calcular(rotulos, grupos, candidatos, triagens)
    if not resultado["rotulados"]:
        print("Nenhum ato rotulado ainda: preencha a coluna 'relevante' (sim/nao) do rotulagem.csv.")
    print(json.dumps(resultado, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
