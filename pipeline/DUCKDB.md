# Como o DuckDB foi usado

Documento sobre o papel do DuckDB no ETL. O assunto principal é o **ETL completo de quatro
camadas**, `landing → bronze → prata → ouro`, em `dou/src/etl_dou.py`. O outro ETL
da pasta, `cadastro/src/etl.py`, aparece quando resolve o mesmo problema de outra forma.

Todos os trechos abaixo saíram do código desta pasta, não de memória.

## As quatro camadas, em ordem

Uma etapa por execução do job, escolhida por `--STAGE`. A máquina de estados chama as quatro
em sequência: `Landing → Bronze → Prata → Ouro`.

| Etapa | Entrada | Saída | Formato | Semântica de escrita |
|---|---|---|---|---|
| `landing` | ZIP da Imprensa Nacional, por HTTP | `landing/dou_xml/ano_mes=.../secao=.../part-*.parquet` | Parquet | substitui a partição |
| `bronze` | Parquet da Landing do mês | `bronze_db.dou_xml` | Iceberg | só insere chave nova |
| `prata` | Bronze do mês e seção | `silver_db.dou_atos` | Iceberg | só insere `id` novo |
| `ouro` | **toda** a Prata | `gold_db.dou_resumo_mensal` | Iceberg | recalcula e sobrescreve |

Por que cada uma é assim:

- **A Landing substitui, não soma.** O ZIP do mês é rebaixado inteiro a cada coleta, e o
  portal republica o arquivo atualizado várias vezes no mês. Somar duplicaria. `_limpa_prefixo()`
  apaga a partição antes de gravar, e é a única etapa que apaga algo no S3.
- **Bronze e Prata só inserem.** É o `WHEN NOT MATCHED THEN INSERT` dos scripts originais do
  Databricks, reproduzido por anti-join. Reprocessar o mesmo mês não muda nada.
- **A Ouro recalcula tudo.** Agregar incrementalmente somaria duas vezes num reprocessamento.
  O volume é pequeno, então recalcular da Prata inteira é mais simples e mais seguro.

### landing: HTTP, ZIP e Parquet em lotes

Esta etapa não tem SQL de transformação, só escrita. O XML é lido do ZIP em memória, 500 por
vez, e cada lote vira um arquivo Parquet (`etl_dou.py:473`):

```python
con.register("lote_landing", tabela)        # tabela Arrow de 500 linhas
con.sql(f"COPY (SELECT * FROM lote_landing) TO {_q(saida)} "
        f"(FORMAT parquet, COMPRESSION zstd)")
con.unregister("lote_landing")
```

Sai `part-00001.parquet`, `part-00002.parquet` e assim por diante na mesma partição. Nunca se
mantém o ZIP inteiro descomprimido em memória, e o ZIP baixado é apagado no fim.

### bronze: dedup na carga, depois anti-join contra o que já existe

Duas defesas em sequência. Primeiro a carga é deduplicada por janela (`etl_dou.py:492`):

```sql
SELECT * EXCLUDE (rn) FROM (
  SELECT *, row_number() OVER (
           PARTITION BY arquivo, hash_xml, secao, ano_mes
           ORDER BY coletado_em) AS rn
  FROM read_parquet('.../landing/dou_xml/ano_mes=2026-11/secao=1/*.parquet')
) WHERE rn = 1
```

O glob `*.parquet` recolhe os vários `part-` como um conjunto só. Depois o `_so_os_novos()`
descarta o que já está na tabela Iceberg (`etl_dou.py:398`):

```sql
SELECT n.* FROM novos_aj n
WHERE NOT EXISTS (SELECT 1 FROM existentes_aj e
                  WHERE e.arquivo IS NOT DISTINCT FROM n.arquivo
                    AND e.hash_xml IS NOT DISTINCT FROM n.hash_xml
                    AND e.secao IS NOT DISTINCT FROM n.secao
                    AND e.ano_mes IS NOT DISTINCT FROM n.ano_mes)
```

Dois detalhes que fazem diferença:

- **`IS NOT DISTINCT FROM` em vez de `=`**, porque compara `NULL` com `NULL` como igual, que é
  o que se quer numa chave que pode ter coluna nula.
- **O lado `existentes_aj` só traz as colunas da chave**, via
  `tabela.scan(selected_fields=("arquivo","hash_xml","secao","ano_mes")).to_arrow()`. A Bronze
  guarda o XML cru; carregar a coluna `xml` só para fazer anti-join seria desastroso.

### prata: parse em Python, desempate em SQL

O parse do XML não dá para fazer em SQL, então roda em Python. O que importa aqui é **como a
Bronze é lida**: em lotes, não de uma vez (`etl_dou.py:565`):

```python
scan = tabela.scan(row_filter=And(EqualTo("ano_mes", ano_mes), EqualTo("secao", secao)))
for lote in scan.to_arrow_batch_reader():
    for reg in lote.to_pylist():
        ...parse_ato(bytes(reg["xml"]), reg["arquivo"])...
```

O `row_filter` empurra o filtro para o Iceberg, que descarta arquivos inteiros pela estatística
de partição, e o `to_arrow_batch_reader()` streama em vez de materializar centenas de MB.

Depois o DuckDB entra para desempatar por `id`:

```sql
SELECT * EXCLUDE (rn) FROM (
  SELECT *, row_number() OVER (PARTITION BY id ORDER BY coletado_em) AS rn
  FROM candidatos
  WHERE id IS NOT NULL AND trim(id) <> ''
) WHERE rn = 1
```

`ORDER BY coletado_em` **ascendente**, ao contrário da Silver do cadastro, que usa
descendente. Aqui queremos a coleta mais antiga, porque a semântica é só inserção: o primeiro
registro de um ato é o que vale, e republicações do mesmo `id` não sobrescrevem.

### ouro: agregação com acento removido

A Prata inteira é lida trazendo três colunas, registrada no DuckDB e agregada
(`etl_dou.py:598`):

```sql
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
```

`strip_accents` é um desvio deliberado do original. O script do Databricks usava
`ILIKE '%Energia Elétrica%'`, que depende do acento estar gravado. Tirar o acento dos dois
lados pega também o registro escrito sem acentuação. O resultado foi conferido contra a origem
no Databricks e bateu: 1931 atos e 110 da ANEEL.

## Por que DuckDB, e não Spark

O Glue tem dois tipos de job. O **Glue ETL (Spark)** cobra no mínimo 2 DPU e sobe um cluster;
o **Glue Python Shell** é um processo Python só, de 1 DPU (4 vCPU, 16 GB), e começa a rodar em
segundos. Para um volume de um item por usuário, Spark é desproporcional.

O problema é que **o conector DynamoDB do Glue só funciona com Spark**. A saída foi pedir o
export nativo do DynamoDB para o S3 pela Step Functions e ler os arquivos resultantes com
DuckDB dentro do Python Shell. O DuckDB virou a engine de transformação, e o PyIceberg cuida
só da escrita nas tabelas Iceberg.

Divisão de trabalho em uma linha: **DuckDB lê, transforma e escreve Parquet; PyIceberg escreve
Iceberg; boto3 fala com as APIs da AWS.**

## Como a conexão é aberta

`connect()` em `cadastro/src/etl.py:117` e `dou/src/etl_dou.py:361`:

```python
con = duckdb.connect()                 # banco em memória, sem arquivo
con.sql("SET TimeZone = 'UTC'")

tmp = os.environ.get("TMPDIR") or "/tmp"
con.sql(f"SET home_directory = {_q(tmp)}")
con.sql(f"SET extension_directory = {_q(tmp + '/.duckdb/extensions')}")

if s3:
    con.sql("INSTALL httpfs; LOAD httpfs; INSTALL aws; LOAD aws;")
    con.sql("CREATE SECRET (TYPE s3, PROVIDER credential_chain)")
```

Quatro decisões aqui, e três delas foram aprendidas na dor:

1. **Banco em memória.** Nunca se cria arquivo `.duckdb`. O estado todo vive no S3.
2. **`SET TimeZone = 'UTC'`** antes de qualquer coisa, para `TIMESTAMPTZ` não depender do fuso
   da máquina e o resultado ser igual no teste local e no Glue.
3. **`home_directory` e `extension_directory` apontando para o temporário.** No Glue Python
   Shell o `HOME` é `/`, que não é gravável. Sem isso o job morre com
   `IO Error: Failed to create directory "/.duckdb/"` na hora de instalar a extensão.
4. **`credential_chain` em vez de chave.** O secret do tipo `s3` com
   `PROVIDER credential_chain` faz o DuckDB usar a role do job. Nenhuma credencial aparece no
   código. As extensões `httpfs` e `aws` são baixadas na hora da execução, o que exige saída
   para a internet: se o job for para dentro de uma VPC sem NAT, elas têm de ser empacotadas.

O parâmetro `s3` é o que deixa o mesmo código rodar nos testes com pastas locais. Quando o
caminho não começa com `s3://`, as extensões não são carregadas e tudo vira arquivo em disco.

## Leitura do export do DynamoDB

O export sai em DynamoDB JSON comprimido, uma linha por item. `landing()`
(`cadastro/src/etl.py:150`):

```sql
COPY (
  SELECT Item AS item,
         now() AS _ingested_at,
         'dynamodb:usuarios-cnpj' AS _source
  FROM read_json('s3://.../data/*.json.gz',
                 format = 'newline_delimited',
                 columns = {'Item': 'JSON'})
) TO 's3://.../landing/usuarios_cnpj/dt=2026-11-07/data.parquet'
  (FORMAT parquet, COMPRESSION snappy)
```

Dois pontos:

- **`columns = {'Item': 'JSON'}` desliga a inferência de esquema** de propósito. O campo
  `empresa` é a resposta inteira do OpenCNPJ e muda de item para item: um tem `cnaes`, outro
  não, um tem 41 sócios, outro nenhum. Deixar o DuckDB inferir quebraria conforme o lote. Na
  Landing o item fica como JSON, cru, e a tipagem só acontece na Bronze.
- O `.gz` é descomprimido pelo DuckDB sem passo intermediário, e o glob `*.json.gz` cobre as
  várias partes do export.

## Extração de campos do DynamoDB JSON

O DynamoDB JSON embrulha todo valor num mapa de tipo: `{"S": "texto"}`, `{"M": {...}}`,
`{"L": [...]}`. O operador `->>` do DuckDB percorre isso com JSON path. `bronze()`
(`cadastro/src/etl.py:170`):

```sql
SELECT
  item->>'$.user_id.S'                                  AS user_id,
  item->>'$.cnpj.S'                                     AS cnpj,
  item->>'$.status.S'                                   AS status,
  CAST(item->>'$.consultado_em.S' AS TIMESTAMPTZ)       AS consultado_em,
  item->>'$.empresa.M.razao_social.S'                   AS razao_social,
  item->>'$.empresa.M.situacao_cadastral.S'             AS situacao_cadastral,
  TRY_CAST(replace(replace(
    item->>'$.empresa.M.capital_social.S', '.', ''), ',', '.')
    AS DECIMAL(20,2))                                   AS capital_social,
  CAST(json_array_length(item->'$.empresa.M.QSA.L') AS INTEGER) AS qtd_socios,
  CAST(item->'$.empresa' AS VARCHAR)                    AS empresa_raw,
  md5(CAST(item AS VARCHAR))                            AS _row_hash,
  _ingested_at
FROM read_parquet('s3://.../landing/usuarios_cnpj/dt=2026-11-07/data.parquet')
```

Detalhes que importam:

- **`->>` devolve texto, `->` devolve JSON.** Por isso `json_array_length(item->'...QSA.L')`
  usa a flecha simples, e `empresa_raw` usa `CAST(item->'$.empresa' AS VARCHAR)` para guardar
  o JSON inteiro como string.
- **Campo que não existe vira `NULL`, não erro.** É o que permite o mesmo SQL atender um
  `status = 'nao_encontrado'`, que não tem `empresa` nenhuma.
- **O capital social vem como `"120000000000,00"`**, no formato brasileiro. A conversão é tirar
  o ponto de milhar e trocar a vírgula por ponto, com `TRY_CAST` para não derrubar a carga se
  vier lixo.
- **`DECIMAL(20,2)`, não `DECIMAL(18,2)`.** Com precisão 18 o PyIceberg 0.9 falha no upsert,
  porque espera `INT64` físico e o pyarrow grava `FIXED_LEN_BYTE_ARRAY`.
- **`md5(CAST(item AS VARCHAR))`** dá um `_row_hash` barato para detectar mudança de linha.

## Explodir lista em linhas

Os sócios são uma lista dentro do item. Virar uma linha por sócio usa `UNNEST` com um cast
para array de JSON (`cadastro/src/etl.py:188`):

```sql
SELECT item->>'$.user_id.S'           AS user_id,
       item->>'$.cnpj.S'              AS cnpj,
       socio->>'$.M.nome_socio.S'     AS nome_socio,
       CAST(socio->'$.M' AS VARCHAR)  AS socio_raw
FROM read_parquet('...'),
     UNNEST(CAST(item->'$.empresa.M.QSA.L' AS JSON[])) AS t(socio)
```

`CAST(... AS JSON[])` transforma o array JSON em array nativo do DuckDB, e o `UNNEST` no
`FROM` faz o produto cartesiano com a linha de origem. Item sem `QSA` simplesmente não produz
linha, sem precisar de `LEFT JOIN`.

## Deduplicação antes de gravar

Em toda etapa que escreve Iceberg, a carga passa por uma janela para garantir uma linha por
chave. `silver()` (`cadastro/src/etl.py:246`):

```sql
SELECT * EXCLUDE (rn), '2026-11-07' AS _carga_dt FROM (
  SELECT *, row_number() OVER (
           PARTITION BY user_id ORDER BY consultado_em DESC) AS rn
  FROM read_parquet('...bronze/usuarios_cnpj/dt=2026-11-07/data.parquet')
) WHERE rn = 1
```

`SELECT * EXCLUDE (rn)` é açúcar do DuckDB que evita listar as doze colunas só para descartar
uma. A mesma receita aparece na Bronze dos atos, com `PARTITION BY arquivo, hash_xml, secao,
ano_mes ORDER BY coletado_em`, e na Prata com `PARTITION BY id ORDER BY coletado_em`, ali
mantendo a coleta **mais antiga** para o merge ser só de inserção.

## Checagens de qualidade numa consulta só

`checar_qualidade()` (`cadastro/src/etl.py:229`) usa `FILTER` para contar quatro problemas
diferentes numa varredura:

```sql
SELECT count(*) FILTER (WHERE user_id IS NULL),
       count(*) - count(DISTINCT user_id),
       count(*) FILTER (WHERE status IS NULL OR status NOT IN ('ativa','inativa','nao_encontrado','cnpj_invalido')),
       count(*) FILTER (WHERE cnpj IS NOT NULL AND length(cnpj) <> 14)
FROM novos_q
```

Se qualquer contador for diferente de zero, a etapa levanta `QualidadeError`, o job falha e a
Gold não roda. A tabela `novos_q` aqui não existe no disco: é uma tabela Arrow registrada, que
é o assunto da próxima seção.

## A ponte com o Arrow e o PyIceberg

É o ponto central do desenho. O DuckDB e o PyIceberg trocam dados em Arrow, sem passar por
arquivo nem por pandas.

**Do DuckDB para o Iceberg**, `_arrow()` (`cadastro/src/etl.py:134`):

```python
def _arrow(con, sql, schema):
    return con.sql(sql).fetch_arrow_table().select(schema.names).cast(schema)
```

Três operações encadeadas, cada uma por um motivo: `fetch_arrow_table()` materializa o
resultado em Arrow; `.select(schema.names)` força a **ordem** das colunas igual à da tabela
Iceberg; `.cast(schema)` força os **tipos** exatos. Sem isso o PyIceberg recusa a escrita por
divergência de esquema, e o erro que ele dá é difícil de ler. Toda escrita Iceberg do projeto
passa por essa função.

**Do Iceberg para o DuckDB**, `con.register()`:

```python
usuarios = catalog.load_table(SILVER_USUARIOS).scan().to_arrow()
con.register("usuarios", usuarios)
# ... agora "usuarios" é uma tabela SQL normal
con.unregister("usuarios")
```

O `register` expõe uma tabela Arrow como se fosse tabela do banco, sem copiar dados. É assim
que a Gold faz agregação sobre a Silver, e é assim que o `_so_os_novos()` dos atos
(`dou/src/etl_dou.py:398`) faz anti-join contra o que já está no Iceberg:

```sql
SELECT n.* FROM novos_aj n
WHERE NOT EXISTS (SELECT 1 FROM existentes_aj e
                  WHERE e.arquivo IS NOT DISTINCT FROM n.arquivo AND ...)
```

`IS NOT DISTINCT FROM` em vez de `=` porque compara `NULL` com `NULL` como igual, que é o
comportamento desejado numa chave que pode ter coluna nula. E o lado `existentes_aj` vem de
`tabela.scan(selected_fields=("arquivo","hash_xml","secao","ano_mes")).to_arrow()`, trazendo só
as colunas da chave: num bronze com XML de centenas de MB, carregar a coluna `xml` para fazer
anti-join seria desastroso.

**O DuckDB nunca escreve Iceberg.** Quem escreve é o PyIceberg, e cada etapa escolhe a
semântica: `upsert(join_cols=["user_id"])` na Silver, `append()` depois de anti-join na Bronze
e Prata dos atos, `overwrite()` na Gold e na Ouro, `delete(In(...))` para trocar a lista de
sócios inteira.

## Agregação na Gold

`gold()` (`cadastro/src/etl.py:279`) e `ouro()` (`dou/src/etl_dou.py:598`):

```sql
-- cadastro
SELECT CAST(consultado_em AS DATE) AS dia, status, count(*) AS cadastros
FROM usuarios GROUP BY ALL ORDER BY dia, status

-- atos do DOU
SELECT ano_mes,
       count(*) AS atos,
       count(*) FILTER (
         WHERE lower(strip_accents(coalesce(orgao, ''))) LIKE '%energia eletrica%'
       ) AS atos_aneel,
       min(data_publicacao) AS de, max(data_publicacao) AS ate
FROM atos GROUP BY ano_mes ORDER BY ano_mes
```

`GROUP BY ALL` agrupa por tudo que não é agregação, sem repetir a lista. E `strip_accents` é o
que permite casar "Energia Elétrica" com registros gravados sem acento: o original no
Databricks usava `ILIKE '%Energia Elétrica%'`, que depende do acento estar lá.

## Escrita de Parquet em lotes

A Landing dos atos recebe milhares de XML, e manter todos em memória seria arriscado.
`_grava_lote()` (`dou/src/etl_dou.py:473`) monta uma tabela Arrow de 500 linhas, registra
e descarrega:

```python
con.register("lote_landing", tabela)
con.sql(f"COPY (SELECT * FROM lote_landing) TO {_q(saida)} "
        f"(FORMAT parquet, COMPRESSION zstd)")
con.unregister("lote_landing")
```

Resulta em `part-00001.parquet`, `part-00002.parquet` e assim por diante na mesma partição, que
a leitura seguinte recolhe com `read_parquet('.../*.parquet')` como um conjunto só.

`snappy` na Landing e `zstd` na Bronze: a Landing é lida uma vez pela etapa seguinte e
descompressão rápida importa mais, a Bronze fica 90 dias e compressão importa mais.

## O mesmo código local e no S3

Nenhuma etapa sabe se está no S3. A diferença inteira está em duas funções:

```python
def _q(uri):                       # literal SQL seguro para caminho
    return "'" + uri.replace("'", "''") + "'"

def _prepara_destino(uri):         # cria a pasta, só no caso local
    if not uri.startswith("s3://"):
        os.makedirs(os.path.dirname(uri), exist_ok=True)
```

Como o `read_parquet` e o `COPY ... TO` do DuckDB aceitam `s3://` e caminho de disco com a
mesma sintaxe, os 24 testes rodam em `tmp_path` com catálogo Iceberg em SQLite, exercitando
exatamente o mesmo SQL que roda no Glue. É o que torna o ETL testável sem AWS.

## Versão e o que não mudar junto

`duckdb==1.2.2`, fixado igual no `pyproject.toml` e no `--additional-python-modules` do
template. Duas regras ao mexer nisso:

- A versão do `pyproject.toml` e a do template têm de andar juntas, senão o teste local valida
  uma coisa e o Glue roda outra.
- O `--additional-python-modules` é **separado por vírgula antes de chegar ao pip**. Extra com
  vírgula dentro quebra: `pyiceberg[glue,pyarrow]==0.9.1` é partido em `pyiceberg[glue` e
  `pyarrow]==0.9.1`, e o pip responde `Invalid requirement`. Escreva um spec por extra.
