# Cada parte do projeto tem seu proprio Makefile. Aqui so delegamos.
# Uso: make <parte>-<alvo>   ex.: make api-test
# Partes vazias (ia) entram aqui quando tiverem codigo.

API_DIR := api

API_TARGETS := install test smoke smoke-login seed-aurora build deploy clean

FRONT_DIR := front/cadastro-teste
FRONT_TARGETS := install env dev build check clean

PIPELINE_DIR := pipeline
PIPELINE_TARGETS := install test lint deploy clean \
	cadastro-deploy cadastro-run cadastro-verify dou-deploy dou-run dou-verify \
	matriz-deploy matriz-run matriz-verify matriz-fixture matriz-proposta-demo matriz-sync-regras

.PHONY: help test matriz-test matriz-deploy $(addprefix api-,$(API_TARGETS)) $(addprefix front-,$(FRONT_TARGETS)) \
	$(addprefix pipeline-,$(PIPELINE_TARGETS))

help:
	@echo "Alvos disponiveis:"
	@echo "  make api-install   instala dependencias (uv sync)"
	@echo "  make api-test      roda os testes da API"
	@echo "  make api-smoke-login  testa login e autenticacao na stack publicada (AWS)"
	@echo "  make api-smoke     fluxo completo na stack publicada (AWS)"
	@echo "  make api-seed-aurora  cria a empresa de teste Aurora na stack publicada (AWS)"
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
	@echo "  make test          roda os testes de todas as partes"

$(addprefix api-,$(API_TARGETS)): api-%:
	$(MAKE) -C $(API_DIR) $*

$(addprefix front-,$(FRONT_TARGETS)): front-%:
	$(MAKE) -C $(FRONT_DIR) $*

$(addprefix pipeline-,$(PIPELINE_TARGETS)): pipeline-%:
	$(MAKE) -C $(PIPELINE_DIR) $*

test: api-test front-check pipeline-test

# API da matriz (api/matriz): mesmo ambiente Python de api/
matriz-test:
	cd $(API_DIR) && uv sync && uv run pytest matriz/tests

matriz-deploy:
	$(MAKE) -C $(API_DIR)/matriz deploy
