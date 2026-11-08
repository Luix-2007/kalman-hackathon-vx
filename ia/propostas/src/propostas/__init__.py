"""
Propostas do DOU: acha os atos que importam para cada empresa e propõe mudanças nas obrigações.

    0 indexar    atos novos do silver_db.dou_atos -> trechos -> Titan v2 -> S3 Vectors (dou-atos-v1)
    1 recuperar  por empresa: consultas (obrigações vigentes, temas, outorgas, atividade e o tipo
                 da classificação do cadastro) -> trechos mais próximos -> atos candidatos
    2 triar      modelo barato: o ato é relevante para a empresa? (JSON estruturado)
    3 extrair    modelo forte: propostas no formato que o ETL da matriz lê
    4 verificar  em código, com as mesmas regras do ETL: o que falhar vai para a auditoria
    5 gravar     landing/matriz/propostas_llm/<data>/<ato_id>__<cnpj>.json, uma vez só

O resto já existe: o ETL da matriz valida, versiona e põe a proposta como "proposta"; o dono
aprova ou rejeita pela API. Nada passa a valer sem ele. Cada etapa grava eventos em
audit/propostas/eventos/ (tabela bronze_db.propostas_eventos), base para medir e melhorar.
"""
