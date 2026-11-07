"""
Roda as quatro etapas dos atos do DOU em pastas locais, com um catálogo Iceberg
em SQLite no lugar do Glue Data Catalog.

A coleta não toca a internet: `listar` e `baixar_zip` são substituídos por um ZIP
montado no teste, com XML no mesmo formato da Imprensa Nacional.
"""

import os
import shutil
import sys
import zipfile

import pytest
from pyiceberg.catalog.sql import SqlCatalog

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import etl_dou  # noqa: E402

ANO, MES, SECAO = 2026, 11, 1
ANO_MES = "2026-11"


def xml_ato(ident, tipo="Portaria", orgao="Ministério de Minas e Energia",
            pub_date="03/11/2026", pagina="5", titulo=None, texto=None):
    """Mesmo formato do XML da base de dados aberta da Imprensa Nacional."""
    return f"""<?xml version="1.0" encoding="utf-8"?>
<articles>
  <article id="{ident}" idMateria="mat-{ident}" name="1.1" pubName="DO1"
           pubDate="{pub_date}" artType="{tipo}" artCategory="{orgao}"
           numberPage="{pagina}" editionNumber="208"
           pdfPage="http://pesquisa.in.gov.br/{ident}.pdf">
    <body>
      <Identifica>{titulo or f'PORTARIA Nº {ident}, DE 3 DE NOVEMBRO DE 2026'}</Identifica>
      <Ementa>Dispõe sobre o assunto {ident}.</Ementa>
      <Texto><![CDATA[<p>O DIRETOR resolve:</p><p>Art. 1º Fica aprovado o ato {ident}.</p>]]></Texto>
    </body>
  </article>
</articles>
""".encode("utf-8")


ATO_ANEEL = ("S01/aneel.xml", xml_ato(
    "900", tipo="Resolução",
    orgao="Ministério de Minas e Energia/Agência Nacional de Energia Elétrica/Diretoria"))
ATO_SAUDE = ("S01/saude.xml", xml_ato("901", orgao="Ministério da Saúde"))
SEM_ARTICLE = ("S01/aviso.xml", b'<?xml version="1.0"?><outros><nada/></outros>')
QUEBRADO = ("S01/quebrado.xml", b"<articles><article id=")


def monta_zip(caminho, entradas):
    with zipfile.ZipFile(caminho, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dado in entradas:
            z.writestr(nome, dado)
    return caminho


@pytest.fixture
def amb(tmp_path, monkeypatch):
    lake = str(tmp_path / "lake")
    catalog = SqlCatalog("teste", uri=f"sqlite:///{tmp_path}/catalogo.db",
                         warehouse=f"file://{tmp_path}/warehouse")
    estado = {"entradas": [ATO_ANEEL, ATO_SAUDE, SEM_ARTICLE]}

    monkeypatch.setattr(etl_dou, "listar",
                        lambda ano, mes: {1: "http://exemplo/dou-S01.zip"})

    def falso_baixar(url, destino):
        origem = monta_zip(str(tmp_path / "origem.zip"), estado["entradas"])
        os.makedirs(os.path.dirname(os.path.abspath(destino)), exist_ok=True)
        shutil.copy(origem, destino)
        return destino

    monkeypatch.setattr(etl_dou, "baixar_zip", falso_baixar)
    return {"tmp": tmp_path, "lake": lake, "catalog": catalog,
            "con": etl_dou.connect(), "estado": estado}


def roda_tudo(amb):
    n_landing = etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO)
    n_bronze = etl_dou.bronze(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO)
    n_prata = etl_dou.prata(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO)
    n_ouro = etl_dou.ouro(amb["con"], amb["catalog"], amb["lake"])
    return n_landing, n_bronze, n_prata, n_ouro


def linhas(amb, ident):
    return amb["catalog"].load_table(ident).scan().to_arrow().to_pylist()


def test_pipeline_completo(amb):
    n_landing, n_bronze, n_prata, n_ouro = roda_tudo(amb)
    # Os tres XML entram na landing e na bronze; so dois viram ato (um nao tem <article>).
    assert n_landing == 3
    assert n_bronze == 3
    assert n_prata == 2
    assert n_ouro == 1

    atos = {a["id"]: a for a in linhas(amb, etl_dou.PRATA_ATOS)}
    assert set(atos) == {"900", "901"}
    a = atos["900"]
    assert a["tipo"] == "Resolução"
    assert "Energia Elétrica" in a["orgao"]
    assert a["jornal"] == "DO1"
    assert a["pagina"] == 5
    assert a["secao"] == SECAO and a["ano_mes"] == ANO_MES
    assert str(a["data_publicacao"]) == "2026-11-03"
    assert a["url_pdf"] == "http://pesquisa.in.gov.br/900.pdf"
    # O texto perde as tags HTML mas mantem a separacao dos paragrafos.
    assert a["texto"] == "O DIRETOR resolve: Art. 1º Fica aprovado o ato 900."
    assert "<p>" not in a["texto"]
    assert a["ementa"] == "Dispõe sobre o assunto 900."


def test_ouro_resume_o_mes_e_conta_aneel(amb):
    roda_tudo(amb)
    resumo = linhas(amb, etl_dou.OURO_RESUMO)
    assert len(resumo) == 1
    r = resumo[0]
    assert r["ano_mes"] == ANO_MES
    assert r["atos"] == 2
    assert r["atos_aneel"] == 1  # so o ato da Agencia Nacional de Energia Eletrica
    assert str(r["de"]) == "2026-11-03" and str(r["ate"]) == "2026-11-03"


def test_recoletar_o_mesmo_mes_nao_duplica(amb):
    roda_tudo(amb)
    # Segunda coleta do mesmo mes: mesmos arquivos, mesmo conteudo.
    assert etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO) == 3
    assert etl_dou.bronze(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 0
    assert etl_dou.prata(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 0
    etl_dou.ouro(amb["con"], amb["catalog"], amb["lake"])

    assert len(linhas(amb, etl_dou.BRONZE_XML)) == 3
    assert len(linhas(amb, etl_dou.PRATA_ATOS)) == 2
    assert linhas(amb, etl_dou.OURO_RESUMO)[0]["atos"] == 2


def test_coleta_seguinte_traz_atos_novos(amb):
    roda_tudo(amb)
    # O mes avanca e o ZIP passa a ter mais um ato, em outro dia.
    novo = ("S01/novo.xml", xml_ato("902", orgao="Ministério da Fazenda",
                                    pub_date="05/11/2026"))
    amb["estado"]["entradas"] = [ATO_ANEEL, ATO_SAUDE, SEM_ARTICLE, novo]

    assert etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO) == 4
    assert etl_dou.bronze(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 1
    assert etl_dou.prata(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 1
    etl_dou.ouro(amb["con"], amb["catalog"], amb["lake"])

    assert len(linhas(amb, etl_dou.PRATA_ATOS)) == 3
    r = linhas(amb, etl_dou.OURO_RESUMO)[0]
    assert r["atos"] == 3 and r["atos_aneel"] == 1
    assert str(r["de"]) == "2026-11-03" and str(r["ate"]) == "2026-11-05"


def test_xml_quebrado_nao_derruba_a_prata(amb):
    amb["estado"]["entradas"] = [ATO_ANEEL, QUEBRADO, ATO_SAUDE]
    assert etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO) == 3
    assert etl_dou.bronze(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 3
    # O XML invalido fica preservado na bronze e so e contado como erro na prata.
    assert etl_dou.prata(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 2
    assert len(linhas(amb, etl_dou.BRONZE_XML)) == 3


def test_so_xml_quebrado_levanta_erro(amb):
    amb["estado"]["entradas"] = [QUEBRADO]
    etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO)
    etl_dou.bronze(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO)
    with pytest.raises(ValueError, match="Nenhum ato valido"):
        etl_dou.prata(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO)


def test_zip_sem_xml_levanta_coleta_vazia(amb):
    amb["estado"]["entradas"] = [("S01/leiame.txt", b"sem xml aqui")]
    with pytest.raises(etl_dou.ColetaVaziaError):
        etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO)


def test_landing_substitui_a_particao(amb):
    etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO)
    pasta = etl_dou.landing_dir(amb["lake"], ANO_MES, SECAO)
    assert len(os.listdir(pasta)) == 1
    # Uma coleta menor nao deve deixar os arquivos da anterior para tras.
    amb["estado"]["entradas"] = [ATO_SAUDE]
    assert etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO) == 1
    assert len(os.listdir(pasta)) == 1
    assert etl_dou.bronze(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 1


def test_landing_quebra_em_lotes(amb, monkeypatch):
    monkeypatch.setattr(etl_dou, "LOTE_LANDING", 2)
    amb["estado"]["entradas"] = [
        (f"S01/a{i}.xml", xml_ato(str(1000 + i))) for i in range(5)
    ]
    assert etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO) == 5
    pasta = etl_dou.landing_dir(amb["lake"], ANO_MES, SECAO)
    assert sorted(os.listdir(pasta)) == [
        "part-00001.parquet", "part-00002.parquet", "part-00003.parquet"]
    # A bronze le os tres arquivos da particao como um so conjunto.
    assert etl_dou.bronze(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 5
    assert etl_dou.prata(amb["con"], amb["catalog"], amb["lake"], ANO_MES, SECAO) == 5


def test_secao_errada_avisa(amb, monkeypatch):
    monkeypatch.setattr(etl_dou, "listar", lambda ano, mes: {2: "http://exemplo/S02.zip"})
    with pytest.raises(ValueError, match="Secao 1 nao encontrada"):
        etl_dou.landing(amb["con"], amb["lake"], ANO, MES, SECAO)


def test_parse_ato_sem_article_devolve_none():
    assert etl_dou.parse_ato(SEM_ARTICLE[1], "aviso.xml") is None


def test_parse_ato_sem_id_levanta():
    with pytest.raises(ValueError, match="sem id"):
        etl_dou.parse_ato(xml_ato(""), "vazio.xml")


# Mesmo markup que o portal devolve em ?ano=2026&mes=Novembro.
PAGINA_REAL = """
<ul class="dados-abertos-lista">
  <li><a href="https://www.in.gov.br/documents/49035712/741444604/S03112026_Atualizado171455.zip/ce77a305-8713-326f-9806-c858ea4119c1?version=1.0&t=1794000763127&download=true">
      S03112026_Atualizado171455.zip</a></li>
  <li><a href="https://www.in.gov.br/documents/49035712/741444604/S02112026_Atualizado171341.zip/6af98983-caf9-4168-5f4e-20854031cb32?version=1.0&t=1794000764767&download=true">
      S02112026_Atualizado171341.zip</a></li>
  <li><a href="https://www.in.gov.br/documents/49035712/741444604/S01112026_Atualizado171256.zip/a2e0058e-98f7-9ed0-bb9d-50e1c3dff4be?version=1.0&t=1794000770483&download=true">
      S01112026_Atualizado171256.zip</a></li>
</ul>
<a href="/tutorial-app-dou">Tutorial</a>
"""


def test_links_secoes_acha_as_tres_secoes():
    links = etl_dou._links_secoes(PAGINA_REAL, etl_dou.PAGINA_DADOS_ABERTOS, 2026, 11)
    assert set(links) == {1, 2, 3}
    assert "S01112026_Atualizado171256.zip" in links[1]
    assert links[1].startswith("https://www.in.gov.br/documents/")


def test_links_secoes_ignora_outro_mes():
    assert etl_dou._links_secoes(PAGINA_REAL, etl_dou.PAGINA_DADOS_ABERTOS, 2026, 10) == {}
    assert etl_dou._links_secoes(PAGINA_REAL, etl_dou.PAGINA_DADOS_ABERTOS, 2025, 11) == {}


def test_links_secoes_fica_com_a_publicacao_mais_recente():
    pagina = """
    <ul class="dados-abertos-lista">
      <li><a href="/documents/1/2/S01112026.zip/aaa?t=100&download=true">antigo</a></li>
      <li><a href="/documents/1/2/S01112026_Atualizado171256.zip/bbb?t=999&download=true">novo</a></li>
    </ul>
    """
    links = etl_dou._links_secoes(pagina, etl_dou.PAGINA_DADOS_ABERTOS, 2026, 11)
    assert set(links) == {1}
    assert "Atualizado171256" in links[1]


def test_mes_invalido_levanta():
    with pytest.raises(ValueError, match="entre 1 e 12"):
        etl_dou.listar(2026, 13)


def test_parse_args_formato_glue():
    args = etl_dou.parse_args(["--STAGE", "prata", "--LAKE_URI", "s3://lake",
                               "--ANO", "2026", "--MES", "11", "--SECAO", "1",
                               "--job-bookmark-option", "job-bookmark-disable"])
    assert args["STAGE"] == "prata" and args["ANO"] == "2026" and args["MES"] == "11"
    with pytest.raises(SystemExit):
        etl_dou.parse_args(["--STAGE", "diamante", "--LAKE_URI", "s3://lake"])
    with pytest.raises(SystemExit):
        etl_dou.parse_args(["--STAGE", "prata"])
