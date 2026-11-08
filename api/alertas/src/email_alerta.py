"""
Aviso de mudanças: o resumo diário que cada pessoa recebe por e-mail (assunto, HTML e texto puro).

Monta o e-mail a partir de um dicionário (formato no README desta pasta e em `montar`). Não envia nada: o envio real
depende de SES com remetente próprio, que ainda não existe. Mesmas decisões do e-mail do código
(api/cnpj-cadastro/src/email_cognito.py):

  - identidade "Laudo": grafite #0E1A24, céu #BFD9EA / #EAF2F7, branco; laranja #FF5A1F só no que pede ação
    (o que espera decisão, o botão e a tarefa atrasada);
  - HTML de e-mail: tabelas, estilo inline, ~600 px, sem SVG; o logo é um PNG público (LOGO_URL), sem <title> e sem <h1>;
    Instrument Sans e IBM Plex Mono só quando o leitor tiver, senão Helvetica/Arial e Consolas/Courier;
  - tudo que vem de dado passa por html.escape; link só http(s), qualquer outro esquema é descartado.

Seções vazias somem. Sem nada para decidir, nada aprovado e nenhuma tarefa em risco, `montar` devolve None: não há
e-mail (a linha da leitura do DOU sozinha não justifica um aviso).
"""

import re
from datetime import date, datetime
import os
from html import escape
from urllib.parse import urlparse

GRAFITE = "#0E1A24"
LARANJA = "#FF5A1F"
CEU = "#BFD9EA"
CEU_CLARO = "#EAF2F7"
TINTA_2 = "#45525E"
TINTA_3 = "#66727D"

# Logo em PNG (Gmail e Outlook bloqueiam SVG), servido pelo front publicado na Lovable. O alt "Kalman" aparece em
# branco sobre o grafite quando o cliente de e-mail bloqueia imagens. Trocar por LOGO_URL no ambiente da Lambda.
LOGO_URL = os.environ.get("LOGO_URL", "https://kalman-vx.lovable.app/marca/kalman-email.png")
SANS = "'Instrument Sans', 'Helvetica Neue', Helvetica, Arial, sans-serif"
MONO = "'IBM Plex Mono', Consolas, 'Courier New', monospace"

DIAS_DE_RISCO = 3  # atrasada ou vencendo em até 3 dias (o mesmo critério de `em_risco` no dash)
TRECHO_MAX = 240

MUDANCA = {"inclusao": "Nova obrigação", "alteracao": "Alteração", "revogacao": "Revogação"}

# Nome do campo da Obrigacao → rótulo no antes/depois. Campos de fonte ficam de fora: a linha da fonte já mostra o ato novo.
CAMPOS = {
    "titulo": "Obrigação",
    "prazo_regra": "Prazo",
    "periodicidade": "Periodicidade",
    "recorrencia": "Recorrência",
    "area_responsavel": "Responsável",
    "evidencia": "Evidência",
    "criticidade": "Criticidade",
    "aplica_a": "Aplica-se a",
    "tema": "Tema",
}
CAMPOS_OCULTOS = {"fonte_ato", "fonte_dispositivo", "fonte_url", "trecho_citado", "orgao_sigla", "versao", "status",
                  "vigente", "confianca", "prazo_json"}


# ─────────────────────────── utilidades ───────────────────────────

def _e(valor) -> str:
    """Texto de dado pronto para o HTML (None vira vazio)."""
    return "" if valor is None else escape(str(valor), quote=True)


def _url(valor) -> str | None:
    """Só http(s) com host; o resto (javascript:, data:, relativo) some."""
    if not valor:
        return None
    u = urlparse(str(valor).strip())
    return str(valor).strip() if u.scheme in ("http", "https") and u.netloc else None


def _data(valor) -> date | None:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except (TypeError, ValueError):
        return None


def _dma(valor) -> str:
    """AAAA-MM-DD → DD/MM/AAAA; o que não for data ISO passa como veio."""
    d = _data(valor)
    return d.strftime("%d/%m/%Y") if d else ("" if valor is None else str(valor))


def _numero(n) -> str:
    return f"{int(n):,}".replace(",", ".")


def _plural(n: int, um: str, varios: str) -> str:
    return f"{n} {um if n == 1 else varios}"


def _curto(texto, limite: int = TRECHO_MAX) -> str:
    texto = " ".join(str(texto or "").split())
    if len(texto) <= limite:
        return texto
    return texto[:limite].rsplit(" ", 1)[0].rstrip(",;:.") + "…"


def _valor(v) -> str:
    if v is None or v == "" or v == []:
        return "(vazio)"
    if isinstance(v, (list, tuple)):
        return ", ".join(str(x) for x in v)
    return str(v)


def _fonte(o: dict) -> str:
    """'REN ANEEL nº 1.174/2026 · art. 166-A · DOU 04/11/2026, p. 68' (só o que existir)."""
    partes = [o.get("fonte_ato"), o.get("fonte_dispositivo")]
    if o.get("data_ato"):
        dou = f"DOU {_dma(o['data_ato'])}"
        if o.get("pagina"):
            dou += f", p. {o['pagina']}"
        partes.append(dou)
    return " · ".join(str(p) for p in partes if p)


def _alteracoes(o: dict) -> list[tuple[str, str, str]]:
    saida = []
    for a in o.get("alteracoes") or []:
        campo = a.get("campo", "")
        if campo in CAMPOS_OCULTOS or a.get("antes") == a.get("depois"):
            continue
        saida.append((CAMPOS.get(campo, campo.replace("_", " ").capitalize()), _valor(a.get("antes")), _valor(a.get("depois"))))
    return saida


def _situacao(vencimento, hoje: date) -> tuple[str, bool]:
    """('Atrasada há 1 dia', True) / ('Vence em 2 dias', False). O bool marca o que já passou do prazo."""
    d = _data(vencimento)
    if not d:
        return "Sem data", False
    dias = (d - hoje).days
    if dias < 0:
        return f"Atrasada há {_plural(-dias, 'dia', 'dias')}", True
    if dias == 0:
        return "Vence hoje", False
    if dias == 1:
        return "Vence amanhã", False
    return f"Vence em {dias} dias", False


def tarefas_em_risco(tarefas: list[dict], hoje: date) -> list[dict]:
    """Abertas ou em andamento, atrasadas ou vencendo em até DIAS_DE_RISCO dias, da mais urgente para a menos."""
    saida = []
    for t in tarefas or []:
        d = _data(t.get("vencimento"))
        if t.get("status") == "concluida" or not d or (d - hoje).days > DIAS_DE_RISCO:
            continue
        saida.append(t)
    return sorted(saida, key=lambda t: str(t.get("vencimento")))


# ─────────────────────────── assunto e título ───────────────────────────

def _contagens(propostas, aprovadas, risco) -> list[str]:
    partes = []
    if propostas:
        partes.append(_plural(len(propostas), "mudança para decidir", "mudanças para decidir"))
    if risco:
        partes.append(_plural(len(risco), "tarefa em risco", "tarefas em risco"))
    if aprovadas:
        partes.append(_plural(len(aprovadas), "mudança aprovada", "mudanças aprovadas"))
    return partes


def _titulo(propostas, aprovadas, risco) -> str:
    if propostas:
        n = len(propostas)
        return "1 mudança espera a sua decisão" if n == 1 else f"{n} mudanças esperam a sua decisão"
    if risco:
        n = len(risco)
        return "1 tarefa precisa de atenção" if n == 1 else f"{n} tarefas precisam de atenção"
    n = len(aprovadas)
    return "1 mudança entrou na matriz" if n == 1 else f"{n} mudanças entraram na matriz"


# ─────────────────────────── HTML ───────────────────────────

def _rotulo(texto: str, contagem: int, cor: str = TINTA_2) -> str:
    return (f'<div style="font-family:{MONO};font-size:11px;line-height:14px;letter-spacing:1.5px;text-transform:uppercase;'
            f'color:{cor};margin:0 0 12px 0;">{_e(texto)} · {contagem}</div>')


def _linha_fonte(o: dict) -> str:
    fonte = _fonte(o)
    link = _url(o.get("fonte_url"))
    if not fonte and not link:
        return ""
    ver = (f' · <a href="{_e(link)}" style="color:{GRAFITE};text-decoration:underline;">ver no DOU</a>' if link else "")
    return (f'<div style="font-family:{MONO};font-size:12px;line-height:18px;color:{TINTA_2};margin-top:10px;">'
            f'{_e(fonte)}{ver}</div>')


def _html_alteracoes(o: dict) -> str:
    linhas = []
    for rotulo, antes, depois in _alteracoes(o):
        linhas.append(
            f'<div style="font-family:{SANS};font-size:14px;line-height:21px;color:{GRAFITE};margin-top:8px;">'
            f'<span style="font-family:{MONO};font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{TINTA_2};">{_e(rotulo)}</span><br>'
            f'<span style="color:{TINTA_3};text-decoration:line-through;">{_e(antes)}</span>'
            f' <span style="color:{TINTA_3};">&rarr;</span> <strong style="font-weight:600;">{_e(depois)}</strong></div>')
    return "".join(linhas)


def _campo(rotulo: str, valor) -> str:
    if not valor:
        return ""
    return (f'<div style="font-family:{SANS};font-size:14px;line-height:21px;color:{GRAFITE};margin-top:8px;">'
            f'<span style="font-family:{MONO};font-size:11px;letter-spacing:1px;text-transform:uppercase;color:{TINTA_2};">{_e(rotulo)}</span><br>'
            f'{_e(valor)}</div>')


def _cartao_proposta(o: dict) -> str:
    tipo = MUDANCA.get(o.get("mudanca"), "Mudança")
    diff = _html_alteracoes(o)
    corpo = diff or _campo("Prazo", o.get("prazo_regra"))
    corpo += _campo("Responsável", o.get("area_responsavel"))
    trecho = ""
    if o.get("trecho_citado"):
        trecho = (f'<div style="font-family:{SANS};font-size:13px;line-height:20px;font-style:italic;color:{TINTA_2};'
                  f'margin-top:10px;padding-left:10px;border-left:2px solid {CEU};">&ldquo;{_e(_curto(o["trecho_citado"]))}&rdquo;</div>')
    return f"""<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="margin:0 0 12px 0;">
        <tr><td class="k-cartao" style="background:{CEU_CLARO};border-left:4px solid {LARANJA};border-radius:8px;padding:16px 20px;">
          <div style="font-family:{MONO};font-size:11px;line-height:14px;letter-spacing:1.5px;text-transform:uppercase;color:{LARANJA};font-weight:600;">{_e(tipo)}</div>
          <div style="font-family:{SANS};font-size:17px;line-height:23px;font-weight:600;color:{GRAFITE};margin-top:6px;">{_e(o.get("titulo"))}</div>
          {corpo}{trecho}{_linha_fonte(o)}
        </td></tr>
      </table>"""


def _botao(texto: str, url: str | None) -> str:
    if not url:
        return ""
    return f"""<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:4px 0 0 0;">
        <tr><td bgcolor="{LARANJA}" style="background:{LARANJA};border-radius:8px;">
          <a href="{_e(url)}" style="display:inline-block;padding:12px 22px;font-family:{SANS};font-size:15px;line-height:20px;font-weight:600;color:#FFFFFF;text-decoration:none;border-radius:8px;">{_e(texto)}</a>
        </td></tr>
      </table>"""


def _item_aprovado(o: dict, ultimo: bool) -> str:
    meta = [MUDANCA.get(o.get("mudanca"), "Mudança")]
    if o.get("vigente_de"):
        meta.append(f"em vigor desde {_dma(o['vigente_de'])}")
    if o.get("aprovada_por"):
        meta.append(f"aprovada por {o['aprovada_por']}")
    if o.get("tarefas_criadas"):
        meta.append(_plural(int(o["tarefas_criadas"]), "tarefa criada", "tarefas criadas"))
    if o.get("tarefas_recalculadas"):
        meta.append(_plural(int(o["tarefas_recalculadas"]), "tarefa recalculada", "tarefas recalculadas"))
    borda = "" if ultimo else f"border-bottom:1px solid {CEU};"
    return f"""<tr><td style="padding:12px 0;{borda}">
          <div style="font-family:{SANS};font-size:15px;line-height:22px;font-weight:600;color:{GRAFITE};">{_e(o.get("titulo"))}</div>
          <div style="font-family:{SANS};font-size:13px;line-height:19px;color:{TINTA_2};margin-top:2px;">{_e(" · ".join(meta))}</div>
          {_html_alteracoes(o)}{_linha_fonte(o)}
        </td></tr>"""


def _item_tarefa(t: dict, hoje: date, ultimo: bool) -> str:
    situacao, atrasada = _situacao(t.get("vencimento"), hoje)
    cor = LARANJA if atrasada else GRAFITE
    d = _data(t.get("vencimento"))
    dia = d.strftime("%d/%m") if d else "--/--"
    meta = " · ".join(x for x in (t.get("area_responsavel"), "em andamento" if t.get("status") == "em_andamento" else None) if x)
    borda = "" if ultimo else f"border-bottom:1px solid {CEU};"
    return f"""<tr>
          <td width="64" valign="top" style="padding:12px 12px 12px 0;{borda}font-family:{MONO};font-size:15px;line-height:22px;font-weight:600;color:{cor};white-space:nowrap;">{_e(dia)}</td>
          <td valign="top" style="padding:12px 0;{borda}">
            <div style="font-family:{SANS};font-size:15px;line-height:22px;color:{GRAFITE};">{_e(t.get("descricao"))}</div>
            <div style="font-family:{SANS};font-size:13px;line-height:19px;color:{TINTA_2};margin-top:2px;"><strong style="font-weight:600;color:{cor};">{_e(situacao)}</strong>{" · " + _e(meta) if meta else ""}</div>
          </td>
        </tr>"""


def _secao(conteudo: str) -> str:
    return f"""<tr><td class="k-pad" style="background:#FFFFFF;padding:8px 32px 20px 32px;">
      {conteudo}
    </td></tr>"""


def montar_html(d: dict) -> str:
    propostas, aprovadas, risco, hoje = d["propostas"], d["aprovadas"], d["risco"], d["hoje"]
    painel, ajustes = d["painel_url"], d["alertas_url"]
    titulo = _titulo(propostas, aprovadas, risco)
    resumo = " · ".join(_contagens(propostas, aprovadas, risco))
    empresa = d.get("empresa")
    cabecalho = " · ".join(x for x in ("Resumo de " + hoje.strftime("%d/%m/%Y"), empresa) if x)

    leitura = ""
    lida = d.get("leitura")
    if lida and lida.get("atos") is not None:
        txt = f"{_numero(lida['atos'])} atos lidos no DOU"
        if lida.get("relevantes") is not None:
            txt += f" · {_numero(lida['relevantes'])} relevantes"
        if lida.get("periodo"):
            txt += f" · {lida['periodo']}"
        leitura = (f'<div style="font-family:{MONO};font-size:12px;line-height:18px;color:{TINTA_2};margin-top:14px;'
                   f'padding-top:12px;border-top:1px solid {CEU};">{_e(txt)}</div>')

    secoes = []
    if propostas:
        secoes.append(_secao(
            _rotulo("Para decidir", len(propostas), LARANJA)
            + "".join(_cartao_proposta(o) for o in propostas)
            + '<p style="margin:4px 0 12px 0;font-family:' + SANS + f';font-size:14px;line-height:21px;color:{TINTA_2};">'
            + "A IA propõe; a mudança só entra na matriz depois que alguém aprova.</p>"
            + _botao("Revisar no painel", painel)))
    if risco:
        itens = "".join(_item_tarefa(t, hoje, i == len(risco) - 1) for i, t in enumerate(risco))
        secoes.append(_secao(
            _rotulo("Tarefas em risco", len(risco))
            + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid {CEU};">{itens}</table>'))
    if aprovadas:
        itens = "".join(_item_aprovado(o, i == len(aprovadas) - 1) for i, o in enumerate(aprovadas))
        secoes.append(_secao(
            _rotulo("Mudanças aprovadas", len(aprovadas))
            + f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="border-top:1px solid {CEU};">{itens}</table>'))

    links = []
    if painel:
        links.append(f'<a href="{_e(painel)}" style="color:{GRAFITE};text-decoration:underline;">Abrir o painel</a>')
    if ajustes:
        links.append(f'<a href="{_e(ajustes)}" style="color:{GRAFITE};text-decoration:underline;">Ajustar alertas</a>')
    por_que = (f"Você recebe este resumo porque acompanha {_e(empresa)} no Kalman." if empresa
               else "Você recebe este resumo porque acompanha uma empresa no Kalman.")

    return f"""<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<meta name="supported-color-schemes" content="light">
<style>
@media only screen and (max-width: 480px) {{
  .k-pad {{ padding-left: 20px !important; padding-right: 20px !important; }}
  .k-cartao {{ padding: 14px 16px !important; }}
  .k-externo {{ padding: 16px 8px !important; }}
}}
</style>
</head>
<body style="margin:0;padding:0;background:{CEU_CLARO};-webkit-text-size-adjust:100%;">
<div style="display:none;max-height:0;overflow:hidden;opacity:0;color:{CEU_CLARO};">{_e(resumo)}</div>
<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="background:{CEU_CLARO};">
<tr><td class="k-externo" align="center" style="padding:32px 16px;">
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="max-width:600px;">
    <tr><td class="k-pad" style="background:{GRAFITE};border-radius:14px 14px 0 0;padding:22px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0"><tr>
        <td>
            <img src="{LOGO_URL}" width="160" height="42" alt="Kalman" style="display:block;border:0;outline:none;text-decoration:none;height:42px;width:160px;font-family:{SANS};font-size:22px;font-weight:700;color:#FFFFFF;">
        </td>
        <td align="right" style="font-family:{MONO};font-size:11px;line-height:14px;letter-spacing:1.5px;text-transform:uppercase;color:{CEU};">Aviso de mudanças</td>
      </tr></table>
    </td></tr>
    <tr><td class="k-pad" style="background:#FFFFFF;padding:32px 32px 20px 32px;">
      <div style="font-family:{MONO};font-size:11px;line-height:14px;letter-spacing:1.5px;text-transform:uppercase;color:{TINTA_2};margin-bottom:10px;">{_e(cabecalho)}</div>
      <div role="heading" aria-level="1" style="margin:0;font-family:{SANS};font-size:26px;line-height:31px;font-weight:600;letter-spacing:-0.6px;color:{GRAFITE};">{_e(titulo)}</div>
      {leitura}
    </td></tr>
    {"".join(secoes)}
    <tr><td class="k-pad" style="background:#FFFFFF;border-radius:0 0 14px 14px;padding:12px 32px 28px 32px;">
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0">
        <tr><td style="border-top:1px solid {CEU};padding-top:16px;font-family:{SANS};font-size:12px;line-height:18px;color:{TINTA_3};">
          {por_que} Ele sai todo dia às 08:00 quando há algo novo.{"<br>" + " · ".join(links) if links else ""}<br><br>
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


# ─────────────────────────── texto puro ───────────────────────────

def montar_texto(d: dict) -> str:
    propostas, aprovadas, risco, hoje = d["propostas"], d["aprovadas"], d["risco"], d["hoje"]
    empresa = d.get("empresa")
    l = ["KALMAN · AVISO DE MUDANÇAS", " · ".join(x for x in ("Resumo de " + hoje.strftime("%d/%m/%Y"), empresa) if x), "",
         _titulo(propostas, aprovadas, risco)]
    lida = d.get("leitura")
    if lida and lida.get("atos") is not None:
        txt = f"{_numero(lida['atos'])} atos lidos no DOU"
        if lida.get("relevantes") is not None:
            txt += f" · {_numero(lida['relevantes'])} relevantes"
        if lida.get("periodo"):
            txt += f" · {lida['periodo']}"
        l.append(txt)

    def fonte(o):
        f = _fonte(o)
        link = _url(o.get("fonte_url"))
        if f:
            l.append(f"   Fonte: {f}")
        if link:
            l.append(f"   {link}")

    if propostas:
        l += ["", f"PARA DECIDIR · {len(propostas)}", ""]
        for o in propostas:
            l.append(f"[{MUDANCA.get(o.get('mudanca'), 'Mudança')}] {o.get('titulo') or ''}")
            diff = _alteracoes(o)
            for rotulo, antes, depois in diff:
                l.append(f"   {rotulo}: {antes} → {depois}")
            if not diff and o.get("prazo_regra"):
                l.append(f"   Prazo: {o['prazo_regra']}")
            if o.get("area_responsavel"):
                l.append(f"   Responsável: {o['area_responsavel']}")
            if o.get("trecho_citado"):
                l.append(f"   “{_curto(o['trecho_citado'])}”")
            fonte(o)
            l.append("")
        l.append("A IA propõe; a mudança só entra na matriz depois que alguém aprova.")
        if d["painel_url"]:
            l.append(f"Revisar no painel: {d['painel_url']}")
    if risco:
        l += ["", f"TAREFAS EM RISCO · {len(risco)}", ""]
        for t in risco:
            situacao, _ = _situacao(t.get("vencimento"), hoje)
            extra = " · ".join(x for x in (t.get("area_responsavel"), "em andamento" if t.get("status") == "em_andamento" else None) if x)
            l.append(f"{_dma(t.get('vencimento'))}  {t.get('descricao') or ''}")
            l.append(f"   {situacao}{' · ' + extra if extra else ''}")
    if aprovadas:
        l += ["", f"MUDANÇAS APROVADAS · {len(aprovadas)}", ""]
        for o in aprovadas:
            l.append(f"[{MUDANCA.get(o.get('mudanca'), 'Mudança')}] {o.get('titulo') or ''}")
            meta = []
            if o.get("vigente_de"):
                meta.append(f"em vigor desde {_dma(o['vigente_de'])}")
            if o.get("aprovada_por"):
                meta.append(f"aprovada por {o['aprovada_por']}")
            if o.get("tarefas_criadas"):
                meta.append(_plural(int(o["tarefas_criadas"]), "tarefa criada", "tarefas criadas"))
            if o.get("tarefas_recalculadas"):
                meta.append(_plural(int(o["tarefas_recalculadas"]), "tarefa recalculada", "tarefas recalculadas"))
            if meta:
                l.append("   " + " · ".join(meta))
            for rotulo, antes, depois in _alteracoes(o):
                l.append(f"   {rotulo}: {antes} → {depois}")
            fonte(o)
            l.append("")

    l += ["", "—",
          f"Você recebe este resumo porque acompanha {empresa} no Kalman." if empresa
          else "Você recebe este resumo porque acompanha uma empresa no Kalman.",
          "Ele sai todo dia às 08:00 quando há algo novo."]
    if d["painel_url"]:
        l.append(f"Abrir o painel: {d['painel_url']}")
    if d["alertas_url"]:
        l.append(f"Ajustar alertas: {d['alertas_url']}")
    l += ["", "Kalman · As normas que valem para a sua empresa, com prazo e responsável.", "E-mail automático: não responda."]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(l)).strip() + "\n"


# ─────────────────────────── entrada ───────────────────────────

def montar(dados: dict) -> dict | None:
    """
    Monta o aviso do dia. Devolve {"assunto", "html", "texto"} ou None quando não há o que avisar.

    Chaves de `dados` (todas opcionais; detalhes no README):
      empresa, hoje (AAAA-MM-DD; padrão = hoje), painel_url, alertas_url,
      leitura {atos, relevantes, periodo},
      propostas [Obrigacao + alteracoes [{campo, antes, depois}] + pagina],
      aprovadas [idem + aprovada_por, tarefas_criadas, tarefas_recalculadas],
      tarefas [Tarefa]  (o módulo filtra: não concluídas, atrasadas ou vencendo em até 3 dias).
    """
    hoje = _data(dados.get("hoje")) or date.today()
    d = {
        "empresa": dados.get("empresa"),
        "hoje": hoje,
        "painel_url": _url(dados.get("painel_url")),
        "alertas_url": _url(dados.get("alertas_url")),
        "leitura": dados.get("leitura"),
        "propostas": list(dados.get("propostas") or []),
        "aprovadas": list(dados.get("aprovadas") or []),
        "risco": tarefas_em_risco(dados.get("tarefas") or [], hoje),
    }
    if not (d["propostas"] or d["aprovadas"] or d["risco"]):
        return None
    contagens = " · ".join(_contagens(d["propostas"], d["aprovadas"], d["risco"]))
    assunto = f"{d['empresa']}: {contagens}" if d["empresa"] else f"Kalman: {contagens}"
    return {"assunto": assunto, "html": montar_html(d), "texto": montar_texto(d)}
