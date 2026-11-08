"""
O contrato da resposta do chatbot (ia/chatbot/contrato): os arquivos que o front usa batem com o
que o código gera, os exemplos validam contra o schema e o schema barra o que não deve passar.
"""

import copy
import json
import sys
from pathlib import Path

import pytest
from jsonschema import Draft202012Validator

CONTRATO = Path(__file__).parents[1] / "contrato"
sys.path.insert(0, str(CONTRATO))
sys.path.insert(0, str(CONTRATO.parent))

import blocos  # noqa: E402
import gerar  # noqa: E402


@pytest.fixture(scope="module")
def schema():
    return json.loads((CONTRATO / "schema.json").read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def exemplos():
    return json.loads((CONTRATO / "exemplos.json").read_text(encoding="utf-8"))


def test_arquivos_do_contrato_estao_atualizados():
    for nome, gerado in (("schema.json", gerar.schema()), ("exemplos.json", gerar.exemplos())):
        atual = (CONTRATO / nome).read_text(encoding="utf-8")
        assert atual == gerar.serializar(gerado), f"{nome} desatualizado: rode make ia-chatbot-contrato"


def test_schema_e_valido_e_cobre_todos_os_tipos(schema):
    Draft202012Validator.check_schema(schema)
    tipos = [b["properties"]["tipo"]["const"] for b in schema["properties"]["blocos"]["items"]["oneOf"]]
    assert tipos == list(blocos.TIPOS)


def test_exemplos_validam_contra_o_schema(schema, exemplos):
    validador = Draft202012Validator(schema)
    assert len(exemplos) >= 6
    for nome, caso in exemplos.items():
        erros = [e.message for e in validador.iter_errors(caso["resposta"])]
        assert erros == [], (nome, erros)


def test_todos_os_tipos_de_bloco_aparecem_nos_exemplos(exemplos):
    usados = {b["tipo"] for c in exemplos.values() for b in c["resposta"]["blocos"]}
    assert usados == set(blocos.TIPOS)
    assert any(not c["resposta"]["blocos"] for c in exemplos.values())      # recusa: resposta sem blocos


def test_o_que_a_lambda_aceita_valida_no_schema(schema, exemplos):
    """blocos.validos (a Lambda) não descarta nenhum bloco dos exemplos: a forma é a mesma."""
    for nome, caso in exemplos.items():
        assert blocos.validos(caso["resposta"]["blocos"]) == caso["resposta"]["blocos"], nome


def alterar(exemplos, fn):
    r = copy.deepcopy(exemplos["tarefas_em_risco"]["resposta"])
    fn(r)
    return r


@pytest.mark.parametrize("mudanca", [
    lambda r: r.pop("blocos"),
    lambda r: r.pop("resposta"),
    lambda r: r.update(extra="x"),
    lambda r: r["blocos"][0].update(tipo="inventado"),
    lambda r: r["blocos"][0]["itens"][0].update(campo_novo="x"),
    lambda r: r["blocos"][0]["itens"][0].update(em_risco="sim"),
    lambda r: r["blocos"][0]["itens"][0].update(obrigacao_versao="1"),
    lambda r: r["blocos"][0]["itens"][0].pop("vencimento"),
    lambda r: r["blocos"][0]["itens"][0].update(decidida_por="sub-secreto"),
    lambda r: r["blocos"][0].update(itens=[r["blocos"][0]["itens"][0]] * (blocos.MAX_ITENS + 1)),
], ids=["sem_blocos", "sem_resposta", "campo_extra", "tipo_desconhecido", "coluna_nova", "booleano_errado",
        "inteiro_errado", "falta_coluna", "dado_pessoal", "itens_demais"])
def test_o_schema_barra_o_que_nao_deve_passar(schema, exemplos, mudanca):
    erros = list(Draft202012Validator(schema).iter_errors(alterar(exemplos, mudanca)))
    assert erros


# ---------------------------------------------------------------- os tipos do front seguem o contrato

FRONT = Path(__file__).parents[3] / "front" / "cadastro-teste" / "src" / "chatbot.ts"
TIPO_TS = {"empresa": "Empresa", "atos": "Ato", "obrigacoes": "Obrigacao", "tarefas": "Tarefa",
           "linha_do_tempo": "EventoDaLinhaDoTempo", "versoes": "Versao"}


def campos_do_tipo_ts(nome: str) -> list[str]:
    import re
    fonte = FRONT.read_text(encoding="utf-8")
    m = re.search(rf"export type {nome} = \{{(.*?)\n\}};", fonte, re.S)
    assert m, f"tipo {nome} não encontrado em chatbot.ts"
    return re.findall(r"^\s+(\w+)\??:", m.group(1), re.M)


@pytest.mark.parametrize("tipo", blocos.TIPOS)
def test_tipo_do_front_tem_os_mesmos_campos_do_bloco(tipo):
    assert campos_do_tipo_ts(TIPO_TS[tipo]) == list(blocos.COLUNAS[tipo])


def test_o_front_conhece_todos_os_tipos_de_bloco():
    import re
    fonte = FRONT.read_text(encoding="utf-8")
    assert re.findall(r'\{ tipo: "(\w+)"; parametros', fonte) == list(blocos.TIPOS)
