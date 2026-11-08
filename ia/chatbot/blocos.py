"""
Blocos de dados da resposta do agente.

O modelo não escreve tabelas nem listas: ele escreve um resumo curto, e o que a tela desenha
vem daqui. Cada ferramenta que devolve linhas do Athena gera um bloco tipado, montado em código
a partir do que a própria ferramenta devolveu. Vantagens:
  - o formato é sempre o mesmo, não depende do humor do modelo;
  - o modelo não pode transcrever errado uma data, um id ou um prazo (os campos vêm da consulta);
  - só entra aqui o que a ferramenta já devolveu para a empresa da sessão (CNPJ fixado).

    bloco = {"tipo": "tarefas", "parametros": {"em_risco": true}, "itens": [{...}, ...]}

`normalizar(tipo, linhas)` converte o texto do Athena em tipos de verdade (bool, int, listas),
troca "" por None, mantém só as colunas conhecidas e aceita link só http(s).
"""

from __future__ import annotations

import json

TIPOS = ("empresa", "atos", "obrigacoes", "tarefas", "linha_do_tempo", "versoes")

# ferramenta -> tipo de bloco (atualizacao_dos_dados não gera bloco: o resumo basta)
TIPO_DA_FERRAMENTA = {
    "painel_da_empresa": "empresa",
    "atos_no_dou": "atos",
    "obrigacoes_da_empresa": "obrigacoes",
    "tarefas": "tarefas",
    "linha_do_tempo": "linha_do_tempo",
    "obrigacao_detalhe": "versoes",
}

# parâmetros da ferramenta que valem a pena mostrar (o limite não)
PARAMETROS_VISIVEIS = ("em_risco", "obrigacao_id")

# coluna -> tipo ("t" texto, "b" booleano, "i" inteiro, "l" lista JSON de textos, "a" alterações, "u" link)
COLUNAS = {
    "empresa": {"cnpj": "t", "razao_social": "t", "situacao_cadastral": "t", "status_cadastro": "t",
                "capital_social": "t", "qtd_socios": "i", "atos_no_dou": "i", "tipos_de_ato": "i",
                "ato_mais_recente": "t"},
    "atos": {"data_publicacao": "t", "tipo": "t", "orgao": "t", "identifica": "t", "ementa": "t", "url_pdf": "u"},
    "obrigacoes": {"obrigacao_id": "t", "versao": "i", "titulo": "t", "orgao_sigla": "t", "tema": "t",
                   "recorrencia": "t", "periodicidade": "t", "prazo_regra": "t", "area_responsavel": "t",
                   "criticidade": "t", "status": "t", "vigente": "b", "data_ato": "t", "vigente_de": "t",
                   "vigente_ate": "t"},
    "tarefas": {"descricao": "t", "vencimento": "t", "status": "t", "em_risco": "b", "area_responsavel": "t",
                "obrigacao_id": "t", "obrigacao_versao": "i"},
    "linha_do_tempo": {"ocorrido_em": "t", "obrigacao_id": "t", "titulo": "t", "versao": "i", "evento": "t",
                       "resumo": "t", "ato_id": "t", "data_ato": "t", "trecho_citado": "t", "alteracoes": "a"},
    "versoes": {"obrigacao_id": "t", "versao": "i", "titulo": "t", "status": "t", "vigente": "b",
                "vigente_de": "t", "vigente_ate": "t", "orgao_sigla": "t", "fonte_ato": "t",
                "fonte_dispositivo": "t", "data_ato": "t", "trecho_citado": "t",
                "prazo_regra": "t", "area_responsavel": "t", "evidencia": "t", "criticidade": "t",
                "aplica_a": "l"},
}

MAX_ITENS = 50
MAX_TEXTO = 1500


def _texto(v):
    if v is None:
        return None
    v = str(v).strip()
    return v[:MAX_TEXTO] if v else None


def _bool(v):
    if isinstance(v, bool):
        return v
    v = _texto(v)
    return None if v is None else v.lower() == "true"


def _int(v):
    try:
        return int(str(v).strip())
    except (TypeError, ValueError):
        return None


def _json(v):
    if v is None or isinstance(v, (list, dict)):
        return v
    try:
        return json.loads(v) if str(v).strip() else None
    except ValueError:
        return None


def _lista(v):
    itens = _json(v)
    if not isinstance(itens, list):
        return None
    return [str(i)[:200] for i in itens if isinstance(i, (str, int, float))][:50] or None


def _alteracoes(v):
    """[{"campo", "antes", "depois"}], só com valores simples."""
    itens = _json(v)
    if not isinstance(itens, list):
        return None
    saida = []
    for i in itens:
        if isinstance(i, dict) and isinstance(i.get("campo"), str):
            saida.append({"campo": i["campo"][:60], "antes": _escalar(i.get("antes")), "depois": _escalar(i.get("depois"))})
    return saida[:30] or None


def _escalar(v):
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)[:MAX_TEXTO]
    return None if v is None else str(v)[:MAX_TEXTO]


def _link(v):
    v = _texto(v)
    return v if v and v.lower().startswith(("http://", "https://")) else None


CONVERSORES = {"t": _texto, "b": _bool, "i": _int, "l": _lista, "a": _alteracoes, "u": _link}


def eh_erro(linhas) -> bool:
    return not isinstance(linhas, list) or (len(linhas) == 1 and isinstance(linhas[0], dict) and "erro" in linhas[0])


def normalizar(tipo: str, linhas: list[dict]) -> list[dict]:
    """Itens do bloco. Linha sem nenhum valor conhecido é descartada."""
    colunas = COLUNAS[tipo]
    itens = []
    for linha in linhas[:MAX_ITENS]:
        if not isinstance(linha, dict):
            continue
        item = {c: CONVERSORES[t](linha.get(c)) for c, t in colunas.items()}
        if any(v is not None for v in item.values()):
            itens.append(item)
    return itens


def montar(ferramenta: str, parametros: dict, linhas) -> dict | None:
    """Bloco da chamada de uma ferramenta, ou None (ferramenta sem bloco, erro, ou sem dados)."""
    tipo = TIPO_DA_FERRAMENTA.get(ferramenta)
    if tipo is None or eh_erro(linhas):
        return None
    itens = normalizar(tipo, linhas)
    if not itens:
        return None
    visiveis = {k: v for k, v in (parametros or {}).items() if k in PARAMETROS_VISIVEIS and v not in (None, "", False)}
    return {"tipo": tipo, "parametros": visiveis, "itens": itens}


def validos(blocos) -> list[dict]:
    """Confere a forma de blocos vindos de fora (a Lambda não confia cegamente no agente)."""
    if not isinstance(blocos, list):
        return []
    saida = []
    for b in blocos[:8]:
        if not (isinstance(b, dict) and b.get("tipo") in TIPOS and isinstance(b.get("itens"), list)):
            continue
        parametros = b.get("parametros") if isinstance(b.get("parametros"), dict) else {}
        itens = [i for i in b["itens"][:MAX_ITENS] if isinstance(i, dict)
                 and all(isinstance(v, (str, int, float, bool, list, type(None))) for v in i.values())]
        if itens:
            saida.append({"tipo": b["tipo"],
                          "parametros": {k: v for k, v in parametros.items() if isinstance(v, (str, bool))},
                          "itens": itens})
    return saida
