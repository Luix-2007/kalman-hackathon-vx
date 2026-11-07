"""
Código comum dos smoke tests (rodam contra a stack JÁ PUBLICADA na AWS).

Os usuários de teste são criados direto no Cognito com credenciais IAM
(admin_create_user, sem enviar e-mail) e apagados no final, junto com os
itens que eles criaram no DynamoDB.
"""

import json
import sys
import urllib.error
import urllib.request
import uuid

import boto3


class Smoke:
    """Lê os outputs da stack, registra as verificações e limpa tudo no final."""

    def __init__(self, stack: str):
        cfn = boto3.client("cloudformation")
        outputs = {o["OutputKey"]: o["OutputValue"] for o in cfn.describe_stacks(StackName=stack)["Stacks"][0]["Outputs"]}
        self.api_url = outputs["ApiUrl"]
        self.pool_id = outputs["UserPoolId"]
        self.client_id = outputs["UserPoolClientId"]
        self.table = boto3.resource("dynamodb").Table(outputs["TableName"])
        self.cognito = boto3.client("cognito-idp")
        self.results: list[bool] = []
        self._users: list[TestUser] = []
        print(f"Stack {stack}\n  API:       {self.api_url}\n  UserPool:  {self.pool_id}\n  Tabela:    {self.table.name}\n")

    def check(self, name: str, ok: bool, detail="") -> bool:
        self.results.append(bool(ok))
        print(f"  {'✅' if ok else '❌'} {name}" + (f"  ({detail})" if detail and not ok else ""))
        return bool(ok)

    def new_user(self) -> "TestUser":
        user = TestUser(self)
        self._users.append(user)
        return user

    def cleanup(self):
        for user in self._users:
            try:
                self.table.delete_item(Key={"user_id": user.sub})
                self.cognito.admin_delete_user(UserPoolId=self.pool_id, Username=user.email)
            except Exception as exc:  # não esconde o resultado dos testes por causa da limpeza
                print(f"  ⚠️  falha ao limpar {user.email}: {exc}")
        if self._users:
            print(f"\n  {len(self._users)} usuário(s) de teste e seus itens apagados")

    def finish(self):
        passed = all(self.results)
        print(f"\n{'PASSOU' if passed else 'FALHOU'}: {sum(self.results)}/{len(self.results)} verificações")
        sys.exit(0 if passed else 1)


class TestUser:
    """Usuário de teste no Cognito, já com senha definitiva (não pede troca no 1º login)."""

    def __init__(self, smoke: Smoke):
        self._s = smoke
        self.email = f"smoke-{uuid.uuid4().hex[:8]}@example.com"
        self.password = f"Sm0ke-{uuid.uuid4().hex}"
        resp = smoke.cognito.admin_create_user(
            UserPoolId=smoke.pool_id,
            Username=self.email,
            UserAttributes=[{"Name": "email", "Value": self.email}, {"Name": "email_verified", "Value": "true"}],
            MessageAction="SUPPRESS",
        )
        self.sub = next(a["Value"] for a in resp["User"]["Attributes"] if a["Name"] == "sub")
        smoke.cognito.admin_set_user_password(
            UserPoolId=smoke.pool_id, Username=self.email, Password=self.password, Permanent=True)
        self.access_token = self.refresh_token = None

    def _auth(self, flow: str, params: dict) -> dict:
        return self._s.cognito.admin_initiate_auth(
            UserPoolId=self._s.pool_id, ClientId=self._s.client_id, AuthFlow=flow, AuthParameters=params,
        )["AuthenticationResult"]

    def login(self, password: str | None = None) -> None:
        auth = self._auth("ADMIN_USER_PASSWORD_AUTH", {"USERNAME": self.email, "PASSWORD": password or self.password})
        self.access_token, self.refresh_token = auth["AccessToken"], auth["RefreshToken"]

    def refresh(self) -> str:
        self.access_token = self._auth("REFRESH_TOKEN_AUTH", {"REFRESH_TOKEN": self.refresh_token})["AccessToken"]
        return self.access_token


def http(method: str, url: str, token: str | None = None, body=None) -> tuple[int, dict]:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            return resp.status, _json(resp.read())
    except urllib.error.HTTPError as exc:
        return exc.code, _json(exc.read())


def _json(raw: bytes) -> dict:
    try:
        return json.loads(raw or b"{}")
    except ValueError:
        return {"raw": raw.decode(errors="replace")}
