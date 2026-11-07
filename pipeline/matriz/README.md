# matriz: obrigações e tarefas (stack lakehouse-matriz)

Transforma o perfil regulatório da empresa, a matriz de obrigações que ela já tem e as propostas
do LLM (pipeline do DOU) em obrigações versionadas e tarefas com data, na gold do lakehouse.

```
landing/matriz/importada/<cnpj>/*.csv|xlsx  ─┐
landing/matriz/propostas_llm/<data>/*.json  ─┼─> bronze_db.matriz_* ─> silver_db.matriz_* ─> gold_db.matriz_obrigacoes
DynamoDB (CNPJ#*) ─ perfis ─> landing/matriz/perfis/<data>/<cnpj>.json ─┘                     gold_db.matriz_tarefas
API da matriz ─ INSERT (Athena) ─> bronze_db.matriz_decisoes ──────────────────────────────>  gold_db.matriz_versoes
```

## Etapas (`--STAGE`)

| Etapa | O que faz |
|---|---|
| `perfis` | Scan dos itens `CNPJ#*` do DynamoDB; um JSON por CNPJ, sem sócios, membros e convites |
| `bronze` | Lista as três pastas da landing e grava só arquivo novo (anti-join por `_arquivo` + `_hash`). Uma linha por linha do CSV/XLSX, por proposta e por perfil. Arquivo ilegível vira linha com `_erro` |
| `silver` | Último perfil de cada CNPJ, com unidades, áreas e outorgas em tabelas próprias; matriz importada e propostas no schema de `matriz_obrigacoes_candidatas`, validadas. O que falha fica com `valida = false` e `erros` (quarentena), não é descartado |
| `gold` | Replay em ordem de importações, propostas e decisões (`regras_matriz.Matriz`): versões das obrigações, tarefas e histórico. Determinístico: rodar de novo não muda nada |

A gold é recalculada inteira a cada execução e gravada com `overwrite` do PyIceberg. Se a API
gravar uma decisão no meio (commit concorrente), o job lê tudo de novo e recalcula. Os snapshots
do Iceberg guardam as versões anteriores da tabela (`FOR TIMESTAMP AS OF` no Athena).

## Regras (`src/regras_matriz.py`)

Python puro, usado pelo job e pela API (cópia em `api/matriz/src/`, atualizada com
`make sync-regras` e conferida por teste).

`prazo_json` é uma lista de regras:

| `unidade` | `referencia` | `valor` | Exemplo |
|---|---|---|---|
| `data_fixa` | `ano_corrente`, `ano_seguinte_exercicio` | `DD/MM` | DCR até 30/04 do ano seguinte; bienal com `ano_base` |
| `dia_do_mes` | `mes_corrente`, `mes_seguinte` | dia | DCTFWeb dia 15 do mês seguinte |
| `dias_apos` | `fim_mes`, `fim_trimestre`, `fim_semestre` | dias | relatório 60 dias após o trimestre |
| `dias_antes` | `validade_outorga` | dias (opcional) | renovar LO 120 dias antes; `tipo_outorga` filtra |

- Periódicas: ocorrências entre hoje e hoje + 12 meses, uma por unidade de `aplica_a`.
- Ligadas a outorga: uma por outorga do perfil (validade menos a antecedência).
- `por_evento` e `continua`: nenhuma tarefa automática.
- `tarefa_id` = hash de cnpj, obrigação, unidade ou outorga e vencimento: regerar não duplica.
- `em_risco`: faltam 7 dias ou menos e não está concluída, ou a obrigação tem proposta pendente.
- Concluída nunca some; aberta que venceu continua (atrasada) enquanto a versão for a vigente;
  aberta de versão antiga é recalculada na versão nova.

Versões: a matriz importada entra aprovada (nova versão só se o conteúdo mudar); proposta do LLM
entra como `proposta`; a decisão da API aprova (vira vigente; revogação deixa sem vigente) ou
rejeita.

## Comandos

```bash
make -C pipeline matriz-deploy          # envia regras_matriz.py ao S3 e faz sam deploy
make -C pipeline matriz-fixture         # matriz.csv da Aurora em landing/matriz/importada/KALMANTESTE100/
make -C pipeline matriz-run             # dispara a máquina de estados (HOJE=AAAA-MM-DD opcional)
make -C pipeline matriz-proposta-demo   # proposta do DOU que altera a OBR-013 (demo)
make -C pipeline matriz-verify          # últimas execuções
```

Da raiz, os mesmos alvos com o prefixo `pipeline-` (ex.: `make pipeline-matriz-run`).
