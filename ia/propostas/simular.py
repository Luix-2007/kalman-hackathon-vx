"""
Simulação do passo de propostas com os dados e os modelos de verdade, sem deploy e sem gravar
nada na AWS: Athena (só leitura), Titan e Claude no Bedrock; o índice vetorial fica em memória e
o que seria o bucket (propostas, auditoria, eventos) vai para uma pasta local.

    uv run python propostas/simular.py --saida /tmp/sim
    uv run python propostas/simular.py --saida /tmp/sim --sem-modelo          # só indexar e recuperar
    uv run python propostas/simular.py --saida /tmp/sim --classificacao /tmp/classificacao.json

--classificacao: saída de pipeline/cadastro/scripts/simular_classificacao.py (tipo de cada empresa),
para quando a gold ainda não tem a tabela classificacao_empresas.

Usa o mesmo código das Lambdas (propostas.fluxo); só troca o índice e o armazém.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import boto3
import numpy as np
from botocore.config import Config as BotoConfig

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI / "src"))

from propostas import dados, fluxo, perfil  # noqa: E402
from propostas.armazem import ArmazemPasta, gravar_json  # noqa: E402
from propostas.athena import Athena  # noqa: E402
from propostas.config import Config  # noqa: E402
from propostas.eventos import Registro  # noqa: E402
from propostas.modelo import Modelo  # noqa: E402
from propostas.vetores import IndiceEmMemoria, TitanEmbedder  # noqa: E402

TAXONOMIA = AQUI.parents[1] / "pipeline/cadastro/config/tipos_empresa.json"


class IndiceNumpy(IndiceEmMemoria):
    """Mesmo contrato do índice em memória, com o produto escalar no numpy (milhares de trechos)."""

    def __init__(self):
        super().__init__()
        self._matriz, self._chaves = None, []

    def gravar(self, itens):
        super().gravar(itens)
        self._matriz = None

    def consultar(self, vetor, top_k, filtro=None):
        if self._matriz is None:
            self._chaves = list(self.vetores)
            self._matriz = np.array([self.vetores[k]["data"] for k in self._chaves], dtype=np.float32)
        if not self._chaves:
            return []
        q = np.array(vetor, dtype=np.float32)
        q /= (np.linalg.norm(q) or 1.0)
        sims = self._matriz @ q
        saida = []
        for i in np.argsort(-sims):
            k = self._chaves[i]
            if self._passa(self.vetores[k]["metadata"], filtro):
                saida.append({"key": k, "distancia": float(1.0 - sims[i]), "metadata": self.vetores[k]["metadata"]})
                if len(saida) == top_k:
                    break
        return saida


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--saida", required=True, type=Path)
    p.add_argument("--desde", default="2026-11-01", help="atos publicados a partir desta data (AAAA-MM-DD)")
    p.add_argument("--dia", default=time.strftime("%Y-%m-%d"))
    p.add_argument("--cnpj", action="append", help="só estas empresas (pode repetir)")
    p.add_argument("--classificacao", type=Path, help="JSON [{cnpj, tipo_empresa, revisar}] da simulação da classificação")
    p.add_argument("--max-pares", type=int, default=40)
    p.add_argument("--limiar", type=float, default=Config.limiar_similaridade)
    p.add_argument("--sem-modelo", action="store_true", help="para depois da busca (sem triagem nem extração)")
    p.add_argument("--regiao", default="us-east-1")
    p.add_argument("--cache-indice", type=Path, help="guarda/reaproveita os vetores dos trechos (.npz) entre rodadas")
    args = p.parse_args()

    cfg = Config(regiao=args.regiao, limiar_similaridade=args.limiar, max_pares=args.max_pares)
    retries = BotoConfig(retries={"mode": "adaptive", "max_attempts": 10}, read_timeout=180)
    athena = Athena(boto3.client("athena", region_name=args.regiao), cfg.athena_workgroup)
    bedrock = boto3.client("bedrock-runtime", region_name=args.regiao, config=retries)
    armazem = ArmazemPasta(args.saida)
    registro = Registro(armazem, "simulacao", args.dia)
    embedder, indice = TitanEmbedder(bedrock), IndiceNumpy()

    t0 = time.monotonic()
    lista_atos = dados.atos_desde(athena, args.desde)
    print(f"atos desde {args.desde}: {len(lista_atos)}  ({time.monotonic() - t0:.0f}s)")
    cfg.max_trechos_por_execucao = 100000
    if args.cache_indice and args.cache_indice.exists():
        guardado = np.load(args.cache_indice, allow_pickle=True)
        indice.gravar([{"key": k, "data": v.tolist(), "metadata": m}
                       for k, v, m in zip(guardado["chaves"], guardado["dados"], guardado["meta"])])
    print("indexar:", fluxo.indexar(lista_atos, embedder, indice, cfg, registro), f"({time.monotonic() - t0:.0f}s)")
    if args.cache_indice:
        chaves = list(indice.vetores)
        np.savez(args.cache_indice, chaves=np.array(chaves, dtype=object),
                 dados=np.array([indice.vetores[k]["data"] for k in chaves], dtype=np.float32),
                 meta=np.array([indice.vetores[k]["metadata"] for k in chaves], dtype=object))

    empresas = dados.carregar_empresas(athena)
    if args.cnpj:
        empresas = [e for e in empresas if e["cnpj"] in args.cnpj]
    if args.classificacao:
        tipos = {c["cnpj"]: c for c in json.loads(args.classificacao.read_text(encoding="utf-8"))}
        for e in empresas:
            c = tipos.get(e["cnpj"]) or {}
            if c.get("tipo_empresa") not in (None, "indefinido") and not c.get("revisar"):
                e["tipo_empresa"] = c["tipo_empresa"]
    taxonomia = perfil.carregar_taxonomia(TAXONOMIA.read_text(encoding="utf-8"))
    contexto, pares = fluxo.preparar(empresas, taxonomia, embedder, indice, cfg, args.desde, {}, registro)
    gravar_json(armazem, "candidatos.json", {cnpj: [{k: c[k] for k in ("ato_id", "score", "origens")}
                                                    for c in cs] for cnpj, cs in
                                             {e["cnpj"]: [c for (cn, c) in pares if cn == e["cnpj"]] for e in empresas}.items()})
    atos_por_id = {a["id"]: a for a in lista_atos}
    for e in empresas:
        cs = [c for cn, c in pares if cn == e["cnpj"]]
        print(f"\n{e['cnpj']} {e['razao_social']} tipo={e.get('tipo_empresa')} vigentes={len(e['vigentes'])} candidatos={len(cs)}")
        for c in cs[:15]:
            a = atos_por_id.get(c["ato_id"], {})
            print(f"  {c['score']:.3f} {','.join(c['origens']):28s} {c['ato_id']:>10s} {a.get('tipo','')[:14]:14s} "
                  f"{(a.get('orgao') or '').split('/')[-1][:45]:45s} {(a.get('identifica') or '')[:50]}")
    registro.descarregar("recuperar")
    if args.sem_modelo:
        return

    triador = Modelo(bedrock, cfg.modelo_triagem, 800)
    extrator = Modelo(bedrock, cfg.modelo_extracao, 8000)

    def um(par):
        cnpj, cand = par
        try:
            return fluxo.processar(contexto["empresas"][cnpj], cand, atos_por_id.get(cand["ato_id"]), triador, extrator,
                                   cfg, armazem, registro, args.dia)
        except Exception as exc:          # na Lambda, o erro sobe para a Step Functions
            return {"cnpj": cnpj, "ato_id": cand["ato_id"], "resultado": "erro", "erro": f"{type(exc).__name__}: {exc}"[:300]}

    with ThreadPoolExecutor(max_workers=4) as pool:
        resultados = list(pool.map(um, pares))
    registro.descarregar("processar")
    resumo = fluxo.resumir(resultados)
    gravar_json(armazem, "resultados.json", {"resumo": resumo, "resultados": resultados})
    print("\nresumo:", resumo, f"({time.monotonic() - t0:.0f}s)")
    for r in resultados:
        if r["resultado"] in ("proposta", "sem_proposta", "erro"):
            print(" ", r)


if __name__ == "__main__":
    main()
