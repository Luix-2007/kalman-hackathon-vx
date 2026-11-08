# Ambiente Python compartilhado pelos agentes desta pasta (Python 3.13, igual ao runtime do AgentCore).
# Cada agente (ex.: chatbot/) tem seu template.yaml, samconfig.toml e Makefile de deploy.

AGENTES := chatbot

.PHONY: install test clean

install:
	uv sync

test: install
	uv run pytest

clean:
	rm -rf .venv .pytest_cache
	@for d in $(AGENTES); do $(MAKE) -C $$d clean; done

# Alvos de um agente só: make chatbot-deploy MODEL_ID=..., make chatbot-eval, make chatbot-integracao
chatbot-%:
	$(MAKE) -C chatbot $*
