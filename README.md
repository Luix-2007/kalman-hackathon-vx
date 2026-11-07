# ETL no Glue com DuckDB e Iceberg: pacote de referência

Pacote para refazer depois, em outra conta ou em outro evento. São **só arquivos**: nada aqui
implanta, agenda ou cria recurso na AWS.

Contém os dois ETL **básicos que ficaram prontos e rodaram ponta a ponta** em 07/11/2026. Não
contém o trabalho de embeddings, classificação por tipo e Knowledge Base, que estava em
andamento quando o pacote foi gerado.

A descrição detalhada do uso do DuckDB, que é o coração das duas pipelines, está em
**[DUCKDB.md](DUCKDB.md)**.

## O que são os dois ETL

| | `cadastro/` | `atos-dou/` |
|---|---|---|
| Origem | tabela DynamoDB, via export nativo para o S3 | ZIP mensal da Imprensa Nacional, por HTTP |
| Etapas | `landing → bronze → silver → gold → kb_docs` | `landing → bronze → prata → ouro` |
| Formato | Landing e Bronze em Parquet, Silver e Gold em Iceberg | Landing em Parquet, resto em Iceberg |
| Runtime | Glue Python Shell, Python 3.9, 1 DPU | igual |
| Engine | DuckDB 1.2.2 | igual |
| Escrita Iceberg | PyIceberg 0.9.1 no Glue Data Catalog | igual |
| Testes | 7, sem AWS | 17, sem AWS e sem rede |

As duas gravam no **mesmo bucket** e no **mesmo Glue Data Catalog**, mas têm job Glue e máquina
de estados separados. É isso que permite rodar uma sem mexer na outra.

## Onde cada arquivo roda

Isso importa mais do que parece: cada script tem um runtime e uma identidade diferente.

| Arquivo | Onde roda | Identidade |
|---|---|---|
| `cadastro/src/etl.py` | Glue Python Shell 3.9 | role do job Glue |
| `atos-dou/src/etl_dou.py` | Glue Python Shell 3.9 | role do job Glue |
| `*/tests/*.py` | máquina local, Python 3.9 | nenhuma, não toca a AWS |
| `*/scripts/verificar.py` | máquina local, Python 3.9 | suas credenciais, somente leitura |
| `lambda-origem/src/app.py` | AWS Lambda, Python 3.13 | role da Lambda |
| `databricks-origem/*.py` | Databricks, PySpark | não roda mais, é referência |

**Um login local não dá acesso ao job Glue.** A role do job precisa das permissões do próprio
`template.yaml`, e um `aws sts get-caller-identity` que funciona no seu terminal não prova nada
sobre o que o job consegue fazer.

## Conteúdo

```
cadastro/                 ETL do DynamoDB (as versões que estão implantadas e funcionando)
  src/etl.py              426 linhas, 5 etapas escolhidas por --STAGE
  tests/test_etl.py       7 testes, catálogo Iceberg em SQLite, pastas locais
  scripts/verificar.py    confere o lake depois de uma execução, sem Athena
  statemachine/           definição da Step Functions, extraída do que está implantado
  template.yaml           SAM, extraído do stack implantado (628 linhas)
  pyproject.toml          dependências diretas
atos-dou/                 ETL dos atos do DOU, portado do Databricks
  src/etl_dou.py          682 linhas, coleta HTTP + 4 etapas
  tests/test_etl_dou.py   17 testes, com ZIP montado no próprio teste
  scripts/verificar.py
  statemachine/ template.yaml Makefile pyproject.toml
lambda-origem/            a Lambda que alimenta o lake. É o contrato de entrada, não é Glue
databricks-origem/        os scripts PySpark originais que o atos-dou/ substituiu
DUCKDB.md                 como o DuckDB foi usado, com o SQL real
```

### Por que o `cadastro/` vem do que está implantado

O `src/etl.py`, o `template.yaml` e a máquina de estados foram extraídos da AWS, não copiados
do diretório de trabalho: o script do bucket de artefatos do job Glue, o template com
`get-template --template-stage Original` e a definição com `describe-state-machine`. O motivo é
que o repositório estava sendo alterado em paralelo, com a parte de embeddings. O que está aqui
é a versão que **de fato rodou verde**, não uma versão intermediária.

Consequência: a máquina de estados deste pacote está com as substituições **já resolvidas**, ou
seja tem ARN e nome de recurso da conta `520499255485`. Ao refazer, troque por `${}` e
`DefinitionSubstitutions`, ou use o `atos-dou/statemachine/pipeline.asl.json`, que está no
formato de origem, como modelo.

## Como refazer, na ordem

Pré-requisitos: [uv](https://docs.astral.sh/uv/), [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html),
AWS CLI autenticado. Validado em Linux x86_64 com Python 3.9 no venv e SAM CLI 1.171.0.

```bash
# 1. rodar os testes primeiro, sem nenhuma AWS
cd cadastro && uv sync && uv run pytest -q     # 7 passam
cd ../atos-dou && uv sync && uv run pytest -q  # 17 passam

# 2. a Lambda de origem, que cria a tabela DynamoDB
cd ../lambda-origem && sam deploy --guided

# 3. o ETL do cadastro: buckets, databases, job Glue, Step Functions
cd ../cadastro && sam deploy --guided

# 4. o ETL dos atos, que reaproveita o bucket e os databases do passo 3
cd ../atos-dou && sam deploy --guided \
  --parameter-overrides LakeBucketName=<bucket do passo 3>
```

A tabela DynamoDB precisa de **PITR ligado** antes do passo 3, porque o
`ExportTableToPointInTime` exige. O `template.yaml` do `lambda-origem/` já liga.

Valores específicos de conta que você tem de trocar: a região (`us-east-1`), o nome dos
databases do Glue se já existirem, o e-mail de alerta do SNS e o nome do bucket do lake no
passo 4.

## Validação feita neste pacote

| O que foi verificado | Resultado |
|---|---|
| `cadastro/tests` rodando de dentro do pacote, em venv isolado | 7 passam |
| `atos-dou/tests` rodando de dentro do pacote, em venv isolado | 17 passam |
| `cadastro/src/etl.py` contém código de embeddings | não, zero ocorrências |
| Credencial, `.venv`, `__pycache__`, `.env` no pacote | nenhum |

O que **não** foi verificado: nada aqui foi implantado a partir deste pacote. As duas pipelines
rodaram verde no repositório de origem, e os artefatos do `cadastro/` vieram de lá, mas um
`sam deploy` a partir desta pasta é um caminho novo e não exercitado.

## Armadilhas do Glue Python Shell que custaram execuções falhadas

Se for refazer, estas cinco são as que quebram primeiro. Todas já estão resolvidas no código do
pacote, e perder qualquer uma faz o job falhar antes de processar uma linha.

1. **`GlueVersion: "3.0"` é obrigatório** com `PythonVersion: "3.9"`. Sem a propriedade o Glue
   assume a 1.0, que é Python 3.6, e o `--additional-python-modules` não é aplicado.
2. **`--additional-python-modules` é separado por vírgula antes de chegar ao pip.** O extra
   `pyiceberg[glue,pyarrow]==0.9.1` é partido em `pyiceberg[glue` e `pyarrow]==0.9.1`, e o pip
   responde `Invalid requirement`. Escreva um spec por extra.
3. **A role do job precisa ler o próprio script no bucket de artefatos do SAM.** A policy
   `AWSGlueServiceRole` só cobre buckets `aws-glue-*`, então sem uma permissão extra em
   `aws-sam-cli-managed-default-samclisourcebucket-*` o job toma `403` no `HeadObject`.
4. **O `HOME` do job é `/` e não é gravável.** O DuckDB tenta guardar extensões em `/.duckdb/`
   e morre. O `connect()` aponta `home_directory` e `extension_directory` para o `TMPDIR`.
5. **Uma etapa logo depois da outra dá `Concurrent runs exceeded`.** Com
   `MaxConcurrentRuns: 1`, o contador do Glue demora a liberar e a etapa seguinte é recusada.
   Cada tarefa Glue da máquina de estados tem `Retry` em
   `Glue.ConcurrentRunsExceededException`.

Mais duas de dados, que não derrubam o job mas corrompem o resultado:

6. **`DECIMAL(20,2)`, não `(18,2)`.** Com precisão 18 o PyIceberg 0.9 falha no upsert.
7. **Não leia os Parquet de uma tabela Iceberg direto.** Vêm arquivos de snapshots antigos.
   Leia pelo catálogo, por Athena ou PyIceberg.

## Dependências

Diretas, iguais nos dois ETL e fixadas também no `--additional-python-modules` do template:

```
duckdb==1.2.2
pyiceberg[glue,pyarrow]==0.9.1
```

De desenvolvimento: `pytest`, `boto3`, `cfn-lint`, `pyiceberg[sql-sqlite]==0.9.1`, esse último
para o catálogo Iceberg em SQLite dos testes.

Os `uv.lock` **não** foram incluídos de propósito: eles fixam o resolvido para Linux x86_64 com
Python 3.9 e mais atrapalham do que ajudam em outra plataforma. Rode `uv sync` para resolver de
novo a partir do `pyproject.toml`.
