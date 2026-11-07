# Front de TESTE do fluxo de cadastro (Vite + React + Amplify).
STACK ?= cnpj-cadastro
REGION ?= us-east-1

.PHONY: install env dev build check clean

node_modules: package.json
	npm install
	@touch node_modules

install: node_modules

# Gera o .env com os outputs da stack publicada (valores públicos, não são segredos)
env:
	@aws cloudformation describe-stacks --stack-name $(STACK) --region $(REGION) \
	  --query "Stacks[0].Outputs[?OutputKey=='ApiUrl' || OutputKey=='UserPoolId' || OutputKey=='UserPoolClientId'].[OutputKey,OutputValue]" \
	  --output text \
	| awk 'BEGIN { m["ApiUrl"]="VITE_API_URL"; m["UserPoolId"]="VITE_USER_POOL_ID"; m["UserPoolClientId"]="VITE_USER_POOL_CLIENT_ID" } { print m[$$1] "=" $$2 }' > .env.tmp
	@if [ "$$(grep -c . .env.tmp)" != 3 ]; then \
	  rm -f .env.tmp; \
	  echo "ERRO: a stack $(STACK) não tem os outputs ApiUrl, UserPoolId e UserPoolClientId."; \
	  echo "      Ela está publicada com o template atual? Rode: make api-deploy"; \
	  exit 1; \
	fi
	@mv .env.tmp .env && echo ".env gerado a partir da stack $(STACK):" && cat .env

dev: install
	@test -f .env || $(MAKE) env
	npm run dev

build: install
	npm run build

check: install
	npm run typecheck

clean:
	rm -rf node_modules dist
