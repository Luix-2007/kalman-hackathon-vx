.PHONY: lint deploy run verify clean

STACK ?= lakehouse-kb
PIPELINE_STACK ?= lakehouse-pipeline
REGION ?= us-east-1

# O bucket do lake é do stack lakehouse-pipeline (pipeline/cadastro).
LAKE_BUCKET = $(shell aws cloudformation describe-stacks --stack-name $(PIPELINE_STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='LakeBucketName'].OutputValue" \
	--output text)
STATE_MACHINE = $(shell aws cloudformation describe-stacks --stack-name $(STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
	--output text)

# O ambiente Python é o de pipeline/ (o uv acha o pyproject.toml na pasta de cima).
lint:
	uv run cfn-lint template.yaml

# Não há Lambda para empacotar: o sam deploy envia src/etl_kb.py e a máquina de estados.
deploy: lint
	@test -n "$(LAKE_BUCKET)" || { echo "Não achei o bucket no stack $(PIPELINE_STACK). Implante-o primeiro."; exit 1; }
	sam deploy --parameter-overrides LakeBucketName=$(LAKE_BUCKET)

# Gera os documentos da gold (empresas + classificação) e sincroniza a Knowledge Base.
run:
	aws stepfunctions start-execution --region $(REGION) --state-machine-arn $(STATE_MACHINE) --input '{}'

verify:
	aws stepfunctions list-executions --region $(REGION) --state-machine-arn $(STATE_MACHINE) \
	  --max-results 3 --query "executions[].[status,startDate,name]" --output table

clean:
	rm -rf .aws-sam
