"""
De onde vêm os dados de um CNPJ: OpenCNPJ (padrão) ou fixture local (empresa de teste).

A fixture só é usada com as duas condições juntas:
  - FIXTURES_ENABLED=true no ambiente (só na stack do hackathon; padrão false);
  - o CNPJ começa com "KALMAN" (ex.: KALMANTESTE100), um prefixo que a Receita não emite.

Um CNPJ "KALMAN..." sem arquivo em fixtures/ volta como não encontrado, sem chamar o
OpenCNPJ. Com a flag desligada, qualquer CNPJ (inclusive "KALMAN...") vai para o OpenCNPJ.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from decimal import Decimal
from pathlib import Path

PREFIXO_FIXTURE = "KALMAN"
PASTA_FIXTURES = Path(__file__).parent / "fixtures"
OPENCNPJ_URL_PADRAO = "https://api.opencnpj.org"


class RetryableError(Exception):
    """Erro temporário (429/5xx/rede): a Lambda falha e o EventBridge/Lambda tenta de novo."""


def fixtures_ligadas() -> bool:
    return os.environ.get("FIXTURES_ENABLED", "false").strip().lower() == "true"


def usa_fixture(cnpj: str) -> bool:
    return fixtures_ligadas() and cnpj.startswith(PREFIXO_FIXTURE)


def de_fixture(cnpj: str) -> dict | None:
    arquivo = PASTA_FIXTURES / f"{cnpj}.json"
    if not arquivo.is_file():
        return None
    return json.loads(arquivo.read_text(encoding="utf-8"), parse_float=Decimal)


def do_opencnpj(cnpj: str) -> dict | None:
    """Retorna os dados do CNPJ, ou None se não existir na base."""
    url = os.environ.get("OPENCNPJ_API_URL", OPENCNPJ_URL_PADRAO)
    req = urllib.request.Request(
        f"{url}/{cnpj}?datasets=receita",
        headers={"User-Agent": "cadastro-usuarios", "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read(), parse_float=Decimal)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return None
        if exc.code == 429 or exc.code >= 500:
            raise RetryableError(f"OpenCNPJ HTTP {exc.code}") from exc
        raise
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RetryableError(str(exc)) from exc


def buscar(cnpj: str) -> dict | None:
    """Dados do CNPJ no formato do OpenCNPJ, ou None se não existir."""
    return de_fixture(cnpj) if usa_fixture(cnpj) else do_opencnpj(cnpj)
