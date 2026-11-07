"""Campos da conferência dos dados (tela do painel) aceitos pela validação do perfil."""

import perfil


def test_conferencia_valida():
    dados = {
        "conferido_em": "2026-11-07T22:40:00.000Z",
        "conferido_por": "ana@empresa.com.br",
        "conferido_por_nome": "Ana Ribeiro",
        "ufs_atuacao": ["RJ", "SP"],
    }
    assert set(dados) <= set(perfil.CAMPOS)
    assert perfil.validar(dados) == {}


def test_conferencia_recusa_email_invalido_e_uf_em_texto():
    erros = perfil.validar({"conferido_por": "sem-arroba", "ufs_atuacao": "RJ,SP"})
    assert set(erros) == {"conferido_por", "ufs_atuacao"}
