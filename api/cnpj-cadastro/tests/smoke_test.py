"""
Smoke test do FLUXO COMPLETO, contra a stack publicada na AWS.

    make api-smoke
    python tests/smoke_test.py --stack outra-stack --cnpj 00000000000191 --cnpj2 33000167000101

Simula o front com dois usuários (A = dono, B = convidado):
  1. A envia o CNPJ e vira dono da organização; B não consegue pegar o mesmo CNPJ (409)
  2. espera a consulta em segundo plano e lê GET /cadastro/me
  3. A preenche o formulário (PATCH: merge, null apaga)
  4. B, sem organização, não enxerga nem altera nada
  5. reenviar o CNPJ não apaga o formulário
  6. A convida B; B aceita, vê os mesmos dados, mas não edita nem convida
  7. B sai da organização
  8. A troca de CNPJ; o anterior fica livre para B
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
    p.add_argument("--cnpj2", default="33000167000101", help="outro CNPJ real e ativo (troca)")
    p.add_argument("--timeout", type=int, default=60, help="segundos esperando a consulta do CNPJ")
    args = p.parse_args()

    s = Smoke(args.stack)
    try:
        run(s, args)
    finally:
        s.cleanup()
    s.finish()


def run(s: Smoke, args):
    me, membros, convite = f"{s.api_url}/me", f"{s.api_url}/membros", f"{s.api_url}/convite"
    a, b = s.new_user(), s.new_user()
    a.login()
    b.login()
    print(f"  usuário A: {a.email}\n  usuário B: {b.email}\n")

    print("  1. envio do CNPJ")
    code, body = http("POST", s.api_url, a.access_token, {"user_id": "outra-pessoa", "cnpj": args.cnpj})
    if not s.check("POST /cadastro -> 202", code == 202, f"{code} {body}"):
        return
    s.check("user_id vem do token, não do body", body.get("user_id") == a.sub, f"user_id={body.get('user_id')}")
    code, body = http("POST", s.api_url, a.access_token, {"cnpj": "123"})
    s.check("CNPJ inválido -> 400", code == 400, f"{code} {body}")
    code, body = http("POST", s.api_url, b.access_token, {"cnpj": args.cnpj})
    s.check("CNPJ que já tem dono -> 409", code == 409, f"{code} {body}")

    print(f"\n  2. consulta em segundo plano (até {args.timeout}s)")

    def ready():
        code, body = http("GET", me, a.access_token)
        return body if code == 200 and body.get("status") != "processando" else None

    cad, secs = wait_for(ready, args.timeout)
    if not s.check("GET /cadastro/me -> 200", cad is not None, "não chegou; veja sam logs -n CnpjLookupFunction"):
        return
    print(f"    chegou em {secs:.0f}s")
    s.check("A é o dono", cad.get("papel") == "dono", f"papel={cad.get('papel')}")
    s.check("status é 'ativa'", cad.get("status") == "ativa", f"status={cad.get('status')}")
    s.check("dados da empresa presentes", bool(cad.get("empresa", {}).get("razao_social")))
    s.check("sócios (QSA) não são expostos", "QSA" not in cad.get("empresa", {}))
    s.check("formulário começa vazio", cad.get("dados") == {}, f"dados={cad.get('dados')}")

    print("\n  3. formulário")
    form = {"setor": "energia", "email_alertas": "alertas@exemplo.com.br", "faixa_funcionarios": "1-19"}
    code, body = http("PATCH", me, a.access_token, {"dados": form})
    s.check("PATCH salva os campos", code == 200 and body.get("dados") == form, f"{code} {body.get('dados')}")
    code, body = http("PATCH", me, a.access_token, {"dados": {"email_alertas": None, "setor": "financeiro"}})
    esperado = {"setor": "financeiro", "faixa_funcionarios": "1-19"}
    s.check("PATCH faz merge e null apaga o campo", code == 200 and body.get("dados") == esperado,
            f"{code} {body.get('dados')}")
    code, body = http("PATCH", me, a.access_token, {"dados": {"Campo Inválido": 1}})
    s.check("PATCH com nome de campo inválido -> 400", code == 400, f"{code} {body}")

    print("\n  4. isolamento (B ainda sem organização)")
    for metodo, url, corpo in (("GET", me, None), ("PATCH", me, {"dados": {"setor": "outro"}}),
                               ("GET", membros, None), ("GET", convite, None)):
        code, body = http(metodo, url, b.access_token, corpo)
        s.check(f"B: {metodo} {url.removeprefix(s.api_url) or '/'} -> 404", code == 404, f"{code} {body}")

    print("\n  5. reenvio do CNPJ")
    antes = cad.get("consultado_em")
    time.sleep(1)  # consultado_em tem resolução de segundos
    code, _ = http("POST", s.api_url, a.access_token, {"cnpj": args.cnpj})
    s.check("POST de novo -> 202", code == 202, f"recebeu {code}")

    def reconsultado():
        code, body = http("GET", me, a.access_token)
        return body if code == 200 and body.get("consultado_em") != antes else None

    cad, _ = wait_for(reconsultado, args.timeout)
    s.check("nova consulta aconteceu", cad is not None, "consultado_em não mudou")
    s.check("nova consulta não apaga o formulário", (cad or {}).get("dados") == esperado,
            f"dados={(cad or {}).get('dados')}")

    print("\n  6. convite")
    code, body = http("POST", membros, a.access_token, {"email": b.email})
    s.check("A convida B -> 201", code == 201, f"{code} {body}")
    code, body = http("GET", convite, b.access_token)
    s.check("B vê o convite", code == 200 and body.get("cnpj") == args.cnpj, f"{code} {body}")
    code, body = http("POST", convite, b.access_token)
    s.check("B aceita -> 200", code == 200 and body.get("papel") == "membro", f"{code} {body}")
    code, body = http("GET", me, b.access_token)
    s.check("B vê os mesmos dados da empresa", code == 200 and body.get("papel") == "membro"
            and body.get("dados") == esperado and body.get("cnpj") == args.cnpj, f"{code} {body}")
    code, body = http("PATCH", me, b.access_token, {"dados": {"setor": "outro"}})
    s.check("B (membro) não edita -> 403", code == 403, f"{code} {body}")
    code, body = http("POST", membros, b.access_token, {"email": "x@example.com"})
    s.check("B (membro) não convida -> 403", code == 403, f"{code} {body}")
    code, body = http("GET", membros, a.access_token)
    s.check("A vê B na lista de membros", code == 200 and [m.get("email") for m in body.get("membros", [])] == [b.email],
            f"{code} {body}")
    code, body = http("POST", s.api_url, a.access_token, {"cnpj": args.cnpj2})
    s.check("A não troca de CNPJ com membros -> 409", code == 409, f"{code} {body}")
    code, body = http("POST", s.api_url, b.access_token, {"cnpj": args.cnpj2})
    s.check("B (membro) não cria outra organização -> 409", code == 409, f"{code} {body}")

    print("\n  7. saída")
    code, body = http("DELETE", f"{membros}/{b.sub}", b.access_token)
    s.check("B sai da organização -> 200", code == 200, f"{code} {body}")
    code, body = http("GET", me, b.access_token)
    s.check("B não vê mais os dados -> 404", code == 404, f"{code} {body}")

    print("\n  8. troca de CNPJ")
    antes = (cad or {}).get("consultado_em")
    time.sleep(1)
    code, body = http("POST", s.api_url, a.access_token, {"cnpj": args.cnpj2})
    s.check("A troca para outro CNPJ -> 202", code == 202, f"{code} {body}")
    cad, _ = wait_for(reconsultado, args.timeout)
    s.check("organização de A aponta para o CNPJ novo e leva o formulário",
            (cad or {}).get("cnpj") == args.cnpj2 and (cad or {}).get("dados") == esperado, f"{cad}")
    code, body = http("POST", s.api_url, b.access_token, {"cnpj": args.cnpj})
    s.check("CNPJ antigo de A fica livre: B consegue -> 202", code == 202, f"{code} {body}")
    code, body = http("POST", s.api_url, b.access_token, {"cnpj": args.cnpj2})
    s.check("B não pega o CNPJ de A -> 409", code == 409, f"{code} {body}")


if __name__ == "__main__":
    main()
