# Cada parte do projeto tem seu proprio Makefile. Aqui so delegamos.
# Uso: make <parte>-<alvo>   ex.: make api-test
# Partes vazias (ia, pipeline) entram aqui quando tiverem codigo.

API_DIR := api

API_TARGETS := install test smoke smoke-login integracao build deploy clean

FRONT_DIR := front/cadastro-teste
FRONT_TARGETS := install env dev build check clean

.PHONY: help test $(addprefix api-,$(API_TARGETS)) $(addprefix front-,$(FRONT_TARGETS))

help:
	@echo "Alvos disponiveis:"
	@echo "  make api-install   instala dependencias (uv sync)"
	@echo "  make api-test      roda os testes da API"
	@echo "  make api-smoke-login  testa login e autenticacao na stack publicada (AWS)"
	@echo "  make api-smoke     fluxo completo na stack publicada (AWS)"
	@echo "  make api-integracao  cadastro -> lakehouse -> agente do chatbot (AWS, roda o pipeline)"
	@echo "  make api-build     sam build"
	@echo "  make api-deploy    sam build + sam deploy"
	@echo "  make api-clean     remove .venv e caches"
	@echo "  make front-env     gera front/cadastro-teste/.env com os outputs da stack"
	@echo "  make front-dev     sobe o front de teste em http://localhost:5173"
	@echo "  make front-build   build de producao do front de teste"
	@echo "  make front-check   typecheck do front de teste"
	@echo "  make test          roda os testes de todas as partes"

$(addprefix api-,$(API_TARGETS)): api-%:
	$(MAKE) -C $(API_DIR) $*

$(addprefix front-,$(FRONT_TARGETS)): front-%:
	$(MAKE) -C $(FRONT_DIR) $*

test: api-test front-check
