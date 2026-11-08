.PHONY: lint package deploy eval integracao contrato sync-blocos clean

REGION ?= us-east-1
PIPELINE_STACK ?= lakehouse-pipeline
SAM_STACK ?= aws-sam-cli-managed-default
MODEL_ID ?=
MEMORY_ID ?=

saida = $(shell aws cloudformation describe-stacks --stack-name $(1) --region $(REGION) \
	--query "Stacks[0].Outputs[?OutputKey=='$(2)'].OutputValue" --output text 2>/dev/null)

lint:
	sam validate --lint --region $(REGION)

# Dependências do projeto ia/ (pyproject.toml + uv.lock, sem as de desenvolvimento), no mesmo pin
# do ambiente de testes, para Linux arm64 e Python 3.13 (o runtime do AgentCore roda em arm64).
build/requirements.txt: ../pyproject.toml ../uv.lock
	mkdir -p build
	uv export --project .. --no-dev --no-hashes --no-emit-project -q -o build/requirements.txt

# build/agente.zip = agent.py + blocos.py + dependências. A chave no S3 leva o hash do conteúdo, então
# um agente novo vira uma atualização do runtime e um igual não muda nada.
package: build/requirements.txt agent.py blocos.py
	rm -rf build/pacote build/agente.zip
	uv pip install -q --target build/pacote --python-platform aarch64-manylinux2014 --python-version 3.13 \
	  -r build/requirements.txt
	cp agent.py blocos.py build/pacote/
	cd build/pacote && zip -qr ../agente.zip .
	@ls -lh build/agente.zip | awk '{print "pacote: " $$5}'

# make deploy MODEL_ID=<modelo ou perfil de inferência do Bedrock>  [MEMORY_ID=<memória do AgentCore>]
deploy: lint package
	@test -n "$(MODEL_ID)" || { echo "Informe o modelo: make deploy MODEL_ID=..."; exit 1; }
	@bucket="$(call saida,$(SAM_STACK),SourceBucket)"; \
	policy="$(call saida,$(PIPELINE_STACK),AcessoLeituraGoldPolicyArn)"; \
	workgroup="$(call saida,$(PIPELINE_STACK),AthenaWorkGroupName)"; \
	test -n "$$bucket" -a -n "$$policy" -a -n "$$workgroup" || { echo "Não achei os outputs dos stacks $(SAM_STACK) e $(PIPELINE_STACK)."; exit 1; }; \
	hash=$$(cat agent.py blocos.py build/requirements.txt | sha256sum | cut -c1-12); \
	chave="chatbot-agent/agente-$$hash.zip"; \
	aws s3 cp build/agente.zip "s3://$$bucket/$$chave" --region $(REGION) && \
	sam deploy --parameter-overrides CodeBucket=$$bucket CodeKey=$$chave ModelId=$(MODEL_ID) \
	  AcessoLeituraGoldPolicyArn=$$policy AthenaWorkGroup=$$workgroup \
	  $(if $(MEMORY_ID),MemoryId=$(MEMORY_ID),)

# Avaliação do comportamento com o modelo de verdade (Bedrock). Precisa de MODEL_ID no ambiente.
# Padrão: dados fixos; make eval ARGS="--dados-reais" consulta a Aurora no lake.
eval:
	uv run python evals/rodar.py $(ARGS)

# Integração cnpj-cadastro -> lakehouse -> agente, contra a AWS. Roda o pipeline (~15 min).
# make integracao ARGS="--com-llm" também chama o modelo (precisa de MODEL_ID).
integracao:
	uv run python tests/integracao_cadastro.py $(ARGS)

# Contrato da resposta para o front: JSON Schema e exemplos (gerados do código; o teste confere)
contrato:
	uv run python contrato/gerar.py

# A Lambda api/chatbot usa uma cópia de blocos.py (um teste confere que são iguais)
sync-blocos:
	cp blocos.py ../../api/chatbot/src/blocos.py

clean:
	rm -rf build .aws-sam
