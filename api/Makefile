# Ambiente Python compartilhado por todas as lambdas desta pasta.
# Cada lambda (ex.: cnpj-cadastro/) tem seu template.yaml e seu Makefile de build/deploy.

LAMBDAS := cnpj-cadastro matriz

.PHONY: install test smoke smoke-login seed-aurora integracao clean build deploy

install:
	uv sync

test: install
	uv run pytest

# Testes contra a stack ja publicada na AWS (usam suas credenciais; criam e apagam usuarios de teste).
# Opcoes: make smoke ARGS="--stack outra --cnpj 00000000000191"
smoke-login: install
	uv run python cnpj-cadastro/tests/smoke_login.py $(ARGS)

smoke: install
	uv run python cnpj-cadastro/tests/smoke_test.py $(ARGS)

# Carga da empresa de teste Aurora (KALMANTESTE100) na stack publicada. Os dados FICAM.
# Precisa de FixturesEnabled=true na stack. Opções: make seed-aurora ARGS="--senha '...'"
seed-aurora: install
	uv run python cnpj-cadastro/tests/seed_aurora.py $(ARGS)

# Integracao cnpj-cadastro -> lakehouse -> chatbot (agent.py), contra a AWS. Roda o pipeline (~15 min).
# Opcoes: make integracao ARGS="--com-llm" (precisa de MODEL_ID no ambiente)
integracao:
	uv run --group chatbot python chatbot/tests/integracao_cadastro.py $(ARGS)

clean:
	rm -rf .venv .pytest_cache
	@for d in $(LAMBDAS); do $(MAKE) -C $$d clean; done

build:
	@for d in $(LAMBDAS); do $(MAKE) -C $$d build || exit 1; done

deploy:
	@for d in $(LAMBDAS); do $(MAKE) -C $$d deploy || exit 1; done
