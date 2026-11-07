"""
Lakehouse da matriz de obrigações: landing -> bronze -> silver -> gold.

Um script com várias etapas, escolhidas por --STAGE:

    perfis   DynamoDB (itens CNPJ#*)            -> landing/matriz/perfis/<data>/<cnpj>.json
    bronze   landing/matriz/{importada,propostas_llm,perfis}/ -> Iceberg, só arquivo novo
    silver   bronze                              -> perfis explodidos e obrigações candidatas
    gold     silver + bronze_db.matriz_decisoes  -> obrigações (versões), tarefas e histórico

A gold é recalculada por replay, em ordem, de todos os eventos da bronze: matrizes
importadas, propostas do LLM e decisões vindas da API. O replay é determinístico: rodar
de novo não muda nada, e a bronze de decisões é a fonte de verdade. As regras (prazos,
tarefas, versões) ficam em regras_matriz.py, o mesmo arquivo que a API usa.

Roda como job AWS Glue Python Shell (Python 3.9). O DuckDB lista e lê os arquivos (S3
ou pasta local) e o PyIceberg grava as tabelas Iceberg no Glue Data Catalog. Nos testes,
pastas locais e catálogo em SQLite.

Argumentos (formato do Glue: --CHAVE valor):
    --STAGE       perfis | bronze | silver | gold
    --LAKE_URI    s3://bucket-do-lake  (ou pasta local)
    --TABLE_NAME  tabela DynamoDB do cadastro (só em perfis)
    --HOJE        AAAA-MM-DD, para reprocessar como se fosse outro dia (padrão: hoje em Brasília)
    --REGION      região AWS
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import logging
import os
import re
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Callable, Dict, List, Optional, Tuple

import pyarrow as pa

import regras_matriz as regras

log = logging.getLogger("etl_matriz")

BRASILIA = timezone(timedelta(hours=-3))

BRONZE_IMPORTADA = "bronze_db.matriz_importada"
BRONZE_PROPOSTAS = "bronze_db.matriz_propostas_llm"
BRONZE_PERFIS = "bronze_db.matriz_perfis"
BRONZE_DECISOES = "bronze_db.matriz_decisoes"
SILVER_PERFIS = "silver_db.matriz_perfis"
SILVER_UNIDADES = "silver_db.matriz_unidades"
SILVER_AREAS = "silver_db.matriz_areas"
SILVER_OUTORGAS = "silver_db.matriz_outorgas"
SILVER_CANDIDATAS = "silver_db.matriz_obrigacoes_candidatas"
GOLD_OBRIGACOES = "gold_db.matriz_obrigacoes"
GOLD_TAREFAS = "gold_db.matriz_tarefas"
GOLD_VERSOES = "gold_db.matriz_versoes"

S, I32, F64, B = pa.string(), pa.int32(), pa.float64(), pa.bool_()
TS = pa.timestamp("us")          # sem fuso, em UTC: o Athena grava neste tipo (INSERT/UPDATE da API)
D = pa.date32()
LS = pa.list_(pa.string())

SCHEMAS: Dict[str, pa.Schema] = {
    BRONZE_IMPORTADA: pa.schema([
        ("_cnpj", S), ("_arquivo", S), ("_hash", S), ("_linha", I32), ("registro", S), ("_ingerido_em", TS),
    ]),
    BRONZE_PROPOSTAS: pa.schema([
        ("_cnpj", S), ("_arquivo", S), ("_hash", S), ("_indice", I32), ("ato_id", S), ("ato_url", S),
        ("data_publicacao", S), ("orgao_emissor", S), ("proposta", S), ("_erro", S), ("_ingerido_em", TS),
    ]),
    BRONZE_PERFIS: pa.schema([
        ("_cnpj", S), ("_arquivo", S), ("_hash", S), ("perfil", S), ("_ingerido_em", TS),
    ]),
    # Escrita pela API da matriz (INSERT no Athena). O job só cria e lê.
    BRONZE_DECISOES: pa.schema([
        ("decisao_id", S), ("tipo", S), ("cnpj", S), ("obrigacao_id", S), ("versao", I32),
        ("tarefa_id", S), ("decisao", S), ("evidencia_url", S), ("usuario", S), ("comentario", S),
        ("decidida_em", TS),
    ]),
    SILVER_PERFIS: pa.schema([
        ("cnpj", S), ("razao_social", S), ("situacao_cadastral", S), ("status", S),
        ("natureza_juridica", S), ("porte_empresa", S), ("opcao_simples", S), ("opcao_mei", S),
        ("cnae_principal", S), ("cnaes", LS), ("uf_sede", S), ("municipio_sede", S),
        ("setor", S), ("email_alertas", S), ("faixa_funcionarios", S), ("ufs_atuacao", LS),
        ("municipios_atuacao", LS), ("orgaos_fiscalizadores", LS), ("temas_interesse", LS),
        ("temas_fora_escopo", LS), ("certificacoes", LS), ("area_padrao", S), ("atualizado_em", TS),
    ]),
    SILVER_UNIDADES: pa.schema([("cnpj", S), ("unidade_id", S), ("nome", S), ("tipo", S), ("tags", LS)]),
    SILVER_AREAS: pa.schema([("cnpj", S), ("area_id", S), ("nome", S), ("responsavel", S), ("email", S)]),
    SILVER_OUTORGAS: pa.schema([
        ("cnpj", S), ("outorga_id", S), ("tipo", S), ("numero", S), ("orgao", S), ("objeto", S),
        ("unidade_id", S), ("validade", D), ("antecedencia_renovacao_dias", I32),
    ]),
    SILVER_CANDIDATAS: pa.schema([
        ("cnpj", S), ("obrigacao_id", S), ("origem", S), ("mudanca", S), ("proposta_id", S),
        ("titulo", S), ("fonte_ato", S), ("fonte_dispositivo", S), ("fonte_url", S), ("trecho_citado", S),
        ("orgao_sigla", S), ("tema", S), ("aplica_a", LS), ("recorrencia", S), ("periodicidade", S),
        ("prazo_regra", S), ("prazo_json", S), ("area_responsavel", S), ("evidencia", S),
        ("criticidade", S), ("confianca", F64), ("ocorrido_em", TS), ("_arquivo", S), ("_linha", I32),
        ("valida", B), ("erros", LS),
    ]),
    GOLD_OBRIGACOES: pa.schema([
        ("cnpj", S), ("obrigacao_id", S), ("versao", I32), ("titulo", S), ("fonte_ato", S),
        ("fonte_dispositivo", S), ("fonte_url", S), ("trecho_citado", S), ("orgao_sigla", S), ("tema", S),
        ("aplica_a", LS), ("recorrencia", S), ("periodicidade", S), ("prazo_regra", S), ("prazo_json", S),
        ("area_responsavel", S), ("evidencia", S), ("criticidade", S), ("origem", S), ("status", S),
        ("confianca", F64), ("incluida_em", D), ("alterada_por", S), ("vigente", B), ("mudanca", S),
        ("proposta_id", S), ("hash_conteudo", S), ("decidida_por", S), ("decidida_em", TS),
    ]),
    GOLD_TAREFAS: pa.schema([
        ("cnpj", S), ("tarefa_id", S), ("obrigacao_id", S), ("obrigacao_versao", I32), ("unidade_id", S),
        ("outorga_id", S), ("descricao", S), ("vencimento", D), ("area_responsavel", S), ("status", S),
        ("evidencia_url", S), ("em_risco", B), ("atualizada_em", TS),
    ]),
    GOLD_VERSOES: pa.schema([
        ("cnpj", S), ("obrigacao_id", S), ("versao", I32), ("evento", S), ("status", S), ("origem", S),
        ("ocorrido_em", D), ("por", S), ("resumo", S),
    ]),
}

ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")
CNPJ = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")


# ============================================================ caminhos e E/S

def landing(lake: str, *partes: str) -> str:
    return "/".join([lake, "landing", "matriz", *partes])


def _q(valor: str) -> str:
    return "'" + valor.replace("'", "''") + "'"


def agora_utc() -> datetime:
    """Sem fuso (UTC), no formato das colunas TS."""
    return datetime.now(timezone.utc).replace(tzinfo=None, microsecond=0)


def hoje_brasilia() -> date:
    return datetime.now(BRASILIA).date()


def escreve_local(uri: str, texto: str) -> None:
    os.makedirs(os.path.dirname(uri), exist_ok=True)
    with open(uri, "w", encoding="utf-8") as f:
        f.write(texto)


def escritor_s3(s3_client) -> Callable[[str, str], None]:
    def escreve(uri: str, texto: str) -> None:
        bucket, key = uri[len("s3://"):].split("/", 1)
        s3_client.put_object(Bucket=bucket, Key=key, Body=texto.encode("utf-8"),
                             ContentType="application/json; charset=utf-8")
    return escreve


def connect(s3: bool = False):
    import duckdb
    con = duckdb.connect()
    con.sql("SET TimeZone = 'UTC'")
    # No Glue Python Shell o HOME é "/" e não é gravável (ver pipeline/README.md, armadilha 4).
    tmp = os.environ.get("TMPDIR") or "/tmp"
    con.sql(f"SET home_directory = {_q(tmp)}")
    con.sql(f"SET extension_directory = {_q(tmp + '/.duckdb/extensions')}")
    if s3:
        con.sql("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
        con.sql("CREATE SECRET (TYPE s3, PROVIDER credential_chain)")
    return con


def listar(con, padrao: str) -> List[str]:
    return sorted(r[0] for r in con.sql(f"SELECT file FROM glob({_q(padrao)})").fetchall())


def ler_bytes(con, arquivo: str) -> bytes:
    return con.sql(f"SELECT content FROM read_blob({_q(arquivo)})").fetchone()[0]


# ============================================================ Iceberg

def _location(lake: str, ident: str) -> Optional[str]:
    if not lake.startswith("s3://"):
        return None
    db, tabela = ident.split(".")
    return f"{lake}/{db.replace('_db', '')}/{tabela}"


def ensure_table(catalog, ident: str, lake: str):
    ns = ident.split(".")[0]
    if (ns,) not in catalog.list_namespaces():
        catalog.create_namespace(ns)  # no Glue o database já vem da stack lakehouse-pipeline
    return catalog.create_table_if_not_exists(ident, schema=SCHEMAS[ident], location=_location(lake, ident))


def ler(catalog, ident: str, lake: str) -> List[dict]:
    return ensure_table(catalog, ident, lake).scan().to_arrow().to_pylist()


def tabela_arrow(ident: str, linhas: List[dict]) -> pa.Table:
    schema = SCHEMAS[ident]
    return pa.Table.from_pylist([{c: l.get(c) for c in schema.names} for l in linhas], schema=schema)


def sobrescrever(catalog, ident: str, lake: str, linhas: List[dict]) -> int:
    ensure_table(catalog, ident, lake).overwrite(tabela_arrow(ident, linhas))
    return len(linhas)


# ============================================================ perfis

def _plano(valor):
    """Decimal do DynamoDB -> int/float, para virar JSON."""
    if isinstance(valor, Decimal):
        return int(valor) if valor == valor.to_integral_value() else float(valor)
    if isinstance(valor, dict):
        return {k: _plano(v) for k, v in valor.items()}
    if isinstance(valor, (list, tuple, set)):
        return [_plano(v) for v in valor]
    return valor


def documento_perfil(item: dict) -> Optional[dict]:
    """O que vai para a landing: sem sócios (LGPD), sem membros nem convites."""
    cnpj = item.get("cnpj") or str(item.get("user_id", "")).replace("CNPJ#", "", 1)
    if not CNPJ.match(cnpj or ""):
        return None
    empresa = {k: v for k, v in (item.get("empresa") or {}).items() if k != "QSA"}
    return _plano({"cnpj": cnpj, "status": item.get("status"), "consultado_em": item.get("consultado_em"),
                   "empresa": empresa, "dados": item.get("dados") or {}})


def exportar_perfis(itens: List[dict], lake: str, dt: str, escreve=escreve_local) -> int:
    n = 0
    for item in itens:
        doc = documento_perfil(item)
        if doc is None:
            continue
        escreve(landing(lake, "perfis", dt, f"{doc['cnpj']}.json"),
                json.dumps(doc, ensure_ascii=False, sort_keys=True))
        n += 1
    log.info("perfis %s: %d organizações", dt, n)
    return n


def scan_organizacoes(table_name: str, region: str) -> List[dict]:
    import boto3
    from boto3.dynamodb.conditions import Attr
    tabela = boto3.resource("dynamodb", region_name=region).Table(table_name)
    itens, kwargs = [], {"FilterExpression": Attr("user_id").begins_with("CNPJ#")}
    while True:
        resp = tabela.scan(**kwargs)
        itens.extend(resp.get("Items", []))
        if "LastEvaluatedKey" not in resp:
            return itens
        kwargs["ExclusiveStartKey"] = resp["LastEvaluatedKey"]


# ============================================================ bronze

def _so_os_novos(arquivos: List[Tuple[str, str, bytes]], existentes: List[dict]):
    """Arquivo entra se (_arquivo, _hash) ainda não está na tabela. Um perfil regravado
    com o mesmo conteúdo não entra de novo; com conteúdo novo, entra."""
    vistos = {(e["_arquivo"], e["_hash"]) for e in existentes}
    return [(a, h, c) for a, h, c in arquivos if (a, h) not in vistos]


def _arquivos(con, padrao: str) -> List[Tuple[str, str, bytes]]:
    saida = []
    for arquivo in listar(con, padrao):
        conteudo = ler_bytes(con, arquivo)
        saida.append((arquivo, hashlib.sha256(conteudo).hexdigest(), conteudo))
    return saida


def _linhas_csv(conteudo: bytes) -> List[dict]:
    """CSV com vírgula ou ponto e vírgula (Excel em português), aspas no padrão RFC 4180."""
    texto = conteudo.decode("utf-8-sig")
    cabecalho = texto.split("\n", 1)[0]
    delimitador = ";" if cabecalho.count(";") > cabecalho.count(",") else ","
    return [dict(r) for r in csv.DictReader(io.StringIO(texto), delimiter=delimitador)]


def _linhas_xlsx(con, arquivo: str) -> List[dict]:
    con.sql("INSTALL excel; LOAD excel;")
    return con.sql(f"SELECT * FROM read_xlsx({_q(arquivo)}, all_varchar = true)").fetch_arrow_table().to_pylist()


def _cnpj_da_pasta(arquivo: str, pasta: str) -> Optional[str]:
    m = re.search(rf"/{pasta}/([^/]+)/", arquivo)
    return m.group(1).upper() if m else None


def bronze(con, catalog, lake: str, agora: Optional[datetime] = None) -> Dict[str, int]:
    agora = agora or agora_utc()
    ensure_table(catalog, BRONZE_DECISOES, lake)  # a API grava nela; precisa existir
    n = {}

    # matriz importada: uma linha por linha do CSV/XLSX
    tabela = ensure_table(catalog, BRONZE_IMPORTADA, lake)
    existentes = tabela.scan(selected_fields=("_arquivo", "_hash")).to_arrow().to_pylist()
    novos = _so_os_novos(_arquivos(con, landing(lake, "importada", "*", "*.csv"))
                         + _arquivos(con, landing(lake, "importada", "*", "*.xlsx")), existentes)
    linhas = []
    for arquivo, h, conteudo in novos:
        registros = _linhas_xlsx(con, arquivo) if arquivo.endswith(".xlsx") else _linhas_csv(conteudo)
        for i, r in enumerate(registros, start=1):
            linhas.append({"_cnpj": _cnpj_da_pasta(arquivo, "importada"), "_arquivo": arquivo, "_hash": h,
                           "_linha": i, "registro": json.dumps(r, ensure_ascii=False), "_ingerido_em": agora})
    if linhas:
        tabela.append(tabela_arrow(BRONZE_IMPORTADA, linhas))
    n["matriz_importada"] = len(linhas)

    # propostas do LLM: uma linha por proposta; arquivo ilegível vira uma linha com _erro
    tabela = ensure_table(catalog, BRONZE_PROPOSTAS, lake)
    existentes = tabela.scan(selected_fields=("_arquivo", "_hash")).to_arrow().to_pylist()
    linhas = []
    for arquivo, h, conteudo in _so_os_novos(_arquivos(con, landing(lake, "propostas_llm", "*", "*.json")), existentes):
        base = {"_arquivo": arquivo, "_hash": h, "_ingerido_em": agora}
        try:
            ato = json.loads(conteudo.decode("utf-8-sig"))
            propostas = ato["propostas"]
            if not isinstance(propostas, list):
                raise ValueError("propostas deve ser lista")
        except (ValueError, KeyError, TypeError) as exc:
            linhas.append({**base, "_indice": 0, "_erro": f"arquivo inválido: {exc}"})
            continue
        for i, p in enumerate(propostas):
            linhas.append({**base, "_indice": i, "_cnpj": str((p or {}).get("cnpj") or "").upper() or None,
                           "ato_id": ato.get("ato_id"), "ato_url": ato.get("ato_url"),
                           "data_publicacao": ato.get("data_publicacao"), "orgao_emissor": ato.get("orgao_emissor"),
                           "proposta": json.dumps(p, ensure_ascii=False)})
    if linhas:
        tabela.append(tabela_arrow(BRONZE_PROPOSTAS, linhas))
    n["matriz_propostas_llm"] = len(linhas)

    # perfis exportados do DynamoDB
    tabela = ensure_table(catalog, BRONZE_PERFIS, lake)
    existentes = tabela.scan(selected_fields=("_arquivo", "_hash")).to_arrow().to_pylist()
    linhas = []
    for arquivo, h, conteudo in _so_os_novos(_arquivos(con, landing(lake, "perfis", "*", "*.json")), existentes):
        texto = conteudo.decode("utf-8")
        cnpj = (json.loads(texto) or {}).get("cnpj")
        linhas.append({"_cnpj": cnpj, "_arquivo": arquivo, "_hash": h, "perfil": texto, "_ingerido_em": agora})
    if linhas:
        tabela.append(tabela_arrow(BRONZE_PERFIS, linhas))
    n["matriz_perfis"] = len(linhas)

    log.info("bronze: %s", n)
    return n


# ============================================================ silver

def _lista(v) -> List[str]:
    if v in (None, ""):
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [x.strip() for x in re.split(r"[;,]", str(v)) if x.strip()]


def _area_padrao(areas: List[dict]) -> Optional[str]:
    for a in areas:
        if "compliance" in f"{a.get('id', '')} {a.get('nome', '')}".lower() or str(a.get("id")).upper() == "COMP":
            return a["id"]
    return areas[0]["id"] if areas else None


def silver_perfis(perfis_bronze: List[dict]) -> Dict[str, List[dict]]:
    """Último perfil de cada CNPJ, com unidades, áreas e outorgas em tabelas próprias."""
    ultimo: Dict[str, dict] = {}
    for p in sorted(perfis_bronze, key=lambda r: (r["_ingerido_em"], r["_arquivo"])):
        if p.get("_cnpj"):
            ultimo[p["_cnpj"]] = p
    saida = {SILVER_PERFIS: [], SILVER_UNIDADES: [], SILVER_AREAS: [], SILVER_OUTORGAS: []}
    for cnpj, p in sorted(ultimo.items()):
        doc = json.loads(p["perfil"])
        e, d = doc.get("empresa") or {}, doc.get("dados") or {}
        areas = [a for a in d.get("areas") or [] if isinstance(a, dict) and a.get("id")]
        cnaes = [c.get("codigo") for c in e.get("cnaes") or [] if isinstance(c, dict) and c.get("codigo")]
        saida[SILVER_PERFIS].append({
            "cnpj": cnpj, "razao_social": e.get("razao_social"), "situacao_cadastral": e.get("situacao_cadastral"),
            "status": doc.get("status"), "natureza_juridica": e.get("natureza_juridica"),
            "porte_empresa": e.get("porte_empresa"), "opcao_simples": e.get("opcao_simples"),
            "opcao_mei": e.get("opcao_mei"), "cnae_principal": e.get("cnae_principal"),
            "cnaes": cnaes or _lista([e.get("cnae_principal")] + list(e.get("cnaes_secundarios") or [])),
            "uf_sede": e.get("uf"), "municipio_sede": e.get("municipio"),
            "setor": d.get("setor"), "email_alertas": d.get("email_alertas"),
            "faixa_funcionarios": d.get("faixa_funcionarios"),
            "ufs_atuacao": _lista(d.get("ufs_atuacao")) or _lista([e.get("uf")]),
            "municipios_atuacao": _lista(d.get("municipios_atuacao")),
            "orgaos_fiscalizadores": _lista(d.get("orgaos_fiscalizadores")),
            "temas_interesse": _lista(d.get("temas_interesse")),
            "temas_fora_escopo": _lista(d.get("temas_fora_escopo")),
            "certificacoes": _lista(d.get("certificacoes")),
            "area_padrao": _area_padrao(areas), "atualizado_em": p["_ingerido_em"],
        })
        for u in d.get("unidades") or []:
            if isinstance(u, dict) and u.get("id"):
                saida[SILVER_UNIDADES].append({"cnpj": cnpj, "unidade_id": u["id"], "nome": u.get("nome"),
                                               "tipo": u.get("tipo"), "tags": _lista(u.get("tags"))})
        for a in areas:
            saida[SILVER_AREAS].append({"cnpj": cnpj, "area_id": a["id"], "nome": a.get("nome"),
                                        "responsavel": a.get("responsavel"), "email": a.get("email")})
        for o in d.get("outorgas") or []:
            if not (isinstance(o, dict) and o.get("id")):
                continue
            try:
                validade = date.fromisoformat(o["validade"]) if o.get("validade") else None
            except ValueError:
                validade = None
            ante = o.get("antecedencia_renovacao_dias")
            saida[SILVER_OUTORGAS].append({
                "cnpj": cnpj, "outorga_id": o["id"], "tipo": o.get("tipo"), "numero": o.get("numero"),
                "orgao": o.get("orgao"), "objeto": o.get("objeto"), "unidade_id": o.get("unidade_id"),
                "validade": validade, "antecedencia_renovacao_dias": int(ante) if ante not in (None, "") else None,
            })
    return saida


def _id_llm(proposta_id: str) -> str:
    return "LLM-" + hashlib.sha1(proposta_id.encode("utf-8")).hexdigest()[:8].upper()


def _validar(c: dict, perfil: Optional[dict], unidades: set, areas: set, area_padrao: Optional[str],
             alvos: set) -> List[str]:
    """Erros da candidata (vazio = válida). Resolve a área contra o perfil (muda `c`)."""
    erros = []
    if perfil is None:
        erros.append("CNPJ sem perfil exportado")
    if not ID.match(c.get("obrigacao_id") or ""):
        erros.append("obrigacao_id ausente ou inválido")
    mudanca = c["mudanca"]
    if mudanca in ("alteracao", "revogacao") and c["obrigacao_id"] not in alvos:
        erros.append(f"obrigação alvo {c['obrigacao_id']} não existe")
    completa = mudanca == "inclusao"
    if c["origem"] == "llm" and not (c.get("trecho_citado") or "").strip():
        erros.append("trecho_citado é obrigatório")
    if completa and not (c.get("titulo") or "").strip():
        erros.append("titulo é obrigatório")
    prazo: List[dict] = []
    if mudanca != "revogacao":
        try:
            prazo = regras.ler_prazo_json(c.get("prazo_json"))
            if completa and c.get("recorrencia") == "periodica" and not prazo:
                erros.append("prazo_json vazio em obrigação periódica")
        except ValueError as exc:
            erros.append(str(exc))
    # ligada a outorga (só regras dias_antes): o ciclo é a validade, não há periodicidade
    so_outorga = bool(prazo) and all(r["unidade"] == "dias_antes" for r in prazo)
    if completa or c.get("recorrencia"):
        if c.get("recorrencia") not in regras.RECORRENCIAS:
            erros.append(f"recorrencia inválida ({c.get('recorrencia')})")
        elif (c["recorrencia"] == "periodica" and not so_outorga
              and c.get("periodicidade") not in regras.PERIODICIDADES):
            erros.append(f"periodicidade inválida ({c.get('periodicidade')})")
    if c.get("criticidade") and c["criticidade"] not in regras.CRITICIDADES:
        erros.append(f"criticidade inválida ({c['criticidade']})")
    fora = [u for u in c.get("aplica_a") or [] if u not in unidades]
    if fora:
        erros.append(f"aplica_a com unidade inexistente: {', '.join(fora)}")
    if c.get("area_responsavel") and c["area_responsavel"] not in areas:
        c["area_responsavel"] = None  # área desconhecida no perfil
    if completa and not c.get("area_responsavel"):
        c["area_responsavel"] = area_padrao  # inclusão sem área: compliance (ou a primeira)
    return erros  # numa alteração sem área, a versão nova herda a da vigente


def candidatas(importada: List[dict], propostas: List[dict], perfis: Dict[str, List[dict]],
               alvos_gold: set) -> List[dict]:
    perfil_por_cnpj = {p["cnpj"]: p for p in perfis[SILVER_PERFIS]}
    unidades: Dict[str, set] = {}
    areas: Dict[str, set] = {}
    for u in perfis[SILVER_UNIDADES]:
        unidades.setdefault(u["cnpj"], set()).add(u["unidade_id"])
    for a in perfis[SILVER_AREAS]:
        areas.setdefault(a["cnpj"], set()).add(a["area_id"])

    saida = []
    for r in importada:
        reg = json.loads(r["registro"])
        reg = {str(k).strip().lower(): (v.strip() if isinstance(v, str) else v) for k, v in reg.items()}
        saida.append({
            "cnpj": r["_cnpj"], "obrigacao_id": reg.get("obrigacao_id"), "origem": "matriz_importada",
            "mudanca": "inclusao", "proposta_id": None,
            **{k: (reg.get(k) or None) for k in ("titulo", "fonte_ato", "fonte_dispositivo", "fonte_url",
                                                 "trecho_citado", "orgao_sigla", "tema", "recorrencia",
                                                 "periodicidade", "prazo_regra", "prazo_json",
                                                 "area_responsavel", "evidencia", "criticidade")},
            "aplica_a": _lista(reg.get("aplica_a")), "confianca": None,
            "ocorrido_em": r["_ingerido_em"], "_arquivo": r["_arquivo"], "_linha": r["_linha"],
        })

    for r in propostas:
        base = {"cnpj": r.get("_cnpj"), "origem": "llm", "ocorrido_em": r["_ingerido_em"],
                "_arquivo": r["_arquivo"], "_linha": r["_indice"], "fonte_ato": r.get("ato_id"),
                "fonte_url": r.get("ato_url"), "proposta_id": f"{r.get('ato_id')}#{r['_indice']}"}
        if r.get("_erro"):
            saida.append({**base, "obrigacao_id": None, "mudanca": "inclusao", "valida": False,
                          "erros": [r["_erro"]], "aplica_a": []})
            continue
        p = json.loads(r["proposta"]) or {}
        tipo = {"nova": "inclusao", "alteracao": "alteracao", "revogacao": "revogacao"}.get(p.get("tipo"))
        prazo = p.get("prazo_json")
        c = {
            **base, "mudanca": tipo or "inclusao",
            "obrigacao_id": p.get("obrigacao_id_alvo") if tipo in ("alteracao", "revogacao") else _id_llm(base["proposta_id"]),
            "titulo": p.get("titulo"), "fonte_dispositivo": p.get("fonte_dispositivo"),
            "trecho_citado": p.get("trecho_citado"), "orgao_sigla": p.get("orgao_sigla") or r.get("orgao_emissor"),
            "tema": p.get("tema"), "aplica_a": _lista(p.get("aplica_a")), "recorrencia": p.get("recorrencia"),
            "periodicidade": p.get("periodicidade"), "prazo_regra": p.get("prazo_regra"),
            "prazo_json": json.dumps(prazo, ensure_ascii=False) if isinstance(prazo, (list, dict)) else prazo,
            "area_responsavel": p.get("area_sugerida"), "evidencia": p.get("evidencia"),
            "criticidade": p.get("criticidade"),
            "confianca": float(p["confianca"]) if isinstance(p.get("confianca"), (int, float)) else None,
        }
        if tipo is None:
            c["_erro_tipo"] = f"tipo inválido ({p.get('tipo')})"
        saida.append(c)

    # alvos possíveis: o que já está na gold e o que a matriz importada traz
    alvos = set(alvos_gold) | {(c["cnpj"], c["obrigacao_id"]) for c in saida if c["origem"] == "matriz_importada"}
    for c in saida:
        if "valida" in c:
            continue
        cnpj = c.get("cnpj")
        erros = _validar(c, perfil_por_cnpj.get(cnpj), unidades.get(cnpj, set()), areas.get(cnpj, set()),
                         (perfil_por_cnpj.get(cnpj) or {}).get("area_padrao"),
                         {o for (cn, o) in alvos if cn == cnpj})
        if c.pop("_erro_tipo", None):
            erros.insert(0, "tipo deve ser nova, alteracao ou revogacao")
        c["valida"], c["erros"] = not erros, erros
    return sorted(saida, key=lambda c: (c["ocorrido_em"], c["_arquivo"], c["_linha"] or 0))


def silver(catalog, lake: str) -> Dict[str, int]:
    perfis = silver_perfis(ler(catalog, BRONZE_PERFIS, lake))
    n = {ident: sobrescrever(catalog, ident, lake, linhas) for ident, linhas in perfis.items()}
    alvos = {(o["cnpj"], o["obrigacao_id"]) for o in ler(catalog, GOLD_OBRIGACOES, lake) if o["vigente"]}
    cands = candidatas(ler(catalog, BRONZE_IMPORTADA, lake), ler(catalog, BRONZE_PROPOSTAS, lake), perfis, alvos)
    n[SILVER_CANDIDATAS] = sobrescrever(catalog, SILVER_CANDIDATAS, lake, cands)
    n["quarentena"] = sum(1 for c in cands if not c["valida"])
    log.info("silver: %s", n)
    return n


# ============================================================ gold

def _data_brasilia(ts: datetime) -> date:
    return ts.replace(tzinfo=timezone.utc).astimezone(BRASILIA).date()


def replay(cands: List[dict], decisoes: List[dict]) -> regras.Matriz:
    """Aplica, em ordem de ocorrência, importações, propostas e decisões."""
    eventos = []
    importacoes: Dict[Tuple[str, str], List[dict]] = {}
    for c in cands:
        if not c["valida"]:
            continue
        if c["origem"] == "matriz_importada":
            importacoes.setdefault((c["cnpj"], c["_arquivo"]), []).append(c)
        else:
            eventos.append((c["ocorrido_em"], 1, c["_arquivo"], c["_linha"] or 0, "proposta", c))
    for (cnpj, arquivo), linhas in importacoes.items():
        eventos.append((min(l["ocorrido_em"] for l in linhas), 0, arquivo, 0, "importacao", (cnpj, linhas)))
    for d in decisoes:
        if d.get("tipo") == "obrigacao":
            eventos.append((d["decidida_em"], 2, d.get("decisao_id") or "", 0, "decisao", d))

    m = regras.Matriz()
    for em, _, arquivo, _, tipo, dado in sorted(eventos, key=lambda e: e[:4]):
        if tipo == "importacao":
            cnpj, linhas = dado
            m.importacao(cnpj, linhas, _data_brasilia(em), os.path.basename(arquivo))
        elif tipo == "proposta":
            m.proposta(dado, _data_brasilia(em))
        else:
            m.decisao(dado["cnpj"], dado["obrigacao_id"], dado["versao"], dado["decisao"],
                      dado.get("usuario"), dado["decidida_em"])
    return m


def status_das_tarefas(decisoes: List[dict]) -> Dict[str, dict]:
    ultimo: Dict[str, dict] = {}
    for d in sorted((d for d in decisoes if d.get("tipo") == "tarefa"), key=lambda d: d["decidida_em"]):
        ultimo[d["tarefa_id"]] = {"status": d["decisao"], "evidencia_url": d.get("evidencia_url"),
                                  "em": d["decidida_em"]}
    return ultimo


def calcular_gold(cands: List[dict], decisoes: List[dict], outorgas: List[dict],
                  tarefas_anteriores: List[dict], hoje: date, agora: datetime) -> Dict[str, List[dict]]:
    m = replay(cands, decisoes)
    por_cnpj: Dict[str, List[dict]] = {}
    for o in outorgas:
        por_cnpj.setdefault(o["cnpj"], []).append(o)
    geradas = []
    for v in m.linhas():
        if v["vigente"] and v["status"] == "aprovada":
            geradas.extend(regras.gerar_tarefas(v, por_cnpj.get(v["cnpj"], []), hoje))
    tarefas = regras.consolidar_tarefas(geradas, tarefas_anteriores, status_das_tarefas(decisoes),
                                        m.versoes_vigentes(), m.pendentes(), hoje, agora)
    obrigacoes = sorted(m.linhas(), key=lambda v: (v["cnpj"], v["obrigacao_id"], v["versao"]))
    return {GOLD_OBRIGACOES: obrigacoes, GOLD_TAREFAS: tarefas, GOLD_VERSOES: m.historico}


def gold(catalog, lake: str, hoje: Optional[date] = None, tentativas: int = 3) -> Dict[str, int]:
    """Recalcula e grava as três tabelas. Se a API gravar uma decisão no meio (commit do
    Iceberg concorrente), lê tudo de novo e recalcula."""
    from pyiceberg.exceptions import CommitFailedException
    hoje = hoje or hoje_brasilia()
    for tentativa in range(1, tentativas + 1):
        try:
            resultado = calcular_gold(
                ler(catalog, SILVER_CANDIDATAS, lake), ler(catalog, BRONZE_DECISOES, lake),
                ler(catalog, SILVER_OUTORGAS, lake), ler(catalog, GOLD_TAREFAS, lake), hoje, agora_utc())
            n = {ident: sobrescrever(catalog, ident, lake, linhas) for ident, linhas in resultado.items()}
            n["tarefas_em_risco"] = sum(1 for t in resultado[GOLD_TAREFAS] if t["em_risco"])
            log.info("gold (hoje=%s): %s", hoje, n)
            return n
        except CommitFailedException:
            if tentativa == tentativas:
                raise
            log.warning("commit concorrente na gold, recalculando (tentativa %d)", tentativa + 1)
    raise AssertionError("inalcançável")


# ============================================================ entrada do job

def parse_args(argv: List[str]) -> Dict[str, str]:
    args, i = {}, 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            args[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    for obrigatorio in ("STAGE", "LAKE_URI"):
        if obrigatorio not in args:
            raise SystemExit(f"faltou --{obrigatorio}")
    if args["STAGE"] == "perfis" and not args.get("TABLE_NAME"):
        raise SystemExit("faltou --TABLE_NAME")
    if args.get("HOJE") == "hoje":   # valor padrão da máquina de estados
        args.pop("HOJE")
    if args.get("HOJE") and not re.fullmatch(r"\d{4}-\d{2}-\d{2}", args["HOJE"]):
        raise SystemExit("--HOJE precisa ser AAAA-MM-DD")
    return args


def main(argv: List[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    stage, lake = args["STAGE"], args["LAKE_URI"].rstrip("/")
    region = args.get("REGION") or os.environ.get("AWS_REGION") or os.environ.get("AWS_DEFAULT_REGION")
    hoje = date.fromisoformat(args["HOJE"]) if args.get("HOJE") else hoje_brasilia()

    import boto3
    from pyiceberg.catalog import load_catalog
    catalog = load_catalog("glue", **{"type": "glue", "glue.region": region,
                                      "client.region": region, "s3.region": region})

    if stage == "perfis":
        itens = scan_organizacoes(args["TABLE_NAME"], region)
        exportar_perfis(itens, lake, hoje.isoformat(), escritor_s3(boto3.client("s3", region_name=region)))
    elif stage == "bronze":
        bronze(connect(s3=lake.startswith("s3://")), catalog, lake)
    elif stage == "silver":
        silver(catalog, lake)
    elif stage == "gold":
        gold(catalog, lake, hoje)
    else:
        raise SystemExit(f"--STAGE desconhecido: {stage}")


if __name__ == "__main__":
    main(sys.argv[1:])
