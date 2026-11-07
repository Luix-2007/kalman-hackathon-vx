.PHONY: install test build deploy clean

install:
	uv sync

test: install
	uv run pytest

build:
	sam build

deploy: build
	sam deploy

clean:
	rm -rf .venv .aws-sam .pytest_cache
