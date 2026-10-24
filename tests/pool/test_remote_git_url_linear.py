"""F3-6 (AppSec I-5) — ``parse_remote_web_url`` com linhas grandes (a regex linear não trava) e formato aceito inalterado."""

import pytest

from empiremuse.rules.git_remote import parse_remote_web_url

OK = "https://github.com/o/r"


class TestLinhasGrandes:
    """Sem cronômetro: o que importa é a decisão para uma linha grande, e a regex linear a toma sem travar."""

    def test_milhares_de_espacos_na_linha_nao_viram_remote(self):
        assert parse_remote_web_url("origin\thttps://h.example/o/r" + " " * 5_000 + "x") == ""

    def test_muitas_linhas_de_push_sem_fetch_nao_viram_remote(self):
        texto = "\n".join(f"r{i}\thttps://h{i}.example/o/r (push)" for i in range(2_000))
        assert parse_remote_web_url(texto) == ""


class TestMesmoResultadoDeSempre:
    """GUARDA: o formato da linha aceito é o mesmo de antes."""

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            (f"origin\t{OK}.git (fetch)\norigin\t{OK}.git (push)\n", OK),
            (f"origin\t{OK} (push)\nup\thttps://u.example/x/y (fetch)", "https://u.example/x/y"),
        ],
        ids=repr,
    )
    def test_linhas_aceitas(self, texto, esperado):
        assert parse_remote_web_url(texto) == esperado

    @pytest.mark.parametrize(
        "texto",
        [
            "",
            "\n\n",
            f"origin\t{OK}(fetch)",
            f"origin\t{OK} (push)",
            f"origin\t{OK}",
            f"origin\t(fetch)",
            "origin\t (fetch)",
            "origin (fetch)",
            "(fetch)",
            f"{OK} (fetch) lixo",
            f"origin\t{OK} (FETCH)",
        ],
        ids=repr,
    )
    def test_linhas_recusadas(self, texto):
        assert parse_remote_web_url(texto) == ""
