"""
Smoke test do FLUXO COMPLETO, contra a stack publicada na AWS.

    make api-smoke
    python tests/smoke_test.py --stack outra-stack --cnpj 00000000000191

Simula o front com dois usuários (A e B):
  1. login no Cognito
  2. POST /cadastro com o CNPJ (o user_id vem do token, nunca do body)
  3. espera a consulta em segundo plano e lê GET /cadastro/me
  4. PATCH /cadastro/me com os campos do formulário (merge, null apaga)
  5. B não enxerga nem altera o cadastro de A
  6. reenviar o CNPJ não apaga o que o usuário preencheu
Apaga os usuários e os itens de teste no final. Sai com 0 se tudo passar, 1 se falhar.
"""

import argparse
import time

from smoke_lib import Smoke, http


def wait_for(fn, timeout: int):
    """Chama fn() até devolver algo diferente de None, ou até o timeout."""
    start = time.time()
    while time.time() - start < timeout:
        result = fn()
        if result is not None:
            return result, time.time() - start
        time.sleep(2)
    return None, time.time() - start


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stack", default="cnpj-cadastro")
    p.add_argument("--cnpj", default="00000000000191", help="um CNPJ real e ativo")
    p.add_argument("--timeout", type=int, default=60, help="segundos esperando a consulta do CNPJ")
    args = p.parse_args()

    s = Smoke(args.stack)
    try:
        run(s, args)
    finally:
        s.cleanup()
    s.finish()


def run(s: Smoke, args):
    me = f"{s.api_url}/me"
    a, b = s.new_user(), s.new_user()
    a.login()
    b.login()
    print(f"  usuário A: {a.email}\n  usuário B: {b.email}\n")

    print("  1. envio do CNPJ")
    code, body = http("POST", s.api_url, a.access_token, {"user_id": "outra-pessoa", "cnpj": args.cnpj})
    s.check("POST /cadastro -> 202", code == 202, f"{code} {body}")
    s.check("user_id vem do token, não do body", body.get("user_id") == a.sub, f"user_id={body.get('user_id')}")
    code, body = http("POST", s.api_url, a.access_token, {"cnpj": "123"})
    s.check("CNPJ inválido -> 400", code == 400, f"{code} {body}")

    print(f"\n  2. consulta em segundo plano (até {args.timeout}s)")

    def ready():
        code, body = http("GET", me, a.access_token)
        return body if code == 200 else None

    cad, secs = wait_for(ready, args.timeout)
    if not s.check("GET /cadastro/me -> 200", cad is not None, "não apareceu; veja sam logs -n CnpjLookupFunction"):
        return
    print(f"    chegou em {secs:.0f}s")
    s.check("status é 'ativa'", cad.get("status") == "ativa", f"status={cad.get('status')}")
    s.check("dados da empresa presentes", bool(cad.get("empresa", {}).get("razao_social")))
    s.check("sócios (QSA) não são expostos", "QSA" not in cad.get("empresa", {}))
    s.check("formulário começa vazio", cad.get("dados") == {}, f"dados={cad.get('dados')}")

    print("\n  3. formulário")
    form = {"telefone": "11999990000", "site": "https://exemplo.com.br", "funcionarios": 12}
    code, body = http("PATCH", me, a.access_token, {"dados": form})
    s.check("PATCH salva os campos", code == 200 and body.get("dados") == form, f"{code} {body.get('dados')}")
    code, body = http("PATCH", me, a.access_token, {"dados": {"site": None, "telefone": "11888880000"}})
    esperado = {"telefone": "11888880000", "funcionarios": 12}
    s.check("PATCH faz merge e null apaga o campo", code == 200 and body.get("dados") == esperado,
            f"{code} {body.get('dados')}")
    code, body = http("PATCH", me, a.access_token, {"dados": {"status": "hackeado"}})
    s.check("PATCH não altera campos do CNPJ", code == 200 and body.get("status") == "ativa",
            f"{code} status={body.get('status')}")
    code, body = http("PATCH", me, a.access_token, {"dados": {"Campo Inválido": 1}})
    s.check("PATCH com nome de campo inválido -> 400", code == 400, f"{code} {body}")
    code, body = http("GET", me, a.access_token)
    s.check("GET reflete o que foi salvo", body.get("dados") == {**esperado, "status": "hackeado"},
            f"dados={body.get('dados')}")

    print("\n  4. isolamento entre usuários")
    code, body = http("GET", me, b.access_token)
    s.check("B não vê o cadastro de A (404)", code == 404, f"{code} {body}")
    code, body = http("PATCH", me, b.access_token, {"dados": {"telefone": "000"}})
    s.check("B não consegue alterar/criar cadastro (404)", code == 404, f"{code} {body}")
    code, body = http("GET", me, a.access_token)
    s.check("cadastro de A continua intacto", body.get("dados", {}).get("telefone") == "11888880000",
            f"dados={body.get('dados')}")

    print("\n  5. reenvio do CNPJ")
    antes = body.get("consultado_em")
    time.sleep(1)  # consultado_em tem resolução de segundos
    code, _ = http("POST", s.api_url, a.access_token, {"cnpj": args.cnpj})
    s.check("POST de novo -> 202", code == 202, f"recebeu {code}")

    def reconsultado():
        code, body = http("GET", me, a.access_token)
        return body if code == 200 and body.get("consultado_em") != antes else None

    cad, _ = wait_for(reconsultado, args.timeout)
    s.check("nova consulta aconteceu", cad is not None, "consultado_em não mudou")
    if cad:
        s.check("nova consulta não apaga o formulário", cad.get("dados", {}).get("telefone") == "11888880000",
                f"dados={cad.get('dados')}")


if __name__ == "__main__":
    main()
