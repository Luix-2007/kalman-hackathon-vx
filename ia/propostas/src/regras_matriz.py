"""
Regras da matriz de obrigações

Usado em dois lugares, com o MESMO arquivo:
  - pipeline/matriz/src/etl_matriz.py  (job Glue, Python 3.9)
  - api/matriz/src/regras_matriz.py    (cópia na Lambda da API, Python 3.13;
                                        `make -C pipeline/matriz sync-regras` atualiza
                                        e um teste confere que as cópias são iguais)

Conteúdo:
  - prazo_json: formatos aceitos e validação
  - geração de tarefas de uma obrigação (periódicas e ligadas a outorga)
  - tarefa_id determinístico e em_risco
  - replay de eventos (importação, proposta, decisão) -> versões das obrigações

Datas são `datetime.date`; nada aqui lê relógio sozinho: `hoje` vem de fora.
"""

from __future__ import annotations

import calendar
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Iterable, List, Optional, Tuple

BRASILIA = timezone(timedelta(hours=-3))
HORIZONTE_DIAS = 365      # tarefas periódicas geradas até hoje + 12 meses
DIAS_RISCO = 7            # faltam 7 dias ou menos -> em risco

RECORRENCIAS = ("periodica", "por_evento", "continua")
PERIODICIDADES = ("mensal", "trimestral", "semestral", "anual", "bienal")
CRITICIDADES = ("baixa", "media", "alta")
STATUS_OBRIGACAO = ("proposta", "aprovada", "rejeitada", "revogada")
STATUS_TAREFA = ("aberta", "em_andamento", "concluida")
MUDANCAS = ("inclusao", "alteracao", "revogacao")

# Campos que definem o conteúdo de uma versão (o hash muda só se algum deles mudar).
CAMPOS_CONTEUDO = (
    "titulo", "fonte_ato", "fonte_dispositivo", "fonte_url", "trecho_citado", "orgao_sigla",
    "tema", "aplica_a", "recorrencia", "periodicidade", "prazo_regra", "prazo_json",
    "area_responsavel", "evidencia", "criticidade",
)


# ============================================================ prazo_json
#
# Lista de regras; cada uma é um objeto {"unidade": ..., "referencia": ..., "valor": ...}:
#
#   data_fixa    valor "DD/MM"   referencia ano_corrente | ano_seguinte_exercicio
#                (anual; bienal usa "ano_base": anos com (ano - ano_base) par)
#   dia_do_mes   valor N         referencia mes_corrente | mes_seguinte          (mensal)
#   dias_apos    valor N         referencia fim_mes | fim_trimestre | fim_semestre
#   dias_antes   valor N (opc.)  referencia validade_outorga, "tipo_outorga" opcional
#                (sem valor, usa a antecedencia_renovacao_dias da outorga)

REFERENCIAS = {
    "data_fixa": ("ano_corrente", "ano_seguinte_exercicio"),
    "dia_do_mes": ("mes_corrente", "mes_seguinte"),
    "dias_apos": ("fim_mes", "fim_trimestre", "fim_semestre"),
    "dias_antes": ("validade_outorga",),
}


def ler_prazo_json(bruto) -> List[dict]:
    """Aceita lista ou texto JSON. Levanta ValueError com a explicação."""
    if bruto is None or bruto == "":
        return []
    try:
        regras = json.loads(bruto) if isinstance(bruto, str) else bruto
    except ValueError:
        raise ValueError("prazo_json não é um JSON válido") from None
    if isinstance(regras, dict):
        regras = [regras]
    if not isinstance(regras, list):
        raise ValueError("prazo_json deve ser uma lista de regras")
    for i, r in enumerate(regras):
        if not isinstance(r, dict):
            raise ValueError(f"prazo_json[{i}] deve ser um objeto")
        unidade, ref = r.get("unidade"), r.get("referencia")
        if unidade not in REFERENCIAS:
            raise ValueError(f"prazo_json[{i}]: unidade desconhecida ({unidade})")
        if ref not in REFERENCIAS[unidade]:
            raise ValueError(f"prazo_json[{i}]: referencia {ref!r} não combina com {unidade}")
        valor = r.get("valor")
        if unidade == "data_fixa":
            _dia_mes(valor, i)
        elif unidade == "dias_antes" and valor in (None, ""):
            pass
        else:
            try:
                int(str(valor))
            except ValueError:
                raise ValueError(f"prazo_json[{i}]: valor deve ser inteiro") from None
    return regras


def _dia_mes(valor, i=0) -> Tuple[int, int]:
    try:
        dia, mes = (int(x) for x in str(valor).split("/"))
        date(2024, mes, dia)  # 2024 é bissexto: aceita 29/02
    except (ValueError, TypeError):
        raise ValueError(f"prazo_json[{i}]: data_fixa precisa de valor DD/MM") from None
    return dia, mes


def _dia_seguro(ano: int, mes: int, dia: int) -> date:
    return date(ano, mes, min(dia, calendar.monthrange(ano, mes)[1]))


def _fim_mes(ano: int, mes: int) -> date:
    return date(ano, mes, calendar.monthrange(ano, mes)[1])


def _soma_meses(ano: int, mes: int, n: int) -> Tuple[int, int]:
    total = ano * 12 + (mes - 1) + n
    return total // 12, total % 12 + 1


# ============================================================ tarefas

def tarefa_id(cnpj: str, obrigacao_id: str, unidade_id: Optional[str],
              outorga_id: Optional[str], vencimento: date) -> str:
    chave = "|".join([cnpj, obrigacao_id, unidade_id or "", outorga_id or "", vencimento.isoformat()])
    return hashlib.sha1(chave.encode("utf-8")).hexdigest()[:16]


def em_risco(vencimento: date, status: str, hoje: date, proposta_pendente: bool = False) -> bool:
    if status == "concluida":
        return False
    return (vencimento - hoje).days <= DIAS_RISCO or proposta_pendente


def _ocorrencias_periodicas(regra: dict, periodicidade: Optional[str], hoje: date) -> List[Tuple[date, str]]:
    """(vencimento, rótulo) dentro de [hoje, hoje + horizonte]."""
    fim = hoje + timedelta(days=HORIZONTE_DIAS)
    unidade, ref, valor = regra["unidade"], regra["referencia"], regra.get("valor")
    saida: List[Tuple[date, str]] = []

    if unidade == "data_fixa":
        dia, mes = _dia_mes(valor)
        base = int(regra.get("ano_base", 0) or 0)
        for ano in range(hoje.year - 2, fim.year + 2):
            if periodicidade == "bienal" and (ano - base) % 2:
                continue
            if ref == "ano_seguinte_exercicio":
                venc, rotulo = _dia_seguro(ano + 1, mes, dia), f"exercício {ano}"
            else:
                venc, rotulo = _dia_seguro(ano, mes, dia), str(ano)
            saida.append((venc, rotulo))

    elif unidade == "dia_do_mes":
        n = int(str(valor))
        desloc = 1 if ref == "mes_seguinte" else 0
        for k in range(-2, 15):
            a, m = _soma_meses(hoje.year, hoje.month, k)           # competência
            va, vm = _soma_meses(a, m, desloc)
            saida.append((_dia_seguro(va, vm, n), f"competência {m:02d}/{a}"))

    elif unidade == "dias_apos":
        n = int(str(valor))
        passo = {"fim_mes": 1, "fim_trimestre": 3, "fim_semestre": 6}[ref]
        for k in range(-3, 16):
            a, m = _soma_meses(hoje.year, hoje.month, k)
            if m % passo:
                continue
            if passo == 1:
                rotulo = f"competência {m:02d}/{a}"
            elif passo == 3:
                rotulo = f"{m // 3}º trimestre de {a}"
            else:
                rotulo = f"{m // 6}º semestre de {a}"
            saida.append((_fim_mes(a, m) + timedelta(days=n), rotulo))

    return sorted({(v, r) for v, r in saida if hoje <= v <= fim})


def gerar_tarefas(obrigacao: dict, outorgas: Iterable[dict], hoje: date) -> List[dict]:
    """Tarefas de uma versão aprovada de obrigação.

    obrigacao: cnpj, obrigacao_id, versao, titulo, recorrencia, periodicidade,
               prazo_json, aplica_a (lista de unidade_id), area_responsavel
    outorgas:  outorga_id, tipo, numero, unidade_id, validade (date ou AAAA-MM-DD),
               antecedencia_renovacao_dias
    Devolve dicts com as colunas de gold_db.matriz_tarefas, sem status/em_risco.
    """
    if obrigacao.get("recorrencia") in ("por_evento", "continua"):
        return []
    regras = ler_prazo_json(obrigacao.get("prazo_json"))
    aplica_a = list(obrigacao.get("aplica_a") or [])
    tarefas: Dict[str, dict] = {}

    def nova(venc: date, rotulo: str, unidade_id: Optional[str], outorga_id: Optional[str]):
        tid = tarefa_id(obrigacao["cnpj"], obrigacao["obrigacao_id"], unidade_id, outorga_id, venc)
        tarefas[tid] = {
            "cnpj": obrigacao["cnpj"],
            "tarefa_id": tid,
            "obrigacao_id": obrigacao["obrigacao_id"],
            "obrigacao_versao": int(obrigacao["versao"]),
            "unidade_id": unidade_id,
            "outorga_id": outorga_id,
            "descricao": f"{obrigacao['titulo']} — {rotulo}",
            "vencimento": venc,
            "area_responsavel": obrigacao.get("area_responsavel"),
        }

    for regra in regras:
        if regra["unidade"] == "dias_antes":
            tipo = regra.get("tipo_outorga")
            for o in outorgas:
                if tipo and o.get("tipo") != tipo:
                    continue
                if aplica_a and o.get("unidade_id") not in aplica_a:
                    continue
                validade = o.get("validade")
                if not validade:
                    continue
                validade = date.fromisoformat(validade) if isinstance(validade, str) else validade
                dias = regra.get("valor")
                dias = int(str(dias)) if dias not in (None, "") else int(o.get("antecedencia_renovacao_dias") or 0)
                venc = validade - timedelta(days=dias)
                if venc > hoje + timedelta(days=HORIZONTE_DIAS):
                    continue
                rotulo = f"{o.get('numero') or o['outorga_id']} (validade {validade.strftime('%d/%m/%Y')})"
                nova(venc, rotulo, o.get("unidade_id"), o["outorga_id"])
        else:
            for venc, rotulo in _ocorrencias_periodicas(regra, obrigacao.get("periodicidade"), hoje):
                for unidade_id in (aplica_a or [None]):
                    nova(venc, rotulo, unidade_id, None)

    return sorted(tarefas.values(), key=lambda t: (t["vencimento"], t["tarefa_id"]))


def consolidar_tarefas(geradas: List[dict], anteriores: List[dict], status_decididos: Dict[str, dict],
                       versoes_vigentes: Dict[Tuple[str, str], int], pendentes: set, hoje: date,
                       agora=None) -> List[dict]:
    """Junta as tarefas recém-geradas com o que já existia.

    - status e evidência vêm da última decisão de cada tarefa_id (ou da linha anterior)
    - tarefa concluída nunca some
    - tarefa aberta que venceu e não é mais gerada (passou de hoje) fica, se a versão
      da obrigação ainda for a vigente: é uma tarefa atrasada
    - tarefa aberta de versão antiga some (foi recalculada na versão nova)
    pendentes: {(cnpj, obrigacao_id)} com proposta aguardando decisão
    """
    final: Dict[str, dict] = {}
    anteriores_por_id = {t["tarefa_id"]: t for t in anteriores}

    for t in geradas:
        final[t["tarefa_id"]] = dict(t)
    for t in anteriores:
        if t["tarefa_id"] in final:
            continue
        chave = (t["cnpj"], t["obrigacao_id"])
        if t.get("status") == "concluida":
            final[t["tarefa_id"]] = dict(t)
        elif versoes_vigentes.get(chave) == t.get("obrigacao_versao") and _data(t["vencimento"]) < hoje:
            final[t["tarefa_id"]] = dict(t)

    for tid, t in final.items():
        antes = anteriores_por_id.get(tid, {})
        decidido = status_decididos.get(tid)
        t["status"] = (decidido or {}).get("status") or antes.get("status") or "aberta"
        t["evidencia_url"] = (decidido or {}).get("evidencia_url") or antes.get("evidencia_url")
        t["atualizada_em"] = (decidido or {}).get("em") or antes.get("atualizada_em") or agora
        t["vencimento"] = _data(t["vencimento"])
        t["em_risco"] = em_risco(t["vencimento"], t["status"], hoje,
                                 (t["cnpj"], t["obrigacao_id"]) in pendentes)
    return sorted(final.values(), key=lambda t: (t["cnpj"], t["vencimento"], t["tarefa_id"]))


def _data(v) -> date:
    return date.fromisoformat(v) if isinstance(v, str) else v


# ============================================================ versões (replay)

def hash_conteudo(o: dict) -> str:
    base = {k: o.get(k) for k in CAMPOS_CONTEUDO}
    base["aplica_a"] = sorted(base.get("aplica_a") or [])
    if isinstance(base.get("prazo_json"), (list, dict)):
        base["prazo_json"] = json.dumps(base["prazo_json"], sort_keys=True, ensure_ascii=False)
    return hashlib.sha1(json.dumps(base, sort_keys=True, ensure_ascii=False, default=str)
                        .encode("utf-8")).hexdigest()[:16]


class Matriz:
    """Estado das obrigações durante o replay. Uma linha por versão.

    Eventos, aplicados em ordem de ocorrência:
      importacao(cnpj, linhas, em, arquivo)   matriz do cliente: entra aprovada
      proposta(candidata, em)                 do LLM: entra como proposta
      decisao(cnpj, obrigacao_id, versao, decisao, usuario, em)
    """

    def __init__(self):
        self.versoes: Dict[Tuple[str, str], List[dict]] = {}   # (cnpj, obrigacao_id) -> versões
        self.historico: List[dict] = []                        # linhas de gold_db.matriz_versoes
        self.propostas_vistas: set = set()

    # -------------------------------------------------- consultas
    def vigente(self, cnpj: str, obrigacao_id: str) -> Optional[dict]:
        for v in reversed(self.versoes.get((cnpj, obrigacao_id), [])):
            if v["vigente"]:
                return v
        return None

    def linhas(self) -> List[dict]:
        return [v for vs in self.versoes.values() for v in vs]

    def pendentes(self) -> set:
        return {(v["cnpj"], v["obrigacao_id"]) for v in self.linhas() if v["status"] == "proposta"}

    def versoes_vigentes(self) -> Dict[Tuple[str, str], int]:
        return {(v["cnpj"], v["obrigacao_id"]): v["versao"] for v in self.linhas() if v["vigente"]}

    # -------------------------------------------------- eventos
    def _nova_versao(self, base: dict, status: str, mudanca: str, em: date,
                     alterada_por: Optional[str], proposta_id: Optional[str]) -> dict:
        chave = (base["cnpj"], base["obrigacao_id"])
        anteriores = self.versoes.setdefault(chave, [])
        linha = {k: base.get(k) for k in CAMPOS_CONTEUDO}
        linha.update({
            "cnpj": base["cnpj"], "obrigacao_id": base["obrigacao_id"],
            "versao": len(anteriores) + 1,
            "origem": base.get("origem"), "confianca": base.get("confianca"),
            "status": status, "mudanca": mudanca, "vigente": False,
            "incluida_em": em, "alterada_por": alterada_por, "proposta_id": proposta_id,
            "data_ato": base.get("data_ato"), "vigente_de": None, "vigente_ate": None,
            "decidida_por": None, "decidida_em": None,
        })
        linha["aplica_a"] = list(linha.get("aplica_a") or [])
        linha["hash_conteudo"] = hash_conteudo(linha)
        if status == "aprovada":
            for v in anteriores:
                _encerrar_vigencia(v, em)
            linha["vigente"], linha["vigente_de"] = True, em
        anteriores.append(linha)
        return linha

    def _registra(self, v: dict, evento: str, em: date, por: Optional[str], resumo: str,
                  alteracoes: Optional[List[dict]] = None):
        """Uma linha da linha do tempo. O ato vem da própria versão (o mesmo vale para a
        aprovação ou rejeição dela, que aponta para o ato que a originou)."""
        self.historico.append({
            "cnpj": v["cnpj"], "obrigacao_id": v["obrigacao_id"], "versao": v["versao"],
            "evento": evento, "status": v["status"], "origem": v.get("origem"),
            "ocorrido_em": em, "por": por, "resumo": resumo,
            "ato_id": v.get("alterada_por"), "ato_url": v.get("fonte_url"),
            "data_ato": v.get("data_ato"), "trecho_citado": v.get("trecho_citado"),
            "alteracoes": json.dumps(alteracoes, ensure_ascii=False) if alteracoes else None,
        })

    def importacao(self, cnpj: str, linhas: Iterable[dict], em: date, arquivo: str) -> None:
        for o in linhas:
            atual = self.vigente(cnpj, o["obrigacao_id"])
            if atual is not None and atual["hash_conteudo"] == hash_conteudo(o):
                continue
            mudanca = "inclusao" if atual is None else "alteracao"
            v = self._nova_versao({**o, "cnpj": cnpj, "origem": "matriz_importada"}, "aprovada",
                                  mudanca, em, f"matriz_importada:{arquivo}", None)
            alt = _alteracoes(atual, v)
            resumo = "incluída pela matriz do cliente" if atual is None else \
                "alterada pela matriz do cliente: " + ", ".join(a["campo"] for a in alt) or "sem mudança de conteúdo"
            self._registra(v, mudanca, em, arquivo, resumo, alt)

    def proposta(self, c: dict, em: date) -> Optional[dict]:
        """c: candidata válida do LLM (mudanca, proposta_id, fonte_ato e campos de conteúdo)."""
        # a mesma proposta (mesmo arquivo e índice) para a mesma empresa conta uma vez; o mesmo
        # ato pode trazer propostas para várias empresas, com índices que se repetem
        chave = (c["cnpj"], c["proposta_id"])
        if chave in self.propostas_vistas:
            return None
        self.propostas_vistas.add(chave)
        mudanca = c["mudanca"]
        if mudanca == "inclusao":
            base = dict(c)
        else:
            atual = self.vigente(c["cnpj"], c["obrigacao_id"])
            if atual is None:
                return None
            base = dict(atual)
            if mudanca == "alteracao":
                base.update({k: c[k] for k in CAMPOS_CONTEUDO if c.get(k) not in (None, "", [])})
                base["fonte_ato"], base["fonte_url"] = c.get("fonte_ato"), c.get("fonte_url")
            base.update({"origem": "llm", "confianca": c.get("confianca")})
        base["data_ato"] = c.get("data_ato")
        v = self._nova_versao(base, "proposta", mudanca, em, c.get("fonte_ato"), c["proposta_id"])
        anterior = self.vigente(c["cnpj"], c["obrigacao_id"])
        alt = _alteracoes(anterior, v) if mudanca == "alteracao" else []
        resumo = {"inclusao": "nova obrigação proposta pelo LLM",
                  "revogacao": "revogação proposta pelo LLM"}.get(mudanca) or \
            "alteração proposta pelo LLM: " + ", ".join(a["campo"] for a in alt) or "sem mudança de conteúdo"
        self._registra(v, mudanca, em, c.get("fonte_ato"), resumo, alt)
        return v

    def decisao(self, cnpj: str, obrigacao_id: str, versao: int, decisao: str,
                usuario: Optional[str], em) -> Optional[dict]:
        vs = self.versoes.get((cnpj, obrigacao_id), [])
        alvo = next((v for v in vs if v["versao"] == int(versao)), None)
        if alvo is None or alvo["status"] != "proposta":
            return None
        aplicar_decisao(vs, alvo, decisao, usuario, em)
        evento = "aprovacao" if decisao == "aprovar" else "rejeicao"
        self._registra(alvo, evento, data_brasilia(em), usuario,
                       f"{'aprovada' if decisao == 'aprovar' else 'rejeitada'} pelo dono")
        return alvo


def data_brasilia(ts) -> date:
    """Dia em Brasília. Datetime sem fuso é UTC (como o Athena e o PyIceberg gravam)."""
    if isinstance(ts, datetime):
        return ts.replace(tzinfo=timezone.utc).astimezone(BRASILIA).date() if ts.tzinfo is None \
            else ts.astimezone(BRASILIA).date()
    return ts


def _encerrar_vigencia(v: dict, dia: date) -> None:
    if v["vigente"]:
        v["vigente"], v["vigente_ate"] = False, dia


def aplicar_decisao(versoes: List[dict], alvo: dict, decisao: str, usuario: Optional[str], em) -> None:
    """Transição de status e de vigência. O job (replay) e a API (que grava o resultado com
    UPDATE no Athena, ver sql_matriz.atualizar_versoes) usam esta mesma função."""
    dia = data_brasilia(em)
    alvo["decidida_por"], alvo["decidida_em"] = usuario, em
    if decisao == "rejeitar":
        alvo["status"] = "rejeitada"
        return
    for v in versoes:
        if v is not alvo:
            _encerrar_vigencia(v, dia)
    if alvo["mudanca"] == "revogacao":
        alvo["status"] = "revogada"
        return
    alvo["status"], alvo["vigente"] = "aprovada", True
    alvo["vigente_de"], alvo["vigente_ate"] = dia, None


def vigente_em(versoes: List[dict], dia: date) -> Optional[dict]:
    """Versão em vigor num dia: vigente_de <= dia < vigente_ate (sem fim = ainda vigente)."""
    for v in versoes:
        if v.get("vigente_de") and v["vigente_de"] <= dia and (v.get("vigente_ate") is None or dia < v["vigente_ate"]):
            return v
    return None


def _alteracoes(antes: Optional[dict], depois: dict) -> List[dict]:
    """O que mudou entre duas versões: [{"campo", "antes", "depois"}], só campos de conteúdo."""
    if antes is None:
        return []
    mudou = []
    for k in CAMPOS_CONTEUDO:
        a, d = antes.get(k), depois.get(k)
        if k == "aplica_a":
            a, d = sorted(a or []), sorted(d or [])
        if a != d:
            mudou.append({"campo": k, "antes": a, "depois": d})
    return mudou
