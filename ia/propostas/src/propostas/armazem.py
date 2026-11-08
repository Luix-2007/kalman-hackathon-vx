"""Onde o passo grava: o bucket do lake (produção) ou uma pasta (testes e simulação)."""

from __future__ import annotations

import json
from pathlib import Path


class ArmazemS3:
    def __init__(self, cliente, bucket: str):
        self.cliente, self.bucket = cliente, bucket

    def existe(self, chave: str) -> bool:
        try:
            self.cliente.head_object(Bucket=self.bucket, Key=chave)
            return True
        except Exception as exc:
            if getattr(exc, "response", {}).get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return False
            raise

    def ler(self, chave: str) -> str:
        return self.cliente.get_object(Bucket=self.bucket, Key=chave)["Body"].read().decode("utf-8")

    def gravar(self, chave: str, texto: str, tipo: str = "application/json") -> None:
        self.cliente.put_object(Bucket=self.bucket, Key=chave, Body=texto.encode("utf-8"),
                                ContentType=f"{tipo}; charset=utf-8")

    def listar(self, prefixo: str) -> list[str]:
        chaves, token = [], None
        while True:
            kw = {"Bucket": self.bucket, "Prefix": prefixo}
            if token:
                kw["ContinuationToken"] = token
            resp = self.cliente.list_objects_v2(**kw)
            chaves += [o["Key"] for o in resp.get("Contents", [])]
            token = resp.get("NextContinuationToken")
            if not token:
                return chaves


class ArmazemPasta:
    def __init__(self, raiz: str | Path):
        self.raiz = Path(raiz)

    def existe(self, chave: str) -> bool:
        return (self.raiz / chave).exists()

    def ler(self, chave: str) -> str:
        return (self.raiz / chave).read_text(encoding="utf-8")

    def gravar(self, chave: str, texto: str, tipo: str = "application/json") -> None:
        alvo = self.raiz / chave
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_text(texto, encoding="utf-8")

    def listar(self, prefixo: str) -> list[str]:
        base = self.raiz / prefixo
        if not base.exists():
            return []
        return sorted(str(p.relative_to(self.raiz)) for p in base.rglob("*") if p.is_file())


def gravar_json(armazem, chave: str, dado) -> None:
    armazem.gravar(chave, json.dumps(dado, ensure_ascii=False, indent=2, default=str))
