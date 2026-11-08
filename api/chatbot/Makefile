.PHONY: build deploy clean

REGION ?= us-east-1
CADASTRO_STACK ?= cnpj-cadastro
AGENT_STACK ?= chatbot-agent

saida = $(shell aws cloudformation describe-stacks --stack-name $(1) --region $(REGION) \
	--query "Stacks[0].Outputs[?OutputKey=='$(2)'].OutputValue" --output text 2>/dev/null)

# Só a Lambda de entrada (src/). O agente (agent.py) é implantado pela stack chatbot-agent.
build:
	sam build

deploy: build
	@test -n "$(call saida,$(AGENT_STACK),AgentRuntimeArn)" || { echo "Não achei o runtime no stack $(AGENT_STACK). Implante o agente primeiro (make -C api/chatbot agent-deploy)."; exit 1; }
	sam deploy --parameter-overrides \
	  UserPoolId=$(call saida,$(CADASTRO_STACK),UserPoolId) \
	  UserPoolClientId=$(call saida,$(CADASTRO_STACK),UserPoolClientId) \
	  CadastroTableName=$(call saida,$(CADASTRO_STACK),TableName) \
	  AgentRuntimeArn=$(call saida,$(AGENT_STACK),AgentRuntimeArn)

clean:
	rm -rf .aws-sam
