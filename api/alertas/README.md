# Aviso de mudanças (e-mail)

O resumo que cada pessoa recebe por e-mail: o que a IA propõe e espera decisão, as tarefas em risco e o que entrou na
matriz. `src/email_alerta.py` só **monta** o e-mail (assunto, HTML e texto puro), sem dependências além da biblioteca
padrão. Mesma identidade e mesmas regras de HTML de e-mail do código do Cognito (`api/cnpj-cadastro/src/email_cognito.py`).

Não é uma stack SAM: ainda não há Lambda, agendamento nem envio.

## Quando é enviado

Resumo diário às 08:00, um por pessoa que acompanha a empresa, **só quando há algo a avisar**. O envio real depende de
SES com remetente próprio, que ainda não existe (pendência em `front/cadastro-teste/TELAS.md`).

## Entrada

`email_alerta.montar(dados)` devolve `{"assunto", "html", "texto"}` ou **`None` quando não há nada para decidir, nada
aprovado e nenhuma tarefa em risco** (a leitura do DOU sozinha não gera e-mail). Todas as chaves são opcionais; os
nomes seguem os tipos `Obrigacao`, `Tarefa` e `Historico` de `front/cadastro-teste/src/matriz.ts`.

```python
{
  "empresa": "Light SESA",
  "hoje": "2026-11-08",                    # AAAA-MM-DD; padrão = hoje. Base de "atrasada há 1 dia" / "vence em 2 dias"
  "painel_url": "https://…/painel",        # botão "Revisar no painel" e rodapé; sem URL http(s), não há botão
  "alertas_url": "https://…",              # "Ajustar alertas" no rodapé (opcional)
  "leitura": {"atos": 1931, "relevantes": 13, "periodo": "03 a 06/11"},
  "propostas": [                           # Obrigacao com status "proposta" (origem llm)
    {"mudanca": "alteracao",               # inclusao | alteracao | revogacao
     "titulo": "…", "prazo_regra": "…", "area_responsavel": "Comercial",
     "fonte_ato": "REN ANEEL nº 1.174/2026", "fonte_dispositivo": "art. 166-A", "fonte_url": "http://…",
     "data_ato": "2026-11-04", "pagina": "68",          # pagina vem do alerta do DOU (não está na Obrigacao)
     "trecho_citado": "…",                               # cortado em ~240 caracteres
     "alteracoes": [{"campo": "prazo_regra", "antes": "…", "depois": "…"}]}   # de Historico.alteracoes
  ],
  "aprovadas": [                           # mesmos campos + estes
    {"vigente_de": "2026-11-07", "aprovada_por": "Ana Ribeiro", "tarefas_criadas": 1, "tarefas_recalculadas": 0}
  ],
  "tarefas": [                             # Tarefa; pode mandar todas, o módulo filtra
    {"descricao": "…", "vencimento": "2026-11-07", "area_responsavel": "Financeiro", "status": "aberta"}
  ]
}
```

- **Tarefas em risco**: não concluídas e atrasadas ou vencendo em até 3 dias (o mesmo `em_risco` do dash), da mais
  urgente para a menos.
- **Antes → depois**: mostra os campos com rótulo (Prazo, Responsável, Periodicidade…). As mudanças de `fonte_*` ficam
  de fora, porque a linha da fonte já mostra o ato novo.
- **Seções vazias somem.** Ordem: Para decidir, Tarefas em risco (o que pede ação primeiro), Mudanças aprovadas.
- Tudo que vem de dado passa por `html.escape`; link que não for `http(s)` é descartado.
- Laranja só no que pede ação: cartões para decidir, botão e data da tarefa atrasada.

## Preview

```
python api/alertas/preview/gerar_preview.py
```

Gera `preview/aviso-mudancas.html` (abrir no navegador) e `preview/aviso-mudancas.txt` com dados fictícios: REN 1.174
(prazo de migração de 10 para 5 dias úteis) e STF PIS/Cofins para decidir, REN 1.175 (Open Energy) aprovada, PROINFA
atrasada e CDE vencendo em 2 dias, leitura real da semana (1.931 atos, 13 relevantes).

## Testes

```
cd api && uv run pytest alertas
```

## Pendências

- Remetente próprio (SES) e a Lambda agendada (08:00) que junta os dados por empresa e envia para cada membro.
- Endereço público do painel: o preview usa `http://localhost:5173/painel`.
- Tela de "ajustar alertas" (frequência, quem recebe) não existe; o link do rodapé aponta para o painel.
- Logo como imagem (precisa de endereço público), como no e-mail do código.
