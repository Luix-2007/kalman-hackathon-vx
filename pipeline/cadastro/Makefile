.PHONY: lint deploy taxonomia run verify clean

STACK ?= lakehouse-pipeline
CADASTRO_STACK ?= cnpj-cadastro
REGION ?= us-east-1

# A stack do cadastro exporta só o nome da tabela; o ARN vem do DynamoDB.
TABLE_NAME = $(shell aws cloudformation describe-stacks --stack-name $(CADASTRO_STACK) \
	--region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='TableName'].OutputValue" \
	--output text)
TABLE_ARN = $(shell aws dynamodb describe-table --table-name $(TABLE_NAME) \
	--region $(REGION) --query "Table.TableArn" --output text)

# O ambiente Python é o de pipeline/ (o uv acha o pyproject.toml na pasta de cima).
lint:
	uv run cfn-lint template.yaml

# Não há Lambda para empacotar: o sam deploy envia src/etl.py e a máquina de estados.
# Os tipos de empresa vão depois para o lake (o bucket é criado por este stack); o job os lê
# de lá nas etapas embeddings e classificar, e o passo de propostas (ia/propostas) também.
deploy: lint
	@test -n "$(TABLE_NAME)" || { echo "Não achei a tabela no stack $(CADASTRO_STACK). Implante a API primeiro."; exit 1; }
	@echo "Tabela: $(TABLE_ARN)"
	sam deploy --parameter-overrides TableArn=$(TABLE_ARN)
	$(MAKE) taxonomia

taxonomia:
	@bucket=$$(aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='LakeBucketName'].OutputValue" --output text); \
	test -n "$$bucket" -a "$$bucket" != "None" || { echo "Não achei o bucket do lake no stack $(STACK)."; exit 1; }; \
	aws s3 cp config/tipos_empresa.json s3://$$bucket/artefatos/cadastro/tipos_empresa.json --region $(REGION)

# make run                    processa a data de hoje
# make run DATA=2026-11-07    reprocessa uma data
run:
	aws stepfunctions start-execution --region $(REGION) \
	  --state-machine-arn $$(aws cloudformation describe-stacks --stack-name $(STACK) \
	      --region $(REGION) --query "Stacks[0].Outputs[?OutputKey=='StateMachineArn'].OutputValue" \
	      --output text) \
	  --input '$(if $(DATA),{"run_date":"$(DATA)"},{})'

# Confere o lake depois de uma execução.
# make verify DATA=2026-11-07
verify:
	uv run python scripts/verificar.py --stack $(STACK) --data $(DATA) --region $(REGION)

clean:
	rm -rf .aws-sam
