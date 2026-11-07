# kalman-hackathon-vx

## api/cpnj-cadastro

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

Ou direto na pasta, sem o prefixo: `cd api/cpnj-cadastro && make test`.

### Evento de entrada

```json
{
  "Source": "app.usuarios",
  "DetailType": "UsuarioCadastrado",
  "Detail": "{\"user_id\": \"123\", \"cnpj\": \"00.000.000/0001-91\"}"
}
```
