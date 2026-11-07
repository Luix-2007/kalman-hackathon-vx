.PHONY: lint deploy run verify clean

STACK ?= lakehouse-dou
PIPELINE_STACK ?= lakehouse-pipeline
REGION ?= us-east-1

# O bucket do lake pertence ao stack do lakehouse-pipeline: esta pipeline só grava nele.
LAKE_BUCKET = $(shell aws cloudformation describe-stacks --stack-name $(PIPELINE_STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='LakeBucketName'].OutputValue" \
	--output text)

# O ambiente Python é o de pipeline/ (o uv acha o pyproject.toml na pasta de cima).
lint:
	uv run cfn-lint template.yaml

# Não há Lambda para empacotar: o sam deploy envia src/etl_dou.py e a máquina de estados.
deploy: lint
	@test -n "$(LAKE_BUCKET)" || { echo "Não achei o bucket do lake no stack $(PIPELINE_STACK). Implante-o primeiro."; exit 1; }
	@echo "Lake: $(LAKE_BUCKET)"
	sam deploy --parameter-overrides LakeBucketName=$(LAKE_BUCKET)

# make run                       coleta o mês atual
# make run ANO=2026 MES=11       reprocessa um mês
run:
	aws stepfunctions start-execution --region $(REGION) \
	  --state-machine-arn $$(aws cloudformation describe-stacks --stack-name $(STACK) \
	      --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
	      --output text) \
	  --input '$(if $(ANO),{"ano":"$(ANO)","mes":"$(MES)"},{})'

# Confere o lake depois de uma execução.
# make verify ANO=2026 MES=11
verify:
	uv run python scripts/verificar.py --stack $(PIPELINE_STACK) --ano $(ANO) --mes $(MES)

clean:
	rm -rf .aws-sam
