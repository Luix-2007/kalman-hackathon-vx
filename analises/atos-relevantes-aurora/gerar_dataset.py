"""
Dataset de atos do DOU relevantes para a Aurora Energia (KALMANTESTE100), para revisão humana.

Só lê: o perfil no DynamoDB (um GetItem) e os atos em silver_db.dou_atos (SELECT no Athena).
O Athena grava o resultado da consulta em --athena-output, como em qualquer consulta.

    # da raiz do repositório, com credenciais AWS válidas
    uv run --with boto3 python analises/atos-relevantes-aurora/gerar_dataset.py

    # sem AWS: atos de um arquivo .jsonl ou .csv com as colunas de silver_db.dou_atos
    uv run --with boto3 python analises/atos-relevantes-aurora/gerar_dataset.py --atos atos.jsonl --sem-perfil-ao-vivo

    # comparar com o dataset de outra pessoa (mesma chave de ato)
    uv run python analises/atos-relevantes-aurora/gerar_dataset.py --comparar outro.csv --chave-outro id --nivel-outro nivel

Saída em --saida (padrão: saida/ ao lado deste arquivo):
    atos_relevantes.csv   um ato por linha, do mais relevante para o menos, com colunas
                          vazias "revisao" e "comentario" para quem revisa
    descartados.csv       atos que casaram termos mas foram tirados (fora de escopo, órgão sem tema)
    resumo.md             perfil usado, critérios, período e contagens
    comparacao.csv        só com --comparar
"""

from __future__ import annotations

import argparse
import collections
import csv
import json
import re
import sys
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

AQUI = Path(__file__).resolve().parent
RAIZ = AQUI.parents[1]
REGION = "us-east-1"
PERFIL_BASE = RAIZ / "api" / "cnpj-cadastro" / "tests" / "aurora_dados.json"  # de onde os critérios saíram
CAMPOS_DO_PERFIL = ("setor", "ufs_atuacao", "municipios_atuacao", "orgaos_fiscalizadores",
                    "temas_interesse", "temas_fora_escopo", "outorgas")
COLUNAS_ATO = ("id", "data_publicacao", "secao", "tipo", "orgao", "identifica", "ementa", "url_pdf", "texto")
COLUNAS_SAIDA = ("id_ato", "data_publicacao", "secao", "tipo", "orgao", "identifica", "ementa", "url_pdf",
                 "nivel", "score", "citacao_direta", "orgaos", "temas", "regiao", "fora_de_escopo",
                 "motivo", "trecho", "revisao", "comentario")
csv.field_size_limit(sys.maxsize)


# ---------------------------------------------------------------- texto

def normalizar(texto) -> str:
    """Minúsculas, sem acento e com espaços simples (o mesmo é feito no SQL do pré-filtro)."""
    t = unicodedata.normalize("NFD", str(texto or ""))
    t = "".join(c for c in t if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", t)


def regex_de(termos) -> re.Pattern | None:
    termos = sorted({normalizar(t) for t in termos if t}, key=len, reverse=True)
    if not termos:
        return None
    return re.compile(r"(?<![a-z0-9])(" + "|".join(re.escape(t) for t in termos) + r")(?![a-z0-9])")


def achados(regex: re.Pattern | None, texto: str) -> list[str]:
    return sorted(set(regex.findall(texto))) if regex else []


# ---------------------------------------------------------------- critérios

class Criterios:
    def __init__(self, caminho: Path):
        self.bruto = json.loads(caminho.read_text(encoding="utf-8"))
        c = self.bruto
        self.direta = regex_de(c["citacao_direta"]["termos"])
        self.orgaos = {nome: (regex_de(o["termos"]), o.get("origem"), bool(o.get("basta_o_orgao")),
                              regex_de(o.get("exceto_orgao", [])))
                       for nome, o in c["orgaos"].items() if not nome.startswith("_")}
        self.temas = {nome: regex_de(t["termos"]) for nome, t in c["temas"].items() if not nome.startswith("_")}
        self.temas_fracos = {nome for nome, t in c["temas"].items() if not nome.startswith("_") and t.get("fraco")}
        self.fora = {nome: regex_de(t) for nome, t in c["fora_de_escopo"].items() if not nome.startswith("_")}
        self.regiao = regex_de(c["regiao"]["termos"])
        self.score = c["score"]

    def termos_do_prefiltro(self) -> tuple[list[str], list[str]]:
        """(termos para orgao, termos para o texto): um ato que não casa nenhum não pode ser relevante."""
        c = self.bruto
        no_orgao = [t for n, o in c["orgaos"].items() if not n.startswith("_") for t in o["termos"]]
        no_texto = list(c["citacao_direta"]["termos"])
        no_texto += [t for n, o in c["temas"].items() if not n.startswith("_") for t in o["termos"]]
        return no_orgao, no_texto

    def classificar(self, ato: dict) -> dict:
        orgao = normalizar(ato.get("orgao"))
        corpo = normalizar(" ".join(str(ato.get(k) or "") for k in ("identifica", "ementa", "texto")))
        tudo = orgao + " " + corpo

        direta = achados(self.direta, tudo)
        orgaos = {n: origem for n, (rx, origem, _, exceto) in self.orgaos.items()
                  if achados(rx, orgao) and not achados(exceto, orgao)}
        basta = any(self.orgaos[n][2] for n in orgaos)
        temas = {n: achados(rx, corpo) for n, rx in self.temas.items()}
        temas = {n: t for n, t in temas.items() if t}
        fora = {n: achados(rx, tudo) for n, rx in self.fora.items()}
        fora = {n: t for n, t in fora.items() if t}
        regiao = achados(self.regiao, corpo)

        if direta:
            nivel, motivo = "direto", f"cita a empresa ou outorga: {', '.join(direta)}"
        elif fora and not orgaos and not set(temas) - self.temas_fracos:
            nivel, motivo = "descartado", (f"fora de escopo ({', '.join(fora)}) sem órgão do perfil"
                                           + (" e só com tema genérico" if temas else " e sem tema"))
        elif orgaos and set(temas) - self.temas_fracos:
            nivel, motivo = "alto", f"órgão {', '.join(orgaos)} + tema {', '.join(temas)}"
        elif orgaos and temas:
            nivel, motivo = "medio", f"órgão {', '.join(orgaos)} + só tema genérico {', '.join(temas)}"
        elif temas:
            nivel, motivo = "medio", f"tema {', '.join(temas)} sem órgão do perfil"
        elif basta:
            nivel, motivo = "baixo", f"órgão {', '.join(orgaos)} sem tema de interesse"
        elif orgaos:
            nivel, motivo = "descartado", f"órgão {', '.join(orgaos)} publica muito ato genérico e não há tema"
        else:
            nivel, motivo = "descartado", "nenhum critério (passou só no pré-filtro)"

        s = self.score
        score = s["base"].get(nivel, 0)
        if nivel != "descartado":
            score += s["por_tema_extra"] * max(0, len(temas) - 1) + (s["regiao"] if regiao else 0)
            if orgaos and all(o == "inferido" for o in orgaos.values()):
                score -= s["orgao_inferido_vale_menos"]
                motivo += " (órgão inferido, não está no perfil)"

        termos = direta + [t for ts in temas.values() for t in ts]
        return {
            "nivel": nivel, "score": score, "motivo": motivo,
            "citacao_direta": "; ".join(direta),
            "orgaos": "; ".join(orgaos),
            "temas": "; ".join(f"{n}({', '.join(t)})" for n, t in temas.items()),
            "regiao": "; ".join(regiao),
            "fora_de_escopo": "; ".join(f"{n}({', '.join(t)})" for n, t in fora.items()),
            "trecho": trecho(ato, termos),
        }


def trecho(ato: dict, termos: list[str], largura: int = 220) -> str:
    """Pedaço da ementa ou do texto em volta do primeiro termo encontrado, para quem revisa."""
    for campo in ("ementa", "texto", "identifica"):
        bruto = re.sub(r"\s+", " ", str(ato.get(campo) or "")).strip()
        norm = normalizar(bruto)  # NFD sem acento mantém o tamanho do texto: os índices batem
        for t in termos:
            i = norm.find(t)
            if i >= 0 and len(norm) == len(bruto):
                ini = max(0, i - largura // 2)
                return ("…" if ini else "") + bruto[ini:ini + largura] + ("…" if ini + largura < len(bruto) else "")
    return re.sub(r"\s+", " ", str(ato.get("ementa") or ato.get("texto") or ""))[:largura]


# ---------------------------------------------------------------- perfil ao vivo

def conferir_perfil(stack: str) -> tuple[str, list[str]]:
    """Compara o perfil gravado hoje (dados da organização no DynamoDB) com o perfil de onde os
    critérios saíram. Devolve (origem, diferenças). Só lê um item."""
    import boto3

    base = json.loads(PERFIL_BASE.read_text(encoding="utf-8"))
    cfn = boto3.client("cloudformation", region_name=REGION)
    outputs = {o["OutputKey"]: o["OutputValue"] for o in cfn.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]}
    tabela = boto3.resource("dynamodb", region_name=REGION).Table(outputs["TableName"])
    item = tabela.get_item(Key={"user_id": "CNPJ#KALMANTESTE100"}, ProjectionExpression="dados").get("Item")
    if not item:
        return "DynamoDB: organização CNPJ#KALMANTESTE100 não existe (rode make api-seed-aurora)", []
    # O DynamoDB devolve números como Decimal: volta para int/float antes de comparar com o JSON.
    def numero(v):
        return int(v) if v == int(v) else float(v)
    atual = json.loads(json.dumps(item.get("dados") or {}, default=numero))
    difs = [c for c in CAMPOS_DO_PERFIL if atual.get(c) != base.get(c)]
    return f"DynamoDB ({outputs['TableName']})", difs


# ---------------------------------------------------------------- atos

ACENTOS, SEM_ACENTO = "áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn"


def sql_normalizado(coluna: str) -> str:
    """Como normalizar(), em SQL do Athena: minúsculas e sem acento (os termos já vêm normalizados)."""
    return f"translate(lower(coalesce({coluna}, '')), '{ACENTOS}', '{SEM_ACENTO}')"


def sql_regex(termos) -> str:
    termos = sorted({normalizar(t) for t in termos}, key=len, reverse=True)
    alternativas = "|".join(re.sub(r"([.^$*+?()\[\]{}|\\])", r"\\\1", t) for t in termos)
    return f"(^|[^a-z0-9])({alternativas})($|[^a-z0-9])".replace("'", "''")


def atos_do_athena(crit: Criterios, output: str, workgroup: str) -> tuple[list[dict], str]:
    import boto3

    no_orgao, no_texto = crit.termos_do_prefiltro()
    corpo = " || ' ' || ".join(sql_normalizado(c) for c in ("identifica", "ementa", "texto"))
    sql = (f"SELECT {', '.join(COLUNAS_ATO)} FROM silver_db.dou_atos "
           f"WHERE regexp_like({sql_normalizado('orgao')}, '{sql_regex(no_orgao)}') "
           f"OR regexp_like({corpo}, '{sql_regex(no_texto)}')")
    athena = boto3.client("athena", region_name=REGION)
    qid = athena.start_query_execution(QueryString=sql, WorkGroup=workgroup,
                                       ResultConfiguration={"OutputLocation": output})["QueryExecutionId"]
    while True:
        st = athena.get_query_execution(QueryExecutionId=qid)["QueryExecution"]["Status"]
        if st["State"] in ("SUCCEEDED", "FAILED", "CANCELLED"):
            break
        time.sleep(2)
    if st["State"] != "SUCCEEDED":
        sys.exit(f"consulta no Athena falhou: {st.get('StateChangeReason', st['State'])}")

    linhas, cabecalho = [], None
    for pagina in athena.get_paginator("get_query_results").paginate(QueryExecutionId=qid):
        for row in pagina["ResultSet"]["Rows"]:
            valores = [c.get("VarCharValue") for c in row["Data"]]
            if cabecalho is None:
                cabecalho = valores
                continue
            linhas.append(dict(zip(cabecalho, valores)))
    return linhas, f"Athena silver_db.dou_atos (consulta {qid})"


def atos_do_arquivo(caminho: Path) -> tuple[list[dict], str]:
    if caminho.suffix == ".jsonl":
        linhas = [json.loads(l) for l in caminho.read_text(encoding="utf-8").splitlines() if l.strip()]
    else:
        with caminho.open(encoding="utf-8", newline="") as f:
            linhas = list(csv.DictReader(f))
    return linhas, f"arquivo {caminho}"


# ---------------------------------------------------------------- saída

def escrever_csv(caminho: Path, linhas: list[dict], colunas) -> None:
    with caminho.open("w", encoding="utf-8-sig", newline="") as f:  # utf-8-sig: abre certo no Excel
        w = csv.DictWriter(f, fieldnames=colunas, extrasaction="ignore")
        w.writeheader()
        w.writerows(linhas)


def gerar(args) -> None:
    crit = Criterios(args.criterios)
    saida = args.saida
    saida.mkdir(parents=True, exist_ok=True)

    origem_perfil, difs = f"arquivo {PERFIL_BASE.relative_to(RAIZ)} (sem conferir o DynamoDB)", []
    if not args.sem_perfil_ao_vivo:
        try:
            origem_perfil, difs = conferir_perfil(args.stack)
        except Exception as exc:
            print(f"⚠️  não deu para ler o perfil ao vivo ({exc.__class__.__name__}: {exc}); seguindo com os critérios")
    if difs:
        print(f"⚠️  o perfil atual difere do usado nos critérios em: {', '.join(difs)}. Revise criterios.json.")

    atos, origem_atos = atos_do_arquivo(args.atos) if args.atos else atos_do_athena(
        crit, args.athena_output, args.workgroup)
    print(f"{len(atos)} atos passaram no pré-filtro ({origem_atos})")

    relevantes, descartados = [], []
    for ato in atos:
        linha = {**ato, "id_ato": ato.get("id"), **crit.classificar(ato), "revisao": "", "comentario": ""}
        (descartados if linha["nivel"] == "descartado" else relevantes).append(linha)
    ordem = {"direto": 0, "alto": 1, "medio": 2, "baixo": 3}
    relevantes.sort(key=lambda l: str(l.get("data_publicacao") or ""), reverse=True)  # mais recente primeiro
    relevantes.sort(key=lambda l: (ordem[l["nivel"]], -l["score"]))                    # sort estável

    escrever_csv(saida / "atos_relevantes.csv", relevantes, COLUNAS_SAIDA)
    escrever_csv(saida / "descartados.csv", descartados, COLUNAS_SAIDA)
    (saida / "resumo.md").write_text(resumo(crit, args, origem_perfil, difs, origem_atos, atos, relevantes,
                                            descartados), encoding="utf-8")
    print(f"{len(relevantes)} relevantes, {len(descartados)} descartados -> {saida}")


def resumo(crit, args, origem_perfil, difs, origem_atos, atos, relevantes, descartados) -> str:
    datas = sorted(str(a.get("data_publicacao")) for a in atos if a.get("data_publicacao"))
    por = lambda campo, linhas: collections.Counter(  # noqa: E731
        v for l in linhas for v in (l[campo].split("; ") if l[campo] else ["(nenhum)"]))
    tabela = lambda cont: "\n".join(f"| {k} | {v} |" for k, v in cont.most_common())  # noqa: E731
    return f"""# Atos do DOU relevantes para a Aurora Energia

Gerado em {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC.

- Perfil: {origem_perfil}{' — DIFERE em ' + ', '.join(difs) if difs else ''}
- Critérios: `{args.criterios.name}`
- Atos: {origem_atos}
- Período dos atos no pré-filtro: {datas[0] if datas else '-'} a {datas[-1] if datas else '-'}
- {len(atos)} atos no pré-filtro: {len(relevantes)} relevantes e {len(descartados)} descartados

## Por nível

| nível | atos |
|---|---|
{tabela(collections.Counter(l['nivel'] for l in relevantes + descartados))}

## Relevantes por órgão

| órgão | atos |
|---|---|
{tabela(por('orgaos', relevantes))}

## Relevantes por tema

| tema | atos |
|---|---|
{tabela(collections.Counter(t.split('(')[0] if l['temas'] else '(nenhum)' for l in relevantes for t in (l['temas'].split('; ') if l['temas'] else [''])))}

## Como revisar

Em `atos_relevantes.csv`, preencha `revisao` com sim, nao ou talvez, e use `comentario` para o porquê.
A coluna `motivo` diz qual regra colocou o ato ali, e `trecho` mostra onde o termo aparece.
"""


# ---------------------------------------------------------------- comparação

def comparar(args) -> None:
    def ler(caminho: Path, chave: str, nivel: str | None) -> dict[str, str]:
        with caminho.open(encoding="utf-8-sig", newline="") as f:
            linhas = list(csv.DictReader(f))
        if linhas and chave not in linhas[0]:
            sys.exit(f"{caminho}: coluna '{chave}' não existe (colunas: {', '.join(linhas[0])})")
        return {str(l[chave]): (l.get(nivel) or "sim") if nivel else "sim" for l in linhas}

    nosso = ler(args.saida / "atos_relevantes.csv", "id_ato", "nivel")
    deles = ler(args.comparar, args.chave_outro, args.nivel_outro)
    linhas = []
    for chave in sorted(set(nosso) | set(deles)):
        situacao = "nos_dois" if chave in nosso and chave in deles else "so_nosso" if chave in nosso else "so_deles"
        linhas.append({"id_ato": chave, "situacao": situacao, "nivel_nosso": nosso.get(chave, ""),
                       "nivel_deles": deles.get(chave, "")})
    escrever_csv(args.saida / "comparacao.csv", linhas, ("id_ato", "situacao", "nivel_nosso", "nivel_deles"))
    cont = collections.Counter(l["situacao"] for l in linhas)
    ambos = cont["nos_dois"]
    print(f"nos dois: {ambos}  só nosso: {cont['so_nosso']}  só deles: {cont['so_deles']}")
    if nosso and deles:
        print(f"concordância: {ambos / len(set(nosso) | set(deles)):.0%} (Jaccard)  "
              f"cobertura do nosso sobre o deles: {ambos / len(deles):.0%}")
    if args.nivel_outro:
        mesmos = sum(1 for l in linhas if l["situacao"] == "nos_dois" and l["nivel_nosso"] == l["nivel_deles"])
        print(f"mesmo nível nos atos em comum: {mesmos}/{ambos}")
    print(f"detalhe em {args.saida / 'comparacao.csv'}")


def main(argv=None) -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--criterios", type=Path, default=AQUI / "criterios.json")
    p.add_argument("--saida", type=Path, default=AQUI / "saida")
    p.add_argument("--atos", type=Path, help="lê os atos de um .jsonl ou .csv em vez do Athena")
    p.add_argument("--stack", default="cnpj-cadastro", help="stack do cadastro (perfil ao vivo)")
    p.add_argument("--sem-perfil-ao-vivo", action="store_true", help="não confere o perfil no DynamoDB")
    p.add_argument("--athena-output", default="s3://lakehouse-pipeline-lakebucket-r3zi7klfeo4o/athena-results/")
    p.add_argument("--workgroup", default="primary")
    p.add_argument("--comparar", type=Path, help="CSV de outra pessoa para comparar com saida/atos_relevantes.csv")
    p.add_argument("--chave-outro", default="id_ato", help="coluna do id do ato no CSV de comparação")
    p.add_argument("--nivel-outro", default=None, help="coluna de nível/rótulo no CSV de comparação (opcional)")
    args = p.parse_args(argv)
    comparar(args) if args.comparar else gerar(args)


if __name__ == "__main__":
    main()
