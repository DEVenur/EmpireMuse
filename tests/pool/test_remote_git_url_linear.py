"""F3-6 (AppSec I-5) — ``parse_remote_web_url`` com linhas grandes (a regex linear não trava) e formato aceito inalterado."""

from empiremuse.rules.git_remote import parse_remote_web_url


class TestLinhasGrandes:
    """Sem cronômetro: o que importa é a decisão para uma linha grande, e a regex linear a toma sem travar."""

    def test_milhares_de_espacos_na_linha_nao_viram_remote(self):
        assert parse_remote_web_url("origin\thttps://h.example/o/r" + " " * 5_000 + "x") == ""
