# Ambiente Python compartilhado por todas as lambdas desta pasta.
# Cada lambda (ex.: cnpj-cadastro/) tem seu template.yaml e seu Makefile de build/deploy.

LAMBDAS := cnpj-cadastro

.PHONY: install test clean build deploy

install:
	uv sync

test: install
	uv run pytest

clean:
	rm -rf .venv .pytest_cache
	@for d in $(LAMBDAS); do $(MAKE) -C $$d clean; done

build:
	@for d in $(LAMBDAS); do $(MAKE) -C $$d build || exit 1; done

deploy:
	@for d in $(LAMBDAS); do $(MAKE) -C $$d deploy || exit 1; done
