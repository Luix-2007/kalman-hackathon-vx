"""Registro de eventos: uma linha JSON por decisão de cada etapa, em
audit/propostas/eventos/dt=<dia>/<run_id>/<etapa>-<id>.jsonl (tabela bronze_db.propostas_eventos).

É a base para medir e melhorar depois: o que a busca trouxe e com que nota, o que a triagem
descartou e por quê, o que a verificação reprovou. Sem isso, os erros mais valiosos (os descartes)
se perdem. Nada de dados pessoais: só CNPJ, ato, notas, motivos e versões."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

from .config import PREFIXO_AUDITORIA, VERSAO_PROMPT

CAMPOS = ("em", "run_id", "etapa", "cnpj", "ato_id", "resultado", "score", "motivo", "modelo",
          "versao_prompt", "detalhes")


class Registro:
    def __init__(self, armazem, run_id: str, dia: str):
        self.armazem, self.run_id, self.dia = armazem, run_id, dia
        self.linhas: list[dict] = []

    def evento(self, etapa: str, cnpj: str | None = None, ato_id: str | None = None, resultado: str | None = None,
               score: float | None = None, motivo: str | None = None, modelo: str | None = None,
               detalhes: dict | None = None) -> None:
        self.linhas.append({
            "em": datetime.now(timezone.utc).isoformat(timespec="seconds"), "run_id": self.run_id, "etapa": etapa,
            "cnpj": cnpj, "ato_id": ato_id, "resultado": resultado, "score": score,
            "motivo": (motivo or "")[:1000] or None, "modelo": modelo, "versao_prompt": VERSAO_PROMPT,
            # texto JSON: a tabela fica com colunas fixas e o detalhe varia por etapa
            "detalhes": json.dumps(detalhes, ensure_ascii=False, default=str) if detalhes else None,
        })

    def descarregar(self, nome: str) -> str | None:
        if not self.linhas:
            return None
        chave = f"{PREFIXO_AUDITORIA}/eventos/dt={self.dia}/{self.run_id}/{nome}-{uuid.uuid4().hex[:8]}.jsonl"
        self.armazem.gravar(chave, "".join(json.dumps(l, ensure_ascii=False) + "\n" for l in self.linhas),
                            "application/x-ndjson")
        self.linhas = []
        return chave
