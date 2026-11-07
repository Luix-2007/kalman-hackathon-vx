.PHONY: lint deploy run fixture proposta-demo sync-regras verify clean

STACK ?= lakehouse-matriz
PIPELINE_STACK ?= lakehouse-pipeline
CADASTRO_STACK ?= cnpj-cadastro
REGION ?= us-east-1
CNPJ ?= KALMANTESTE100

# O bucket e os databases pertencem ao stack lakehouse-pipeline; a tabela, ao cnpj-cadastro.
LAKE_BUCKET = $(shell aws cloudformation describe-stacks --stack-name $(PIPELINE_STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='LakeBucketName'].OutputValue" \
	--output text)
TABLE_NAME = $(shell aws cloudformation describe-stacks --stack-name $(CADASTRO_STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue" \
	--output text)
STATE_MACHINE = $(shell aws cloudformation describe-stacks --stack-name $(STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
	--output text)
API_REGRAS := ../../api/matriz/src/regras_matriz.py

# O ambiente Python é o de pipeline/ (o uv acha o pyproject.toml na pasta de cima).
lint:
	uv run cfn-lint template.yaml

# regras_matriz.py vai para o S3 (--extra-py-files do job) antes do deploy, e a cópia da
# API precisa ser igual (teste em tests/test_regras_iguais.py).
deploy: lint
	@test -n "$(LAKE_BUCKET)" || { echo "Não achei o bucket no stack $(PIPELINE_STACK). Implante-o primeiro."; exit 1; }
	@test -n "$(TABLE_NAME)" || { echo "Não achei a tabela no stack $(CADASTRO_STACK)."; exit 1; }
	@echo "Lake: $(LAKE_BUCKET)  Tabela: $(TABLE_NAME)"
	aws s3 cp src/regras_matriz.py s3://$(LAKE_BUCKET)/artefatos/matriz/regras_matriz.py --region $(REGION)
	sam deploy --parameter-overrides LakeBucketName=$(LAKE_BUCKET) CadastroTableName=$(TABLE_NAME)

# make run                  processa com a data de hoje (Brasília)
# make run HOJE=2026-11-07  recalcula como se fosse outro dia
run:
	aws stepfunctions start-execution --region $(REGION) --state-machine-arn $(STATE_MACHINE) \
	  --input '$(if $(HOJE),{"hoje":"$(HOJE)"},{})'

# Matriz da Aurora na landing, como se fosse o upload do cliente.
fixture:
	aws s3 cp fixtures/aurora/matriz.csv \
	  s3://$(LAKE_BUCKET)/landing/matriz/importada/$(CNPJ)/matriz.csv --region $(REGION)

# Demo (etapa 5): proposta do DOU que antecipa a entrega das DCR (OBR-013).
proposta-demo:
	aws s3 cp fixtures/aurora/proposta_obr013.json \
	  s3://$(LAKE_BUCKET)/landing/matriz/propostas_llm/$$(date +%F)/dou-2026-11-07-s1-000013.json --region $(REGION)

sync-regras:
	cp src/regras_matriz.py $(API_REGRAS)

# Última execução da máquina de estados.
verify:
	aws stepfunctions list-executions --region $(REGION) --state-machine-arn $(STATE_MACHINE) \
	  --max-results 3 --query "executions[].[status,startDate,name]" --output table

clean:
	rm -rf .aws-sam
