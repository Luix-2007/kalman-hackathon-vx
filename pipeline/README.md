# pipeline: ETLs do lakehouse (Glue, DuckDB e Iceberg)

Os dois ETLs que alimentam o lakehouse na AWS. Os dois rodaram ponta a ponta em 07/11/2026. O
trabalho de embeddings, classificação por tipo e Knowledge Base ainda não está aqui.

O uso do DuckDB, que é o coração das duas pipelines, está descrito com o SQL real em
**[DUCKDB.md](DUCKDB.md)**.

## Os dois ETLs

| | `cadastro/` | `dou/` |
|---|---|---|
| Stack | `lakehouse-pipeline` | `lakehouse-dou` |
| Origem | tabela DynamoDB do `api/cnpj-cadastro`, via export nativo para o S3 | ZIP mensal da Imprensa Nacional, por HTTP |
| Etapas | `landing → bronze → silver → gold → kb_docs` | `landing → bronze → prata → ouro` |
| Formato | Landing e Bronze em Parquet, Silver e Gold em Iceberg | Landing em Parquet, resto em Iceberg |
| Runtime | Glue Python Shell, Python 3.9, 1 DPU | igual |
| Engine | DuckDB 1.2.2 | igual |
| Escrita Iceberg | PyIceberg 0.9.1 no Glue Data Catalog | igual |
| Agendamento | todo dia às 02:00 (America/Sao_Paulo) | todo dia às 05:00 |
| Testes | 7, sem AWS | 17, sem AWS e sem rede |

Os dois gravam no **mesmo bucket** e no **mesmo Glue Data Catalog**, mas têm job Glue e máquina
de estados separados. É isso que permite rodar um sem mexer no outro. O `cadastro/` é dono do
bucket, dos databases (`landing_db`, `bronze_db`, `silver_db`, `gold_db`) e do workgroup do
Athena; o `dou/` recebe o bucket por parâmetro.

## Onde cada arquivo roda

Cada script tem um runtime e uma identidade diferente.

| Arquivo | Onde roda | Identidade |
|---|---|---|
| `cadastro/src/etl.py` | Glue Python Shell 3.9 | role do job Glue |
| `dou/src/etl_dou.py` | Glue Python Shell 3.9 | role do job Glue |
| `*/tests/*.py` | máquina local, Python 3.9 | nenhuma, não toca a AWS |
| `*/scripts/verificar.py` | máquina local, Python 3.9 | suas credenciais, somente leitura |

**Um login local não dá acesso ao job Glue.** A role do job precisa das permissões do próprio
`template.yaml`, e um `aws sts get-caller-identity` que funciona no seu terminal não prova nada
sobre o que o job consegue fazer.

## Estrutura

```
pipeline/
  pyproject.toml, uv.lock   ambiente Python compartilhado (Python 3.9, igual ao Glue)
  Makefile                  install, test, lint, deploy de todos; <etl>-<alvo> para um só
  DUCKDB.md                 como o DuckDB foi usado, com o SQL real
  cadastro/                 ETL do DynamoDB (stack lakehouse-pipeline)
    src/etl.py              5 etapas escolhidas por --STAGE
    tests/test_etl.py       catálogo Iceberg em SQLite, pastas locais
    scripts/verificar.py    confere o lake depois de uma execução, sem Athena
    statemachine/           definição da Step Functions
    template.yaml           SAM: buckets, databases, job Glue, Step Functions, Athena
    samconfig.toml, Makefile
  dou/                      ETL dos atos do DOU, portado do Databricks (stack lakehouse-dou)
    src/etl_dou.py          coleta HTTP + 4 etapas
    tests/test_etl_dou.py   com ZIP montado no próprio teste
    scripts/verificar.py
    statemachine/ template.yaml samconfig.toml Makefile
```

O `etl.py`, o `template.yaml` e a máquina de estados do `cadastro/` foram extraídos do que está
implantado (script do bucket de artefatos do job, `get-template --template-stage Original` e
`describe-state-machine`). Na extração, o template apontava para o script e a definição já
enviados ao S3, e a máquina de estados tinha os ARNs da conta escritos direto. Os dois foram
devolvidos ao formato de origem: `ScriptLocation: src/etl.py`,
`DefinitionUri: statemachine/pipeline.asl.json` e `${TableArn}`, `${GlueJobName}` etc. resolvidos
pelo `DefinitionSubstitutions`, como no `dou/`.

## Comandos

Da raiz do repositório (`make pipeline-<alvo>`) ou de dentro de `pipeline/` (`make <alvo>`):

```bash
make pipeline-test            # uv sync + pytest dos dois ETLs, sem AWS (24 testes)
make pipeline-lint            # cfn-lint nos dois template.yaml
make pipeline-deploy          # lint + sam deploy do cadastro e depois do dou
make pipeline-cadastro-run    # dispara a máquina de estados (DATA=AAAA-MM-DD para reprocessar)
make pipeline-cadastro-verify DATA=2026-11-07
make pipeline-dou-run         # coleta o mês atual (ANO=2026 MES=11 para reprocessar)
make pipeline-dou-verify ANO=2026 MES=11
make pipeline-clean
```

Pré-requisitos: [uv](https://docs.astral.sh/uv/), [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
e AWS CLI autenticado. O uv baixa o Python 3.9 sozinho (`.python-version`).

### Ordem de implantação

1. `make api-deploy`: cria a tabela DynamoDB do cadastro.
2. Ligar o **PITR** na tabela. O `ExportTableToPointInTime` exige, e o template da API ainda não
   liga (na conta do hackathon ele foi ligado à mão).
3. `make pipeline-deploy`: o `cadastro/` cria bucket, databases, job e máquina de estados; o
   `dou/` lê o bucket do output `LakeBucketName` e implanta em seguida.

O `cadastro/Makefile` descobre o ARN da tabela pelos outputs da stack `cnpj-cadastro`. Em outra
conta, troque a região (`us-east-1`), os nomes dos databases do Glue se já existirem e o e-mail de
alerta do SNS (`AlertEmail`).

## Validação

| O que foi verificado | Resultado |
|---|---|
| Testes dos dois ETLs no ambiente compartilhado, Python 3.9 | 24 passam (7 + 17) |
| `cfn-lint` e `sam validate` nos dois templates | sem erros |
| `src/etl.py` e `src/etl_dou.py` iguais aos scripts implantados | iguais |
| Máquinas de estados iguais às implantadas, tirando as substituições | iguais |

O que **não** foi verificado: nenhum `sam deploy` a partir desta pasta. As stacks atuais foram
implantadas do repositório de origem.


## Armadilhas do Glue Python Shell que custaram execuções falhadas

Se for refazer, estas cinco são as que quebram primeiro. Todas já estão resolvidas no código desta
pasta, e perder qualquer uma faz o job falhar antes de processar uma linha.

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

Diretas, iguais nos dois ETLs e fixadas também no `--additional-python-modules` do template:

```
duckdb==1.2.2
pyiceberg[glue,pyarrow]==0.9.1
```

De desenvolvimento: `pytest`, `boto3`, `cfn-lint`, `pyiceberg[sql-sqlite]==0.9.1`, esse último
para o catálogo Iceberg em SQLite dos testes.

O `uv.lock` fica em `pipeline/`, compartilhado pelos dois ETLs, como o de `api/`.
