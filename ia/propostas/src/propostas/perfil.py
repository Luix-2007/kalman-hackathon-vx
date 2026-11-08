"""Do perfil da empresa às consultas da busca semântica, e o resumo do perfil que vai para o modelo."""

from __future__ import annotations

import json

from . import vocabulario
from .atos import normalizar


def carregar_taxonomia(texto: str) -> dict:
    """Mesma taxonomia da classificação do cadastro (pipeline/cadastro/config/tipos_empresa.json)."""
    t = json.loads(texto)
    if not isinstance(t, dict) or not isinstance(t.get("tipos"), list):
        raise ValueError("taxonomia sem tipos")
    return t


def consultas(empresa: dict, taxonomia: dict | None = None) -> list[dict]:
    """Perguntas curtas para o índice de atos. Cada uma tem a origem, para medir depois qual
    tipo de consulta acha o quê:

      obrigacao   uma por obrigação vigente: acha alteração e revogação
      tema        uma por tema de interesse (fora os fora de escopo): acha obrigação nova
      outorga     uma por outorga (licença, autorização): acha renovação e condicionante
      atividade   a atividade principal (CNAE)
      tipo        as consultas do tipo de empresa da classificação, se ela decidiu
    """
    saida: list[dict] = []
    vistos: set[str] = set()

    def add(texto: str, origem: str, **extra):
        texto = " ".join(texto.split())[:700]
        chave = normalizar(texto)
        if len(chave) >= 12 and chave not in vistos:
            vistos.add(chave)
            saida.append({"texto": texto, "origem": origem, **extra})

    for v in empresa.get("vigentes", []):
        partes = [v.get("titulo"), v.get("orgao_sigla"), v.get("fonte_ato"), v.get("fonte_dispositivo"),
                  v.get("trecho_citado")]
        add(". ".join(p for p in partes if p), "obrigacao", obrigacao_id=v["obrigacao_id"])
    fora = set(empresa.get("temas_fora_escopo") or [])
    setor = (empresa.get("setor") or "").replace("_", " ")
    for tema in empresa.get("temas_interesse") or []:
        if tema not in fora:
            add(f"{vocabulario.frase_tema(tema)} {('no setor de ' + setor) if setor else ''}", "tema", tema=tema)
    for o in empresa.get("outorgas", []):
        add(f"{vocabulario.frase_outorga(o.get('tipo'))} {o.get('orgao') or ''} {o.get('objeto') or ''}", "outorga")
    if empresa.get("atividade_principal"):
        add(f"atividade de {empresa['atividade_principal']}", "atividade")
    tipo = empresa.get("tipo_empresa")
    if tipo and taxonomia:
        for t in taxonomia["tipos"]:
            if t.get("id") == tipo:
                for c in t.get("consultas") or []:
                    add(c, "tipo", tipo=tipo)
    return saida


def resumo_para_modelo(empresa: dict) -> dict:
    """O que o modelo precisa saber da empresa. Sem pessoas (responsáveis e e-mails ficam de fora)."""
    return {
        "cnpj": empresa["cnpj"], "razao_social": empresa.get("razao_social"), "setor": empresa.get("setor"),
        "atividade_principal": empresa.get("atividade_principal"),
        "atividades_secundarias": empresa.get("atividades_secundarias"),
        "tipo_empresa": empresa.get("tipo_empresa"), "ufs_atuacao": empresa.get("ufs_atuacao"),
        "orgaos_fiscalizadores": empresa.get("orgaos_fiscalizadores"),
        "temas_interesse": empresa.get("temas_interesse"), "temas_fora_escopo": empresa.get("temas_fora_escopo"),
        "unidades": [{"id": u["id"], "nome": u.get("nome"), "tipo": u.get("tipo"), "tags": u.get("tags")}
                     for u in empresa.get("unidades", [])],
        "areas": [{"id": a["id"], "nome": a.get("nome")} for a in empresa.get("areas", [])],
        "outorgas": [{"tipo": o.get("tipo"), "orgao": o.get("orgao"), "objeto": o.get("objeto"),
                      "unidade_id": o.get("unidade_id")} for o in empresa.get("outorgas", [])],
    }


def vigentes_para_modelo(empresa: dict) -> list[dict]:
    return [{k: v.get(k) for k in ("obrigacao_id", "titulo", "orgao_sigla", "tema", "fonte_ato",
                                   "fonte_dispositivo", "prazo_regra", "recorrencia", "periodicidade", "aplica_a")}
            for v in empresa.get("vigentes", [])]
