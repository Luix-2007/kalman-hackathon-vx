"""Embedding (Titan v2) e índice vetorial: S3 Vectors em produção, em memória nos testes e na simulação."""

from __future__ import annotations

import json
import math
from concurrent.futures import ThreadPoolExecutor

from .config import DIMENSAO, MODELO_EMBEDDING


class TitanEmbedder:
    def __init__(self, cliente):
        self.cliente = cliente          # boto3 bedrock-runtime

    def embed(self, texto: str) -> list[float]:
        corpo = json.dumps({"inputText": texto[:40000], "dimensions": DIMENSAO, "normalize": True})
        resp = self.cliente.invoke_model(modelId=MODELO_EMBEDDING, body=corpo,
                                         contentType="application/json", accept="application/json")
        return json.loads(resp["body"].read())["embedding"]

    def embed_varios(self, textos: list[str], paralelo: int = 8) -> list[list[float]]:
        with ThreadPoolExecutor(max_workers=paralelo) as pool:
            return list(pool.map(self.embed, textos))


class IndiceS3Vectors:
    def __init__(self, cliente, bucket: str, indice: str):
        self.cliente, self.bucket, self.indice = cliente, bucket, indice

    def existentes(self, chaves: list[str]) -> set[str]:
        achadas: set[str] = set()
        for i in range(0, len(chaves), 100):
            resp = self.cliente.get_vectors(vectorBucketName=self.bucket, indexName=self.indice,
                                            keys=chaves[i:i + 100], returnData=False, returnMetadata=False)
            achadas |= {v["key"] for v in resp.get("vectors", [])}
        return achadas

    def gravar(self, itens: list[dict]) -> None:
        for i in range(0, len(itens), 500):
            self.cliente.put_vectors(vectorBucketName=self.bucket, indexName=self.indice, vectors=[
                {"key": it["key"], "data": {"float32": it["data"]}, "metadata": it.get("metadata", {})}
                for it in itens[i:i + 500]])

    def consultar(self, vetor: list[float], top_k: int, filtro: dict | None = None) -> list[dict]:
        args = {"vectorBucketName": self.bucket, "indexName": self.indice, "queryVector": {"float32": vetor},
                "topK": top_k, "returnMetadata": True, "returnDistance": True}
        if filtro:
            args["filter"] = filtro
        resp = self.cliente.query_vectors(**args)
        return [{"key": v["key"], "distancia": float(v["distance"]), "metadata": v.get("metadata") or {}}
                for v in resp.get("vectors", [])]


class IndiceEmMemoria:
    """Mesmo contrato, com distância de cosseno; o filtro aceita {"campo": {"$gte": n}} e igualdade."""

    def __init__(self):
        self.vetores: dict[str, dict] = {}

    def existentes(self, chaves: list[str]) -> set[str]:
        return {c for c in chaves if c in self.vetores}

    def gravar(self, itens: list[dict]) -> None:
        for it in itens:
            n = math.sqrt(sum(x * x for x in it["data"])) or 1.0
            self.vetores[it["key"]] = {"data": [x / n for x in it["data"]], "metadata": it.get("metadata", {})}

    @staticmethod
    def _passa(meta: dict, filtro: dict | None) -> bool:
        for campo, cond in (filtro or {}).items():
            valor = meta.get(campo)
            if isinstance(cond, dict):
                if "$gte" in cond and not (valor is not None and valor >= cond["$gte"]):
                    return False
                if "$eq" in cond and valor != cond["$eq"]:
                    return False
            elif valor != cond:
                return False
        return True

    def consultar(self, vetor: list[float], top_k: int, filtro: dict | None = None) -> list[dict]:
        n = math.sqrt(sum(x * x for x in vetor)) or 1.0
        q = [x / n for x in vetor]
        sims = []
        for k, v in self.vetores.items():
            if self._passa(v["metadata"], filtro):
                sims.append((sum(a * b for a, b in zip(q, v["data"])), k))
        sims.sort(reverse=True)
        return [{"key": k, "distancia": 1.0 - s, "metadata": self.vetores[k]["metadata"]} for s, k in sims[:top_k]]
