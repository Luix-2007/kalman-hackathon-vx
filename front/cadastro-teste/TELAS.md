# Landing, acesso, cadastro e equipe (07/11/2026)

> Estado: **testado de ponta a ponta contra a stack real** (Cognito + API + DynamoDB), na branch `feat/front-kalman`
> (feita a partir do `main` do Gabriel com membros e convites). A lógica e o cliente `src/api.ts` são os do Gabriel;
> mudaram a interface, os textos e o fluxo de conta. O produto é para **qualquer segmento**: energia elétrica é só o caso
> de teste, então nenhum texto fala em "distribuidora".

## Rodar

```bash
make front-dev     # http://localhost:5173 (porta fixa, liberada no CORS)
make front-check   # typecheck
```

`http://localhost:5173/` abre a landing. O `.env` virou opcional: sem ele, `src/config.ts` usa os valores públicos da stack `cnpj-cadastro` (é o que a Lovable vai
usar). Se a stack for recriada, troque os três valores do `STACK` em `src/config.ts`.

## Rotas (React Router)

| Rota | O que abre |
|---|---|
| `/` | **Landing** (`src/landing/`). Links antigos `/?criar&cnpj=` redirecionam para `/criar-conta` |
| `/entrar` | Entrar |
| `/criar-conta` | Criar conta; `?cnpj=33050071000158` já preenche e confere o CNPJ (é para onde a landing manda). A etapa "Confirme seu e-mail" acontece aqui dentro |
| `/esqueci-senha` | Redefinir a senha (a etapa "Crie uma senha nova" acontece aqui dentro) |
| `/painel` | Área logada. Sem sessão → `/entrar`. Com sessão, `/entrar` e `/criar-conta` → `/painel`. Sair → `/` |
| `/privacidade`, `/termos` | Páginas legais |
| qualquer outra | `/` |

Em dev o Vite devolve o `index.html` para qualquer caminho; na hospedagem (Lovable ou outra), as rotas precisam do
mesmo "fallback de SPA". O logo das telas de acesso e do painel leva a `/`.

Demonstração sem Cognito (só em dev): `/entrar?demo` (qualquer e-mail e senha; código: 6 dígitos quaisquer) e
`/painel?demo=vazio` · `dados` · `membro` · `convite` (antes do CNPJ · dono com equipe · membro · convite pendente).

## Conferência do CNPJ (`src/cnpj.ts`)

1. **Conta dos dígitos verificadores**, instantânea: com 14 dígitos já diz se é válido; incompleto, ao sair do campo
   diz quantos faltam.
2. **Consulta na Receita** pela OpenCNPJ (`api.opencnpj.org`, pública, sem chave, CORS liberado), 250 ms depois que a
   pessoa para de digitar. Respondeu em 50 a 450 ms nos testes. Mostra a razão social e a cidade (e a situação, se não
   for "ativa"), ou "Este CNPJ não aparece na Receita Federal" (404).
3. **Ao criar a conta**, espera a consulta se ela ainda estiver andando. CNPJ inexistente **bloqueia**; OpenCNPJ fora
   do ar ou lenta (> 4 s) **não bloqueia** ("Não deu para conferir na Receita agora. Você pode seguir."). O cadastro
   oficial continua sendo a consulta da API do Kalman depois do `POST /cadastro`.

Vale para "Criar conta" e para "Qual é o CNPJ da empresa?" no painel. Resultados ficam em cache na aba.

O modo demonstração (`src/demo.ts`) só existe em `npm run dev`; o build de produção não o inclui (conferido). Para
tirá-lo do projeto: apagar `demo.ts` e as referências a `demoApi`, `demoAuth`, `demoAtivo`, `demoLogado` e `DEMO_EMAIL`
no `App.tsx`.

## Identidade

Kit **Laudo** copiado sem alteração da branch `identidade-visual` para `src/identidade/` (`tokens.css`, `base.css`,
`componentes.css`, `marca.tsx`), favicon em `public/favicon.svg`. `src/styles.css` só faz layout e as peças destas
telas. Tema só claro, de propósito. Desvio pedido pelo time: botão laranja com **texto branco** (o kit usa grafite;
branco sobre esse laranja dá 3,1:1).

## Telas

### 0. Landing (`/`)
A versão aprovada em HTML (`torre-regulatoria/mockups/landing-final/index.html`) portada para React sem mudar o visual
(conferido: mesma altura e mesmas posições de seção em 1440 px e 390 px). Marcação em `src/landing/Landing.tsx`, estilo
em `landing.css` (todo dentro de `.lp`, CSS aninhado, animações com prefixo `lp-`), comportamento do `<script>` em
`iniciar.ts` (com limpeza ao sair da rota). Textos sem setor: sem "distribuidora" e sem "ANEEL" (a citação da
REN 1.174 usa "(...)" no lugar do sujeito, para não alterar o texto da norma).

### 1. Acesso (tela dividida)
Esquerda grafite (só no PC) com o logo (link para `/`), o motivo animado (`src/MotivoAnimado.tsx`) e "Saiba quais
normas afetam **a sua empresa.**". Direita, o formulário (24 rem), com o título numa linha só e "Kalman" em laranja.
No celular, só o formulário, com o logo (link para `/`) no topo.

| Modo | O que tem |
|---|---|
| **Entrar** | E-mail, senha (com olho), "Esqueci a senha", Entrar, "Criar conta". Conta não confirmada → reenvia o código e vai para Confirmar |
| **Criar conta** | CNPJ (máscara, conta dos dígitos na hora e consulta na Receita, ver acima), **seu nome** (obrigatório; vai para o atributo `name` do Cognito, sem espaços sobrando), e-mail corporativo, senha com medidor (Fraca/Boa/Forte, mostra o que falta pela regra do Cognito), confirmar senha. Botão só libera com tudo válido |
| **Confirmar e-mail** | Código de 6 dígitos num campo grande; "Reenviar código" com espera de 30 s; "Usar outro e-mail" |
| **Esqueci a senha** | E-mail → "Enviar código" |
| **Crie uma senha nova** | Código + senha nova (com medidor) + confirmar → salva e já entra |

Erros do Cognito traduzidos (senha errada, código errado/expirado, muitas tentativas, conta já existe…).

### 2. Painel (depois de entrar)
Barra fixa: marca (link para `/`), nome da empresa, e-mail, Sair. Aba do navegador: "Kalman · Painel" (todas as abas
seguem "Kalman · …").

Empresa de referência a partir de 07/11: **Light SESA, CNPJ 60.444.437/0001-46**. Os dados dela na OpenCNPJ estão em
`src/dados/light-opencnpj.json` (sem os sócios) e o modo demo usa esse arquivo, sem consultar nada.

- **Convite recebido** (sem empresa e com convite pendente): quem convidou, cartão grafite com razão social e CNPJ,
  validade, **Aceitar convite** / Recusar. O convite é buscado antes de decidir a tela (sem isso a tela do CNPJ piscava).
- **Pedir CNPJ** (sem empresa e sem convite): campo grande com máscara e dígitos. Se a conta foi criada com CNPJ, a
  consulta sai sozinha. CNPJ que já tem dono → "Este CNPJ já foi cadastrado por outra pessoa da empresa. Peça a ela um
  convite para a equipe."
- **Consultando:** "Lendo o CNPJ na Receita" com os segundos.

**Com a empresa cadastrada, o painel é uma página só, em três etapas liberadas uma de cada vez** (componente `Fluxo`,
indicador de etapas no topo): **1. Dados da empresa** → **2. Matriz de obrigações** → **3. Revisão**. A ideia
é a pessoa fazer uma coisa de cada vez; o que ainda não faz sentido aparece bloqueado, com o motivo.

- Etapa 1 começa aberta. **Confirmar dados** fica no fim da conferência (não é mais barra fixa). Ao confirmar, a etapa
  vira um resumo ("✓ … conferidos em … por …", com "Rever os dados") e a página desce para a etapa 2.
- Etapa 2 fica bloqueada até a confirmação. Quando a planilha é recebida, a etapa conta como feita na hora (a análise
  não prende ninguém) e a página desce para a revisão. Quem não tem a planilha pode "Pular esta etapa" (lembrado no
  navegador, por CNPJ).
- Etapa 3 (**Revisão**) fica bloqueada até a matriz ser enviada ou pulada. Mostra um cartão da empresa (razão social,
  CNPJ, estados onde atua, quem conferiu, "Rever") e um da matriz (planilha enviada e o estado da análise, que se
  atualiza sozinho: "Análise em andamento" → "Análise concluída: N obrigações vigentes"; "Ver a matriz"), a nota "A
  equipe você convida depois, em Configurações" e **Concluir cadastro** → cartão "Cadastro concluído" (lembrado no
  navegador, por CNPJ; ainda não vai para a API).
- A **equipe saiu do fluxo** (08/11): convidar e gerenciar membros fica para a tela de Configurações. O componente
  `Equipe` continua no `App.tsx`, exportado, pronto para ser usado lá.
- Membro: as três etapas liberadas e só leitura.
- `/painel/matriz` abre a mesma página já na etapa 2.
- **Etapa 1 · Conferência dos dados** (no lugar do formulário): cartão grafite (razão social, CNPJ, cidade/UF, ano de
  início, "Trocar CNPJ"), só com o que o Kalman usa para decidir quais normas valem. Tudo vem
  da Receita e **não se edita** aqui; se estiver errado, corrige-se na Receita e "consulte de novo" refaz a consulta.
  - **Identificação:** razão social, nome fantasia (se houver), CNPJ, matriz/filial, natureza jurídica, porte,
    situação na Receita (e desde quando), início das atividades.
  - **Atividades:** CNAE principal e secundários; o órgão regulador aparece quando o CNAE o deixa óbvio (ANEEL, ANP,
    Anatel, Banco Central, SUSEP, ANS, Anvisa, ANTAQ, ANAC, ANA).
  - **Onde atua:** sede (da Receita) e **Estados onde atua**, o único dado nosso: grade das 27 UFs, a sede marcada e
    fixa, as outras se marcam com um clique.
  - **Regime tributário:** Simples Nacional / MEI (ou "não optante").
  - No fim: "Os dados conferem?" + **Confirmar dados**. Grava em `dados` (PATCH `/cadastro/me`): `conferido_em`,
    `conferido_por` (e-mail), `conferido_por_nome` e `ufs_atuacao` (lista: `["RJ", "SP"]`), campos aceitos por
    `perfil.py`. Revendo os dados depois, o botão volta como "Salvar estados" se os estados mudarem.
  - Fora da tela, de propósito: contato (e-mail, telefone), endereço detalhado, capital social e sócios. O antigo
    formulário (`src/campos.ts`: responsável, contato, endereço) não é mais usado pela tela.
- **Membro:** a mesma conferência, só leitura (sem Confirmar, sem Trocar CNPJ, sem "consulte de novo"), com o aviso
  "Você é membro desta empresa: vê os dados, mas quem confirma é quem criou a conta."
- **Equipe** (fora do fluxo; vai para Configurações): lista de e-mails, sem selos de papel; "(você)" na própria linha e "Convite pendente até dd/mm/aaaa" nos
  convites. Quem criou a conta convida pelo e-mail, remove membros e cancela convites; o membro pode sair da empresa. O
  convite **não envia e-mail** (é assim na API): a tela avisa para combinar com a pessoa.

- A seção "Sua conta" (editar o nome) saiu do painel em 08/11. O nome vem do cadastro (atributo `name` do Cognito); a
  barra do topo mostra o nome, com o e-mail no tooltip.

### Onde fica o nome da pessoa
No **Cognito** (atributo padrão `name`: já existe no pool, opcional e editável; o app client não restringe atributos),
sem mudança na stack. O DynamoDB não tem dados da pessoa (só o vínculo usuário → CNPJ e papel) e a API não tem rota
para isso. Para a lista da Equipe mostrar nomes, a API teria de ler o `name` no Cognito, como já lê o e-mail.

### 3. Etapa 2 · Matriz de obrigações
A planilha que a empresa já usa vira obrigações com prazo calculado e tarefas com data (job `pipeline/matriz`). É a
base do dashboard. Arquivos: `src/TelaMatriz.tsx` (tela), `src/planilha.ts` (leitura e conferência do CSV),
`src/matriz.ts` (cliente da API, do Gabriel, com `getImportacoes` e `importarMatriz`).

- **Enviar a planilha** (só quem criou a conta): arrastar ou escolher um `.csv` ou `.xlsx` (até 2 MB), ou baixar o
  modelo. O CSV é lido e **conferido no navegador com as mesmas regras do job** (`_validar` e `ler_prazo_json`):
  `obrigacao_id`, `titulo`, `recorrencia`, `periodicidade`, `criticidade`, `prazo_json`, unidades de `aplica_a` que
  existem no perfil, IDs repetidos. A prévia mostra primeiro as linhas com erro, com o motivo. Linhas com erro ficam
  de fora; sem nenhuma válida (ou sem as colunas obrigatórias), o envio fica bloqueado. O `.xlsx` não tem prévia: é
  conferido no processamento. "Colunas da planilha" explica cada coluna e dá exemplos de `prazo_json`.
- **Planilha recebida:** depois do envio, a área de envio vira um cartão com o arquivo, a data e "Enviar nova versão".
  A análise roda **em segundo plano**: "Analisando o perfil da empresa e cruzando a matriz com as normas. Você pode
  seguir…". A tela confere de novo a cada 30 s, sem prender ninguém. Falha → "roda de novo sozinha em até 1 hora".
  Por que demora: o job da matriz (Step Functions + Glue) tem 4 etapas (Perfis, Bronze, Silver, Gold), cada uma sobe
  uma máquina do Glue, que aceita uma execução por vez; 7 a 15 min, mais se coincidir com a rodada de hora em hora.
  O aviso no dashboard e o e-mail de conclusão ficam para o dashboard.
- **Obrigações:** só aparecem **depois** que a análise termina (antes, nada para navegar). As vigentes, vindas de
  `GET /obrigacoes` (ID, título, órgão, criticidade); um clique abre prazo, recorrência, fonte (com link), trecho,
  área, evidência e versão.
- Membro: vê a planilha recebida e as obrigações, sem a área de envio.
- Planilha de exemplo da Ampla (Enel Distribuição Rio): `pipeline/matriz/fixtures/ampla/matriz.csv`, 25 obrigações,
  `aplica_a` e área vazios (a Ampla não tem unidades nem áreas no perfil); passa inteira na conferência.
- Conferido com a planilha da Aurora (`pipeline/matriz/fixtures/aurora/matriz.csv`): 22 de 22 válidas com as
  unidades do perfil dela; com o perfil da Light (sem unidades), 1 de 22, porque as outras citam `UN-xx` em `aplica_a`.
- **Lacuna:** a tela não tem onde cadastrar as unidades, as áreas e as outorgas do perfil (o formulário de teste do
  Gabriel tinha). Sem unidades, a planilha precisa vir com `aplica_a` vazio (a tela avisa).

## E-mail do código (Cognito)

Gatilho **CustomMessage** (`api/cnpj-cadastro/src/email_cognito.py`, publicado em 07/11): assunto e HTML na identidade
Laudo para cadastro, reenvio e "esqueci a senha" (textos diferentes). Remetente continua o padrão do Cognito
(`no-reply@verificationemail.com`, limite baixo por dia); remetente próprio exige SES. Sem `<title>` (alguns leitores
mostram o texto dele no topo do e-mail) e sem `<h1>` (alguns aplicam a fonte deles): o título é um `<div>`. O logo é
texto ("kalman" + ponto laranja): imagem precisa de um endereço público, o que fica para quando o front for publicado.
Recebido de verdade em 08/11 (temp mail), com o visual certo.

## Vínculo da conta com o CNPJ
1. Em **Criar conta**, o CNPJ vai para o `localStorage` (`kalman:cnpj-da-conta`) antes do `signUp`.
2. Depois de confirmar o e-mail e entrar, sem empresa e sem convite, o painel dispara a consulta sozinho.
3. Limite: vale no mesmo navegador. Para valer entre aparelhos, criar `custom:cnpj` no User Pool.

## Teste de ponta a ponta (07/11, stack real)
Criar conta → tela de código (o gatilho do e-mail rodou sem erro) → conta confirmada pela API (o endereço de teste não
recebe e-mail) → entrar → consulta automática do CNPJ → salvar formulário → convidar → entrar como convidado → convite
→ aceitar → modo membro. Usuários e itens de teste apagados no fim. As telas de "esqueci a senha" foram vistas no modo
demo; o envio real do código ainda precisa de uma pessoa com caixa de entrada.

## Testes de 08/11
- Fluxo do painel no modo demo, como dono e como membro: confirmar dados → matriz liberada → enviar a planilha da Ampla
  (25 de 25 válidas) → revisão liberada e página rolando para ela → análise simulada termina → obrigações e resumo
  atualizam sozinhos → "Concluir cadastro".
- AWS, depois do merge com `chatbot-respostas-estruturadas` e do novo deploy: gatilho do e-mail ligado, `matriz-api`
  com as 8 rotas (`/linha-do-tempo` do Gabriel e `/importacoes`), leituras reais 200 com usuário temporário (apagado),
  smoke do cadastro 35/35, 182 testes da API.
- Envio real: a planilha da Ampla enviada pela tela às 09:11 foi processada às 09:17 (o Glue repetiu a etapa Bronze uma
  vez por `ConcurrentRunsExceeded`, o que é esperado: uma execução por vez).

## Pendências
1. **Dashboard:** obrigações, tarefas e normas do dia; aviso de "análise em andamento" e **e-mail quando a análise da
   matriz terminar**; e-mail de alerta de normas (quando os campos do alerta estiverem definidos).
2. **Configurações:** equipe (o componente `Equipe` já existe, exportado no `App.tsx`), editar o nome (`name` no
   Cognito), unidades, áreas e outorgas do perfil (sem unidades, a planilha precisa vir com `aplica_a` vazio).
3. **"Concluir cadastro" na API:** hoje fica só no navegador (`localStorage`, por CNPJ). Para o dashboard saber que o
   cadastro terminou, criar um campo em `perfil.py` (como os `conferido_*`). O mesmo vale para "Pular esta etapa".
4. **Assistente e linha do tempo** do front do Gabriel (`Chatbot.tsx`, `BlocosChat.tsx`, `Matriz.tsx`) no painel, na
   identidade Laudo.
5. **Lovable:** o app precisa estar na raiz de um repositório (hoje está em `front/cadastro-teste/`), a hospedagem
   precisa do fallback de SPA para as rotas, e a URL dela precisa entrar no `AllowedOrigins` das stacks (CORS).
6. `custom:cnpj` no Cognito, para o vínculo conta → CNPJ valer fora do navegador.
7. Logo de verdade no e-mail do código (imagem num endereço público) e remetente próprio (SES).
8. E-mail de convite (hoje o convite não envia e-mail).
