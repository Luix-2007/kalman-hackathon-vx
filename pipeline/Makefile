# Ambiente Python compartilhado por todos os ETLs desta pasta (Python 3.9, igual ao Glue).
# Cada ETL (ex.: cadastro/) tem seu template.yaml, samconfig.toml e Makefile de deploy/run.
# A ordem importa: o dou grava no bucket criado pelo cadastro.

ETLS := cadastro dou

.PHONY: install test lint deploy clean

install:
	uv sync

test: install
	uv run pytest

lint: install
	@for d in $(ETLS); do uv run cfn-lint $$d/template.yaml || exit 1; done

deploy: lint
	@for d in $(ETLS); do $(MAKE) -C $$d deploy || exit 1; done

clean:
	rm -rf .venv .pytest_cache
	@for d in $(ETLS); do $(MAKE) -C $$d clean; done

# Alvos de um ETL só: make cadastro-run, make dou-verify ANO=2026 MES=11, ...
cadastro-%:
	$(MAKE) -C cadastro $*

dou-%:
	$(MAKE) -C dou $*
