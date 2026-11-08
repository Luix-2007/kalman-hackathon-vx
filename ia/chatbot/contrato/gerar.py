"""
Gera o contrato da resposta do chatbot para quem desenha a tela (front, Lovable):

    schema.json     JSON Schema da resposta de POST /chatbot/mensagens, gerado de blocos.COLUNAS
    exemplos.json   respostas de exemplo da Aurora, geradas pelo próprio código (blocos.montar)
                    a partir de dados fixos: dá para usar como mock do front

    make ia-chatbot-contrato        regera os dois arquivos
    (o teste test_contrato.py falha se eles estiverem diferentes do que o código gera)

Os exemplos são a forma exata do campo `blocos`; o `resposta` é um resumo ilustrativo (na
resposta real quem escreve é o modelo).
"""

import json
import sys
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI.parent))
sys.path.insert(0, str(AQUI.parent / "evals"))

import blocos  # noqa: E402
import dados_fixture as fx  # noqa: E402

TIPO_JSON = {
    "t": {"type": ["string", "null"]},
    "u": {"type": ["string", "null"], "description": "link http(s); o front só deve abrir links http(s)"},
    "b": {"type": ["boolean", "null"]},
    "i": {"type": ["integer", "null"]},
    "l": {"type": ["array", "null"], "items": {"type": "string"}},
    "a": {"type": ["array", "null"], "items": {
        "type": "object", "additionalProperties": False, "required": ["campo", "antes", "depois"],
        "properties": {"campo": {"type": "string"}, "antes": {"type": ["string", "null"]}, "depois": {"type": ["string", "null"]}}}},
}

DESCRICAO = {
    "empresa": "Dados da empresa (1 item)",
    "atos": "Atos do DOU sobre a empresa, do mais recente ao mais antigo",
    "obrigacoes": "Versão em vigor de cada obrigação e propostas aguardando decisão",
    "tarefas": "Tarefas com vencimento; parametros.em_risco = true quando só as em risco",
    "linha_do_tempo": "O que cada ato mudou, do mais recente ao mais antigo; alteracoes traz o antes e o depois",
    "versoes": "Todas as versões de uma obrigação (parametros.obrigacao_id), com o período em vigor",
}


def schema() -> dict:
    def bloco(tipo):
        itens = {"type": "object", "additionalProperties": False, "required": list(blocos.COLUNAS[tipo]),
                 "properties": {c: TIPO_JSON[t] for c, t in blocos.COLUNAS[tipo].items()}}
        return {"type": "object", "additionalProperties": False, "required": ["tipo", "parametros", "itens"],
                "description": DESCRICAO[tipo],
                "properties": {"tipo": {"const": tipo},
                               "parametros": {"type": "object", "properties": {
                                   "em_risco": {"type": "boolean"}, "obrigacao_id": {"type": "string"}}},
                               "itens": {"type": "array", "maxItems": blocos.MAX_ITENS, "items": itens}}}

    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "title": "Resposta de POST /chatbot/mensagens",
        "description": "resposta é um resumo curto escrito pelo modelo (texto puro: nunca renderize como HTML); "
                       "blocos são os dados que a tela desenha, montados em código a partir das consultas. "
                       "Pode vir sem blocos (recusa, pergunta sem dado, conversa).",
        "type": "object", "additionalProperties": False, "required": ["resposta", "blocos"],
        "properties": {"resposta": {"type": "string"},
                       "blocos": {"type": "array", "maxItems": 8, "items": {"oneOf": [bloco(t) for t in blocos.TIPOS]}}},
    }


def exemplos() -> dict:
    obrig = fx.OBRIGACOES
    cenarios = {
        "tarefas_em_risco": {
            "pergunta": "Quais tarefas estão em risco?",
            "resposta": "Há 2 tarefas em risco. A mais urgente é a renovação da Licença de Operação, que vence em 10/11/2026.",
            "blocos": [blocos.montar("tarefas", {"em_risco": True}, [t for t in fx.TAREFAS if t["em_risco"] == "true"])],
        },
        "quem_mudou_a_obr013": {
            "pergunta": "Quem mudou o prazo da OBR-013 e para quando?",
            "resposta": "O ato dou-2026-11-07-s1-000013 propôs antecipar a entrega das DCR de 30/04 para 31/03. A mudança ainda aguarda decisão.",
            "blocos": [blocos.montar("linha_do_tempo", {"obrigacao_id": "OBR-013"}, fx.LINHA_DO_TEMPO[:2])],
        },
        "obrigacoes_da_empresa": {
            "pergunta": "Quais são as minhas obrigações da ANEEL?",
            "resposta": "A empresa tem 3 obrigações vigentes ligadas à ANEEL e 1 proposta de mudança aguardando decisão.",
            "blocos": [blocos.montar("obrigacoes_da_empresa", {}, [o for o in obrig if o["orgao_sigla"] == "ANEEL"])],
        },
        "versoes_de_uma_obrigacao": {
            "pergunta": "Mostre as versões da OBR-013.",
            "resposta": "A OBR-013 tem 2 versões: a 1 está em vigor e a 2 é uma proposta que antecipa o prazo para 31/03.",
            "blocos": [blocos.montar("obrigacao_detalhe", {"obrigacao_id": "OBR-013"},
                                     [dict(o, fonte_ato="", fonte_dispositivo="", trecho_citado="", evidencia="", aplica_a='["UN-01"]')
                                      for o in obrig if o["obrigacao_id"] == "OBR-013"])],
        },
        "atos_do_dou": {
            "pergunta": "Quais atos do DOU saíram sobre a minha empresa?",
            "resposta": "Há 2 atos recentes: uma resolução da ANEEL sobre prazos contábeis e uma portaria do MTE sobre a NR-10.",
            "blocos": [blocos.montar("atos_no_dou", {}, fx.ATOS)],
        },
        "empresa_e_tarefas": {
            "pergunta": "Resuma a situação da minha empresa e o que vence primeiro.",
            "resposta": "A Aurora Energia está ativa. O que vence primeiro é a renovação da Licença de Operação, em 10/11/2026.",
            "blocos": [blocos.montar("painel_da_empresa", {}, fx.PAINEL), blocos.montar("tarefas", {}, fx.TAREFAS[:2])],
        },
        "sem_blocos": {
            "pergunta": "Me passa uma receita de bolo.",
            "resposta": "Só posso ajudar com a sua empresa, os atos do DOU e a matriz de obrigações.",
            "blocos": [],
        },
    }
    return {nome: {"pergunta": c["pergunta"], "resposta": {"resposta": c["resposta"], "blocos": [b for b in c["blocos"] if b]}}
            for nome, c in cenarios.items()}


def serializar(obj) -> str:
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def main():
    (AQUI / "schema.json").write_text(serializar(schema()), encoding="utf-8")
    (AQUI / "exemplos.json").write_text(serializar(exemplos()), encoding="utf-8")
    print("contrato/schema.json e contrato/exemplos.json gerados")


if __name__ == "__main__":
    main()
