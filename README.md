# kalman-hackathon-vx

## identidade-visual

Marca, cores, tipografia, componentes e regras do Kalman (versão "Laudo"), prontos para qualquer parte do projeto:
SVGs e PNGs da marca, `tokens.css` + `componentes.css` para HTML puro, tema para Tailwind v4/shadcn, `tokens.json` para
Python e gráficos. Guia em [`identidade-visual/README.md`](identidade-visual/README.md); para ver tudo, abra
`identidade-visual/especime.html` no navegador.

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
make api-seed-aurora  # cria a empresa de teste Aurora (KALMANTESTE100) com perfil completo; os dados ficam
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
| `PATCH /cadastro/me` | `{"dados": {"setor": "energia_eletrica", "ufs_atuacao": ["SP"], "email_alertas": null}}` | **200** com o cadastro atualizado. Só o dono (**403** para membros). Faz merge campo a campo (uma lista é trocada inteira), e `null` apaga o campo. **400** com `campos` se um campo não for do perfil ou tiver o tipo errado. **404** se não houver organização. |

`status` pode ser `processando` (logo depois do POST), `ativa`, `inativa` ou `nao_encontrado`.

`dados` guarda o **perfil regulatório**, que o filtro da matriz de obrigações usa junto com os dados da Receita em `empresa` (CNAEs, natureza jurídica, porte, UF). Os campos e as regras de cada um estão em `src/perfil.py`:

| Campo | Tipo |
|---|---|
| `nome_fantasia`, `email_alertas`, `faixa_funcionarios`, `setor` | texto |
| `ufs_atuacao` (siglas), `municipios_atuacao` (código IBGE), `orgaos_fiscalizadores`, `temas_interesse`, `temas_fora_escopo`, `certificacoes` | lista de textos |
| `unidades` (`id`, `nome`, `tipo`, `tags`) | lista de objetos |
| `outorgas` (`id`, `tipo`, `numero`, `orgao`, `objeto`, `unidade_id`, `validade` AAAA-MM-DD, `antecedencia_renovacao_dias`) | lista de objetos |
| `areas` (`id`, `nome`, `responsavel`, `email`) | lista de objetos |

Em cada lista de objetos o `id` é obrigatório e único.

**Empresa de teste.** Com `FixturesEnabled=true` (só na stack do hackathon, ligado no `samconfig.toml`), CNPJs que começam com `KALMAN` vêm de `src/fixtures/` em vez do OpenCNPJ. `KALMANTESTE100` é a Aurora Energia S.A., distribuidora ativa em SP. `make api-seed-aurora` cria o usuário, envia o CNPJ e grava o perfil de `tests/aurora_dados.json`.

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

O `PATCH /cadastro/me` responde **403** para membros. O dono só troca de CNPJ enquanto a organização não tem membros, convites pendentes nem unidades, outorgas ou áreas no perfil (senão **409**): o perfil vai para o lake da matriz de obrigações chaveado pelo CNPJ. O CNPJ anterior fica livre e o formulário vai junto. Um membro não cadastra CNPJ: precisa sair da organização antes.

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
await fetch(`${API_URL}/me`, { method: "PATCH", headers: auth, body: JSON.stringify({ dados: { setor } }) });
```

O e-mail padrão do Cognito tem limite baixo de envios por dia. Antes de produção, configure o Amazon SES no User Pool.

## api/matriz

API da **matriz de obrigações** (stack `matriz-api`): lê obrigações e tarefas da gold do lakehouse pelo Athena e registra as decisões do dono. Usa o mesmo login (Cognito) e a tabela do cadastro, só para leitura: o CNPJ e o papel vêm de lá, nunca do front.

| Rota | Body | Resposta |
|---|---|---|
| `GET /obrigacoes` | | versão vigente de cada obrigação e propostas do LLM aguardando decisão |
| `GET /obrigacoes/{id}` | | todas as versões e o histórico (inclusões, alterações, aprovações) |
| `POST /obrigacoes/{id}/decisao` | `{"versao": 2, "decisao": "aprovar"}` | **200** com as versões e as tarefas recalculadas. **409** se a versão já foi decidida. Só o dono (**403**) |
| `GET /tarefas` | `?em_risco=true&obrigacao_id=OBR-013` | tarefas com vencimento, área, status e `em_risco` |
| `PATCH /tarefas/{id}` | `{"status": "concluida", "evidencia_url": "https://..."}` | **200** com a tarefa. Só o dono (**403**) |

A decisão é gravada em `bronze_db.matriz_decisoes` (de onde o job refaz a gold) e já aplicada na gold, para o front ver o resultado na hora. As regras de prazo e de versão são as mesmas do job (`pipeline/matriz/src/regras_matriz.py`, copiado em `api/matriz/src/`). Os dados vêm do ETL em `pipeline/matriz/`.

```bash
make matriz-test     # testes (o SQL roda num DuckDB no lugar do Athena)
make matriz-deploy   # sam deploy; resolve User Pool, tabela, bucket e workgroup pelos outputs das stacks
```

## api/chatbot

Agente da Kalman (`agent.py`, Strands + Bedrock AgentCore). Responde só com dados do Athena (`gold_db`), sempre filtrando pelo `user_id` do payload.

### Integração com o cnpj-cadastro

O agente não chama a API do cadastro. O caminho do dado é:

```
API cnpj-cadastro ──> DynamoDB ──(pipeline do stack lakehouse-pipeline, todo dia às 2h)──> gold_db.empresas_clientes ──> agent.py (Athena)
```

O contrato é o `user_id`: o `sub` do Cognito que a API grava precisa chegar ao gold, onde o agente filtra `WHERE user_id = '<sub>'`. O pipeline (Step Functions + Glue) fica em `pipeline/cadastro/`.

```bash
make api-integracao                    # cadastro -> pipeline -> ferramentas do agente
make api-integracao ARGS="--com-llm"   # também chama o modelo (precisa de MODEL_ID no ambiente)
```

O teste (`api/chatbot/tests/integracao_cadastro.py`) usa suas credenciais AWS e:

1. pela API, cria um dono (A), um membro que aceitou o convite (B) e um usuário sem organização (C)
2. dispara o pipeline do lakehouse e espera terminar (~15 min, por causa do export do DynamoDB)
3. chama as ferramentas do agente com o `user_id` de cada um: A e B veem a empresa (mesmo CNPJ e razão social do `GET /cadastro/me`) e C não vê nada
4. confere que o `invoke` recusa `user_id` fora do formato
5. apaga os usuários, os itens do DynamoDB e as linhas deles no silver e no gold (o pipeline só faz upsert e nunca apaga)

Se o pipeline falhar, o tópico de alerta dele recebe o aviso, como numa falha real.

**Pendente (nov/2026):** o ETL já ignora os vínculos `<sub>` e os convites `CONVITE#...`, então a Silver não quebra mais. Mas ele ainda usa a chave do item como `user_id`, e o dado da empresa está no item da organização: no gold, o `user_id` vira `CNPJ#<cnpj>`, e o agente, que filtra pelo `sub`, não encontra nada. Até o ETL gerar uma linha por usuário (dono e membros, ligando `<sub>` -> `cnpj` -> `CNPJ#<cnpj>`) com o `sub` como `user_id`, o teste falha no passo 3.

## front/cadastro-teste

Front de **teste** do fluxo completo: login no Cognito, envio do CNPJ, espera pela consulta, formulário pré-preenchido com os dados da Receita e organização (convidar, aceitar convite, remover membros). Foi feito com Vite, React, TypeScript e Amplify, a mesma base do Lovable. O arquivo `src/api.ts` é o cliente da API que serve de referência para o front definitivo.

```bash
make front-env     # gera front/cadastro-teste/.env com os outputs da stack (precisa de credenciais AWS)
make front-dev     # http://localhost:5173 (porta fixa: é a que está liberada no CORS)
make front-check   # typecheck
```

Com `VITE_MATRIZ_API_URL` no `.env` (o `make front-env` preenche se a stack `matriz-api` existir) aparece a tela da matriz: propostas para aprovar ou rejeitar, tarefas com status e as obrigações vigentes com o histórico. O cliente está em `src/matriz.ts`.

Os campos do perfil ficam em `src/campos.ts`, espelhando `src/perfil.py` da API: texto, opções, listas como chips (UFs, órgãos, temas) e linhas repetíveis (unidades, outorgas, áreas).

### Front no Lovable: cuidados

- **CORS:** o API Gateway só aceita a origem exata (ou `*`), sem curinga de subdomínio. Inclua a URL de preview do Lovable, a publicada (`*.lovable.app`) e o domínio próprio, se houver:
  `sam deploy --parameter-overrides 'AllowedOrigins="http://localhost:5173,https://<preview>,https://<app>.lovable.app"'`
- **Autenticação:** o Lovable sugere Supabase / Lovable Cloud para login. Não use. O login é o Cognito, via `aws-amplify/auth`, como em `src/App.tsx`. Os dois juntos criariam usuários em dois lugares.
- **Configuração:** `UserPoolId`, `UserPoolClientId` e `ApiUrl` são públicos e podem ir no código. Nunca coloque credenciais AWS (access key) no front.
- **Contrato:** sempre `Authorization: Bearer <accessToken>`. Nunca envie `user_id`. Depois do POST, repita o GET `/cadastro/me` até aparecer um `consultado_em` novo (o `aguardarConsulta` faz isso). Trate o 409 do POST (CNPJ com dono) e o 403 do PATCH (membros só leem). Para quem ainda não tem organização, consulte `GET /cadastro/convite`. Copie o `src/api.ts`.

## pipeline

ETLs do lakehouse na AWS: o `cadastro/` lê a tabela do DynamoDB desta API e o `dou/` coleta os atos do Diário Oficial. Os dois rodam como jobs Glue Python Shell com DuckDB e gravam em Iceberg no Glue Data Catalog, no mesmo bucket. Detalhes em [pipeline/README.md](pipeline/README.md).

```bash
make pipeline-test     # testes dos dois ETLs, sem AWS
make pipeline-deploy   # sam deploy do cadastro e depois do dou
make pipeline-dou-run  # dispara a coleta do mês atual
```
