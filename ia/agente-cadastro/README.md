# Agente de IA — Bedrock AgentCore

Assistente conversacional sobre as empresas cadastradas no sistema.
Responde perguntas em linguagem natural, consulta dados em tempo real no Athena
e lembra do histórico de cada usuário entre sessões.

---

## O que o agente faz

Você manda uma pergunta, ele responde com dados reais do lake:

```
"Qual a situação da empresa cadastrada pelo usuário abc123?"
→ Razão social, CNPJ, situação na Receita, capital social, sócios e publicações recentes no DOU.

"Essa empresa teve alguma resolução da ANEEL nos últimos meses?"
→ Busca nos atos do DOU que citam a empresa.

"Me dá um resumo geral dessa empresa."
→ Cruza dados do cadastro com documentos da Knowledge Base.
```

### Ferramentas disponíveis para o agente

| Ferramenta | O que faz |
|---|---|
| `consultar_empresa` | Consulta Athena: cadastro (`gold_db.empresas_clientes`) + atos no DOU (`vw_empresas_atos`) |
| `buscar_documentos` | Busca semântica na Bedrock Knowledge Base (documentos `.md` gerados pelo pipeline) |

### Memória

- **Dentro da sessão** — o agente lembra tudo que foi dito na conversa atual.
- **Entre sessões** — o AgentCore Memory guarda fatos e resumos por usuário. Na próxima conversa o agente já sabe o contexto anterior.

---

## Pré-requisitos

Confirme que estes stacks já estão implantados na conta `520499255485` (`us-east-1`):

| Stack | O que cria |
|---|---|
| `lakehouse-pipeline` | Bucket do lake, tabelas Gold, workgroup do Athena |
| `lakehouse-dou` | Tabelas do DOU (necessário para `vw_empresas_atos`) |
| `lakehouse-kb` | Bedrock Knowledge Base com os documentos das empresas |

Para verificar:
```bash
aws cloudformation describe-stacks --stack-name lakehouse-pipeline --region us-east-1 --query "Stacks[0].StackStatus"
aws cloudformation describe-stacks --stack-name lakehouse-kb        --region us-east-1 --query "Stacks[0].StackStatus"
```
Ambos devem retornar `"UPDATE_COMPLETE"` ou `"CREATE_COMPLETE"`.

### Ferramentas locais necessárias

- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) configurado com credenciais da conta
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html)
- [Docker](https://docs.docker.com/get-docker/) (só para o `make ia-build`)
- Python 3.8+

---

## Deploy — passo a passo

O deploy é feito em **3 fases** porque o AgentCore Runtime precisa da imagem Docker
já no ECR antes de ser criado.

### Fase 1 — criar repositório ECR e Memory (sem Docker)

```bash
make ia-bootstrap
```

Cria o repositório ECR e a AgentCore Memory com estratégias `SemanticMemory` e `SummaryMemory`.

> Não precisa de Docker. Leva ~2 minutos.

### Fase 2 — construir e enviar a imagem Docker

```bash
make ia-build
```

Constrói a imagem do agente para `linux/arm64` e faz push para o ECR.

> Precisa do Docker rodando. Leva ~5 minutos na primeira vez.

### Fase 3 — deploy completo com o Runtime

```bash
make ia-deploy
```

Cria o AgentCore Runtime e o endpoint padrão.

---

### Atalho: tudo de uma vez

```bash
make ia-install-all
```

Executa as 3 fases em sequência.

---

## Invocar o agente

### Via Makefile (linha de comando)

```bash
# Pergunta simples
make ia-invoke PROMPT="Quais empresas estão com situação ativa?"

# Com user_id (filtra os dados para aquele usuário)
make ia-invoke PROMPT="Qual a situação da minha empresa?" USER_ID="abc123"
```

### Via Python (para integrar no backend)

```python
import json
import uuid
import boto3

client = boto3.client("bedrock-agentcore", region_name="us-east-1")

# Pegue o RuntimeArn no output do stack ia-agente:
# aws cloudformation describe-stacks --stack-name ia-agente \
#   --query "Stacks[0].Outputs[?OutputKey=='RuntimeArn'].OutputValue" --output text
RUNTIME_ARN = "<RuntimeArn do output do stack ia-agente>"

resposta = client.invoke_agent_runtime(
    agentRuntimeArn=RUNTIME_ARN,
    runtimeSessionId=str(uuid.uuid4()),   # novo ID = nova sessão; mesmo ID = continua a conversa
    payload=json.dumps({
        "prompt":     "Qual a situação da minha empresa?",
        "user_id":    "abc123",            # user_id do cadastro (filtra os dados)
        "session_id": "sessao-xyz-001",    # mesmo valor entre chamadas = memória de sessão
    }).encode(),
    qualifier="DEFAULT",
)

resultado = json.loads(resposta["response"].read())
print(resultado["resposta"])
```

### Payload de entrada

| Campo | Tipo | Obrigatório | Descrição |
|---|---|---|---|
| `prompt` | string | **Sim** | Pergunta em linguagem natural |
| `user_id` | string | Recomendado | ID do usuário no cadastro; filtra os dados para ele |
| `session_id` | string | Recomendado | ID da sessão; mantém o histórico da conversa |

### Resposta

```json
{
  "resposta": "A empresa Banco do Brasil S.A. (CNPJ 00.000.000/0001-91) está com situação ATIVA...",
  "user_id": "abc123"
}
```

---

## Testar localmente (sem deploy na AWS)

```bash
# 1. Sobe o container na porta 8080
make ia-run-local

# 2. Em outro terminal, manda uma requisição
curl -s http://localhost:8080 \
  -H "Content-Type: application/json" \
  -d '{"prompt": "Olá, quais dados você tem acesso?", "user_id": "teste"}' | python3 -m json.tool
```

> O container usa suas credenciais AWS locais (`~/.aws`), então as consultas Athena e KB são reais.

---

## Atualizar o agente

Se você alterar o código em `ia/src/agent.py`:

```bash
make ia-build    # reconstrói e faz push da imagem
make ia-deploy   # atualiza o Runtime com a nova imagem
```

---

## Arquitetura resumida

```
Usuário / Front
    │
    └── InvokeAgentRuntime (boto3 / api/agente-chat)
              │
              ▼
    AgentCore Runtime  (container ARM64, porta 8080)
    ┌─────────────────────────────────────────────┐
    │  Strands Agent  (Claude Sonnet 3.5 v2)      │
    │                                              │
    │  tool: consultar_empresa                     │
    │    └─ Athena → gold_db.empresas_clientes     │
    │               gold_db.vw_empresas_atos       │
    │                                              │
    │  tool: buscar_documentos                     │
    │    └─ Bedrock KB → kb_docs/empresas/         │
    └─────────────────────────────────────────────┘
              │
              ▼
    AgentCore Memory  (por actorId = user_id)
        SemanticMemory  — fatos sobre as empresas
        SummaryMemory   — resumo das conversas
```

---

## Recursos criados na AWS

Stack CloudFormation: **`ia-agente`** — conta `520499255485`, região `us-east-1`.

| Recurso | Nome | Descrição |
|---|---|---|
| ECR Repository | `ia-agente-agent` | Imagem Docker do agente |
| AgentCore Memory | `ia-agente_mem` | Memória persistente por usuário |
| AgentCore Runtime | `ia-agente_runtime` | Executa o agente em microVM ARM64 |
| AgentCore Endpoint | `ia-agente_ep` | Ponto de entrada para `InvokeAgentRuntime` |
| IAM Role (Runtime) | — | Permissões: Bedrock, Athena, S3, Glue, Memory |
| IAM Role (Memory) | — | Permissões: Bedrock (extração de memórias) |

---

## Dados que o agente acessa

Somente leitura nas camadas **Silver** e **Gold**. Nunca grava no lake.
Detalhes completos em [`docs/ACESSO-AOS-DADOS.md`](../docs/ACESSO-AOS-DADOS.md).

| Tabela | Descrição |
|---|---|
| `gold_db.empresas_clientes` | Uma linha por empresa: CNPJ, situação, capital, sócios |
| `gold_db.vw_empresas_atos` | Atos do DOU que citam cada empresa |
| Bedrock KB | Documentos `.md` gerados pelo pipeline, um por empresa |

> **Privacidade (LGPD):** o agente não expõe nomes de sócios individualmente.

---

## Problemas comuns

**`Stack lakehouse-kb não encontrado`**
→ Faça o deploy da Knowledge Base primeiro: `make kb-deploy` na raiz do projeto.

**`ECR não encontrado` ao rodar `make ia-build`**
→ Rode `make ia-bootstrap` antes para criar o repositório ECR.

**`AccessDeniedException` no Bedrock**
→ Verifique se o modelo `anthropic.claude-3-5-sonnet-20241022-v2:0` está habilitado
  no console do Bedrock em `us-east-1` → Model Access.

**`No output location provided` no Athena**
→ O workgroup correto é `lakehouse-pipeline-lakehouse`, não o `primary`.
  O agente já usa o correto por padrão.

**Agente não lembra da conversa anterior**
→ Use o mesmo `session_id` entre as chamadas. Sessões diferentes não compartilham histórico.
