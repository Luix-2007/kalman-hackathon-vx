"""
Amostra de atos do DOU para rotular (relevante ou não para uma empresa).

    uv run python propostas/rotulagem/amostra.py --contar
    uv run python propostas/rotulagem/amostra.py                 # grava em amostra-<hoje>/
    uv run python propostas/rotulagem/amostra.py --resto 200 --semente 7

Para medir uma busca por relevância não basta rotular o que ela já pega: o que ela deixa de
fora só aparece se houver atos de fora no conjunto. A amostra tem dois grupos:

    orgao_do_perfil  todos os atos de órgãos ligados ao perfil da empresa (ORGAOS abaixo)
    resto            amostra aleatória, de tamanho fixo, de todos os outros atos

Saída em `amostra-AAAA-MM-DD/`, que vai para o git. O lake ganha atos todo dia, então sortear de
novo daria outra amostra: depois de gerada, ela fica congelada e o arquivo rotulado é commitado no
mesmo lugar. O script não sobrescreve uma pasta que já tem amostra (--sobrescrever força).
    rotulagem.csv  o que a pessoa preenche. Linhas embaralhadas e SEM o grupo, para ela
                   não ser influenciada pelo órgão. Preencher: relevante (sim/nao),
                   tipo_mudanca (inclusao/alteracao/revogacao) e obrigacao_alvo.
    grupos.csv     ato_id -> grupo, para cruzar depois com o que for rotulado.

Lê silver_db.dou_atos pelo Athena (só leitura), com as credenciais AWS do ambiente.
"""

from __future__ import annotations

import argparse
import csv
import random
import time
import unicodedata
from collections import Counter
from datetime import date
from pathlib import Path

REGION = "us-east-1"
WORKGROUP = "lakehouse-pipeline-lakehouse"
DATABASE = "silver_db"
TRECHO = 700   # caracteres do início do texto que vão para a planilha

# Órgãos do perfil da KALMANTESTE100 (energia elétrica, SP e MG), como aparecem no DOU: o órgão
# vem como caminho ("Ministério .../Agência .../Superintendência ..."), então se procura um
# trecho do nome, sem acento nem maiúsculas. CETESB, SP Águas e CBPMESP são estaduais e não
# entram aqui. Os dois últimos cobrem temas do perfil (licenciamento, recursos hídricos).
ORGAOS = {
    "ANEEL": "agencia nacional de energia eletrica",
    "ONS": "operador nacional do sistema",
    "CCEE": "camara de comercializacao de energia",
    "MTE": "ministerio do trabalho e emprego",
    "RFB": "receita federal",
    "IBAMA": "instituto brasileiro do meio ambiente",
    "ANA": "agencia nacional de aguas",
}

COLUNAS_ROTULAGEM = ["ato_id", "data_publicacao", "secao", "tipo", "orgao", "identifica", "ementa",
                     "url_pdf", "tamanho", "trecho", "relevante", "tipo_mudanca", "obrigacao_alvo",
                     "observacao"]


def normalizar(texto: str | None) -> str:
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return sem_acento.lower()


def orgao_do_perfil(orgao: str | None) -> str | None:
    """Sigla do órgão do perfil que aparece no caminho do órgão do ato, ou None."""
    caminho = normalizar(orgao)
    return next((sigla for sigla, trecho in ORGAOS.items() if trecho in caminho), None)


def montar_amostra(atos: list[dict], n_resto: int, semente: int) -> list[tuple[dict, str, str]]:
    """[(ato, grupo, sigla)] embaralhado: todos os dos órgãos do perfil e `n_resto` dos outros."""
    do_perfil, resto = [], []
    for ato in atos:
        sigla = orgao_do_perfil(ato.get("orgao"))
        (do_perfil if sigla else resto).append((ato, sigla))
    sorteio = random.Random(semente)
    sorteados = sorteio.sample(resto, min(n_resto, len(resto)))
    amostra = [(a, "orgao_do_perfil", s) for a, s in do_perfil] + [(a, "resto", "") for a, _ in sorteados]
    sorteio.shuffle(amostra)
    return amostra


def consultar(sql: str) -> list[dict]:
    import boto3
    athena = boto3.client("athena", region_name=REGION)
    qid = athena.start_query_execution(
        QueryString=sql, WorkGroup=WORKGROUP, QueryExecutionContext={"Database": DATABASE})["QueryExecutionId"]
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(1)
    if st["State"] != "SUCCEEDED":
        raise SystemExit(f"consulta {st['State']}: {st.get('StateChangeReason', '')}")
    linhas, cabecalho = [], None
    for pagina in athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
        for r in pagina["ResultSet"]["Rows"]:
            valores = [c.get("VarCharValue") for c in r["Data"]]
            if cabecalho is None:
                cabecalho = valores
            else:
                linhas.append(dict(zip(cabecalho, valores)))
    return linhas


def ler_atos() -> list[dict]:
    return consultar(
        "SELECT id AS ato_id, data_publicacao, secao, tipo, orgao, identifica, ementa, url_pdf, "
        f"length(texto) AS tamanho, substr(texto, 1, {TRECHO}) AS trecho FROM dou_atos")


def limpar(valor: str | None) -> str:
    return " ".join((valor or "").split())


def gravar(amostra: list[tuple[dict, str, str]], pasta: Path, sobrescrever: bool = False) -> None:
    if (pasta / "rotulagem.csv").exists() and not sobrescrever:
        raise SystemExit(f"{pasta}/rotulagem.csv já existe (pode ter rótulos). "
                         "Use outra --saida ou --sobrescrever.")
    pasta.mkdir(parents=True, exist_ok=True)
    with open(pasta / "rotulagem.csv", "w", newline="", encoding="utf-8-sig") as f:   # utf-8-sig: abre bem no Excel
        w = csv.DictWriter(f, fieldnames=COLUNAS_ROTULAGEM)
        w.writeheader()
        for ato, _, _ in amostra:
            w.writerow({c: limpar(ato.get(c)) for c in COLUNAS_ROTULAGEM if c in ato} | {
                c: "" for c in ("relevante", "tipo_mudanca", "obrigacao_alvo", "observacao")})
    with open(pasta / "grupos.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ato_id", "grupo", "orgao_casou"])
        for ato, grupo, sigla in amostra:
            w.writerow([ato["ato_id"], grupo, sigla])


def resumo(atos: list[dict], amostra: list[tuple[dict, str, str]]) -> str:
    por_sigla = Counter(orgao_do_perfil(a.get("orgao")) for a in atos)
    por_tipo = Counter(a.get("tipo") for a, g, _ in amostra if g == "orgao_do_perfil")
    grupos = Counter(g for _, g, _ in amostra)
    linhas = [f"atos no lake: {len(atos)}",
              "por órgão do perfil: " + ", ".join(f"{s} {por_sigla[s]}" for s in ORGAOS),
              f"fora do perfil: {por_sigla[None]}",
              f"amostra: {len(amostra)} atos ({grupos['orgao_do_perfil']} dos órgãos do perfil + {grupos['resto']} do resto)",
              "tipos nos órgãos do perfil: " + ", ".join(f"{t} {n}" for t, n in por_tipo.most_common(6))]
    return "\n".join(linhas)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--resto", type=int, default=120, help="atos sorteados fora dos órgãos do perfil (padrão 120)")
    p.add_argument("--semente", type=int, default=42, help="semente do sorteio, para repetir a mesma amostra")
    p.add_argument("--saida", type=Path, default=Path(__file__).parent / f"amostra-{date.today():%Y-%m-%d}")
    p.add_argument("--sobrescrever", action="store_true", help="grava mesmo se a pasta já tiver uma amostra")
    p.add_argument("--contar", action="store_true", help="só mostra os números, sem gravar arquivos")
    args = p.parse_args()

    atos = ler_atos()
    amostra = montar_amostra(atos, args.resto, args.semente)
    print(resumo(atos, amostra))
    if not args.contar:
        gravar(amostra, args.saida, args.sobrescrever)
        print(f"gravado em {args.saida}/ (rotulagem.csv e grupos.csv)")


if __name__ == "__main__":
    main()
