"""Amostragem dos atos para rotular: o agrupamento por órgão e o sorteio, sem AWS."""

import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "rotulagem"))
import amostra  # noqa: E402


def ato(i, orgao):
    return {"ato_id": f"a{i}", "data_publicacao": "2026-11-03", "secao": "1", "tipo": "Despacho",
            "orgao": orgao, "identifica": f"DESPACHO {i}", "ementa": "", "url_pdf": "http://x", "tamanho": "10",
            "trecho": "linha 1\n  linha 2"}


ANEEL = "Ministério de Minas e Energia/Agência Nacional de Energia Elétrica/Superintendência de Concessões"
SAUDE = "Ministério da Saúde/Gabinete do Ministro"


def test_orgao_do_perfil_ignora_acento_e_caixa_e_acha_no_caminho():
    assert amostra.orgao_do_perfil(ANEEL) == "ANEEL"
    assert amostra.orgao_do_perfil("MINISTERIO DO TRABALHO E EMPREGO/Secretaria") == "MTE"
    assert amostra.orgao_do_perfil(SAUDE) is None
    assert amostra.orgao_do_perfil(None) is None


def test_amostra_leva_todos_do_perfil_e_so_n_do_resto():
    atos = [ato(i, ANEEL) for i in range(5)] + [ato(100 + i, SAUDE) for i in range(50)]
    a = amostra.montar_amostra(atos, 10, semente=1)
    grupos = [g for _, g, _ in a]
    assert grupos.count("orgao_do_perfil") == 5 and grupos.count("resto") == 10
    assert {x["ato_id"] for x, g, _ in a if g == "orgao_do_perfil"} == {f"a{i}" for i in range(5)}


def test_resto_menor_que_o_pedido_leva_todos():
    a = amostra.montar_amostra([ato(1, SAUDE), ato(2, SAUDE)], 10, semente=1)
    assert len(a) == 2


def test_mesma_semente_mesma_amostra_e_ordem_embaralhada():
    atos = [ato(i, ANEEL) for i in range(20)] + [ato(100 + i, SAUDE) for i in range(80)]
    a1 = [x["ato_id"] for x, _, _ in amostra.montar_amostra(atos, 30, semente=7)]
    a2 = [x["ato_id"] for x, _, _ in amostra.montar_amostra(atos, 30, semente=7)]
    outra = [x["ato_id"] for x, _, _ in amostra.montar_amostra(atos, 30, semente=8)]
    assert a1 == a2 and a1 != outra
    assert a1[:20] != [f"a{i}" for i in range(20)]      # os do perfil não vêm todos no começo


def test_planilha_sem_o_grupo_e_com_colunas_para_preencher(tmp_path):
    atos = [ato(1, ANEEL), ato(2, SAUDE)]
    amostra.gravar(amostra.montar_amostra(atos, 5, semente=1), tmp_path)
    with open(tmp_path / "rotulagem.csv", encoding="utf-8-sig") as f:
        linhas = list(csv.DictReader(f))
    assert len(linhas) == 2 and "grupo" not in linhas[0] and "orgao_casou" not in linhas[0]
    assert all(l["relevante"] == "" and l["tipo_mudanca"] == "" for l in linhas)
    assert linhas[0]["trecho"] == "linha 1 linha 2"       # quebras de linha viram espaço
    with open(tmp_path / "grupos.csv", encoding="utf-8") as f:
        grupos = {r["ato_id"]: r["grupo"] for r in csv.DictReader(f)}
    assert grupos == {"a1": "orgao_do_perfil", "a2": "resto"}


def test_nao_sobrescreve_amostra_ja_gravada_sem_pedir(tmp_path):
    import pytest
    a = amostra.montar_amostra([ato(1, ANEEL), ato(2, SAUDE)], 5, semente=1)
    amostra.gravar(a, tmp_path)
    rotulada = tmp_path / "rotulagem.csv"
    rotulada.write_text("rotulos feitos à mão", encoding="utf-8")
    with pytest.raises(SystemExit):
        amostra.gravar(a, tmp_path)
    assert rotulada.read_text(encoding="utf-8") == "rotulos feitos à mão"      # nada foi perdido
    amostra.gravar(a, tmp_path, sobrescrever=True)
    assert "ato_id" in rotulada.read_text(encoding="utf-8-sig")
