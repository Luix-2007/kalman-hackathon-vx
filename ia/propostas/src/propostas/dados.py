"""Leitura do lake pelo Athena: atos do DOU, perfis da matriz, obrigações vigentes e a classificação."""

from __future__ import annotations

import json

from .athena import Athena, ErroConsulta, TabelaInexistente

COLUNAS_ATO = ("id, CAST(data_publicacao AS VARCHAR) AS data_publicacao, tipo, orgao, identifica, ementa, "
               "url_pdf, texto")


def _lista(valor) -> list:
    if valor in (None, ""):
        return []
    try:
        v = json.loads(valor)
    except ValueError:
        return []
    return v if isinstance(v, list) else []


def atos_desde(athena: Athena, desde: str) -> list[dict]:
    return athena.consultar(f"SELECT {COLUNAS_ATO} FROM silver_db.dou_atos "
                            "WHERE data_publicacao >= CAST(? AS DATE) ORDER BY data_publicacao, id", [desde])


def ato(athena: Athena, ato_id: str) -> dict | None:
    linhas = athena.consultar(f"SELECT {COLUNAS_ATO} FROM silver_db.dou_atos WHERE id = ? LIMIT 1", [ato_id])
    return linhas[0] if linhas else None


def _opcional(athena: Athena, sql: str) -> list[dict]:
    """Tabela ou coluna que pode ainda não existir (o ETL que a cria não rodou): vazio."""
    try:
        return athena.consultar(sql)
    except (TabelaInexistente, ErroConsulta):
        return []


def carregar_empresas(athena: Athena) -> list[dict]:
    """Uma empresa por perfil exportado pelo ETL da matriz (só elas podem receber proposta: o
    ETL rejeita proposta de CNPJ sem perfil), com unidades, áreas, outorgas, obrigações vigentes,
    atividade (CNAE) e o tipo da classificação do cadastro, quando existir."""
    perfis = athena.consultar(
        "SELECT cnpj, razao_social, setor, cnae_principal, json_format(CAST(cnaes AS JSON)) AS cnaes, "
        "json_format(CAST(ufs_atuacao AS JSON)) AS ufs_atuacao, "
        "json_format(CAST(orgaos_fiscalizadores AS JSON)) AS orgaos_fiscalizadores, "
        "json_format(CAST(temas_interesse AS JSON)) AS temas_interesse, "
        "json_format(CAST(temas_fora_escopo AS JSON)) AS temas_fora_escopo, area_padrao "
        "FROM silver_db.matriz_perfis ORDER BY cnpj")
    unidades = athena.consultar("SELECT cnpj, unidade_id, nome, tipo, json_format(CAST(tags AS JSON)) AS tags "
                                "FROM silver_db.matriz_unidades")
    areas = athena.consultar("SELECT cnpj, area_id, nome FROM silver_db.matriz_areas")
    outorgas = athena.consultar("SELECT cnpj, outorga_id, tipo, orgao, objeto, unidade_id FROM silver_db.matriz_outorgas")
    vigentes = athena.consultar(
        "SELECT cnpj, obrigacao_id, versao, titulo, orgao_sigla, tema, fonte_ato, fonte_dispositivo, "
        "trecho_citado, prazo_regra, recorrencia, periodicidade, json_format(CAST(aplica_a AS JSON)) AS aplica_a, "
        "area_responsavel, criticidade FROM gold_db.matriz_obrigacoes WHERE vigente ORDER BY cnpj, obrigacao_id")
    atividades = {r["user_id"]: r for r in _opcional(
        athena, "SELECT user_id, cnae_principal_descricao, cnaes_secundarios_descricao FROM gold_db.empresas_clientes")}
    tipos = {r["user_id"]: r for r in _opcional(
        athena, "SELECT user_id, tipo_empresa, CAST(revisar AS VARCHAR) AS revisar FROM gold_db.classificacao_empresas")}

    def de(linhas, cnpj):
        return [r for r in linhas if r["cnpj"] == cnpj]

    saida = []
    for p in perfis:
        cnpj = p["cnpj"]
        org = f"CNPJ#{cnpj}"
        tipo = tipos.get(org) or {}
        tipo_empresa = tipo.get("tipo_empresa")
        if tipo_empresa == "indefinido" or str(tipo.get("revisar")).lower() == "true":
            tipo_empresa = None   # a classificação não decidiu: não vale como sinal
        saida.append({
            "cnpj": cnpj, "razao_social": p.get("razao_social"), "setor": p.get("setor"),
            "cnae_principal": p.get("cnae_principal"), "cnaes": _lista(p.get("cnaes")),
            "ufs_atuacao": _lista(p.get("ufs_atuacao")),
            "orgaos_fiscalizadores": _lista(p.get("orgaos_fiscalizadores")),
            "temas_interesse": _lista(p.get("temas_interesse")),
            "temas_fora_escopo": _lista(p.get("temas_fora_escopo")),
            "area_padrao": p.get("area_padrao"),
            "atividade_principal": (atividades.get(org) or {}).get("cnae_principal_descricao"),
            "atividades_secundarias": (atividades.get(org) or {}).get("cnaes_secundarios_descricao"),
            "tipo_empresa": tipo_empresa,
            "unidades": [{"id": u["unidade_id"], "nome": u.get("nome"), "tipo": u.get("tipo"),
                          "tags": _lista(u.get("tags"))} for u in de(unidades, cnpj)],
            "areas": [{"id": a["area_id"], "nome": a.get("nome")} for a in de(areas, cnpj)],
            "outorgas": [{"id": o["outorga_id"], "tipo": o.get("tipo"), "orgao": o.get("orgao"),
                          "objeto": o.get("objeto"), "unidade_id": o.get("unidade_id")} for o in de(outorgas, cnpj)],
            "vigentes": [{"obrigacao_id": v["obrigacao_id"], "titulo": v.get("titulo"),
                          "orgao_sigla": v.get("orgao_sigla"), "tema": v.get("tema"), "fonte_ato": v.get("fonte_ato"),
                          "fonte_dispositivo": v.get("fonte_dispositivo"), "trecho_citado": v.get("trecho_citado"),
                          "prazo_regra": v.get("prazo_regra"), "recorrencia": v.get("recorrencia"),
                          "periodicidade": v.get("periodicidade"), "aplica_a": _lista(v.get("aplica_a")),
                          "area_responsavel": v.get("area_responsavel"), "criticidade": v.get("criticidade")}
                         for v in de(vigentes, cnpj)],
        })
    return saida
