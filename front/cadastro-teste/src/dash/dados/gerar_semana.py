"""Gera src/dash/dados/semana-2026-11.json (front do dash) a partir do benchmark do torre-regulatoria.

Uso: python -X utf8 gerar_semana.py <pasta benchmark> <saida.json>
Fonte: dados/semana-2026-11.jsonl (1.931 atos reais da seção 1 do DOU, 03 a 06/11/2026) e
resultados/kalman-pipeline-v2-qwen-semana.jsonl (triagem Llama + decisão Qwen, prompt v2).
"""
import collections
import json
import random
import re
import sys
from pathlib import Path

base, saida = Path(sys.argv[1]), Path(sys.argv[2])
atos = {str(a["id"]): a for a in map(json.loads, open(base / "dados/semana-2026-11.jsonl", encoding="utf-8"))}
pipe = [json.loads(l) for l in open(base / "resultados/kalman-pipeline-v2-qwen-semana.jsonl", encoding="utf-8")]


def curto(t, n):
    t = re.sub(r"\s+", " ", t or "").strip()
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0] + "…"


def orgao(o):
    o = o or ""
    if "Energia Elétrica" in o: return "ANEEL"
    if "Supremo" in o: return "STF"
    if "Minas e Energia" in o: return "MME"
    if "Fazenda" in o: return "Fazenda"
    return o.split("/")[-1][:40] if "/" in o else o[:40]


def ident(a):
    i = (a.get("identifica") or "").strip()
    if not i: return "Registro sem título (continuação de ato anterior)"
    return curto(i.title() if i.isupper() else i, 90)


CAT_DECISAO = [
    ("Usina ou geração de outro agente", r"usina|ufv|uhe|eol|pch|cgh|ute|gera[çc][ãa]o|eólic|fotovolt|solar|hidrel|termel"),
    ("Transmissão", r"transmiss"),
    ("Outra distribuidora", r"distribuidora|concession[áa]ria|permission[áa]ria|cooperativa"),
    ("Comercialização ou mercado", r"comercializ|ccee|leil[ãa]o"),
]


def categoria(s, a):
    if "triagem" in (s.get("motivo") or ""):
        return "Outro assunto (triagem)"
    alvo = f"{s.get('destinatario', '')} {s.get('o_que_determina', '')}".lower()
    if orgao(a["orgao"]) not in ("ANEEL", "MME"):
        return "Outro setor"
    for nome, rx in CAT_DECISAO:
        if re.search(rx, alvo): return nome
    return "Sem efeito para a empresa"


dias = collections.OrderedDict()
for a in sorted(atos.values(), key=lambda a: a["data"]):
    dias.setdefault(a["data"], {"data": a["data"], "atos": 0, "triagem": 0, "obrigacao": 0, "acompanhar": 0})["atos"] += 1

alertas, descartes, cats = [], [], collections.Counter()
for p in pipe:
    s, a = p["saida"] or {}, atos[str(p["id"])]
    d = dias[a["data"]]
    if "triagem" not in (s.get("motivo") or ""): d["triagem"] += 1
    if s.get("decisao") in ("obrigacao", "acompanhar"):
        d[s["decisao"]] += 1
        alertas.append({
            "id": str(p["id"]), "data": a["data"], "orgao": orgao(a["orgao"]), "tipo": a.get("tipo"),
            "identifica": ident(a), "ementa": curto(a.get("ementa"), 220), "pagina": a.get("pagina"),
            "url": a.get("url_pdf"), "decisao": s["decisao"], "destinatario": curto(s.get("destinatario"), 120),
            "o_que_determina": curto(s.get("o_que_determina"), 220), "motivo": curto(s.get("motivo"), 240),
            "trecho": curto(s.get("trecho"), 300), "prazo": s.get("prazo"), "unidade": s.get("unidade"),
            "altera_norma": s.get("altera_norma"), "confianca": s.get("confianca"),
        })
    else:
        c = categoria(s, a)
        cats[c] += 1
        descartes.append({"id": str(p["id"]), "data": a["data"], "orgao": orgao(a["orgao"]), "identifica": ident(a),
                          "categoria": c, "motivo": curto(s.get("motivo", "").replace("barrado na triagem: ", "Triagem: "), 200)})

# amostra: todos os descartes da ANEEL/MME (os interessantes) + 40 sorteados do resto (semente fixa)
random.seed(20261107)
setor = random.sample([x for x in descartes if x["orgao"] in ("ANEEL", "MME")], 60)
resto = random.sample([x for x in descartes if x["orgao"] not in ("ANEEL", "MME")], 40)
amostra = sorted(setor + resto, key=lambda x: (x["data"], x["id"]))

json.dump({
    "_fonte": "torre-regulatoria/benchmark: semana real do DOU (seção 1, 03 a 06/11/2026) e saída do pipeline do Kalman "
              "(triagem Llama 3.3 + decisão Qwen3, prompt v2). Gabarito provisório por IA. Gerado por gerar_semana.py.",
    "dias": list(dias.values()),
    "alertas": sorted(alertas, key=lambda x: (x["data"], x["decisao"] != "obrigacao")),
    "descartes": {"total": len(descartes), "categorias": cats.most_common(), "amostra": amostra},
}, open(saida, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
print(json.dumps(list(dias.values()), ensure_ascii=False), len(alertas), cats.most_common(), len(amostra))
