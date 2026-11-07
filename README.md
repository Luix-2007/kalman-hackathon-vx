# kalman-hackathon-vx

## api/cnpj-cadastro

Cadastro de usuários pessoa jurídica: login com **Amazon Cognito**, consulta do CNPJ no [OpenCNPJ](https://api.opencnpj.org) e dados salvos no DynamoDB.

```
Front ──login──> Cognito (e-mail + senha) ──> access token
Front ──token──> API Gateway (valida o token) ──> Lambdas ──> DynamoDB
                                                    └─ POST: EventBridge ──> consulta OpenCNPJ
```

- **Cognito** guarda e-mail e senha. A senha nunca passa pelo nosso código nem pelo DynamoDB.
- **DynamoDB** (tabela única) guarda a organização de cada CNPJ (dados da empresa e formulário), a qual organização cada usuário pertence e os convites pendentes.
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
make api-smoke     # fluxo completo: CNPJ, formulário, isolamento, convite, membro, troca de CNPJ (stack publicada)
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
| `POST /cadastro` | `{"cnpj": "00.000.000/0001-91"}` | **202** na hora: cria a organização do CNPJ com o usuário como dono, e a consulta roda em segundo plano (~3s). **409** se o CNPJ já tiver dono. **400** se o CNPJ for inválido. |
| `GET /cadastro/me` | | **200** com `papel`, `cnpj`, `status`, `empresa` (sem sócios) e `dados` da organização. **404** se o usuário ainda não participa de uma. |
| `PATCH /cadastro/me` | `{"dados": {"telefone": "1199...", "site": null}}` | **200** com o cadastro atualizado. Só o dono (**403** para membros). Faz merge campo a campo, e `null` apaga o campo. **404** se não houver organização. |

`status` pode ser `processando` (logo depois do POST), `ativa`, `inativa` ou `nao_encontrado`. Os campos de `dados` ainda são livres (snake_case). Depois de definir o formulário, liste-os em `CAMPOS_PERMITIDOS` em `src/usuario.py`.

### Organizações: dono e membros

Cada CNPJ é uma **organização** com um único dono: quem enviou o CNPJ primeiro. O dono convida outras pessoas pelo e-mail. Os membros veem os mesmos dados da empresa e do formulário, mas não editam. Cada usuário participa de uma única organização, como dono ou como membro.

| Rota | Quem | Body | Resposta |
|---|---|---|---|
| `GET /cadastro/membros` | dono e membros | | **200** com `dono`, `membros` e, só para o dono, `convites` pendentes |
| `POST /cadastro/membros` | dono | `{"email": "pessoa@empresa.com"}` | **201**. Convite válido por 7 dias. **409** se a pessoa já faz parte ou já tem convite de outra organização |
| `DELETE /cadastro/membros/{id}` | dono, ou o próprio membro | | `id` = `user_id` remove o membro (ou é o membro saindo); `id` = e-mail cancela o convite |
| `GET /cadastro/convite` | convidado | | **200** com o convite pendente para o e-mail do usuário. **404** se não houver |
| `POST /cadastro/convite` | convidado | | **200**: aceita e vira membro. **409** se já participa de uma organização |
| `DELETE /cadastro/convite` | convidado | | **200**: recusa |

O convite não envia e-mail. O dono avisa a pessoa, ela cria a conta com o e-mail convidado e vê o convite ao entrar. O e-mail vem do Cognito, que só confirma a conta depois que a pessoa digita o código recebido. Por isso só quem tem acesso ao e-mail aceita o convite.

O `PATCH /cadastro/me` responde **403** para membros. O dono só troca de CNPJ enquanto a organização não tem membros nem convites pendentes (senão **409**). O CNPJ anterior fica livre e o formulário vai junto. Um membro não cadastra CNPJ: precisa sair da organização antes.

Tudo fica na tabela única, com a chave `user_id` (detalhes em `src/dados.py`):

| `user_id` (chave) | Campos | Para quê |
|---|---|---|
| `<sub do Cognito>` | `cnpj`, `papel` (`dono` ou `membro`) | a organização do usuário |
| `CNPJ#<cnpj>` | `dono`, `dono_email`, `status`, `empresa`, `dados`, `membros`, `convites` | a organização: um item por CNPJ, um dono |
| `CONVITE#<email>` | `cnpj`, `convidado_por`, `expira_em` (TTL) | convite pendente, um por e-mail |

O DynamoDB só garante unicidade pela chave. Por isso, criar a organização, aceitar um convite e remover um membro são transações: ou grava tudo, ou nada. Se duas pessoas enviarem o mesmo CNPJ ao mesmo tempo, só uma vira dona; a outra recebe 409. A Lambda da consulta só grava o resultado se quem disparou o evento ainda é o dono do CNPJ.

Ninguém prova que é dono do CNPJ: quem enviar primeiro fica com ele. Se precisar disso, valide a titularidade (por exemplo, com certificado e-CNPJ) antes de criar a organização.

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
const cadastro = await (await fetch(`${API_URL}/me`, { headers: auth })).json();   // repita enquanto status for "processando"
await fetch(`${API_URL}/me`, { method: "PATCH", headers: auth, body: JSON.stringify({ dados: { telefone } }) });
```

O e-mail padrão do Cognito tem limite baixo de envios por dia. Antes de produção, configure o Amazon SES no User Pool.

### E-mails de código (gatilho CustomMessage)

`src/email_cognito.py` é chamado pelo Cognito antes de cada e-mail com código e devolve assunto e HTML na identidade do
Kalman: um texto para cadastro e reenvio, outro para "esqueci a senha". Outros tipos (AdminCreateUser, MFA) ficam com a
mensagem padrão. O envio continua pelo Cognito, com o remetente padrão (`no-reply@verificationemail.com`). Se a Lambda
falhar, o cadastro falha junto: o HTML não depende de nada externo e tem teste (`tests/test_email_cognito.py`).

⚠️ Um `sam deploy` feito de uma branch sem este gatilho tira o `LambdaConfig` do User Pool, e o e-mail volta ao padrão em
inglês.

## front/cadastro-teste

Front de **teste** do fluxo completo: login no Cognito, envio do CNPJ, espera pela consulta, formulário pré-preenchido com os dados da Receita e organização (convidar, aceitar convite, remover membros). Foi feito com Vite, React, TypeScript e Amplify, a mesma base do Lovable. O arquivo `src/api.ts` é o cliente da API que serve de referência para o front definitivo.

```bash
make front-env     # gera front/cadastro-teste/.env com os outputs da stack (precisa de credenciais AWS)
make front-dev     # http://localhost:5173 (porta fixa: é a que está liberada no CORS)
make front-check   # typecheck
```

Os campos do formulário de teste ficam em `src/campos.ts`. Quando os campos reais forem definidos, troque essa lista e preencha `CAMPOS_PERMITIDOS` na API.

### Front no Lovable: cuidados

- **CORS:** o API Gateway só aceita a origem exata (ou `*`), sem curinga de subdomínio. Inclua a URL de preview do Lovable, a publicada (`*.lovable.app`) e o domínio próprio, se houver:
  `sam deploy --parameter-overrides 'AllowedOrigins="http://localhost:5173,https://<preview>,https://<app>.lovable.app"'`
- **Autenticação:** o Lovable sugere Supabase / Lovable Cloud para login. Não use. O login é o Cognito, via `aws-amplify/auth`, como em `src/App.tsx`. Os dois juntos criariam usuários em dois lugares.
- **Configuração:** `UserPoolId`, `UserPoolClientId` e `ApiUrl` são públicos e podem ir no código. Nunca coloque credenciais AWS (access key) no front.
- **Contrato:** sempre `Authorization: Bearer <accessToken>`. Nunca envie `user_id`. Depois do POST, repita o GET `/cadastro/me` até aparecer um `consultado_em` novo (o `aguardarConsulta` faz isso). Trate o 409 do POST (CNPJ com dono) e o 403 do PATCH (membros só leem). Para quem ainda não tem organização, consulte `GET /cadastro/convite`. Copie o `src/api.ts`.

