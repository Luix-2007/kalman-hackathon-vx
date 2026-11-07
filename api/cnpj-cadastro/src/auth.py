"""
Quem está chamando a API.

O API Gateway valida o token do Cognito antes de chamar a Lambda (JWT authorizer
no template.yaml) e repassa os dados do token em requestContext.authorizer.jwt.claims.
O `sub` é o ID fixo e único do usuário no Cognito: é ele que usamos como user_id.
Nunca use um user_id vindo do body ou da URL.
"""


def user_id_from_event(event: dict) -> str | None:
    claims = (
        (event.get("requestContext") or {})
        .get("authorizer", {})
        .get("jwt", {})
        .get("claims", {})
    )
    sub = str(claims.get("sub") or "").strip()
    return sub or None
