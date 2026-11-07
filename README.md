# kalman-hackathon-vx

## identidade-visual

Marca, cores, tipografia, componentes e regras do Kalman (versão "Laudo"), prontos para qualquer parte do projeto:
SVGs e PNGs da marca, `tokens.css` + `componentes.css` para HTML puro, tema para Tailwind v4/shadcn, `tokens.json` para
Python e gráficos. Guia em [`identidade-visual/README.md`](identidade-visual/README.md); para ver tudo, abra
`identidade-visual/especime.html` no navegador.

## api/cnpj-cadastro

Lambda que consulta o CNPJ do usuário no [OpenCNPJ](https://api.opencnpj.org) e salva o resultado no DynamoDB. É disparada por um evento `UsuarioCadastrado` no EventBridge.

### Pré-requisitos

- [uv](https://docs.astral.sh/uv/)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) (só para build e deploy)

### Comandos

Da raiz do repositório (cada parte tem seu próprio `Makefile`, e a raiz só delega):

```bash
make help          # lista os alvos
make api-test      # uv sync + pytest (DynamoDB mockado com moto, OpenCNPJ com servidor local)
make api-build     # sam build
make api-deploy    # sam build + sam deploy (samconfig.toml: stack cnpj-cadastro, us-east-1)
make api-clean     # remove .venv e caches
make test          # testes de todas as partes
```

O ambiente Python (`pyproject.toml`, `uv.lock`, `.venv`) fica em `api/` e é compartilhado por todas as lambdas. Cada lambda tem seu `template.yaml` e seu `Makefile` de build/deploy. Ou direto na pasta, sem o prefixo: `cd api && make test`.

### Evento de entrada

```json
{
  "Source": "app.usuarios",
  "DetailType": "UsuarioCadastrado",
  "Detail": "{\"user_id\": \"123\", \"cnpj\": \"00.000.000/0001-91\"}"
}
```
