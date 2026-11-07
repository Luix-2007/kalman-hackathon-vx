"""
Gatilho CustomMessage do Cognito: troca o texto padrão ("Your verification code is...") pelos e-mails do Kalman.

O Cognito chama esta Lambda antes de enviar cada e-mail com código. Ela devolve assunto e HTML na identidade
"Laudo" (grafite #0E1A24, laranja #FF5A1F, céu #BFD9EA / #EAF2F7). O envio continua sendo o do próprio Cognito
(remetente padrão, no-reply@verificationemail.com, limite baixo por dia): para remetente próprio, configurar o SES.

Regras do Cognito para a resposta:
  - o HTML precisa conter event.request.codeParameter ("{####}") UMA vez: o Cognito troca pelo código;
  - emailMessage até 20.000 caracteres;
  - se esta Lambda falhar, o cadastro falha junto. Por isso qualquer tipo não tratado devolve o evento intacto
    (mensagem padrão do Cognito), e o HTML não depende de nada externo.

E-mail é HTML de 2005: tabelas, estilo inline, sem SVG, sem fonte obrigatória (Instrument Sans e IBM Plex Mono só
quando o leitor tiver; senão caem em Helvetica/Arial e Consolas/Courier). Sem <title> (alguns leitores mostram o texto
dele no topo do e-mail) e sem <h1> (alguns aplicam a fonte deles ao h1): o título é um <div> com estilo próprio.
O logo é texto: imagem precisa de um endereço público (fica para quando o front estiver publicado).
"""

from html import escape

GRAFITE = "#0E1A24"
LARANJA = "#FF5A1F"
CEU = "#BFD9EA"
CEU_CLARO = "#EAF2F7"
TINTA_2 = "#45525E"
TINTA_3 = "#66727D"

SANS = "'Instrument Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'IBM Plex Mono', Consolas, 'Courier New', monospace"

# triggerSource → (assunto, título, texto, validade e aviso)
TEXTOS = {
    "confirmar": (
        "Confirme seu e-mail no Kalman",
        "Confirme seu e-mail",
        "Digite este código no Kalman para ativar sua conta.",
        "O código vale por 24 horas. Se você não criou uma conta no Kalman, ignore este e-mail.",
    ),
    "senha": (
        "Código para redefinir sua senha do Kalman",
        "Redefina sua senha",
        "Digite este código no Kalman para criar uma senha nova.",
        "O código vale por 1 hora. Se você não pediu a troca, ignore este e-mail: sua senha atual continua valendo.",
    ),
    "atributo": (
        "Confirme seu novo e-mail no Kalman",
        "Confirme seu novo e-mail",
        "Digite este código no Kalman para confirmar o endereço.",
        "Se você não pediu essa troca, ignore este e-mail.",
    ),
}

GATILHOS = {
    "CustomMessage_SignUp": "confirmar",
    "CustomMessage_ResendCode": "confirmar",
    "CustomMessage_ForgotPassword": "senha",
    "CustomMessage_UpdateUserAttribute": "atributo",
    "CustomMessage_VerifyUserAttribute": "atributo",
}


def montar_html(titulo: str, texto: str, aviso: str, codigo: str) -> str:
    """HTML do e-mail. `codigo` é o marcador do Cognito ({####}) e aparece uma única vez."""
    titulo, texto, aviso = escape(titulo), escape(texto), escape(aviso)
    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
</head>
<body style="margin:0;padding:0;background:{CEU_CLARO};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{CEU_CLARO};">{texto}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{CEU_CLARO};">
<tr><td align="center" style="padding:32px 16px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:520px;">
    <tr><td style="background:{GRAFITE};border-radius:14px 14px 0 0;padding:22px 32px;">
      <table role="presentation" cellpadding="0" cellspacing="0" border="0"><tr>
        <td style="font-family:{SANS};font-size:24px;line-height:24px;font-weight:700;letter-spacing:-0.5px;color:#FFFFFF;">kalman</td>
        <td style="padding-left:6px;vertical-align:bottom;">
          <div style="width:8px;height:8px;border-radius:4px;background:{LARANJA};font-size:0;line-height:0;margin-bottom:3px;">&nbsp;</div>
        </td>
      </tr></table>
    </td></tr>
    <tr><td style="background:#FFFFFF;padding:36px 32px 12px 32px;">
      <div role="heading" aria-level="1" style="margin:0 0 10px 0;font-family:{SANS};font-size:26px;line-height:30px;font-weight:600;letter-spacing:-0.6px;color:{GRAFITE};">{titulo}</div>
      <p style="margin:0 0 24px 0;font-family:{SANS};font-size:16px;line-height:24px;color:{TINTA_2};">{texto}</p>
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td style="background:{CEU_CLARO};border-left:4px solid {LARANJA};border-radius:8px;padding:20px 24px;">
          <div style="font-family:{MONO};font-size:11px;line-height:14px;letter-spacing:1.5px;text-transform:uppercase;color:{TINTA_2};margin-bottom:8px;">Seu código</div>
          <div style="font-family:{MONO};font-size:34px;line-height:40px;font-weight:600;letter-spacing:8px;color:{GRAFITE};">{codigo}</div>
        </td></tr>
      </table>
      <p style="margin:20px 0 0 0;font-family:{SANS};font-size:14px;line-height:21px;color:{TINTA_3};">{aviso}</p>
    </td></tr>
    <tr><td style="background:#FFFFFF;border-radius:0 0 14px 14px;padding:24px 32px 28px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td style="border-top:1px solid {CEU};padding-top:16px;font-family:{SANS};font-size:12px;line-height:18px;color:{TINTA_3};">
          <strong style="color:{GRAFITE};font-weight:600;">Kalman</strong> · As normas que valem para a sua empresa, com prazo e responsável.<br>
          E-mail automático: não responda.
        </td></tr>
      </table>
    </td></tr>
  </table>
</td></tr>
</table>
</body>
</html>"""


def handler(event, context=None):
    tipo = GATILHOS.get(event.get("triggerSource", ""))
    request = event.get("request") or {}
    codigo = request.get("codeParameter")
    if not tipo or not codigo:
        return event  # AdminCreateUser, MFA etc.: mensagem padrão do Cognito

    assunto, titulo, texto, aviso = TEXTOS[tipo]
    event.setdefault("response", {})
    event["response"]["emailSubject"] = assunto
    event["response"]["emailMessage"] = montar_html(titulo, texto, aviso, codigo)
    return event
