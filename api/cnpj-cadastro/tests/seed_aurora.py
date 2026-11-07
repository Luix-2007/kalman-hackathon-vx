"""
Carga da empresa de teste Aurora Energia na stack publicada (não é teste: os dados ficam).

    make api-seed-aurora
    python tests/seed_aurora.py --stack cnpj-cadastro --email aurora@kalman.example --senha '...'

Passos, no mesmo estilo dos smoke tests:
  1. cria (ou reaproveita) o usuário no Cognito, sem enviar e-mail, e define a senha
  2. POST /cadastro {"cnpj": "KALMANTESTE100"} (o usuário vira dono da organização)
  3. espera a consulta: com FixturesEnabled=true a organização fica "ativa" com os dados
     da fixture (src/fixtures/KALMANTESTE100.json)
  4. PATCH /cadastro/me com o perfil regulatório de tests/aurora_dados.json

Pode rodar de novo: reenviar o CNPJ só refaz a consulta e o PATCH regrava o perfil.
No fim imprime o e-mail e a senha para entrar no front.
"""

import argparse
import json
import secrets
import sys
import time
from pathlib import Path

from smoke_lib import Smoke, http

CNPJ = "KALMANTESTE100"
DADOS = Path(__file__).with_name("aurora_dados.json")


def garantir_usuario(s: Smoke, email: str, senha: str) -> str:
    """Cria o usuário (ou reaproveita) e define a senha. Devolve o sub."""
    try:
        resp = s.cognito.admin_create_user(
            UserPoolId=s.pool_id, Username=email, MessageAction="SUPPRESS",
            UserAttributes=[{"Name": "email", "Value": email}, {"Name": "email_verified", "Value": "true"}])
        attrs = resp["User"]["Attributes"]
        print(f"  usuário criado: {email}")
    except s.cognito.exceptions.UsernameExistsException:
        attrs = s.cognito.admin_get_user(UserPoolId=s.pool_id, Username=email)["UserAttributes"]
        print(f"  usuário já existia: {email}")
    s.cognito.admin_set_user_password(UserPoolId=s.pool_id, Username=email, Password=senha, Permanent=True)
    return next(a["Value"] for a in attrs if a["Name"] == "sub")


def login(s: Smoke, email: str, senha: str) -> str:
    return s.cognito.admin_initiate_auth(
        UserPoolId=s.pool_id, ClientId=s.client_id, AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={"USERNAME": email, "PASSWORD": senha})["AuthenticationResult"]["AccessToken"]


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--stack", default="cnpj-cadastro")
    p.add_argument("--email", default="aurora@kalman.example")
    p.add_argument("--senha", default=None, help="padrão: gera uma e imprime no fim")
    p.add_argument("--timeout", type=int, default=60)
    args = p.parse_args()
    senha = args.senha or f"Aurora-{secrets.token_urlsafe(9)}1a"

    s = Smoke(args.stack)
    me = f"{s.api_url}/me"
    sub = garantir_usuario(s, args.email, senha)
    token = login(s, args.email, senha)

    print(f"\n  1. POST /cadastro {CNPJ}")
    code, body = http("POST", s.api_url, token, {"cnpj": CNPJ})
    if not s.check("POST /cadastro -> 202", code == 202, f"{code} {body}"):
        org = s.table.get_item(Key={"user_id": f"CNPJ#{CNPJ}"}).get("Item") or {}
        if org.get("dono") and org["dono"] != sub:
            print(f"     o CNPJ já tem outro dono ({org.get('dono_email')}); use --email {org.get('dono_email')}")
        s.finish()

    print(f"\n  2. consulta da empresa (até {args.timeout}s)")
    inicio, cad = time.time(), None
    while time.time() - inicio < args.timeout:
        code, body = http("GET", me, token)
        if code == 200 and body.get("status") != "processando":
            cad = body
            break
        time.sleep(2)
    if not s.check("consulta terminou", cad is not None, "veja sam logs -n CnpjLookupFunction"):
        s.finish()
    ok = s.check("organização ativa", cad["status"] == "ativa",
                 f"status={cad['status']}: FixturesEnabled está true na stack?")
    s.check("dados da fixture em empresa", cad["empresa"].get("cnae_principal") == "3514000",
            f"empresa={cad['empresa'].get('razao_social')}")
    if not ok:
        s.finish()

    print("\n  3. PATCH /cadastro/me com o perfil regulatório")
    perfil = json.loads(DADOS.read_text(encoding="utf-8"))
    code, body = http("PATCH", me, token, {"dados": perfil})
    s.check("PATCH -> 200", code == 200, f"{code} {body}")
    s.check("perfil completo no GET", http("GET", me, token)[1].get("dados") == perfil)

    print(f"\n  Entre no front com:\n    e-mail: {args.email}\n    senha:  {senha}")
    s.finish()


if __name__ == "__main__":
    sys.exit(main())
