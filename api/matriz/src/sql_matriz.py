"""
SQL da API da matriz, para o Athena (Trino) sobre as tabelas Iceberg da gold e da bronze.

O Athena não aceita parâmetros em UPDATE e DELETE, então os valores entram como literais.
Para não abrir espaço para injeção:
  - identificadores (cnpj, obrigacao_id, tarefa_id) passam por regex antes de chegar aqui;
  - enums (status, decisão) são conferidos contra listas fixas;
  - texto livre (comentário, URL de evidência, usuário) passa por `texto()`, que escapa
    aspas e recusa caracteres de controle.

As transições de status são as mesmas do job (regras_matriz.aplicar_decisao).
"""

from __future__ import annotations

import re
from datetime import date, datetime

GOLD_OBRIGACOES = "gold_db.matriz_obrigacoes"
GOLD_TAREFAS = "gold_db.matriz_tarefas"
GOLD_VERSOES = "gold_db.matriz_versoes"
BRONZE_DECISOES = "bronze_db.matriz_decisoes"

CNPJ = re.compile(r"^[0-9A-Z]{12}[0-9]{2}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")
TAREFA_ID = re.compile(r"^[0-9a-f]{16}$")
CONTROLE = re.compile(r"[\x00-\x1f\x7f]")

COLUNAS_OBRIGACAO = (
    "cnpj", "obrigacao_id", "versao", "titulo", "fonte_ato", "fonte_dispositivo", "fonte_url",
    "trecho_citado", "orgao_sigla", "tema", "aplica_a", "recorrencia", "periodicidade", "prazo_regra",
    "prazo_json", "area_responsavel", "evidencia", "criticidade", "origem", "status", "confianca",
    "incluida_em", "alterada_por", "vigente", "mudanca", "proposta_id", "hash_conteudo",
    "decidida_por", "decidida_em", "data_ato", "vigente_de", "vigente_ate",
)
COLUNAS_TAREFA = (
    "cnpj", "tarefa_id", "obrigacao_id", "obrigacao_versao", "unidade_id", "outorga_id", "descricao",
    "vencimento", "area_responsavel", "status", "evidencia_url", "em_risco", "atualizada_em",
)
STATUS_TAREFA = ("aberta", "em_andamento", "concluida")


class ValorInvalido(ValueError):
    pass


# ---------------------------------------------------------------- literais

def ident(valor: str, padrao: re.Pattern = ID) -> str:
    if not isinstance(valor, str) or not padrao.match(valor):
        raise ValorInvalido(f"identificador inválido: {valor!r}")
    return f"'{valor}'"


def texto(valor, max_len: int = 1000) -> str:
    if valor is None:
        return "NULL"
    valor = str(valor)
    if len(valor) > max_len or CONTROLE.search(valor):
        raise ValorInvalido("texto longo demais ou com caractere de controle")
    return "'" + valor.replace("'", "''") + "'"


def inteiro(valor) -> str:
    if valor is None:
        return "NULL"
    if isinstance(valor, bool) or not isinstance(valor, int):
        raise ValorInvalido(f"inteiro inválido: {valor!r}")
    return str(valor)


def booleano(valor: bool) -> str:
    return "true" if valor else "false"


def data(valor) -> str:
    if valor is None:
        return "NULL"
    valor = date.fromisoformat(valor) if isinstance(valor, str) else valor
    return f"DATE '{valor.isoformat()}'"


def momento(valor: datetime | None) -> str:
    if valor is None:
        return "NULL"
    return f"TIMESTAMP '{valor.strftime('%Y-%m-%d %H:%M:%S.%f')}'"


# ---------------------------------------------------------------- leituras

def _select_obrigacoes() -> str:
    cols = [c if c != "aplica_a" else "json_format(CAST(aplica_a AS JSON)) AS aplica_a" for c in COLUNAS_OBRIGACAO]
    return f"SELECT {', '.join(cols)} FROM {GOLD_OBRIGACOES}"


def obrigacoes_atuais(cnpj: str) -> str:
    """Versão vigente de cada obrigação e propostas aguardando decisão."""
    return (f"{_select_obrigacoes()} WHERE cnpj = {ident(cnpj, CNPJ)} "
            f"AND (vigente OR status = 'proposta') ORDER BY obrigacao_id, versao")


def versoes_da_obrigacao(cnpj: str, obrigacao_id: str) -> str:
    return (f"{_select_obrigacoes()} WHERE cnpj = {ident(cnpj, CNPJ)} "
            f"AND obrigacao_id = {ident(obrigacao_id)} ORDER BY versao")


COLUNAS_HISTORICO = (
    "cnpj", "obrigacao_id", "versao", "evento", "status", "origem", "ocorrido_em", "por", "resumo",
    "ato_id", "ato_url", "data_ato", "trecho_citado", "alteracoes",
)


def obrigacoes_em(cnpj: str, dia: date) -> str:
    """Como a matriz estava num dia: a versão em vigor de cada obrigação."""
    return (f"{_select_obrigacoes()} WHERE cnpj = {ident(cnpj, CNPJ)} AND vigente_de <= {data(dia)} "
            f"AND (vigente_ate IS NULL OR vigente_ate > {data(dia)}) ORDER BY obrigacao_id")


def historico_da_obrigacao(cnpj: str, obrigacao_id: str) -> str:
    return (f"SELECT {', '.join(COLUNAS_HISTORICO)} FROM {GOLD_VERSOES} "
            f"WHERE cnpj = {ident(cnpj, CNPJ)} AND obrigacao_id = {ident(obrigacao_id)} ORDER BY ocorrido_em, versao")


def linha_do_tempo(cnpj: str, obrigacao_id: str | None = None, ato_id: str | None = None) -> str:
    """Eventos de todas as obrigações (ou de uma, ou de um ato), do mais recente ao mais antigo,
    com o título da versão a que se referem."""
    filtro = f"h.cnpj = {ident(cnpj, CNPJ)}"
    if obrigacao_id:
        filtro += f" AND h.obrigacao_id = {ident(obrigacao_id)}"
    if ato_id:
        filtro += f" AND h.ato_id = {texto(ato_id, 200)}"
    cols = ", ".join(f"h.{c}" for c in COLUNAS_HISTORICO)
    return (f"SELECT {cols}, o.titulo, o.orgao_sigla FROM {GOLD_VERSOES} h LEFT JOIN {GOLD_OBRIGACOES} o "
            f"ON o.cnpj = h.cnpj AND o.obrigacao_id = h.obrigacao_id AND o.versao = h.versao "
            f"WHERE {filtro} ORDER BY h.ocorrido_em DESC, h.obrigacao_id, h.versao DESC LIMIT 500")


def tarefas(cnpj: str, obrigacao_id: str | None = None, so_em_risco: bool = False) -> str:
    filtro = f"cnpj = {ident(cnpj, CNPJ)}"
    if obrigacao_id:
        filtro += f" AND obrigacao_id = {ident(obrigacao_id)}"
    if so_em_risco:
        filtro += " AND em_risco"
    return f"SELECT {', '.join(COLUNAS_TAREFA)} FROM {GOLD_TAREFAS} WHERE {filtro} ORDER BY vencimento, tarefa_id"


def tarefa(cnpj: str, tarefa_id: str) -> str:
    return (f"SELECT {', '.join(COLUNAS_TAREFA)} FROM {GOLD_TAREFAS} "
            f"WHERE cnpj = {ident(cnpj, CNPJ)} AND tarefa_id = {ident(tarefa_id, TAREFA_ID)}")


# ---------------------------------------------------------------- escritas

def inserir_decisao(d: dict) -> str:
    valores = ", ".join([
        texto(d["decisao_id"], 64), texto(d["tipo"], 20), ident(d["cnpj"], CNPJ),
        ident(d["obrigacao_id"]) if d.get("obrigacao_id") else "NULL",
        inteiro(d.get("versao")),
        ident(d["tarefa_id"], TAREFA_ID) if d.get("tarefa_id") else "NULL",
        texto(d["decisao"], 20), texto(d.get("evidencia_url"), 2000), texto(d.get("usuario"), 200),
        texto(d.get("comentario"), 2000), momento(d["decidida_em"]),
    ])
    return (f"INSERT INTO {BRONZE_DECISOES} (decisao_id, tipo, cnpj, obrigacao_id, versao, tarefa_id, decisao, "
            f"evidencia_url, usuario, comentario, decidida_em) VALUES ({valores})")


def atualizar_versoes(cnpj: str, obrigacao_id: str, antes: list[dict], depois: list[dict]) -> str | None:
    """Um UPDATE com CASE por versão, só nas versões que mudaram (status, vigente, decisão)."""
    chave = lambda v: (v["status"], v["vigente"], v.get("decidida_por"),  # noqa: E731
                       str(v.get("vigente_de") or ""), str(v.get("vigente_ate") or ""))
    mudou = [d for a, d in zip(antes, depois) if chave(a) != chave(d)]
    if not mudou:
        return None
    caso = lambda col, f: "CASE versao " + " ".join(  # noqa: E731
        f"WHEN {inteiro(d['versao'])} THEN {f(d[col])}" for d in mudou) + f" ELSE {col} END"
    sets = ", ".join([
        f"status = {caso('status', lambda v: texto(v, 20))}",
        f"vigente = {caso('vigente', booleano)}",
        f"decidida_por = {caso('decidida_por', lambda v: texto(v, 200))}",
        f"decidida_em = {caso('decidida_em', momento)}",
        f"vigente_de = {caso('vigente_de', data)}",
        f"vigente_ate = {caso('vigente_ate', data)}",
    ])
    versoes = ", ".join(inteiro(d["versao"]) for d in mudou)
    return (f"UPDATE {GOLD_OBRIGACOES} SET {sets} WHERE cnpj = {ident(cnpj, CNPJ)} "
            f"AND obrigacao_id = {ident(obrigacao_id)} AND versao IN ({versoes})")


def inserir_historico(h: dict) -> str:
    valores = ", ".join([
        ident(h["cnpj"], CNPJ), ident(h["obrigacao_id"]), inteiro(h["versao"]), texto(h["evento"], 20),
        texto(h["status"], 20), texto(h.get("origem"), 40), data(h["ocorrido_em"]), texto(h.get("por"), 200),
        texto(h.get("resumo"), 1000), texto(h.get("ato_id"), 200), texto(h.get("ato_url"), 2000),
        data(h.get("data_ato")), texto(h.get("trecho_citado"), 4000), texto(h.get("alteracoes"), 20000),
    ])
    return f"INSERT INTO {GOLD_VERSOES} ({', '.join(COLUNAS_HISTORICO)}) VALUES ({valores})"


def apagar_tarefas_da_obrigacao(cnpj: str, obrigacao_id: str) -> str:
    return f"DELETE FROM {GOLD_TAREFAS} WHERE cnpj = {ident(cnpj, CNPJ)} AND obrigacao_id = {ident(obrigacao_id)}"


def inserir_tarefas(linhas: list[dict]) -> str | None:
    if not linhas:
        return None
    valores = []
    for t in linhas:
        valores.append("(" + ", ".join([
            ident(t["cnpj"], CNPJ), ident(t["tarefa_id"], TAREFA_ID), ident(t["obrigacao_id"]),
            inteiro(t["obrigacao_versao"]),
            ident(t["unidade_id"]) if t.get("unidade_id") else "NULL",
            ident(t["outorga_id"]) if t.get("outorga_id") else "NULL",
            texto(t["descricao"], 1000), data(t["vencimento"]), texto(t.get("area_responsavel"), 50),
            texto(t["status"], 20), texto(t.get("evidencia_url"), 2000), booleano(t["em_risco"]),
            momento(t.get("atualizada_em")),
        ]) + ")")
    return f"INSERT INTO {GOLD_TAREFAS} ({', '.join(COLUNAS_TAREFA)}) VALUES {', '.join(valores)}"


def atualizar_tarefa(cnpj: str, tarefa_id: str, status: str, evidencia_url: str | None, em_risco: bool,
                     agora: datetime) -> str:
    if status not in STATUS_TAREFA:
        raise ValorInvalido(f"status inválido: {status!r}")
    return (f"UPDATE {GOLD_TAREFAS} SET status = {texto(status, 20)}, evidencia_url = {texto(evidencia_url, 2000)}, "
            f"em_risco = {booleano(em_risco)}, atualizada_em = {momento(agora)} "
            f"WHERE cnpj = {ident(cnpj, CNPJ)} AND tarefa_id = {ident(tarefa_id, TAREFA_ID)}")
