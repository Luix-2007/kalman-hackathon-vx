"""Métricas da busca e da triagem contra os rótulos (sem AWS)."""

import json
import sys

from apoio import AQUI

sys.path.insert(0, str(AQUI.parent / "avaliacao"))
import metricas  # noqa: E402


def test_cobertura_e_precisao_por_grupo():
    rotulos = {"a": True, "b": True, "c": False, "d": True, "e": None}
    grupos = {"a": "orgao_do_perfil", "b": "orgao_do_perfil", "c": "orgao_do_perfil", "d": "resto"}
    r = metricas.calcular(rotulos, grupos, candidatos={"a", "c", "d", "x"},
                          triagens={"a": True, "c": True, "d": False})
    assert r["rotulados"] == 4 and r["relevantes"] == 3
    assert r["busca"]["cobertura"] == 0.667 and r["busca"]["perdidos"] == ["b"]
    assert r["busca"]["precisao"] == 0.667                              # a, d relevantes entre a, c, d
    assert r["busca"]["por_grupo"]["resto"] == {"relevantes": 1, "achados": 1, "cobertura": 1.0}
    t = r["triagem"]
    assert (t["verdadeiro_positivo"], t["falso_positivo"], t["falso_negativo"]) == (1, 1, 1)
    assert t["descartados_relevantes"] == ["d"]


def test_sem_rotulos_nao_divide_por_zero():
    r = metricas.calcular({"a": None}, {}, set(), {})
    assert r["rotulados"] == 0 and r["busca"]["cobertura"] is None and r["triagem"]["precisao"] is None


def test_rotulo_aceita_variacoes_e_le_a_simulacao(tmp_path):
    assert metricas.sim("Sim") and metricas.sim("não") is False and metricas.sim("") is None
    (tmp_path / "candidatos.json").write_text(json.dumps({"C": [{"ato_id": "a"}]}))
    ev = tmp_path / "audit/propostas/eventos/dt=2026-11-08/sim"
    ev.mkdir(parents=True)
    (ev / "x.jsonl").write_text(json.dumps({"etapa": "triar", "cnpj": "C", "ato_id": "a", "resultado": "relevante"}) + "\n")
    assert metricas.ler_simulacao(tmp_path, "C") == ({"a"}, {"a": True})
