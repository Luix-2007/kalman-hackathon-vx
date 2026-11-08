# Cada parte do projeto tem seu proprio Makefile. Aqui so delegamos.
# Uso: make <parte>-<alvo>   ex.: make api-test

API_DIR := api

API_TARGETS := install test smoke smoke-login seed-aurora build deploy clean

FRONT_DIR := front/cadastro-teste
FRONT_TARGETS := install env dev build check clean

IA_DIR := ia
IA_TARGETS := install test clean chatbot-deploy chatbot-eval chatbot-integracao chatbot-package chatbot-contrato chatbot-sync-blocos \
	propostas-build propostas-deploy propostas-run propostas-verify propostas-classificar propostas-simular propostas-validar propostas-metricas propostas-sync-regras

PIPELINE_DIR := pipeline
PIPELINE_TARGETS := install test lint deploy clean \
	cadastro-deploy cadastro-run cadastro-verify dou-deploy dou-run dou-verify \
	matriz-deploy matriz-run matriz-verify matriz-fixture matriz-proposta-demo matriz-sync-regras \
	cadastro-taxonomia kb-deploy kb-run kb-verify

.PHONY: help test matriz-test matriz-deploy chatbot-deploy $(addprefix api-,$(API_TARGETS)) $(addprefix front-,$(FRONT_TARGETS)) \
	$(addprefix pipeline-,$(PIPELINE_TARGETS)) $(addprefix ia-,$(IA_TARGETS))

help:
	@echo "Alvos disponiveis:"
	@echo "  make api-install   instala dependencias (uv sync)"
	@echo "  make api-test      roda os testes da API"
	@echo "  make api-smoke-login  testa login e autenticacao na stack publicada (AWS)"
	@echo "  make api-smoke     fluxo completo na stack publicada (AWS)"
	@echo "  make api-seed-aurora  cria a empresa de teste Aurora na stack publicada (AWS)"
	@echo "  make chatbot-deploy  API de entrada do chatbot (stack chatbot-api; implante o agente antes)"
	@echo "  make api-build     sam build"
	@echo "  make api-deploy    sam build + sam deploy"
	@echo "  make api-clean     remove .venv e caches"
	@echo "  make matriz-test   testes da API da matriz"
	@echo "  make matriz-deploy  sam deploy da API da matriz (stack matriz-api)"
	@echo "  make front-env     gera front/cadastro-teste/.env com os outputs da stack"
	@echo "  make front-dev     sobe o front de teste em http://localhost:5173"
	@echo "  make front-build   build de producao do front de teste"
	@echo "  make front-check   typecheck do front de teste"
	@echo "  make pipeline-test  roda os testes dos ETLs (sem AWS)"
	@echo "  make pipeline-lint  cfn-lint nos templates dos ETLs"
	@echo "  make pipeline-deploy  sam deploy do ETL do cadastro e depois do DOU"
	@echo "  make pipeline-cadastro-run  dispara o ETL do cadastro (DATA=AAAA-MM-DD)"
	@echo "  make pipeline-dou-run  dispara o ETL do DOU (ANO=AAAA MES=M)"
	@echo "  make pipeline-matriz-fixture  coloca a matriz da Aurora na landing"
	@echo "  make pipeline-matriz-run  dispara o ETL da matriz (HOJE=AAAA-MM-DD)"
	@echo "  make pipeline-matriz-proposta-demo  proposta do DOU que altera a OBR-013"
	@echo "  make ia-test       testes dos agentes de IA (sem AWS)"
	@echo "  make ia-chatbot-deploy MODEL_ID=...  agente do chatbot: runtime, role e Guardrail (stack chatbot-agent)"
	@echo "  make ia-chatbot-eval  avalia o agente com o modelo (precisa de MODEL_ID; ARGS=--dados-reais usa o lake)"
	@echo "  make ia-chatbot-integracao  cadastro -> lakehouse -> agente (AWS, roda o pipeline)"
	@echo "  make ia-chatbot-contrato  regera o JSON Schema e os exemplos da resposta do chatbot (para o front)"
	@echo "  make pipeline-kb-deploy  documentos da Knowledge Base (stack lakehouse-kb)"
	@echo "  make pipeline-cadastro-taxonomia  envia os tipos de empresa (config/tipos_empresa.json) ao lake"
	@echo "  make ia-propostas-classificar  classificação das empresas com o Titan, sem gravar na AWS"
	@echo "  make ia-propostas-simular  propostas do DOU com dados e modelos reais, sem gravar na AWS"
	@echo "  make ia-propostas-validar  confere no ETL da matriz (local) o que a simulação gerou"
	@echo "  make ia-propostas-deploy  passo de propostas do DOU (stack matriz-propostas)"
	@echo "  make test          roda os testes de todas as partes"

$(addprefix api-,$(API_TARGETS)): api-%:
	$(MAKE) -C $(API_DIR) $*

$(addprefix front-,$(FRONT_TARGETS)): front-%:
	$(MAKE) -C $(FRONT_DIR) $*

$(addprefix pipeline-,$(PIPELINE_TARGETS)): pipeline-%:
	$(MAKE) -C $(PIPELINE_DIR) $*

$(addprefix ia-,$(IA_TARGETS)): ia-%:
	$(MAKE) -C $(IA_DIR) $*

test: api-test front-check pipeline-test ia-test

# API da matriz (api/matriz): mesmo ambiente Python de api/
matriz-test:
	cd $(API_DIR) && uv sync && uv run pytest matriz/tests

matriz-deploy:
	$(MAKE) -C $(API_DIR)/matriz deploy

# Chatbot: o agente (ia/chatbot, stack chatbot-agent) vai antes da API de entrada (api/chatbot, stack chatbot-api)
chatbot-deploy:
	$(MAKE) -C $(API_DIR)/chatbot deploy
