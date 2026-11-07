.PHONY: build deploy clean

REGION ?= us-east-1
CADASTRO_STACK ?= cnpj-cadastro
PIPELINE_STACK ?= lakehouse-pipeline
MATRIZ_STACK ?= lakehouse-matriz

saida = $(shell aws cloudformation describe-stacks --stack-name $(1) --region $(REGION) \
	--query "Stacks[0].Outputs[?OutputKey=='$(2)'].OutputValue" --output text)

# regras_matriz.py é o mesmo arquivo do job (pipeline/matriz/src); a cópia daqui é conferida
# por teste. Se o teste falhar: make -C pipeline/matriz sync-regras
build:
	sam build

deploy: build
	sam deploy --parameter-overrides \
	  UserPoolId=$(call saida,$(CADASTRO_STACK),UserPoolId) \
	  UserPoolClientId=$(call saida,$(CADASTRO_STACK),UserPoolClientId) \
	  CadastroTableName=$(call saida,$(CADASTRO_STACK),TableName) \
	  LakeBucketName=$(call saida,$(PIPELINE_STACK),LakeBucketName) \
	  AthenaWorkGroup=$(call saida,$(PIPELINE_STACK),AthenaWorkGroupName) 	  MatrizStateMachineArn=$(call saida,$(MATRIZ_STACK),StateMachineArn)

clean:
	rm -rf .aws-sam
