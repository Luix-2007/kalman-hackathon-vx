"""
Smoke test da AUTENTICAÇÃO (Cognito + JWT authorizer do API Gateway), contra a stack publicada.

    make api-smoke-login
    python tests/smoke_login.py --stack outra-stack

Verifica que o login funciona e que nenhuma rota aceita chamada sem token válido.
Não cria cadastro no DynamoDB. Sai com código 0 se tudo passar, 1 se falhar.
"""

import argparse

from botocore.exceptions import ClientError

from smoke_lib import Smoke, http


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stack", default="cnpj-cadastro")
    args = p.parse_args()

    s = Smoke(args.stack)
    me = f"{s.api_url}/me"
    try:
        user = s.new_user()
        print(f"  usuário de teste: {user.email}\n")

        try:
            user.login(password="SenhaErrada123")
            s.check("senha errada é recusada", False, "login aceitou a senha errada")
        except ClientError as exc:
            s.check("senha errada é recusada", exc.response["Error"]["Code"] == "NotAuthorizedException",
                    exc.response["Error"]["Code"])

        user.login()
        s.check("login com e-mail e senha gera tokens", bool(user.access_token and user.refresh_token))

        print("\n  rotas sem token válido:")
        for method, url, body in [("GET", me, None), ("PATCH", me, {"dados": {"a": 1}}),
                                  ("POST", s.api_url, {"cnpj": "00000000000191"})]:
            code, _ = http(method, url, body=body)
            s.check(f"{method:5} sem token -> 401", code == 401, f"recebeu {code}")
        code, _ = http("GET", me, token="token.invalido.qualquer")
        s.check("GET   com token inválido -> 401", code == 401, f"recebeu {code}")
        bad = user.access_token[:-4] + ("AAAA" if not user.access_token.endswith("AAAA") else "BBBB")
        code, _ = http("GET", me, token=bad)
        s.check("GET   com assinatura adulterada -> 401", code == 401, f"recebeu {code}")

        print("\n  rotas com token válido:")
        code, body = http("GET", me, token=user.access_token)
        s.check("GET   passa pela autenticação (404: ainda sem cadastro)", code == 404, f"{code} {body}")

        old = user.access_token
        user.refresh()
        s.check("refresh token gera um novo access token", user.access_token and user.access_token != old)
        code, body = http("GET", me, token=user.access_token)
        s.check("novo access token é aceito pela API", code == 404, f"{code} {body}")
    finally:
        s.cleanup()
    s.finish()


if __name__ == "__main__":
    main()
