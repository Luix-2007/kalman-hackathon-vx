"""Atos do DOU em trechos para o índice vetorial, e normalização de texto para comparar citações."""

from __future__ import annotations

import re
import unicodedata

ARTIGO = re.compile(r"(?=\bArt\.?\s*\d)")
ESPACOS = re.compile(r"\s+")


def limpar(texto: str | None) -> str:
    return ESPACOS.sub(" ", texto or "").strip()


def trechos(texto: str | None, maximo: int = 1800, limite: int = 40) -> list[str]:
    """Quebra o ato por artigo ("Art. 1º", "Art. 2"...) e junta artigos curtos até `maximo`
    caracteres. Artigo maior que isso é cortado no fim de frase mais próximo. Até `limite` trechos."""
    saida: list[str] = []
    atual = ""
    for parte in (p.strip() for p in ARTIGO.split(limpar(texto))):
        if not parte:
            continue
        while len(parte) > maximo:
            corte = parte.rfind(". ", 0, maximo)
            corte = corte + 1 if corte > maximo // 2 else maximo
            if atual:
                saida.append(atual)
                atual = ""
            saida.append(parte[:corte].strip())
            parte = parte[corte:].strip()
        if not parte:
            continue
        if atual and len(atual) + 1 + len(parte) > maximo:
            saida.append(atual)
            atual = parte
        else:
            atual = f"{atual} {parte}".strip()
    if atual:
        saida.append(atual)
    return saida[:limite]


def chave(ato_id: str, n: int) -> str:
    return f"{ato_id}#{n:03d}"


def ato_da_chave(chave_trecho: str) -> str:
    return chave_trecho.rsplit("#", 1)[0]


def data_int(data: str) -> int:
    """'2026-11-05' -> 20261105 (filtro numérico do S3 Vectors)."""
    return int(str(data)[:10].replace("-", ""))


def texto_para_embedding(ato: dict, trecho: str) -> str:
    """O trecho com o que identifica o ato: o mesmo artigo de órgãos diferentes não se confunde."""
    cabecalho = " | ".join(x for x in (limpar(ato.get("identifica")), limpar(ato.get("orgao"))) if x)
    return f"{cabecalho}\n{trecho}" if cabecalho else trecho


def normalizar(texto: str | None) -> str:
    """Para conferir citações: sem acento, minúsculas, aspas e espaços uniformes."""
    t = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode().lower()
    t = t.replace("“", '"').replace("”", '"').replace("’", "'")
    t = re.sub(r"[\"'«»]", "", t)
    return ESPACOS.sub(" ", t).strip()


def citacao_esta_no_texto(citacao: str | None, texto: str | None, minimo: int = 20) -> bool:
    """O trecho citado aparece no ato (ignorando acento, caixa, aspas e espaços)? Citação curta
    demais não prova nada, então não vale."""
    c = normalizar(citacao).rstrip(".;:, ")
    return len(c) >= minimo and c in normalizar(texto)
