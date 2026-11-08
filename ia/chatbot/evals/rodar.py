"""
Avaliação do comportamento do agente com o modelo de verdade (Bedrock).

    make ia-chatbot-eval                                  dados fixos (a Aurora no dia da demo)
    make ia-chatbot-eval ARGS="--dados-reais"             consulta a Aurora no lake (Athena)
    make ia-chatbot-eval ARGS="--caso tarefas_em_risco --repeticoes 3"

Precisa de credenciais AWS com acesso ao Bedrock e de MODEL_ID no ambiente (o mesmo do runtime).
Com dados fixos, o resultado depende só do modelo e do prompt; com --dados-reais, também do
estado do lake (rode antes: make pipeline-matriz-fixture, pipeline-matriz-run e, para o caso
da OBR-013, pipeline-matriz-proposta-demo e outra execução).

Cada caso (casos.json) roda `repeticoes` vezes e só passa se passar em todas: a resposta de um
modelo varia. As conferências estão em avaliador.py. Sai com 0 se tudo passar, 1 se falhar.
"""

import argparse
import os
import sys
import time
from pathlib import Path

AQUI = Path(__file__).resolve().parent
sys.path.insert(0, str(AQUI))            # avaliador, dados_fixture
sys.path.insert(0, str(AQUI.parent))     # agent.py

import json  # noqa: E402

import avaliador  # noqa: E402
import dados_fixture  # noqa: E402


def carregar_casos(caminho: Path = AQUI / "casos.json") -> list[dict]:
    casos = json.loads(caminho.read_text(encoding="utf-8"))
    ids = [c["id"] for c in casos]
    assert len(ids) == len(set(ids)), "ids de caso repetidos"
    return casos


def rodar_caso(agent, caso: dict, cnpj: str, dados_reais: bool) -> tuple[list[str], dict, list[dict], float]:
    consultas = []
    original = agent.athena_query

    def gravador(sql, params):
        linhas = original(sql, params) if dados_reais else dados_fixture.responder(sql, params, caso.get("fixture_extra"))
        consultas.append({"sql": sql, "params": params, "linhas": linhas})
        return linhas

    agent.athena_query = gravador
    inicio = time.monotonic()
    try:
        saida = agent.invoke({"cnpj": cnpj, "user_id": "avaliacao", "prompt": caso["prompt"]})
    finally:
        agent.athena_query = original
    return avaliador.avaliar(caso, saida, consultas, cnpj), saida, consultas, time.monotonic() - inicio


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--caso", action="append", help="id do caso (pode repetir); padrão: todos")
    p.add_argument("--repeticoes", type=int, default=1)
    p.add_argument("--dados-reais", action="store_true", help="consulta o Athena em vez dos dados fixos")
    p.add_argument("--cnpj", default=dados_fixture.CNPJ)
    p.add_argument("--mostrar", action="store_true", help="imprime a resposta de cada execução")
    args = p.parse_args()
    if not os.environ.get("MODEL_ID"):
        sys.exit("faltou MODEL_ID no ambiente (o mesmo do runtime do agente)")

    import agent  # lê MODEL_ID, GUARDRAIL_ID etc. na importação

    casos = carregar_casos()
    if args.caso:
        desconhecidos = set(args.caso) - {c["id"] for c in casos}
        if desconhecidos:
            sys.exit(f"caso(s) desconhecido(s): {', '.join(sorted(desconhecidos))}")
        casos = [c for c in casos if c["id"] in args.caso]
    if args.dados_reais:
        casos = [c for c in casos if not c.get("so_fixture")]

    print(f"Modelo {os.environ['MODEL_ID']} · {'Athena (dados reais)' if args.dados_reais else 'dados fixos'} · "
          f"CNPJ {args.cnpj} · {len(casos)} caso(s) × {args.repeticoes}\n")
    reprovados = 0
    for caso in casos:
        falhas_do_caso, tempos = [], []
        for i in range(args.repeticoes):
            falhas, saida, consultas, seg = rodar_caso(agent, caso, args.cnpj, args.dados_reais)
            tempos.append(seg)
            if args.mostrar:
                print(f"    [{i + 1}] {str(saida.get('resposta', saida))[:400]!r}")
            falhas_do_caso += [f"(execução {i + 1}) {f}" for f in falhas]
        ok = not falhas_do_caso
        reprovados += not ok
        print(f"  {'✅' if ok else '❌'} {caso['id']}  ({sum(tempos) / len(tempos):.1f}s)  {caso['descricao']}")
        for f in falhas_do_caso:
            print(f"       - {f}")
    print(f"\n{'PASSOU' if not reprovados else 'FALHOU'}: {len(casos) - reprovados}/{len(casos)} casos")
    sys.exit(1 if reprovados else 0)


if __name__ == "__main__":
    main()
