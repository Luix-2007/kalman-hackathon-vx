"""Gatilho CustomMessage do Cognito: e-mails de código na identidade do Kalman."""

import email_cognito


def evento(trigger: str, codigo: str | None = "{####}") -> dict:
    return {
        "triggerSource": trigger,
        "userPoolId": "us-east-1_teste",
        "request": {"codeParameter": codigo, "usernameParameter": None, "userAttributes": {"email": "a@b.com"}},
        "response": {"smsMessage": None, "emailMessage": None, "emailSubject": None},
    }


def test_cadastro_tem_assunto_e_codigo_uma_vez():
    r = email_cognito.handler(evento("CustomMessage_SignUp"))["response"]
    assert r["emailSubject"] == "Confirme seu e-mail no Kalman"
    assert r["emailMessage"].count("{####}") == 1
    assert "Confirme seu e-mail" in r["emailMessage"]
    assert len(r["emailMessage"]) < 20_000  # limite do Cognito


def test_reenvio_usa_o_mesmo_texto_do_cadastro():
    a = email_cognito.handler(evento("CustomMessage_SignUp"))["response"]
    b = email_cognito.handler(evento("CustomMessage_ResendCode"))["response"]
    assert a["emailSubject"] == b["emailSubject"]


def test_esqueci_a_senha_tem_texto_proprio():
    r = email_cognito.handler(evento("CustomMessage_ForgotPassword"))["response"]
    assert "senha" in r["emailSubject"]
    assert "Redefina sua senha" in r["emailMessage"]
    assert r["emailMessage"].count("{####}") == 1


def test_tipos_nao_tratados_ficam_com_a_mensagem_padrao():
    for trigger in ("CustomMessage_AdminCreateUser", "CustomMessage_Authentication", "Outro"):
        r = email_cognito.handler(evento(trigger))["response"]
        assert r["emailMessage"] is None and r["emailSubject"] is None


def test_sem_codigo_nao_mexe():
    r = email_cognito.handler(evento("CustomMessage_SignUp", codigo=None))["response"]
    assert r["emailMessage"] is None
