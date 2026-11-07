.PHONY: install test lint deploy run verify clean

STACK ?= lakehouse-dou
PIPELINE_STACK ?= lakehouse-pipeline
REGION ?= us-east-1

# O bucket do lake pertence ao stack do lakehouse-pipeline: esta pipeline so grava nele.
LAKE_BUCKET = $(shell aws cloudformation describe-stacks --stack-name $(PIPELINE_STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='LakeBucketName'].OutputValue" \
	--output text)

install:
	uv sync

test: install
	uv run pytest

lint: install
	uv run cfn-lint template.yaml

# Nao ha Lambda para empacotar: o sam deploy envia src/etl_dou.py e a maquina de estados.
deploy: lint
	@test -n "$(LAKE_BUCKET)" || { echo "Nao achei o bucket do lake no stack $(PIPELINE_STACK). Implante-o primeiro."; exit 1; }
	@echo "Lake: $(LAKE_BUCKET)"
	sam deploy --parameter-overrides LakeBucketName=$(LAKE_BUCKET)

# make run                       coleta o mes atual
# make run ANO=2026 MES=11       reprocessa um mes
run:
	aws stepfunctions start-execution --region $(REGION) \
	  --state-machine-arn $$(aws cloudformation describe-stacks --stack-name $(STACK) \
	      --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
	      --output text) \
	  --input '$(if $(ANO),{"ano":"$(ANO)","mes":"$(MES)"},{})'

# Confere o lake depois de uma execucao.
# make verify ANO=2026 MES=11
verify: install
	uv run python scripts/verificar.py --stack $(PIPELINE_STACK) --ano $(ANO) --mes $(MES)

clean:
	rm -rf .venv .pytest_cache
