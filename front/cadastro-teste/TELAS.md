# Telas de acesso, cadastro e equipe (07/11/2026)

> Estado: **testado de ponta a ponta contra a stack real** (Cognito + API + DynamoDB), na branch `feat/front-kalman`
> (feita a partir do `main` do Gabriel com membros e convites). A lógica e o cliente `src/api.ts` são os do Gabriel;
> mudaram a interface, os textos e o fluxo de conta. O produto é para **qualquer segmento**: energia elétrica é só o caso
> de teste, então nenhum texto fala em "distribuidora".

## Rodar

```bash
make front-dev     # http://localhost:5173 (porta fixa, liberada no CORS)
make front-check   # typecheck
```

O `.env` virou opcional: sem ele, `src/config.ts` usa os valores públicos da stack `cnpj-cadastro` (é o que a Lovable vai
usar). Se a stack for recriada, troque os três valores do `STACK` em `src/config.ts`.

| Endereço | O que abre |
|---|---|
| `/` | Fluxo real, tela **Entrar** |
| `/?criar` | Fluxo real, tela **Criar conta** (é para onde a landing manda) |
| `/?criar&cnpj=33050071000158` | Criar conta com o CNPJ já preenchido e validado |
| `/?demo` | Demonstração sem Cognito (qualquer e-mail e senha; código: 6 dígitos quaisquer) |
| `/?demo=vazio` · `dados` · `membro` · `convite` | Demonstração já logado: antes do CNPJ · dono com equipe · membro (só leitura) · com convite pendente |

O modo demonstração (`src/demo.ts`) só existe em `npm run dev`; o build de produção não o inclui (conferido). Para
tirá-lo do projeto: apagar `demo.ts` e as referências a `demoApi`, `demoAuth`, `demoAtivo`, `demoLogado` e `DEMO_EMAIL`
no `App.tsx`.

## Identidade

Kit **Laudo** copiado sem alteração da branch `identidade-visual` para `src/identidade/` (`tokens.css`, `base.css`,
`componentes.css`, `marca.tsx`), favicon em `public/favicon.svg`. `src/styles.css` só faz layout e as peças destas
telas. Tema só claro, de propósito. Desvio pedido pelo time: botão laranja com **texto branco** (o kit usa grafite;
branco sobre esse laranja dá 3,1:1).

## Telas

### 1. Acesso (tela dividida)
Esquerda grafite (só no PC) com o motivo animado (`src/MotivoAnimado.tsx`) e "Saiba quais normas afetam **a sua
empresa.**". Direita, o formulário (24 rem). No celular, só o formulário.

| Modo | O que tem |
|---|---|
| **Entrar** | E-mail, senha (com olho), "Esqueci a senha", Entrar, "Criar conta". Conta não confirmada → reenvia o código e vai para Confirmar |
| **Criar conta** | CNPJ (máscara + dígitos verificadores, ✓ quando válido), e-mail corporativo, senha com medidor (Fraca/Boa/Forte, mostra o que falta pela regra do Cognito), confirmar senha. Botão só libera com tudo válido |
| **Confirmar e-mail** | Código de 6 dígitos num campo grande; "Reenviar código" com espera de 30 s; "Usar outro e-mail" |
| **Esqueci a senha** | E-mail → "Enviar código" |
| **Crie uma senha nova** | Código + senha nova (com medidor) + confirmar → salva e já entra |

Erros do Cognito traduzidos (senha errada, código errado/expirado, muitas tentativas, conta já existe…).

### 2. Painel (depois de entrar)
Barra fixa: marca, nome da empresa, e-mail, Sair.

- **Convite recebido** (sem empresa e com convite pendente): quem convidou, cartão grafite com razão social e CNPJ,
  validade, **Aceitar convite** / Recusar. O convite é buscado antes de decidir a tela (sem isso a tela do CNPJ piscava).
- **Pedir CNPJ** (sem empresa e sem convite): campo grande com máscara e dígitos. Se a conta foi criada com CNPJ, a
  consulta sai sozinha. CNPJ que já tem dono → "Este CNPJ já foi cadastrado por outra pessoa da empresa. Peça a ela um
  convite para a equipe."
- **Consultando:** "Lendo o CNPJ na Receita" com os segundos.
- **Dados da empresa:** cartão grafite (razão social, CNPJ, CNAE, cidade/UF, ano de início, "Trocar CNPJ" e "O Kalman
  vai ler as normas de *atividade do CNAE* · Diário Oficial e *regulador*"; o regulador só aparece quando o CNAE o deixa
  óbvio: ANEEL, ANP, Anatel, Banco Central, SUSEP, ANS, Anvisa, ANTAQ, ANAC, ANA). Formulário em seções: Responsável,
  Contato, Empresa, Endereço (resumo da Receita + "Corrigir"). Salvar fixo no rodapé.
- **Membro:** os mesmos dados, só leitura (campos em céu claro, sem Salvar, sem Trocar CNPJ, sem Corrigir) e o aviso
  "Você é membro desta empresa: vê os dados, mas só o dono edita."
- **Equipe:** lista com o dono (selo grafite com ponto laranja), membros e convites pendentes (com validade). O dono
  convida pelo e-mail, remove membros e cancela convites; o membro pode sair da empresa. O convite **não envia e-mail**
  (é assim na API): a tela avisa para combinar com a pessoa.

## E-mail do código (Cognito)

Gatilho **CustomMessage** (`api/cnpj-cadastro/src/email_cognito.py`, publicado em 07/11): assunto e HTML na identidade
Laudo para cadastro, reenvio e "esqueci a senha" (textos diferentes). Remetente continua o padrão do Cognito
(`no-reply@verificationemail.com`, limite baixo por dia); remetente próprio exige SES.

## Vínculo da conta com o CNPJ
1. Em **Criar conta**, o CNPJ vai para o `localStorage` (`kalman:cnpj-da-conta`) antes do `signUp`.
2. Depois de confirmar o e-mail e entrar, sem empresa e sem convite, o painel dispara a consulta sozinho.
3. Limite: vale no mesmo navegador. Para valer entre aparelhos, criar `custom:cnpj` no User Pool.

## Teste de ponta a ponta (07/11, stack real)
Criar conta → tela de código (o gatilho do e-mail rodou sem erro) → conta confirmada pela API (o endereço de teste não
recebe e-mail) → entrar → consulta automática do CNPJ → salvar formulário → convidar → entrar como convidado → convite
→ aceitar → modo membro. Usuários e itens de teste apagados no fim. As telas de "esqueci a senha" foram vistas no modo
demo; o envio real do código ainda precisa de uma pessoa com caixa de entrada.

## Pendências
1. Testar com um e-mail de verdade: receber o código (cadastro e esqueci a senha) e ver o e-mail no Gmail/Outlook.
2. CORS: incluir a URL da Lovable em `AllowedOrigins` e publicar (`sam deploy --parameter-overrides ...`).
3. Lovable: o app precisa estar na raiz de um repositório (hoje está em `front/cadastro-teste/`).
4. `custom:cnpj` no Cognito, para o vínculo valer fora do navegador.
5. E-mail de convite e e-mail de alerta de normas (depois do dashboard, quando os campos do alerta estiverem definidos).
