"""
Perfil regulatório: os campos que o dono preenche em `dados` (PATCH /cadastro/me).

O filtro da matriz de obrigações usa estes campos junto com os dados da Receita
(`empresa`: CNAEs, natureza jurídica, porte, UF). Cada campo tem um tipo:

    texto               str
    lista de textos     list[str]
    lista de objetos    list[dict] com chaves conhecidas e `id` único

`validar(dados)` devolve a lista de erros (vazia = ok). `None` em qualquer campo
significa "apagar o campo" e é sempre aceito.
"""

from __future__ import annotations

import re
from datetime import date
from typing import Callable

MAX_TEXTO = 500
MAX_ITENS = 200

UFS = {
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS", "MG", "PA",
    "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
}
EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
IBGE_MUNICIPIO = re.compile(r"^\d{7}$")
ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,49}$")

Validador = Callable[[object], "str | None"]


# ---------------------------------------------------------------- tipos simples

def texto(max_len: int = MAX_TEXTO, padrao: re.Pattern | None = None, nome: str = "texto") -> Validador:
    def v(valor):
        if not isinstance(valor, str):
            return f"esperado {nome}"
        if not valor.strip() or len(valor) > max_len:
            return f"{nome} vazio ou com mais de {max_len} caracteres"
        if padrao and not padrao.match(valor):
            return f"{nome} em formato inválido"
        return None
    return v


def data_iso(valor) -> str | None:
    if not isinstance(valor, str):
        return "esperada data AAAA-MM-DD"
    try:
        date.fromisoformat(valor)
    except ValueError:
        return "esperada data AAAA-MM-DD"
    return None


def inteiro(minimo: int = 0, maximo: int = 3650) -> Validador:
    def v(valor):
        # o PATCH usa parse_float=Decimal: 120 chega como int, 120.0 como Decimal
        if isinstance(valor, bool) or not isinstance(valor, int):
            return "esperado número inteiro"
        if not minimo <= valor <= maximo:
            return f"esperado inteiro entre {minimo} e {maximo}"
        return None
    return v


def lista_textos(item: Validador | None = None, permitidos: set[str] | None = None) -> Validador:
    item = item or texto(200)

    def v(valor):
        if not isinstance(valor, list):
            return "esperada lista de textos"
        if len(valor) > MAX_ITENS:
            return f"no máximo {MAX_ITENS} itens"
        for i, x in enumerate(valor):
            erro = item(x)
            if erro:
                return f"item {i}: {erro}"
            if permitidos is not None and x not in permitidos:
                return f"item {i}: valor não permitido ({x})"
        if len(set(valor)) != len(valor):
            return "itens repetidos"
        return None
    return v


def lista_objetos(chaves: dict[str, Validador], obrigatorias: set[str]) -> Validador:
    """Lista de objetos com `id` único. Chave desconhecida é erro (evita lixo no item)."""
    def v(valor):
        if not isinstance(valor, list):
            return "esperada lista de objetos"
        if len(valor) > MAX_ITENS:
            return f"no máximo {MAX_ITENS} itens"
        ids = set()
        for i, obj in enumerate(valor):
            if not isinstance(obj, dict):
                return f"item {i}: esperado objeto"
            faltando = obrigatorias - obj.keys()
            if faltando:
                return f"item {i}: faltou {', '.join(sorted(faltando))}"
            for k, x in obj.items():
                if k not in chaves:
                    return f"item {i}: chave desconhecida ({k})"
                if x is None:
                    continue
                erro = chaves[k](x)
                if erro:
                    return f"item {i}, {k}: {erro}"
            if obj["id"] in ids:
                return f"item {i}: id repetido ({obj['id']})"
            ids.add(obj["id"])
        return None
    return v


# ---------------------------------------------------------------- campos do perfil

UNIDADES = lista_objetos(
    {"id": texto(50, ID, "id"), "nome": texto(200), "tipo": texto(100), "tags": lista_textos()},
    obrigatorias={"id", "nome"},
)
OUTORGAS = lista_objetos(
    {
        "id": texto(50, ID, "id"),
        "tipo": texto(100),
        "numero": texto(100),
        "orgao": texto(50),
        "objeto": texto(500),
        "unidade_id": texto(50, ID, "id"),
        "validade": data_iso,
        "antecedencia_renovacao_dias": inteiro(0, 3650),
    },
    obrigatorias={"id", "tipo", "orgao"},
)
AREAS = lista_objetos(
    {"id": texto(50, ID, "id"), "nome": texto(200), "responsavel": texto(200), "email": texto(254, EMAIL, "e-mail")},
    obrigatorias={"id", "nome"},
)

CAMPOS: dict[str, Validador] = {
    # mantidos do formulário anterior
    "nome_fantasia": texto(200),
    "faixa_funcionarios": texto(50),
    # perfil regulatório
    "email_alertas": texto(254, EMAIL, "e-mail"),
    "setor": texto(100),
    "ufs_atuacao": lista_textos(texto(2), permitidos=UFS),
    "municipios_atuacao": lista_textos(texto(7, IBGE_MUNICIPIO, "código IBGE de 7 dígitos")),
    "orgaos_fiscalizadores": lista_textos(texto(50)),
    "outorgas": OUTORGAS,
    "unidades": UNIDADES,
    "areas": AREAS,
    "temas_interesse": lista_textos(),
    "temas_fora_escopo": lista_textos(),
    "certificacoes": lista_textos(),
    # conferência dos dados da Receita na tela do painel (quem confirmou e quando)
    "conferido_em": texto(40),
    "conferido_por": texto(254, EMAIL, "e-mail"),
    "conferido_por_nome": texto(200),
}

# Listas que ligam a organização ao lake: o perfil é exportado para a matriz chaveado
# pelo CNPJ e as obrigações e tarefas são derivadas dele (ver cadastro.py).
CAMPOS_DO_LAKE = ("unidades", "outorgas", "areas")


def validar(dados: dict) -> dict[str, str]:
    """{campo: erro} para os campos inválidos. Campo fora de CAMPOS não é checado aqui."""
    erros = {}
    for campo, valor in dados.items():
        if valor is None or campo not in CAMPOS:
            continue
        erro = CAMPOS[campo](valor)
        if erro:
            erros[campo] = erro
    return erros


def tem_perfil_no_lake(dados: dict | None) -> bool:
    return any((dados or {}).get(c) for c in CAMPOS_DO_LAKE)
