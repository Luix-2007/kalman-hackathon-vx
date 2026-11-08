# AWS: liberar o front da Lovable e a logo nos e-mails

> Passo a passo para rodar em qualquer PC com acesso à conta **520499255485** (us-east-1).
> Contexto: o front está publicado em **https://kalman-vx.lovable.app**, mas as APIs só aceitam chamadas de
> `localhost` (CORS). No site da Lovable, o cadastro mostra "Sem conexão com o servidor".

## O que muda

| Stack | O que muda | Como |
|---|---|---|
| `matriz-api` | CORS passa a aceitar a Lovable | só o parâmetro `AllowedOrigins`, **sem publicar código** (passo 2) |
| `chatbot-api` | CORS passa a aceitar a Lovable | só o parâmetro `AllowedOrigins`, **sem publicar código** (passo 2) |
| `cnpj-cadastro` | CORS + **logo do Kalman** no e-mail do código de cadastro | `sam deploy` do branch `feat/front-kalman` (passo 3) |

Nenhum dado muda (usuários, empresas, matriz). Origens que entram, além das de hoje:

```
https://kalman-vx.lovable.app                                         (site publicado)
https://id-preview--5990bf85-e155-4938-9d3d-82669b693809.lovable.app  (preview do editor da Lovable)
http://localhost:8080                                                 (dev do projeto da Lovable)
```

Lista completa (é o valor do parâmetro):

```
http://localhost:3000,http://localhost:5173,http://localhost:8080,https://kalman-vx.lovable.app,https://id-preview--5990bf85-e155-4938-9d3d-82669b693809.lovable.app
```

## 0. Pré-requisitos

- AWS CLI v2 (`aws --version`) e SAM CLI (`sam --version`) — só o passo 3 precisa do SAM.
- Git e **Python 3.13** no PATH (o `sam build` da `cnpj-cadastro` usa o runtime `python3.13`; sem ele, use
  `sam build --use-container`, que precisa do Docker).
- Credenciais **novas** do portal do evento (elas vencem em poucas horas).

Credenciais no terminal:

```bash
# Git Bash / Linux / macOS
export AWS_DEFAULT_REGION="us-east-1"
export AWS_ACCESS_KEY_ID="..."
export AWS_SECRET_ACCESS_KEY="..."
export AWS_SESSION_TOKEN="..."
```

```powershell
# PowerShell
$env:AWS_DEFAULT_REGION="us-east-1"; $env:AWS_ACCESS_KEY_ID="..."; $env:AWS_SECRET_ACCESS_KEY="..."; $env:AWS_SESSION_TOKEN="..."
```

## 1. Conferir o acesso

```bash
aws sts get-caller-identity --query "[Account,Arn]" --output text
# esperado: 520499255485   arn:aws:sts::520499255485:assumed-role/WSParticipantRole/...
```

## 2. CORS da `matriz-api` e da `chatbot-api` (sem publicar código)

Atualiza **só** o parâmetro `AllowedOrigins`; o template e os outros parâmetros ficam como estão
(`--use-previous-template` + `UsePreviousValue`).

**Git Bash / Linux / macOS:**

```bash
export ORIGENS="http://localhost:3000,http://localhost:5173,http://localhost:8080,https://kalman-vx.lovable.app,https://id-preview--5990bf85-e155-4938-9d3d-82669b693809.lovable.app"
for STACK in matriz-api chatbot-api; do
  aws cloudformation describe-stacks --stack-name "$STACK" --query "Stacks[0].Parameters[].ParameterKey" --output json \
    | python -c "import sys,json,os; o=os.environ['ORIGENS']; print(json.dumps([{'ParameterKey':k,'ParameterValue':o} if k=='AllowedOrigins' else {'ParameterKey':k,'UsePreviousValue':True} for k in json.load(sys.stdin)]))" \
    > "params-$STACK.json"
  aws cloudformation update-stack --stack-name "$STACK" --use-previous-template \
    --parameters "file://params-$STACK.json" --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND
  aws cloudformation wait stack-update-complete --stack-name "$STACK" && echo "$STACK: ok"
done
```

**PowerShell:**

```powershell
$ORIGENS = "http://localhost:3000,http://localhost:5173,http://localhost:8080,https://kalman-vx.lovable.app,https://id-preview--5990bf85-e155-4938-9d3d-82669b693809.lovable.app"
foreach ($STACK in "matriz-api", "chatbot-api") {
  $chaves = aws cloudformation describe-stacks --stack-name $STACK --query "Stacks[0].Parameters[].ParameterKey" --output json | ConvertFrom-Json
  $params = @($chaves | ForEach-Object {
    if ($_ -eq "AllowedOrigins") { @{ ParameterKey = $_; ParameterValue = $ORIGENS } } else { @{ ParameterKey = $_; UsePreviousValue = $true } }
  })
  ConvertTo-Json -InputObject $params | Set-Content -Encoding ascii "params-$STACK.json"
  aws cloudformation update-stack --stack-name $STACK --use-previous-template --parameters "file://params-$STACK.json" --capabilities CAPABILITY_IAM CAPABILITY_AUTO_EXPAND
  aws cloudformation wait stack-update-complete --stack-name $STACK; if ($?) { "$STACK: ok" }
}
```

Se aparecer `No updates are to be performed`, a stack já estava com essas origens: pode seguir.

## 3. `cnpj-cadastro`: CORS + logo no e-mail do código (publica código)

⚠️ Regra do README da raiz: cada `sam deploy` publica o código **do branch de quem roda**. O que está no ar hoje
saiu do `feat/front-kalman`, então publique **desse branch, atualizado**.

```bash
git clone https://github.com/gabriellsar/kalman-hackathon-vx.git   # ou, se já tiver: git fetch
cd kalman-hackathon-vx
git checkout feat/front-kalman && git pull
git log --oneline -1    # deve incluir "feat(api): Kalman logo image in emails; Lovable origins in CORS defaults" (f3311a3) ou mais novo

cd api/cnpj-cadastro
sam build               # ou: sam build --use-container
sam deploy --parameter-overrides \
  EventSource="app.usuarios" EventDetailType="UsuarioCadastrado" FixturesEnabled="true" \
  AllowedOrigins="http://localhost:3000,http://localhost:5173,http://localhost:8080,https://kalman-vx.lovable.app,https://id-preview--5990bf85-e155-4938-9d3d-82669b693809.lovable.app"
```

No PowerShell, troque as `\` do fim de linha por `` ` `` (crase) ou ponha o comando numa linha só.

O `sam deploy` mostra o **changeset** e pergunta se aplica (`confirm_changeset = true`). Antes de responder `y`:

- **Esperado:** `Modify` nas funções (`CustomMessageFunction`, `CadastroFunction`, `UsuarioFunction`,
  `MembrosFunction`...) e na API (`CadastroApi`, por causa do CORS).
- **Pare (`n`) se aparecer:** `Remove`/`Delete` de qualquer recurso, sobretudo `UserPool`, `UsuariosCnpjTable` ou
  rotas da API. Isso indicaria que o branch está atrás do que já foi publicado.

## 4. Conferir

```bash
# CORS das três APIs (deve listar https://kalman-vx.lovable.app)
for API in usxtt4q6zi ooe7nuoz9l idgv0m8bmd; do aws apigatewayv2 get-api --api-id $API --query "[Name,CorsConfiguration.AllowOrigins]" --output text; done

# pré-voo de CORS, como o navegador faz (deve voltar access-control-allow-origin: https://kalman-vx.lovable.app)
curl -s -i -X OPTIONS "https://ooe7nuoz9l.execute-api.us-east-1.amazonaws.com/obrigacoes" \
  -H "Origin: https://kalman-vx.lovable.app" -H "Access-Control-Request-Method: GET" \
  -H "Access-Control-Request-Headers: authorization" | grep -i "access-control-allow-origin"

# gatilho do e-mail continua ligado no Cognito (não pode voltar vazio)
aws cognito-idp describe-user-pool --user-pool-id us-east-1_MmMe6Ii7z --query "UserPool.LambdaConfig.CustomMessage" --output text
```

No navegador: abrir **https://kalman-vx.lovable.app/criar-conta**, criar conta com o CNPJ de teste
**04.368.898/0001-06** (Copel Distribuição, PR), confirmar o código (o e-mail deve vir com a **logo do Kalman** no
cabeçalho), conferir os dados, marcar **PR** e enviar a planilha `pipeline/matriz/fixtures/copel/matriz.csv`.
A análise da matriz leva de 5 a 15 minutos; depois o dash e a IA mostram os dados da empresa.

## Se der errado

- **`ExpiredToken`:** credenciais vencidas. Gere novas no portal e repita o passo 0.
- **Passo 2 falhou:** o CloudFormation volta sozinho ao estado anterior (`UPDATE_ROLLBACK_COMPLETE`). Veja o motivo
  em `aws cloudformation describe-stack-events --stack-name <stack> --max-items 10`.
- **Desfazer o CORS:** rode o passo 2 com `ORIGENS="http://localhost:3000,http://localhost:5173"`.
- **E-mail do código voltou em inglês depois do passo 3:** o gatilho `CustomMessage` saiu do User Pool (deploy de
  branch errado). Publique de novo do `feat/front-kalman` atualizado.

## Referências

- Logo usada nos e-mails: https://kalman-vx.lovable.app/marca/kalman-email.png (repositório `Cloway/kalman-vx`,
  `public/marca/`). Trocar com a variável `LOGO_URL` da Lambda, se precisar.
- Origens gravadas como padrão nos templates (`api/*/template.yaml`, parâmetro `AllowedOrigins`), para não se
  perderem em deploys futuros.
- Plano da Lovable: `front/cadastro-teste/LOVABLE.md`.
