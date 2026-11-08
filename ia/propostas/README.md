# ia/propostas: propostas do DOU

Quando o ETL do DOU termina, este passo acha os atos que importam para cada empresa e propõe
mudanças nas obrigações dela. Ele só escreve um arquivo na landing da matriz: o ETL da matriz
valida e versiona, e **nada vale sem a decisão do dono** pela API.

```
ETL do DOU termina ──EventBridge──> Step Functions (stack matriz-propostas)
  0 indexar    atos novos (silver_db.dou_atos) -> trechos por artigo -> Titan v2 -> S3 Vectors (dou-atos-v1)
  1 recuperar  por empresa: uma consulta por obrigação vigente, tema, outorga, atividade e
               o tipo da classificação do cadastro -> atos candidatos (nota = melhor trecho)
  2 triar      Haiku 4.5: o ato muda alguma obrigação DESTA empresa? (motivo vai para o log)
  3 extrair    Sonnet 5: propostas no formato que o ETL da matriz lê
  4 verificar  em código, com as regras do ETL + o trecho citado tem de estar no ato
  5 gravar     landing/matriz/propostas_llm/<dia>/<ato_id>__<cnpj>.json, uma vez só
        └──> ETL da matriz (a cada hora) -> gold com status "proposta" -> dono aprova ou rejeita
```

A busca usa o mesmo bucket de vetores, o mesmo modelo (Titan v2, 1024 dimensões) e a mesma
taxonomia (`pipeline/cadastro/config/tipos_empresa.json`) da classificação das empresas do
cadastro: o tipo da empresa vira consultas a mais. Cada etapa grava eventos em
`audit/propostas/eventos/` (tabela `bronze_db.propostas_eventos`), para medir e melhorar.

## Testar antes do deploy

```bash
make ia-test                    # unitários e o fluxo inteiro pelos handlers, com AWS falsa
make pipeline-test              # inclui o contrato: o ETL da matriz aceita o arquivo gerado
make ia-propostas-classificar   # classificação com o Titan de verdade (lê o DynamoDB, não grava)
make ia-propostas-simular       # dados e modelos de verdade, índice em memória, saída em /tmp
make ia-propostas-validar       # o que a simulação gerou entra válido no ETL da matriz (local)
make ia-propostas-metricas      # cobertura e precisão contra rotulagem/amostra-*/rotulagem.csv
```

`make ia-propostas-build` monta o pacote das Lambdas (precisa do `uv`).

## Deploy (ordem)

Cada stack depende da anterior. Todas usam `confirm_changeset`: confira o changeset antes do `y`.

1. **`make pipeline-cadastro-deploy`** (lakehouse-pipeline). Traz as etapas embeddings e
   classificar, o bucket de vetores e a correção do bronze (só itens de organização), sem a
   qual o ETL do cadastro falha desde 08/11. Envia também os tipos de empresa ao lake.
2. **`make pipeline-kb-deploy`** (lakehouse-kb). Mesmo código que está em produção, agora no repositório.
3. **`make pipeline-matriz-deploy`** e depois **`make pipeline-matriz-run`** (lakehouse-matriz).
   Gera a gold com as colunas que o chatbot usa (`vigente_de`, `ato_id`...) e corrige a perda de
   propostas quando duas empresas recebem proposta do mesmo ato.
4. **`make matriz-deploy`** (matriz-api) e **`make api-deploy`** se o cadastro mudar. Sobrescreve a
   rota `POST /importacoes` e a `CustomMessageFunction` que só existem em produção (combinado).
5. **`make ia-propostas-deploy`** (matriz-propostas). Por último: precisa do bucket de vetores (1)
   e da máquina de estados do DOU.
6. **`make pipeline-cadastro-run`** para a empresa de teste entrar na gold e ser classificada, e
   **`make ia-propostas-run DIAS=14`** para um primeiro disparo manual.

## O que mudou em relação ao que está em produção

- **ETL do cadastro** (fork em produção, feito a partir de `6071f48`): ganhou a correção `43b0552`;
  os tipos de empresa passaram a vir de `config/tipos_empresa.json` (antes o caminho relativo não
  existia no Glue); `S3VectorsStore` passou a pedir a distância (`returnDistance`) e a mandar
  `keys` como lista de textos (as duas chamadas falhariam na primeira execução); a classificação
  deixou de acessar `_client` diretamente.
- **ETL da KB**: o join com a classificação é feito em Python (pelo DuckDB exigia `pytz`), e tipo
  `indefinido` não vai para o documento.
- **`regras_matriz.py`**: propostas são deduplicadas por (CNPJ, id da proposta), não só pelo id.

## Limites conhecidos

- A taxonomia foi calibrada com duas empresas reais (Light e a Aurora de teste). Revisar quando
  houver mais cadastros.
- Sem atos rotulados ainda, as métricas não dizem nada: rotular `rotulagem/amostra-2026-11-08`.
- Prazo único ("em até 12 meses") não tem regra no `prazo_json` do ETL: vai como `por_evento`,
  com o prazo só em texto, e não gera tarefa com data.
