.PHONY: install lint build push deploy invoke clean

# ---------------------------------------------------------------- configuração
STACK           ?= ia-agente
PIPELINE_STACK  ?= lakehouse-pipeline
KB_STACK        ?= lakehouse-kb
REGION          ?= us-east-1
IMAGE_TAG       ?= latest

# Resolve valores dos stacks já implantados.
LAKE_BUCKET = $(shell aws cloudformation describe-stacks \
    --stack-name $(PIPELINE_STACK) --region $(REGION) \
    --query "Stacks[0].Outputs[?OutputKey=='LakeBucketName'].OutputValue" \
    --output text 2>/dev/null)

KB_ID = $(shell aws cloudformation describe-stacks \
    --stack-name $(KB_STACK) --region $(REGION) \
    --query "Stacks[0].Outputs[?OutputKey=='KbId'].OutputValue" \
    --output text 2>/dev/null)

# URI do ECR: lida do stack (disponível após o primeiro deploy).
ECR_URI = $(shell aws cloudformation describe-stacks \
    --stack-name $(STACK) --region $(REGION) \
    --query "Stacks[0].Outputs[?OutputKey=='EcrRepositoryUri'].OutputValue" \
    --output text 2>/dev/null)

ACCOUNT_ID = $(shell aws sts get-caller-identity --query Account --output text 2>/dev/null)

# ---------------------------------------------------------------- alvos

install:
	pip install cfn-lint

lint: install
	cfn-lint template.yaml

# Fase 1: implanta ECR + Memory, sem Runtime (ImageTag vazio pula o Runtime).
# Roda na primeira vez (sem docker) ou se só quiser atualizar a Memory.
bootstrap: lint
	@test -n "$(LAKE_BUCKET)" || { echo "Stack $(PIPELINE_STACK) não encontrado. Implante-o primeiro."; exit 1; }
	@echo "Lake: $(LAKE_BUCKET)  |  KB: $(KB_ID)"
	sam deploy \
	    --parameter-overrides \
	        LakeBucketName=$(LAKE_BUCKET) \
	        KbId="$(KB_ID)" \
	        ImageTag="" \
	    --no-confirm-changeset

# Fase 2: constrói e faz push da imagem Docker para o ECR.
# Requer Docker e credenciais AWS com permissão de push ao ECR.
build:
	@test -n "$(ECR_URI)" || { echo "Execute 'make bootstrap' primeiro para criar o repositório ECR."; exit 1; }
	@echo "Construindo para linux/arm64 → $(ECR_URI):$(IMAGE_TAG)"
	aws ecr get-login-password --region $(REGION) | \
	    docker login --username AWS --password-stdin $(ACCOUNT_ID).dkr.ecr.$(REGION).amazonaws.com
	docker build --platform linux/arm64 \
	    -t $(ECR_URI):$(IMAGE_TAG) .
	docker push $(ECR_URI):$(IMAGE_TAG)
	@echo "Push concluído: $(ECR_URI):$(IMAGE_TAG)"

# Fase 3: deploy completo com o Runtime (exige imagem já no ECR).
deploy: lint
	@test -n "$(LAKE_BUCKET)" || { echo "Stack $(PIPELINE_STACK) não encontrado. Implante-o primeiro."; exit 1; }
	@test -n "$(ECR_URI)" || { echo "Execute 'make bootstrap' e 'make build' primeiro."; exit 1; }
	@echo "Lake: $(LAKE_BUCKET)  |  KB: $(KB_ID)  |  Imagem: $(IMAGE_TAG)"
	sam deploy \
	    --parameter-overrides \
	        LakeBucketName=$(LAKE_BUCKET) \
	        KbId="$(KB_ID)" \
	        ImageTag=$(IMAGE_TAG)

# Atalho: bootstrap → build → deploy em sequência.
# Para a primeira instalação completa (requer Docker).
install-all: bootstrap build deploy

# ---------------------------------------------------------------- testes

# Invoca o agente localmente (requer Docker e credenciais AWS com permissão ao Bedrock).
# Útil para testar antes do deploy.
run-local:
	docker run --rm --platform linux/arm64 \
	    -p 8080:8080 \
	    -e AWS_REGION=$(REGION) \
	    -e KB_ID="$(KB_ID)" \
	    -e MEMORY_ID="" \
	    -e ATHENA_WORKGROUP="$(shell aws cloudformation describe-stacks \
	        --stack-name $(PIPELINE_STACK) --region $(REGION) \
	        --query "Stacks[0].Outputs[?OutputKey=='AthenaWorkgroupName'].OutputValue" \
	        --output text 2>/dev/null || echo "lakehouse-pipeline-lakehouse")" \
	    -e LAKE_BUCKET="$(LAKE_BUCKET)" \
	    -e MODEL_ID="anthropic.claude-3-5-sonnet-20241022-v2:0" \
	    -v ~/.aws:/root/.aws:ro \
	    $(ECR_URI):$(IMAGE_TAG)

# Invoca o agente já implantado no AgentCore Runtime.
# make invoke PROMPT="Qual a situação da empresa do user abc123?"
invoke:
	@RUNTIME_ARN=$$(aws cloudformation describe-stacks --stack-name $(STACK) \
	    --region $(REGION) \
	    --query "Stacks[0].Outputs[?OutputKey=='RuntimeArn'].OutputValue" \
	    --output text); \
	test -n "$$RUNTIME_ARN" || { echo "Runtime não encontrado no stack $(STACK)."; exit 1; }; \
	echo "Invocando $$RUNTIME_ARN..."; \
	aws bedrock-agentcore invoke-agent-runtime \
	    --region $(REGION) \
	    --agent-runtime-arn "$$RUNTIME_ARN" \
	    --runtime-session-id "$$(python3 -c 'import uuid; print(str(uuid.uuid4()))')" \
	    --payload "$$(echo '{"prompt":"$(PROMPT)","user_id":"$(USER_ID)"}' | base64)" \
	    --qualifier DEFAULT \
	    --output json

clean:
	rm -rf .venv .pytest_cache __pycache__ src/__pycache__
