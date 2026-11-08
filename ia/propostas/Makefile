.PHONY: lint build deploy run verify simular classificar validar metricas sync-regras clean

STACK ?= matriz-propostas
PIPELINE_STACK ?= lakehouse-pipeline
DOU_STACK ?= lakehouse-dou
REGION ?= us-east-1
SAIDA ?= /tmp/propostas-simulacao

saida = $(shell aws cloudformation describe-stacks --stack-name $(1) --region $(REGION) \
	--query "Stacks[0].Outputs[?OutputKey=='$(2)'].OutputValue" --output text 2>/dev/null)

lint:
	sam validate --lint --region $(REGION)

# O sam build precisa de um python3.13 com pip no PATH (para instalar o boto3 de src/requirements.txt,
# que traz o s3vectors); o uv cria um só para isso, sem depender do Python da máquina.
build:
	uv venv --quiet --python 3.13 --seed --allow-existing .aws-sam/python
	PATH="$(CURDIR)/.aws-sam/python/bin:$$PATH" sam build

# Precisa do lakehouse-pipeline com o bucket de vetores (EmpresasVectorBucketName) e do lakehouse-dou.
deploy: lint build
	@test -n "$(call saida,$(PIPELINE_STACK),EmpresasVectorBucketName)" || { echo "O stack $(PIPELINE_STACK) não tem o bucket de vetores: implante pipeline/cadastro antes."; exit 1; }
	@test -n "$(call saida,$(DOU_STACK),StateMachineArn)" || { echo "Não achei a máquina de estados do stack $(DOU_STACK)."; exit 1; }
	sam deploy --parameter-overrides \
	  LakeBucketName=$(call saida,$(PIPELINE_STACK),LakeBucketName) \
	  VectorBucketName=$(call saida,$(PIPELINE_STACK),EmpresasVectorBucketName) \
	  AthenaWorkGroup=$(call saida,$(PIPELINE_STACK),AthenaWorkGroupName) \
	  AcessoLeituraGoldPolicyArn=$(call saida,$(PIPELINE_STACK),AcessoLeituraGoldPolicyArn) \
	  DouStateMachineArn=$(call saida,$(DOU_STACK),StateMachineArn)

# Disparo manual (normalmente quem dispara é o fim do ETL do DOU). make run DIAS=14
run:
	aws stepfunctions start-execution --region $(REGION) \
	  --state-machine-arn $(call saida,$(STACK),StateMachineArn) --input '$(if $(DIAS),{"dias":$(DIAS)},{})'

verify:
	aws stepfunctions list-executions --region $(REGION) --state-machine-arn $(call saida,$(STACK),StateMachineArn) \
	  --max-results 3 --query "executions[].[status,startDate,name]" --output table

# Antes do deploy: os modelos e os dados de verdade, sem gravar nada na AWS (ver simular.py).
classificar:
	cd ../../pipeline && uv run python cadastro/scripts/simular_classificacao.py --saida $(SAIDA)-classificacao.json

simular:
	cd .. && uv run python propostas/simular.py --saida $(SAIDA) --cache-indice $(SAIDA)-indice.npz \
	  $(if $(wildcard $(SAIDA)-classificacao.json),--classificacao $(SAIDA)-classificacao.json,) $(ARGS)

# O que a simulação gerou entra válido no ETL da matriz?
validar:
	cd ../../pipeline && uv run python matriz/scripts/validar_propostas.py $(SAIDA)/landing/matriz/propostas_llm

metricas:
	cd .. && uv run python propostas/avaliacao/metricas.py --rotulos propostas/rotulagem/amostra-2026-11-08/rotulagem.csv \
	  --grupos propostas/rotulagem/amostra-2026-11-08/grupos.csv --simulacao $(SAIDA)

# src/regras_matriz.py é cópia de pipeline/matriz/src (um teste confere)
sync-regras:
	cp ../../pipeline/matriz/src/regras_matriz.py src/regras_matriz.py

clean:
	rm -rf .aws-sam
