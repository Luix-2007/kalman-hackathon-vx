"""
Lakehouse dos atos do Diario Oficial da Uniao (DOU).

Porte do ETL que rodava no Databricks (coletar_dou.py, bronze.py, prata.py, ouro.py)
para um job AWS Glue Python Shell. A coleta baixa o ZIP mensal direto da base de
dados aberta da Imprensa Nacional: nao passa por S3 de staging nem pelo Databricks.

Um script com varias etapas, escolhidas por --STAGE:

    landing  ZIP da Imprensa Nacional  -> Parquet, XML cru + metadados
    bronze   Landing                   -> Iceberg, so insere arquivo/conteudo novo
    prata    Bronze                    -> Iceberg, parse dos XML, so insere id novo
    ouro     Prata                      -> Iceberg, resumo mensal recalculado

Roda como job AWS Glue Python Shell (Python 3.9). O DuckDB e a engine de
processamento e o PyIceberg grava as tabelas Iceberg no Glue Data Catalog.
Os caminhos funcionam com s3:// (no Glue) e com pastas locais (nos testes).

Argumentos (formato do Glue: --CHAVE valor):
    --STAGE     landing | bronze | prata | ouro
    --LAKE_URI  s3://bucket-do-lake  (ou pasta local)
    --ANO       AAAA      (padrao: ano atual em America/Sao_Paulo)
    --MES       1 a 12    (padrao: mes atual em America/Sao_Paulo)
    --SECAO     1, 2 ou 3 (padrao: 1)
    --REGION    regiao AWS
"""

from __future__ import annotations

import datetime
import hashlib
import html
import logging
import os
import re
import shutil
import sys
import tempfile
import time
import unicodedata
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
from typing import Dict, Iterator, List, Optional, Tuple
from urllib.parse import quote, unquote, urljoin

import duckdb
import pyarrow as pa

log = logging.getLogger("etl_dou")

BRONZE_XML = "bronze_db.dou_xml"
PRATA_ATOS = "silver_db.dou_atos"
OURO_RESUMO = "gold_db.dou_resumo_mensal"

# Quantos XML vao em cada arquivo Parquet da Landing. O ZIP mensal da secao 1
# passa de 700 MB, entao a gravacao e em lotes para nao subir tudo de uma vez.
LOTE_LANDING = 500

TS = pa.timestamp("us", tz="UTC")

LANDING_SCHEMA = pa.schema([
    ("hash_xml", pa.string()),
    ("arquivo", pa.string()),
    ("xml", pa.binary()),
    ("secao", pa.int32()),
    ("ano_mes", pa.string()),
    ("coletado_em", TS),
])

SCHEMAS: Dict[str, pa.Schema] = {
    BRONZE_XML: LANDING_SCHEMA,
    PRATA_ATOS: pa.schema([
        ("id", pa.string()),
        ("id_materia", pa.string()),
        ("nome", pa.string()),
        ("jornal", pa.string()),
        ("data_publicacao", pa.date32()),
        ("tipo", pa.string()),
        ("orgao", pa.string()),
        ("pagina", pa.int32()),
        ("edicao", pa.string()),
        ("url_pdf", pa.string()),
        ("identifica", pa.string()),
        ("ementa", pa.string()),
        ("texto", pa.string()),
        ("arquivo", pa.string()),
        ("secao", pa.int32()),
        ("ano_mes", pa.string()),
        ("coletado_em", TS),
    ]),
    OURO_RESUMO: pa.schema([
        ("ano_mes", pa.string()),
        ("atos", pa.int64()),
        ("atos_aneel", pa.int64()),
        ("de", pa.date32()),
        ("ate", pa.date32()),
    ]),
}

CHAVE_BRONZE = ["arquivo", "hash_xml", "secao", "ano_mes"]
CHAVE_PRATA = ["id"]


class ColetaVaziaError(Exception):
    """O ZIP nao trouxe XML. As etapas seguintes nao devem rodar."""


# ============================================================ coleta do DOU
# Portado de dou.py (o modulo que o notebook do Databricks importava).
# So biblioteca padrao: nada para instalar alem do que o job ja tem.

# Os nomes vao na query string exatamente como o seletor do portal os escreve.
MESES = (
    "Janeiro", "Fevereiro", "Março", "Abril", "Maio", "Junho",
    "Julho", "Agosto", "Setembro", "Outubro", "Novembro", "Dezembro",
)

PAGINA_DADOS_ABERTOS = ("https://www.in.gov.br/acesso-a-informacao/dados-abertos/"
                        "base-de-dados")

# O portal responde 403 para User-Agent curto. Com cabecalho de navegador, 200.
CABECALHOS = {
    "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "pt-BR,pt;q=0.9,en;q=0.8",
}

# Nome do arquivo publicado: S<secao><mes><ano>, ex. S01112026_Atualizado171256.zip
ARQUIVO_DOU = re.compile(r"S(\d{2})(\d{2})(\d{4})[^/]*\.zip", re.IGNORECASE)


def _normalizar(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", texto)
                   if not unicodedata.combining(c)).casefold()


def _abrir(url: str):
    pedido = urllib.request.Request(url, headers=dict(CABECALHOS))
    return urllib.request.urlopen(pedido, timeout=120)


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.atual = None

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            dados = dict(attrs)
            self.atual = [dados.get("href", ""), [], dados.get("class", "")]

    def handle_data(self, data):
        if self.atual is not None:
            self.atual[1].append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self.atual is not None:
            href, partes, classe = self.atual
            self.links.append((href, " ".join(partes), classe))
            self.atual = None


def _momento_do_link(href: str) -> int:
    """O parametro t= da URL do portal: quanto maior, mais recente a publicacao."""
    achado = re.search(r"[?&]t=(\d+)", href)
    return int(achado.group(1)) if achado else 0


def _links_secoes(conteudo: str, pagina: str, ano: Optional[int] = None,
                  mes: Optional[int] = None) -> Dict[int, str]:
    """Tira do HTML do portal um link de ZIP por secao do DOU.

    O portal lista os arquivos num <ul class="dados-abertos-lista">, com nome
    S<secao><mes><ano>.zip (ex. S01112026_Atualizado171256.zip). Quando ha mais
    de um arquivo para a mesma secao, fica o de publicacao mais recente.
    """
    parser = _Links()
    parser.feed(conteudo)
    candidatos: Dict[int, Tuple[int, str]] = {}
    for href, titulo, classe in parser.links:
        if not href:
            continue
        achado = ARQUIVO_DOU.search(unquote(f"{href} {titulo}"))
        if not achado:
            continue
        numero, mes_arq, ano_arq = (int(achado.group(1)), int(achado.group(2)),
                                    int(achado.group(3)))
        if numero not in (1, 2, 3):
            continue
        # O portal as vezes mantem na pagina arquivo de outro mes: confere o nome.
        if (ano is not None and ano_arq != ano) or (mes is not None and mes_arq != mes):
            continue
        endereco = urljoin(pagina, href)
        momento = _momento_do_link(endereco)
        if numero not in candidatos or momento > candidatos[numero][0]:
            candidatos[numero] = (momento, endereco)
    return {secao: endereco for secao, (_, endereco) in candidatos.items()}


def listar(ano: int, mes: int) -> Dict[int, str]:
    """Localiza os ZIP mensais por secao na base de dados aberta da Imprensa Nacional.

    A pagina e sempre a mesma; o ano e o mes vao na query string, com o nome do
    mes escrito como o seletor do portal escreve ("Novembro", "Março").
    """
    if not 1 <= mes <= 12:
        raise ValueError("Mes deve estar entre 1 e 12.")
    pagina = f"{PAGINA_DADOS_ABERTOS}?ano={ano}&mes={quote(MESES[mes - 1])}"
    try:
        with _abrir(pagina) as resposta:
            charset = resposta.headers.get_content_charset() or "utf-8"
            conteudo = resposta.read().decode(charset, errors="replace")
            links = _links_secoes(conteudo, resposta.geturl(), ano, mes)
    except OSError as erro:
        raise RuntimeError(f"Nao foi possivel abrir {pagina}: {erro}") from erro
    if not links:
        raise RuntimeError(
            f"Nenhum ZIP do DOU encontrado para {mes:02d}/{ano} em {pagina}. "
            "O mes pode ainda nao ter publicacao, ou o portal mudou o formato da lista.")
    return links


def baixar_zip(url: str, destino: str) -> str:
    """Baixa em blocos para disco e repete ate tres vezes se houver falha."""
    destino = os.fspath(destino)
    os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
    parcial = destino + ".part"
    for tentativa in range(3):
        try:
            with _abrir(url) as resposta, open(parcial, "wb") as saida:
                esperado = resposta.headers.get("Content-Length")
                shutil.copyfileobj(resposta, saida, length=1024 * 1024)
            if esperado and os.path.getsize(parcial) != int(esperado):
                raise OSError("Download incompleto do ZIP.")
            with zipfile.ZipFile(parcial) as arquivo:
                if not arquivo.namelist():
                    raise ValueError("O ZIP recebido esta vazio.")
            os.replace(parcial, destino)
            return destino
        except (OSError, ValueError, zipfile.BadZipFile, EOFError):
            if os.path.exists(parcial):
                os.remove(parcial)
            if tentativa == 2:
                raise
            time.sleep(2 ** tentativa)
    raise RuntimeError("baixar_zip esgotou as tentativas")


def _atos_zip(arquivo: zipfile.ZipFile, prefixo: str = "") -> Iterator[Tuple[str, bytes]]:
    for item in arquivo.infolist():
        if item.is_dir():
            continue
        nome = prefixo + item.filename
        if item.filename.lower().endswith(".xml"):
            yield nome, arquivo.read(item)
        elif item.filename.lower().endswith(".zip"):
            # Tambem aceita pacotes mensais contendo ZIP diarios.
            with tempfile.TemporaryFile() as temporario:
                with arquivo.open(item) as origem:
                    shutil.copyfileobj(origem, temporario, length=1024 * 1024)
                temporario.seek(0)
                with zipfile.ZipFile(temporario) as interno:
                    for par in _atos_zip(interno, nome + "/"):
                        yield par


def atos_de_arquivo(caminho: str) -> Iterator[Tuple[str, bytes]]:
    """Le somente os XML, sem extrair o ZIP inteiro para disco."""
    with zipfile.ZipFile(caminho) as arquivo:
        for par in _atos_zip(arquivo):
            yield par


class _Texto(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.partes = []

    def handle_data(self, data):
        self.partes.append(data)

    def handle_starttag(self, tag, attrs):
        if tag in ("p", "br", "div", "li", "tr"):
            self.partes.append(" ")

    def handle_endtag(self, tag):
        if tag in ("p", "div", "li", "tr"):
            self.partes.append(" ")


def _sem_html(texto: str) -> str:
    parser = _Texto()
    parser.feed(texto)
    return re.sub(r"\s+", " ", html.unescape("".join(parser.partes))).strip()


def parse_ato(dado: bytes, nome: str) -> Optional[dict]:
    """Extrai os campos do artigo do XML da Imprensa Nacional."""
    raiz = ET.fromstring(dado)
    artigo = next((no for no in raiz.iter()
                   if no.tag.rsplit("}", 1)[-1].lower() == "article"), None)
    if artigo is None:
        return None
    campos = ("id", "idMateria", "name", "pubName", "pubDate", "artType",
              "artCategory", "numberPage", "editionNumber", "pdfPage")
    ato = {campo: artigo.get(campo, "").strip() for campo in campos}
    if not ato["id"]:
        raise ValueError(f"Artigo sem id: {nome}")
    for tag, campo in (("Identifica", "identifica"), ("Ementa", "ementa"), ("Texto", "texto")):
        no = next((no for no in artigo.iter()
                   if no.tag.rsplit("}", 1)[-1].lower() == tag.lower()), None)
        if no is None:
            ato[campo] = ""
        else:
            # Mantem separacao entre paragrafos tanto em CDATA quanto em elementos XML.
            conteudo = (no.text or "") + "".join(
                ET.tostring(filho, encoding="unicode") for filho in no
            )
            ato[campo] = _sem_html(conteudo)
    ato["arquivo"] = nome
    return ato


# ============================================================ caminhos

def landing_dir(lake: str, ano_mes: str, secao: int) -> str:
    return f"{lake}/landing/dou_xml/ano_mes={ano_mes}/secao={secao}"


def _q(valor: str) -> str:
    """Literal SQL seguro."""
    return "'" + valor.replace("'", "''") + "'"


def _prepara_destino(uri: str) -> None:
    if not uri.startswith("s3://"):
        os.makedirs(os.path.dirname(uri), exist_ok=True)


def _limpa_prefixo(uri: str, s3_client=None) -> None:
    """Apaga o que havia na particao, para a Landing ser substituida e nao somada."""
    if uri.startswith("s3://"):
        if s3_client is None:
            return
        bucket, prefixo = uri[len("s3://"):].split("/", 1)
        pag = s3_client.get_paginator("list_objects_v2")
        for pagina in pag.paginate(Bucket=bucket, Prefix=prefixo.rstrip("/") + "/"):
            chaves = [{"Key": o["Key"]} for o in pagina.get("Contents", [])]
            if chaves:
                s3_client.delete_objects(Bucket=bucket, Delete={"Objects": chaves})
    elif os.path.isdir(uri):
        shutil.rmtree(uri)


# ============================================================ DuckDB

def connect(s3: bool = False) -> duckdb.DuckDBPyConnection:
    con = duckdb.connect()
    con.sql("SET TimeZone = 'UTC'")

    # No Glue Python Shell o HOME e "/", que nao e gravavel. O DuckDB guarda as
    # extensoes em $HOME/.duckdb e morreria com
    # 'IO Error: Failed to create directory "/.duckdb/"'. Aponta para o temporario.
    tmp = os.environ.get("TMPDIR") or "/tmp"
    con.sql(f"SET home_directory = {_q(tmp)}")
    con.sql(f"SET extension_directory = {_q(tmp + '/.duckdb/extensions')}")

    if s3:
        con.sql("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
        con.sql("CREATE SECRET (TYPE s3, PROVIDER credential_chain)")
    return con


def _arrow(con: duckdb.DuckDBPyConnection, sql: str, schema: pa.Schema) -> pa.Table:
    """Executa a consulta e devolve Arrow com exatamente o esquema da tabela Iceberg."""
    return con.sql(sql).fetch_arrow_table().select(schema.names).cast(schema)


def _location(lake: str, ident: str) -> Optional[str]:
    if not lake.startswith("s3://"):
        return None  # catalogo local decide a pasta
    db, tabela = ident.split(".")
    return f"{lake}/{db.replace('_db', '')}/{tabela}"


def ensure_table(catalog, ident: str, lake: str):
    ns = ident.split(".")[0]
    if (ns,) not in catalog.list_namespaces():
        catalog.create_namespace(ns)  # no Glue o database ja vem do template
    return catalog.create_table_if_not_exists(
        ident, schema=SCHEMAS[ident], location=_location(lake, ident))


def _so_os_novos(con: duckdb.DuckDBPyConnection, tabela, novos: pa.Table,
                 chave: List[str]) -> pa.Table:
    """Anti-join com o que ja esta na tabela Iceberg.

    Reproduz o 'WHEN NOT MATCHED THEN INSERT' dos scripts do Databricks: linha
    com chave ja existente nao atualiza nada. O scan traz so as colunas da chave,
    para nao carregar os XML inteiros.
    """
    existentes = tabela.scan(selected_fields=tuple(chave)).to_arrow()
    if existentes.num_rows == 0:
        return novos
    con.register("novos_aj", novos)
    con.register("existentes_aj", existentes)
    condicao = " AND ".join(f"e.{c} IS NOT DISTINCT FROM n.{c}" for c in chave)
    resultado = con.sql(f"""
        SELECT n.* FROM novos_aj n
        WHERE NOT EXISTS (SELECT 1 FROM existentes_aj e WHERE {condicao})
    """).fetch_arrow_table().select(novos.schema.names).cast(novos.schema)
    con.unregister("novos_aj")
    con.unregister("existentes_aj")
    return resultado


# ============================================================ etapas

def landing(con: duckdb.DuckDBPyConnection, lake: str, ano: int, mes: int, secao: int,
            pasta_tmp: Optional[str] = None, s3_client=None) -> int:
    """Baixa o ZIP do mes direto da Imprensa Nacional e grava os XML crus em Parquet."""
    links = listar(ano, mes)
    if secao not in links:
        raise ValueError(f"Secao {secao} nao encontrada para {mes:02d}/{ano}: {sorted(links)}")
    url = links[secao]
    ano_mes = f"{ano}-{mes:02d}"
    log.info("coletando %s, secao %d. ZIP: %s", ano_mes, secao, url)

    destino = landing_dir(lake, ano_mes, secao)
    _limpa_prefixo(destino, s3_client)
    coletado_em = datetime.datetime.now(datetime.timezone.utc)

    criada = pasta_tmp is None
    pasta = pasta_tmp or tempfile.mkdtemp(prefix="dou-")
    try:
        caminho_zip = baixar_zip(url, os.path.join(pasta, f"dou-S0{secao}-{ano}{mes:02d}.zip"))
        log.info("ZIP local: %.0f MB", os.path.getsize(caminho_zip) / 1e6)

        lote: List[tuple] = []
        parte = total = 0

        def descarrega() -> None:
            nonlocal parte, lote
            parte += 1
            _grava_lote(con, lote, destino, parte)
            lote = []

        for nome, dado in atos_de_arquivo(caminho_zip):
            if isinstance(dado, str):
                dado = dado.encode("utf-8")
            lote.append((hashlib.sha256(dado).hexdigest(), nome, dado,
                         secao, ano_mes, coletado_em))
            total += 1
            if len(lote) >= LOTE_LANDING:
                descarrega()
        if lote:
            descarrega()
        os.remove(caminho_zip)
    finally:
        if criada:
            shutil.rmtree(pasta, ignore_errors=True)

    if not total:
        raise ColetaVaziaError("O ZIP nao contem XML; as proximas etapas nao devem rodar.")
    log.info("landing %s secao %d: %d XML em %d arquivo(s)", ano_mes, secao, total, parte)
    return total


def _grava_lote(con: duckdb.DuckDBPyConnection, lote: List[tuple], destino: str,
                parte: int) -> None:
    colunas = list(zip(*lote))
    tabela = pa.table({
        "hash_xml": pa.array(colunas[0], pa.string()),
        "arquivo": pa.array(colunas[1], pa.string()),
        "xml": pa.array(colunas[2], pa.binary()),
        "secao": pa.array(colunas[3], pa.int32()),
        "ano_mes": pa.array(colunas[4], pa.string()),
        "coletado_em": pa.array(colunas[5], TS),
    }, schema=LANDING_SCHEMA)
    saida = f"{destino}/part-{parte:05d}.parquet"
    _prepara_destino(saida)
    con.register("lote_landing", tabela)
    con.sql(f"COPY (SELECT * FROM lote_landing) TO {_q(saida)} "
            f"(FORMAT parquet, COMPRESSION zstd)")
    con.unregister("lote_landing")


def bronze(con: duckdb.DuckDBPyConnection, catalog, lake: str, ano_mes: str,
           secao: int) -> int:
    """Insere na Bronze os XML da Landing, sem repetir o mesmo arquivo/conteudo."""
    glob = f"{landing_dir(lake, ano_mes, secao)}/*.parquet"
    novos = _arrow(con, f"""
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (
                   PARTITION BY arquivo, hash_xml, secao, ano_mes
                   ORDER BY coletado_em) AS rn
          FROM read_parquet({_q(glob)})
        ) WHERE rn = 1
    """, SCHEMAS[BRONZE_XML])

    tabela = ensure_table(catalog, BRONZE_XML, lake)
    inserir = _so_os_novos(con, tabela, novos, CHAVE_BRONZE)
    if inserir.num_rows:
        tabela.append(inserir)
    log.info("bronze %s secao %d: %d na landing, %d novos", ano_mes, secao,
             novos.num_rows, inserir.num_rows)
    return inserir.num_rows


def _linhas_do_xml(registros: Iterator[dict]) -> Tuple[List[dict], int, int]:
    """Aplica o parse_ato a cada XML da Bronze. Devolve as linhas da Prata."""
    linhas: List[dict] = []
    vistos = erros = 0
    for reg in registros:
        vistos += 1
        try:
            ato = parse_ato(bytes(reg["xml"]), reg["arquivo"])
            if not ato:
                continue
            dia, mes, ano = ato["pubDate"].split("/")
            linhas.append({
                "id": ato["id"],
                "id_materia": ato["idMateria"],
                "nome": ato["name"],
                "jornal": ato["pubName"],
                "data_publicacao": datetime.date(int(ano), int(mes), int(dia)),
                "tipo": ato["artType"],
                "orgao": ato["artCategory"],
                "pagina": int(ato["numberPage"]) if ato["numberPage"].isdigit() else None,
                "edicao": ato["editionNumber"],
                "url_pdf": ato["pdfPage"],
                "identifica": ato["identifica"],
                "ementa": ato["ementa"],
                "texto": ato["texto"],
                "arquivo": ato["arquivo"],
                "secao": reg["secao"],
                "ano_mes": reg["ano_mes"],
                "coletado_em": reg["coletado_em"],
            })
        except Exception as erro:  # noqa: BLE001
            erros += 1
            log.warning("XML com erro: %s: %s", reg.get("arquivo"), erro)
    return linhas, vistos, erros


def _registros_da_bronze(tabela, ano_mes: str, secao: int) -> Iterator[dict]:
    """Le a Bronze do mes/secao em lotes, para nao ter todos os XML na memoria."""
    from pyiceberg.expressions import And, EqualTo

    scan = tabela.scan(row_filter=And(EqualTo("ano_mes", ano_mes), EqualTo("secao", secao)))
    leitor = getattr(scan, "to_arrow_batch_reader", None)
    if leitor is None:
        for reg in scan.to_arrow().to_pylist():
            yield reg
        return
    for lote in leitor():
        for reg in lote.to_pylist():
            yield reg


def prata(con: duckdb.DuckDBPyConnection, catalog, lake: str, ano_mes: str,
          secao: int) -> int:
    """Faz o parse dos XML da Bronze e insere na Prata os id ainda nao vistos."""
    bronze_t = catalog.load_table(BRONZE_XML)
    linhas, vistos, erros = _linhas_do_xml(_registros_da_bronze(bronze_t, ano_mes, secao))
    log.info("prata %s secao %d: %d XML lidos, %d atos validos, %d com erro",
             ano_mes, secao, vistos, len(linhas), erros)
    if erros and not linhas:
        raise ValueError(f"Nenhum ato valido: {erros} XML com erro.")
    if not linhas:
        return 0

    esquema = SCHEMAS[PRATA_ATOS]
    candidatos = pa.Table.from_pylist(linhas, schema=esquema)
    con.register("candidatos", candidatos)
    # Mesmo desempate do script do Databricks: por id, fica a coleta mais antiga.
    novos = _arrow(con, """
        SELECT * EXCLUDE (rn) FROM (
          SELECT *, row_number() OVER (PARTITION BY id ORDER BY coletado_em) AS rn
          FROM candidatos
          WHERE id IS NOT NULL AND trim(id) <> ''
        ) WHERE rn = 1
    """, esquema)
    con.unregister("candidatos")

    tabela = ensure_table(catalog, PRATA_ATOS, lake)
    inserir = _so_os_novos(con, tabela, novos, CHAVE_PRATA)
    if inserir.num_rows:
        tabela.append(inserir)
    log.info("prata %s secao %d: %d novos atos", ano_mes, secao, inserir.num_rows)
    return inserir.num_rows


def ouro(con: duckdb.DuckDBPyConnection, catalog, lake: str) -> int:
    """Resumo mensal recalculado a partir de toda a Prata, para nao somar duas vezes."""
    atos = catalog.load_table(PRATA_ATOS).scan(
        selected_fields=("ano_mes", "orgao", "data_publicacao")).to_arrow()
    con.register("atos", atos)
    # O script do Databricks usa ILIKE '%Energia Eletrica%'. Aqui tira o acento
    # antes de comparar, para pegar tambem orgao gravado sem acentuacao.
    resumo = _arrow(con, """
        SELECT ano_mes,
               count(*) AS atos,
               count(*) FILTER (
                 WHERE lower(strip_accents(coalesce(orgao, ''))) LIKE '%energia eletrica%'
               ) AS atos_aneel,
               min(data_publicacao) AS de,
               max(data_publicacao) AS ate
        FROM atos
        GROUP BY ano_mes
        ORDER BY ano_mes
    """, SCHEMAS[OURO_RESUMO])
    con.unregister("atos")

    ensure_table(catalog, OURO_RESUMO, lake).overwrite(resumo)
    log.info("ouro: %d meses", resumo.num_rows)
    return resumo.num_rows


# ============================================================ entrada do job

def mes_atual_brasilia() -> Tuple[int, int]:
    agora = datetime.datetime.now(datetime.timezone(datetime.timedelta(hours=-3)))
    return agora.year, agora.month


def parse_args(argv: List[str]) -> Dict[str, str]:
    """Le pares --CHAVE valor (formato que o Glue passa ao script)."""
    args: Dict[str, str] = {}
    i = 0
    while i < len(argv):
        if argv[i].startswith("--") and i + 1 < len(argv) and not argv[i + 1].startswith("--"):
            args[argv[i][2:]] = argv[i + 1]
            i += 2
        else:
            i += 1
    for obrigatorio in ("STAGE", "LAKE_URI"):
        if obrigatorio not in args:
            raise SystemExit(f"faltou --{obrigatorio}")
    if args["STAGE"] not in ("landing", "bronze", "prata", "ouro"):
        raise SystemExit(f"--STAGE desconhecido: {args['STAGE']}")
    return args


def main(argv: List[str]) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s %(message)s")
    args = parse_args(argv)
    stage, lake = args["STAGE"], args["LAKE_URI"].rstrip("/")
    region = (args.get("REGION") or os.environ.get("AWS_REGION")
              or os.environ.get("AWS_DEFAULT_REGION"))

    ano_padrao, mes_padrao = mes_atual_brasilia()
    ano = int(args.get("ANO") or ano_padrao)
    mes = int(args.get("MES") or mes_padrao)
    secao = int(args.get("SECAO") or 1)
    ano_mes = f"{ano}-{mes:02d}"

    import boto3
    from pyiceberg.catalog import load_catalog

    no_s3 = lake.startswith("s3://")
    con = connect(s3=no_s3)
    catalog = load_catalog("glue", **{"type": "glue", "glue.region": region,
                                      "client.region": region, "s3.region": region})

    if stage == "landing":
        landing(con, lake, ano, mes, secao,
                s3_client=boto3.client("s3", region_name=region) if no_s3 else None)
    elif stage == "bronze":
        bronze(con, catalog, lake, ano_mes, secao)
    elif stage == "prata":
        prata(con, catalog, lake, ano_mes, secao)
    elif stage == "ouro":
        ouro(con, catalog, lake)


if __name__ == "__main__":
    main(sys.argv[1:])
