# kalman-hackathon-vx

## api/cnpj-cadastro

Cadastro de usuários pessoa jurídica: login com **Amazon Cognito**, consulta do CNPJ no [OpenCNPJ](https://api.opencnpj.org) e dados salvos no DynamoDB.

```
Front ──login──> Cognito (e-mail + senha) ──> access token
Front ──token──> API Gateway (valida o token) ──> Lambdas ──> DynamoDB
                                                    └─ POST: EventBridge ──> consulta OpenCNPJ
```

- **Cognito** guarda e-mail e senha. A senha nunca passa pelo nosso código nem pelo DynamoDB.
- **DynamoDB** guarda um item por usuário, com chave `user_id` igual ao `sub` do Cognito: dados do CNPJ e os campos do formulário (`dados`).
- O `user_id` **sempre** vem do token. A API ignora qualquer `user_id` enviado pelo front.

### Pré-requisitos

- [uv](https://docs.astral.sh/uv/)
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) (só para build e deploy)

### Comandos

Da raiz do repositório (cada parte tem seu próprio `Makefile`, e a raiz só delega):

```bash
make help          # lista os alvos
make api-test      # uv sync + pytest (local: DynamoDB com moto, OpenCNPJ com servidor local)
make api-smoke-login  # login + rotas recusam chamadas sem token (stack publicada, usa suas credenciais AWS)
make api-smoke     # fluxo completo: login, POST, GET, PATCH, isolamento entre usuários (stack publicada)
make api-build     # sam build
make api-deploy    # sam build + sam deploy (samconfig.toml: stack cnpj-cadastro, us-east-1)
make api-clean     # remove .venv e caches
make test          # testes de todas as partes
```

O ambiente Python (`pyproject.toml`, `uv.lock`, `.venv`) fica em `api/` e é compartilhado por todas as lambdas. Cada lambda tem seu `template.yaml` e seu `Makefile` de build/deploy. Ou direto na pasta, sem o prefixo: `cd api && make test`.

Os smoke tests criam usuários de teste direto no Cognito (sem enviar e-mail) e apagam esses usuários e os itens deles no final.

### Rotas

Todas exigem o header `Authorization: Bearer <access token do Cognito>`. Sem token, a API responde **401**.

| Rota | Body | Resposta |
|---|---|---|
| `POST /cadastro` | `{"cnpj": "00.000.000/0001-91"}` | **202** na hora. A consulta do CNPJ roda em segundo plano (~3s). **400** se o CNPJ for inválido. |
| `GET /cadastro/me` | | **200** com `cnpj`, `status`, `empresa` (sem sócios) e `dados`. **404** enquanto a consulta não terminou. |
| `PATCH /cadastro/me` | `{"dados": {"telefone": "1199...", "site": null}}` | **200** com o cadastro atualizado. Faz merge campo a campo, e `null` apaga o campo. **404** se não houver cadastro. |

`status` pode ser `ativa`, `inativa`, `nao_encontrado` ou `cnpj_invalido`. Os campos de `dados` ainda são livres (snake_case). Depois de definir o formulário, liste-os em `CAMPOS_PERMITIDOS` em `src/usuario.py`.

### Como o front usa (Amplify v6)

Os valores vêm dos outputs da stack: `aws cloudformation describe-stacks --stack-name cnpj-cadastro --query "Stacks[0].Outputs"`.

```js
import { Amplify } from "aws-amplify";
import { signUp, confirmSignUp, signIn, fetchAuthSession } from "aws-amplify/auth";

Amplify.configure({ Auth: { Cognito: { userPoolId: "<UserPoolId>", userPoolClientId: "<UserPoolClientId>" } } });

await signUp({ username: email, password });                // Cognito envia um código por e-mail
await confirmSignUp({ username: email, confirmationCode });
await signIn({ username: email, password });

const { tokens } = await fetchAuthSession();                 // renova o token sozinho quando expira
const auth = { Authorization: `Bearer ${tokens.accessToken}`, "Content-Type": "application/json" };

await fetch(API_URL, { method: "POST", headers: auth, body: JSON.stringify({ cnpj }) });
const cadastro = await (await fetch(`${API_URL}/me`, { headers: auth })).json();   // repita enquanto for 404
await fetch(`${API_URL}/me`, { method: "PATCH", headers: auth, body: JSON.stringify({ dados: { telefone } }) });
```

O e-mail padrão do Cognito tem limite baixo de envios por dia. Antes de produção, configure o Amazon SES no User Pool.
