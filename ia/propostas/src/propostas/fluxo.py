"""As etapas ligadas, iguais na Lambda e na simulação (que só troca o índice e o armazém)."""

from __future__ import annotations

import json
import re

from . import atos as A
from . import modelo as M
from . import perfil as P
from .armazem import gravar_json
from .config import PREFIXO_AUDITORIA, PREFIXO_PROPOSTAS, Config
from .recuperar import limitar_pares, recuperar
from .verificar import ajustar_area, limpar, verificar


def _seguro(texto: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(texto))


def caminho_proposta(dia: str, ato_id: str, cnpj: str) -> str:
    return f"{PREFIXO_PROPOSTAS}/{dia}/{_seguro(ato_id)}__{_seguro(cnpj)}.json"


def caminho_processado(cnpj: str, ato_id: str) -> str:
    return f"{PREFIXO_AUDITORIA}/processados/{_seguro(cnpj)}/{_seguro(ato_id)}.json"


def caminho_contexto(run_id: str) -> str:
    return f"{PREFIXO_AUDITORIA}/execucoes/{_seguro(run_id)}/contexto.json"


# ---------------------------------------------------------------- 0 indexar

def indexar(lista_atos: list[dict], embedder, indice, cfg: Config, registro) -> dict:
    """Trechos dos atos que ainda não estão no índice, até o teto da execução (o resto fica para a
    próxima). A chave do trecho é fixa (ato#nnn), então reindexar só sobrescreve."""
    pendentes: list[tuple[dict, str, str]] = []
    for ato in lista_atos:
        for n, trecho in enumerate(A.trechos(ato.get("texto"))):
            pendentes.append((ato, A.chave(ato["id"], n), trecho))
    ja = indice.existentes([c for _, c, _ in pendentes]) if pendentes else set()
    novos = [p for p in pendentes if p[1] not in ja][:cfg.max_trechos_por_execucao]
    vetores = embedder.embed_varios([A.texto_para_embedding(ato, t) for ato, _, t in novos]) if novos else []
    indice.gravar([{"key": c, "data": v, "metadata": {
        "ato_id": ato["id"], "data": A.data_int(ato["data_publicacao"]), "orgao": (ato.get("orgao") or "")[:500],
        "tipo": ato.get("tipo") or "", "texto": t}} for (ato, c, t), v in zip(novos, vetores)])
    resumo = {"atos": len(lista_atos), "trechos": len(pendentes), "ja_indexados": len(ja), "indexados": len(novos),
              "adiados": max(0, len(pendentes) - len(ja) - len(novos))}
    registro.evento("indexar", resultado="ok", detalhes=resumo)
    return resumo


# ---------------------------------------------------------------- 1 recuperar

def preparar(empresas: list[dict], taxonomia: dict | None, embedder, indice, cfg: Config, desde: str,
             processados: dict[str, set[str]], registro) -> tuple[dict, list[tuple[str, dict]]]:
    """Candidatos de todas as empresas e os pares que seguem (com teto). O contexto (perfil,
    vigentes e candidatos) vai para o armazém, para a etapa seguinte não consultar tudo de novo."""
    cache: dict[str, list[float]] = {}
    candidatos_por_cnpj: dict[str, list[dict]] = {}
    for e in empresas:
        cons = P.consultas(e, taxonomia)
        faltam = [c["texto"] for c in cons if c["texto"] not in cache]
        for texto, v in zip(faltam, embedder.embed_varios(faltam) if faltam else []):
            cache[texto] = v
        cands = recuperar(e, cons, [cache[c["texto"]] for c in cons], indice, A.data_int(desde), cfg.top_k,
                          cfg.limiar_similaridade, cfg.max_atos_por_empresa, processados.get(e["cnpj"], set()))
        candidatos_por_cnpj[e["cnpj"]] = cands
        for c in cands:
            registro.evento("recuperar", cnpj=e["cnpj"], ato_id=c["ato_id"], resultado="candidato", score=c["score"],
                            detalhes={"origens": c["origens"], "consultas": c["consultas"][:10]})
        registro.evento("recuperar", cnpj=e["cnpj"], resultado="resumo",
                        detalhes={"consultas": len(cons), "candidatos": len(cands),
                                  "por_origem": {o: sum(1 for c in cons if c["origem"] == o)
                                                 for o in sorted({c["origem"] for c in cons})}})
    pares = limitar_pares(candidatos_por_cnpj, cfg.max_pares)
    contexto = {"empresas": {e["cnpj"]: e for e in empresas},
                "candidatos": {f"{cnpj}|{c['ato_id']}": c for cnpj, c in pares}}
    return contexto, pares


# ---------------------------------------------------------------- 2 a 5, um par

def processar(empresa: dict, candidato: dict, ato: dict | None, triador: M.Modelo, extrator: M.Modelo,
              cfg: Config, armazem, registro, dia: str) -> dict:
    cnpj, ato_id = empresa["cnpj"], candidato["ato_id"]
    base = {"cnpj": cnpj, "ato_id": ato_id}

    def fim(resultado: str, **extra) -> dict:
        gravar_json(armazem, caminho_processado(cnpj, ato_id), {**base, "resultado": resultado, "dia": dia, **extra})
        return {**base, "resultado": resultado, **extra}

    if ato is None:
        registro.evento("processar", cnpj=cnpj, ato_id=ato_id, resultado="ato_nao_encontrado")
        return fim("ato_nao_encontrado")

    perfil, vigentes = P.resumo_para_modelo(empresa), P.vigentes_para_modelo(empresa)
    triagem, uso = M.triar(triador, perfil, vigentes, ato, candidato["trechos"])
    registro.evento("triar", cnpj=cnpj, ato_id=ato_id, resultado="relevante" if triagem.get("relevante") else "irrelevante",
                    score=triagem.get("confianca"), motivo=triagem.get("motivo"), modelo=triador.model_id,
                    detalhes={"tipo_mudanca": triagem.get("tipo_mudanca"), "obrigacao_alvo": triagem.get("obrigacao_alvo"),
                              "score_busca": candidato["score"], "uso": uso})
    if not triagem.get("relevante") or triagem.get("tipo_mudanca") == "nenhuma":
        return fim("irrelevante", motivo=triagem.get("motivo"))

    brutas, uso = M.extrair(extrator, perfil, vigentes, ato, triagem, cfg.max_texto_extracao)
    aprovadas, reprovadas = [], []
    for bruta in brutas:
        p = ajustar_area(limpar(bruta, cnpj), empresa)
        erros = verificar(p, ato.get("texto") or "", empresa, cfg.limiar_confianca)
        (reprovadas if erros else aprovadas).append({**p, **({"_erros": erros} if erros else {})})
        registro.evento("verificar", cnpj=cnpj, ato_id=ato_id, resultado="reprovada" if erros else "aprovada",
                        score=p.get("confianca"), motivo="; ".join(erros) or None, modelo=extrator.model_id,
                        detalhes={"tipo": p.get("tipo"), "obrigacao_id_alvo": p.get("obrigacao_id_alvo"), "uso": uso})
    if reprovadas:
        gravar_json(armazem, f"{PREFIXO_AUDITORIA}/reprovadas/{dia}/{_seguro(ato_id)}__{_seguro(cnpj)}.json",
                    {**base, "ato": {k: ato.get(k) for k in ("identifica", "orgao", "url_pdf")}, "propostas": reprovadas})
    if not aprovadas:
        return fim("sem_proposta", extraidas=len(brutas), reprovadas=len(reprovadas))

    destino = caminho_proposta(dia, ato_id, cnpj)
    if armazem.existe(destino):          # uma vez só: o ETL leria um arquivo reescrito como novo
        return fim("ja_existia", arquivo=destino)
    orgao = next((p["orgao_sigla"] for p in aprovadas if p.get("orgao_sigla")), None) or \
        (ato.get("orgao") or "").split("/")[-1][:60]
    gravar_json(armazem, destino, {"ato_id": ato_id, "ato_url": ato.get("url_pdf"),
                                   "data_publicacao": ato.get("data_publicacao"), "orgao_emissor": orgao,
                                   "gerado_por": "ia/propostas", "propostas": aprovadas})
    registro.evento("gravar", cnpj=cnpj, ato_id=ato_id, resultado="gravada", detalhes={"arquivo": destino,
                                                                                        "propostas": len(aprovadas)})
    return fim("proposta", arquivo=destino, propostas=len(aprovadas), reprovadas=len(reprovadas))


def resumir(resultados: list[dict]) -> dict:
    contagem: dict[str, int] = {}
    for r in resultados or []:
        chave = (r or {}).get("resultado") or "erro"
        contagem[chave] = contagem.get(chave, 0) + 1
    return {"pares": len(resultados or []), "por_resultado": dict(sorted(contagem.items()))}


def ler_contexto(armazem, run_id: str) -> dict:
    return json.loads(armazem.ler(caminho_contexto(run_id)))
