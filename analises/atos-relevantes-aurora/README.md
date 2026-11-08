# Atos do DOU relevantes para a Aurora Energia

Análise avulsa para **revisão humana**: quais atos do Diário Oficial da União importam para a empresa de teste Aurora Energia (`KALMANTESTE100`), segundo o perfil regulatório dela. Não muda nada no projeto: só lê o perfil (um `GetItem` no DynamoDB) e os atos (`SELECT` em `silver_db.dou_atos`).

**Estado: semi-pronto.** Os critérios e o script estão prontos e testados com atos de exemplo. Ainda não rodei sobre o DOU de verdade porque as credenciais AWS expiraram. A ideia é comparar com o resultado do colega quando a parte dele ficar pronta.

## Arquivos

| Arquivo | O que é |
|---|---|
| `criterios.json` | as regras, derivadas do perfil (`api/cnpj-cadastro/tests/aurora_dados.json`) e dos CNAEs da fixture. Edite aqui, não no script |
| `gerar_dataset.py` | busca os atos, classifica e gera os CSVs; também compara com outro CSV |
| `saida/` | resultado (fora do git, ver `.gitignore`) |

## Como rodar

Da raiz do repositório, com credenciais AWS válidas (`aws login`):

```bash
uv run --with boto3 python analises/atos-relevantes-aurora/gerar_dataset.py
```

O script avisa se o perfil gravado hoje no DynamoDB for diferente do que gerou os critérios (setor, UFs, órgãos, temas, outorgas). Nesse caso, revise o `criterios.json` antes de confiar no resultado.

Saída em `saida/`:

- `atos_relevantes.csv`: um ato por linha, do mais relevante para o menos. As colunas `revisao` (sim / nao / talvez) e `comentario` ficam vazias para quem revisa. `motivo` diz qual regra colocou o ato ali, e `trecho` mostra onde o termo aparece.
- `descartados.csv`: atos que passaram no pré-filtro mas saíram (fora de escopo, órgão genérico sem tema). Vale olhar por amostragem para achar falso negativo.
- `resumo.md`: perfil usado, período e contagens por nível, órgão e tema.

## Como classifica

| Nível | Regra |
|---|---|
| `direto` | cita a empresa, o CNPJ ou o número de uma outorga dela |
| `alto` | órgão do perfil (ANEEL, MTE, RFB; MME e ANA inferidos) e um tema de interesse |
| `medio` | tema de interesse sem órgão do perfil |
| `baixo` | só o órgão, e apenas para a ANEEL (RFB e MTE publicam muito ato genérico) |
| descartado | fora de escopo (telecom, petróleo e gás) sem órgão do perfil e só com o tema genérico `setor_eletrico`, ou órgão genérico sem tema |

Os termos são comparados sem acento, em minúsculas e com limite de palavra. Assim "NR-10" não casa com "NR-100", e "Dec." de decreto não vira indicador DEC.

CETESB, SP Águas e Bombeiros (CBPMESP) estão no perfil, mas são estaduais e não publicam no DOU. ONS e CCEE não são órgãos públicos e só aparecem citados no texto.

## Comparar com o dataset do colega

Depois de gerar o nosso, passe o CSV dele, com a coluna que identifica o ato (o `id` de `silver_db.dou_atos`) e, se houver, a coluna de nível ou rótulo:

```bash
uv run python analises/atos-relevantes-aurora/gerar_dataset.py --comparar caminho/dele.csv --chave-outro id --nivel-outro nivel
```

O script mostra quantos atos estão nos dois, só no nosso ou só no dele, a concordância (Jaccard) e, nos atos em comum, quantos têm o mesmo nível. O detalhe ato a ato vai para `saida/comparacao.csv`.

## Pendências

- Rodar sobre o DOU real e conferir o período que existe em `silver_db.dou_atos`.
- O pré-filtro em SQL (`translate` + `regexp_like`) não foi executado no Athena ainda.
- Revisar os termos de `criterios.json` com quem conhece o setor, principalmente os marcados `"origem": "inferido"`.
- Combinar com o colega o formato do CSV dele (nome da coluna do id do ato) para a comparação.
