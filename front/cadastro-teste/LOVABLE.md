# Front do Kalman na Lovable: plano de publicação

> Escrito em 08/11/2026 a partir da branch `feat/front-kalman` e da documentação da Lovable nessa data. Nada foi
> alterado, publicado nem chamado na AWS.
> Legenda: **[fato]** = conferido no código ou na doc oficial (com a fonte) · **[hipótese]** = inferência ou fonte
> fraca: testar antes de confiar.

## Resumo

- Só o front (SPA estática) vai para a Lovable. O back continua todo na AWS, sem Lovable Cloud nem Supabase.
- A stack é compatível com o que a Lovable chama de "React + Vite antigo". Mas **não dá para importar o nosso
  repositório**: a Lovable sempre cria um repositório novo, e o upload de ZIP **reescreve o app em TanStack Start**.
  O caminho que preserva o código é: criar o projeto na Lovable → ligar o GitHub (gera um repositório novo) → colocar
  o conteúdo de `front/cadastro-teste/` na raiz desse repositório → dar push.
- Na AWS não há segredo nem callback para configurar. Basta pôr as origens da Lovable no `AllowedOrigins` das 3
  stacks com HTTP API (`cnpj-cadastro`, `matriz-api`, `chatbot-api`).

## 1. O que vai para a Lovable

**Só o front.** A hipótese se confirma.

| Peça | Onde fica | Evidência |
|---|---|---|
| SPA (landing, acesso, painel, dash) | **Lovable** (build estático do Vite) | `package.json`: `vite build`, sem servidor. `index.html` + `src/main.tsx` com `BrowserRouter` |
| Login | **Cognito**, chamado direto do navegador pelo `aws-amplify` | `src/config.ts` linhas 29-40 |
| APIs `cnpj-cadastro`, `matriz-api`, `chatbot-api` | AWS (API Gateway HTTP + Lambda) | `api/*/template.yaml` |
| Agente (`chatbot-agent`), pipelines, Athena/Glue | AWS. Nenhuma dessas peças é chamada pelo front | `ia/chatbot/template.yaml`: runtime com IAM, sem HTTP público. README da raiz, linha 175: "O agente não é uma API" |
| Consulta de CNPJ | OpenCNPJ, chamada direto do navegador (pública, com CORS liberado) | `src/cnpj.ts`, `TELAS.md` linha 394 |

**[fato]** Os segredos da Lovable ("Secrets") só valem para o backend da própria Lovable (Edge Functions / Supabase)
([docs: Secrets](https://docs.lovable.dev/features/secrets)). Não temos nada para pôr lá.

## 2. A Lovable e a nossa stack

| Item | Nossa stack | Lovable | Situação |
|---|---|---|---|
| Framework | Vite 8 + React 19 + TS 7 + React Router 7 (SPA) | Desde 13/05/2026 os projetos novos nascem em **TanStack Start**. O "React + Vite" antigo "keeps working" ([docs: TanStack Start](https://docs.lovable.dev/features/upgrade-to-tanstack-start.md)) | **[fato]** Compatível. A IA da Lovable tende a sugerir TanStack Start |
| Importar repositório existente | Monorepo `gabriellsar/kalman-hackathon-vx`, app em `front/cadastro-teste/` | "Git sync always creates a new repository". "You can't import an existing repository into Lovable" ([GitHub](https://docs.lovable.dev/integrations/github), [Git sync](https://docs.lovable.dev/integrations/git-sync-overview.md)) | **[fato]** Precisa de um repositório novo, criado pela Lovable |
| Upload de ZIP | n/a | "Lovable rebuilds the app the way it builds new Lovable apps, on TanStack Start". "treats the export as source material" ([docs: Import](https://docs.lovable.dev/features/projects/import-project.md)) | **[fato]** **Não usar.** Reescreve o app |
| Commits de fora | n/a | "Commits you push to the synced branch appear in your Lovable project". Sincroniza **uma** branch só (a padrão). Em conflito, a Lovable grava na branch `lovable-sync` | **[fato]** É por aqui que entramos com o código |
| App na raiz | Hoje o app está em subpasta (`TELAS.md` linha 566) | A doc não fala de monorepo nem de subpasta | **[hipótese]** Exige o app na raiz, que é como a Lovable gera os projetos dela. Pôr na raiz e pronto |
| Tailwind / shadcn | CSS próprio (`src/identidade/`, `styles.css`, `dash.css`), sem Tailwind | Nenhuma doc oficial exige os dois. Só um importador de terceiros "valida React, Vite, Tailwind" | **[hipótese]** Não é obrigatório para hospedar. A IA da Lovable gera Tailwind/shadcn quando edita |
| Gerenciador de pacotes | npm (`package-lock.json`) | A doc de hospedagem externa usa `npm run build` e Node 22 ([docs](https://docs.lovable.dev/tips-tricks/external-deployment-hosting.md)) | **[hipótese]** OK. Conferir se o build da Lovable aceita Vite 8 / TS 7 (o nosso `build` roda `tsc --noEmit` antes) |
| `VITE_*` | `src/config.ts` lê `VITE_*` e, se faltarem, usa os valores da stack (linhas 9-25) | `VITE_*` ficam num `.env` **versionado** ("Do not add .env to .gitignore"), e não em Secrets ([docs: Secrets](https://docs.lovable.dev/features/secrets)) | **[fato]** Não precisa de nada: o fallback já cobre. Um `.env` versionado é opcional |
| Rotas SPA (`/painel`, `/termos`…) | `BrowserRouter`. `TELAS.md` linha 384 pede o fallback | A doc não fala do fallback na hospedagem da Lovable. Os próprios projetos Vite da Lovable usam `BrowserRouter`. Guias de terceiros dizem que o lovable.app já faz o fallback | **[hipótese]** Funciona. Testar com F5 em `/painel` e `/termos` publicados |
| Porta do dev | `vite.config.ts`: `port 5173, strictPort: true` | Os templates da Lovable usam a 8080 | **[hipótese]** O preview do editor pode falhar por causa do `strictPort`. Ver o passo 4 |
| Domínio próprio | n/a | `*.lovable.app` grátis em todos os planos. Domínio próprio só no plano pago ([docs: Hosting](https://docs.lovable.dev/features/hosting.md)) | **[fato]** |

**Risco da IA reescrever o código: alto se o time editar pelo chat da Lovable.** A IA trabalha no padrão dela
(TanStack Start, Tailwind, shadcn, login por Supabase). O README da raiz (linha 340) já avisa: **não aceitar
Supabase/Lovable Cloud para login**, porque os usuários ficariam em dois lugares. Recomendação: usar a Lovable como
**hospedagem + preview**, editar no repositório (local ou pelo editor de código) e, se usar o chat, pedir mudanças
pequenas e revisar o diff do commit que ela gera.

## 3. Ligar na AWS

### O que o front precisa (tudo público)

**[fato]** `src/config.ts` linhas 9-15 (com fallback, então não exige `.env`):

| Valor | Hoje | `VITE_*` |
|---|---|---|
| API do cadastro | `https://usxtt4q6zi.execute-api.us-east-1.amazonaws.com/cadastro` | `VITE_API_URL` |
| User Pool | `us-east-1_MmMe6Ii7z` | `VITE_USER_POOL_ID` |
| App Client | `7d9om4gaq7b24kbn1augsijj29` | `VITE_USER_POOL_CLIENT_ID` |
| API da matriz | `https://ooe7nuoz9l.execute-api.us-east-1.amazonaws.com` | `VITE_MATRIZ_API_URL` |
| API do chat | `https://idgv0m8bmd.execute-api.us-east-1.amazonaws.com` | `VITE_CHATBOT_API_URL` |

### Cognito: nada a mudar

**[fato]** O App Client não tem Hosted UI nem OAuth, e por isso não tem callback/logout URL
(`api/cnpj-cadastro/template.yaml` linhas 73-83). Ele é público (`GenerateSecret: false`) e usa SRP
(`ALLOW_USER_SRP_AUTH`). O login acontece no navegador e funciona em qualquer domínio. As APIs só validam
`issuer`/`audience` do JWT (cnpj linhas 117-124, matriz 37-44, chatbot 45-52).

### CORS: o que muda

**[fato]** As 3 HTTP APIs têm `AllowedOrigins` com default `http://localhost:3000,http://localhost:5173`
(cnpj linhas 12-14 e 125-128, matriz 27-29 e 45-48, chatbot 21-23 e 53-56). Um `*.lovable.app` não funciona: o
API Gateway aceita a origem exata, `*`, `https://*` ou `http://*`, e não aceita curinga de subdomínio
([AWS: HTTP API CORS](https://docs.aws.amazon.com/apigateway/latest/developerguide/http-api-cors.html)). Com CORS
configurado, o API Gateway ignora os headers de CORS que a Lambda devolver.

Origens que precisam entrar:
1. A URL publicada, `https://<slug>.lovable.app`.
2. A origem do preview do editor, se o time for testar login por lá. **[hipótese]** O formato é
   `https://id-preview--<uuid>.lovable.app`. Copie a origem exata do header `Origin` no DevTools.
3. O domínio próprio, se houver.
4. Manter `http://localhost:5173`.

**[fato] Onde gravar:** o `AllowedOrigins` não está no repositório. Não aparece no `samconfig.toml` do cadastro
(linha 11) nem nos `Makefile` de `api/matriz` (linhas 17-23) e `api/chatbot` (linhas 16-20). O `sam deploy` repete
o valor anterior de todo parâmetro não informado (`UsePreviousValue`, conferido no código do SAM CLI:
`deploy_context.merge_parameters`). Então um `--parameter-overrides AllowedOrigins=...` avulso funciona e
**persiste na stack**, mas some se a stack for recriada e é sobrescrito por quem passar outro valor.
Recomendação: gravar as origens no repositório, mudando o `Default` nos 3 templates ou uma variável
`ALLOWED_ORIGINS` nos Makefiles. Publicar seguindo o aviso "uma branch por vez" do README (linhas 3-13).

### O que **não** pode ir para o front

- Credenciais AWS (access key/secret), tokens de sessão IAM, qualquer `aws-sdk` com credencial
  (README linha 341).
- O ARN do runtime do AgentCore, o `MODEL_ID`, os nomes de tabela, bucket e workgroup: o front não usa nenhum deles,
  e eles ficam nas Lambdas.
- O `.env` local não tem segredo (`.env.example`: "Nenhum desses valores é segredo"), mas também não é necessário.
- Supabase/Lovable Cloud: não ativar.

## 4. Passo a passo

1. **Fechar o front na branch.** Terminar o dash: trocar a loja de `src/dash/dados.ts` (linhas 1-13) por
   `matriz.ts` e `chatbot.ts`. Ligar o chat: `Ia.tsx` linha 5 → `enviarMensagem`. Hoje `src/dash/` e `public/ia/`
   **não estão no git** (aparecem como `??` no `git status`). Commitar antes, senão nada disso chega à Lovable.
2. **Criar o projeto na Lovable** (projeto em branco) e, em *Settings → GitHub*, conectar a conta ou org do time.
   A Lovable cria um repositório novo, por exemplo `kalman-front`.
3. **Colocar o app na raiz do repositório novo.** Duas formas:
   - simples: clonar o repositório, apagar o conteúdo gerado e copiar `front/cadastro-teste/*` sem `node_modules/`,
     `dist/` e `.env`. Adicionar um `.gitignore` próprio (`node_modules`, `dist`). Commit + push na branch padrão.
   - com histórico: `git subtree split --prefix front/cadastro-teste -b front-only` no monorepo e push dessa branch
     para o `main` do repositório novo.
4. **Conferir o preview no editor da Lovable.** **[hipótese]** Se o preview não subir, trocar no `vite.config.ts`
   do repositório novo `strictPort: true` por `false` (ou a porta por 8080). Nesse caso, pôr também
   `http://localhost:8080` no CORS.
5. **Variáveis:** nada obrigatório, porque o `config.ts` usa os valores das stacks. Se preferir explícito, criar um
   `.env` **versionado** com as 5 `VITE_*` da tabela acima. São públicas, e a doc da Lovable pede o `.env` no git.
6. **Publicar** (*Publish*) e anotar a URL `https://<slug>.lovable.app`, que dá para personalizar. Anotar também a
   origem do preview.
7. **CORS:** incluir as origens no `AllowedOrigins` de `cnpj-cadastro`, `matriz-api` e `chatbot-api`, gravadas no
   repositório (seção 3). Publicar da branch que tem tudo o que já está no ar. Conferir com
   `aws apigatewayv2 get-api --api-id <id> --query CorsConfiguration` (não executado aqui).
8. **Testar ponta a ponta na URL publicada:** landing → criar conta com código por e-mail → entrar → CNPJ (Light ou
   `KALMANTESTE100`) → confirmar dados → enviar a planilha (`pipeline/matriz/fixtures/ampla/matriz.csv`) → dash →
   pergunta no chat. Cuidado: o chat tem limite de 20 mensagens/hora e 100/dia por usuário, e acima disso responde
   429. Dar **F5 em `/painel`, `/termos` e `/painel/matriz`** para checar o fallback. Abrir o DevTools e conferir
   que nenhum pedido falha por CORS.
9. **Modo demo.** **[fato]** `demoAtivo = import.meta.env.DEV && params.has("demo")` (`src/demo.ts` linha 24): no
   build publicado ele não existe, então `?demo` não faz nada (`TELAS.md` linha 403). **[hipótese]** No preview do
   editor, que roda o servidor de dev, o `?demo` deve funcionar. Decisão: para mostrar o produto sem login na URL
   pública (pitch), é preciso uma flag, por exemplo `VITE_DEMO=1` em vez de `DEV`. Caso contrário, deixar como está.
   Remover o modo de vez: apagar `demo.ts` e as referências no `App.tsx` (linhas 21, 35-59, 146-156).
10. **Opcional:** domínio próprio (plano pago) e incluí-lo no CORS. Com a URL pública, resolver a pendência do logo
    em imagem no e-mail do código (`TELAS.md` linha 569).

## 5. Riscos e decisões em aberto

| Tema | Opções / risco | Recomendação |
|---|---|---|
| Repositório | (a) o front **muda** para o repositório da Lovable, que vira a fonte da verdade, e o monorepo fica só com o back. (b) o front continua no monorepo e é empurrado para o repositório da Lovable por `subtree` | (a) se o time for editar na Lovable. (b) só se **ninguém** editar na Lovable, senão as duas cópias divergem e a Lovable abre `lovable-sync` |
| Quem mantém a sincronia | Uma branch sincronizada só. Commits em outras branches não aparecem | Uma pessoa dona do repositório do front. Mudanças via PR no `main` |
| IA da Lovable | Pode trocar CSS próprio por Tailwind/shadcn, propor Supabase ou migrar para TanStack Start | Não aceitar sugestões de auth/backend. Revisar cada commit da Lovable |
| Conta GitHub | O repositório atual é pessoal (`gabriellsar`). Não dá para trocar a conta de um projeto Lovable depois sem criar outro repositório ([docs](https://docs.lovable.dev/integrations/github)) | Criar já na org/conta definitiva |
| Versões novas (Vite 8, TS 7) | **[hipótese]** O ambiente da Lovable pode estar numa versão de Node que não roda o build | Testar no passo 4. Se falhar, ver o erro de build antes de rebaixar versões |
| CORS fora do git | O valor fica só na stack | Gravar no template ou no Makefile (seção 3) |
| Plano | Free: publica em `lovable.app`, com o selo "Edit with Lovable" e 5 créditos/dia (30/mês). Pro, a partir de US$ 25/mês: domínio próprio e sem selo ([docs: planos](https://docs.lovable.dev/introduction/subscription-plans.md)) | Free basta para o hackathon. Pro só se houver domínio próprio |
| Remetente e e-mail | O e-mail do código sai pelo Cognito padrão, com limite diário baixo (README linha 131) | No dia do pitch, não depender de muitos cadastros novos. Usar contas já criadas |
| `Matriz.tsx` × `matriz.ts` | Só diferem em maiúscula. No Linux (build da Lovable) não há colisão, e `./matriz` resolve para o `.ts` | Renomear mesmo assim, como o README pede |

Observação: o `front/cadastro-teste/README.md` citado no pedido não existe. A documentação do front está na seção
`front/cadastro-teste` do `README.md` da raiz e em `TELAS.md`.
