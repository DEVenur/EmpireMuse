"""F3-6 (AppSec I-5) — ``parse_remote_web_url`` em tempo linear, mesmo com milhares de espaços na linha.

A regex ``^(\\S+)\\s+(\\S.*?)\\s+\\(fetch\\)\\s*$`` era quadrática: 50 000 espaços levavam uns 4 s (o ``git remote -v`` é
lido na partida). Esperado: qualquer linha grande é decidida em bem menos de 0,5 s, e o resultado para linhas normais não
muda (sufixo ``(fetch)`` obrigatório e separado por espaço, remote ``push`` ignorado, ``origin`` preferido).
"""

import time

import pytest

from empiremuse.rules.git_remote import parse_remote_web_url

N = 50_000
LIMITE = 0.5
OK = "https://github.com/o/r"


def medir(texto):
    inicio = time.perf_counter()
    resultado = parse_remote_web_url(texto)
    return resultado, time.perf_counter() - inicio


FORMAS_GRANDES = {
    "espacos-no-fim-sem-fetch": "origin\t" + OK + " " * N + "(fetch",
    "espacos-dentro-da-url": "origin\thttps://github.com/o" + " " * N + "r (fetch)",
    "espacos-depois-do-fetch": "origin\t" + OK + " (fetch)" + " " * N + "x",
    "espacos-no-nome-e-no-fim": "origin" + " " * N + "x" + " " * N + "y",
    "tabs-e-espacos-alternados": "origin" + " \t" * N + "x (fetch",
    "espacos-antes-do-fetch": "origin\t" + OK + " " * N + "(fetch)x",
}


class TestTempoLinear:
    @pytest.mark.parametrize("texto", FORMAS_GRANDES.values(), ids=FORMAS_GRANDES.keys())
    def test_linha_grande_e_decidida_em_menos_de_meio_segundo(self, texto):
        _, segundos = medir(texto)
        assert segundos < LIMITE, f"{segundos:.2f} s"

    def test_muitas_linhas_tambem_ficam_rapidas(self):
        texto = "\n".join(f"r{i}\thttps://h{i}.example/o/r (push)" for i in range(20_000))
        _, segundos = medir(texto)
        assert segundos < LIMITE, f"{segundos:.2f} s"

    def test_url_valida_precedida_de_milhares_de_espacos_continua_valendo(self):
        """Muito espaço entre o nome e a URL ainda é só um separador."""
        resultado, segundos = medir("origin" + " " * N + OK + " (fetch)")
        assert resultado == OK and segundos < LIMITE


class TestMesmoResultadoDeSempre:
    """GUARDA: o formato da linha aceito é o mesmo de antes."""

    @pytest.mark.parametrize(
        ("texto", "esperado"),
        [
            (f"origin\t{OK}.git (fetch)\norigin\t{OK}.git (push)\n", OK),
            (f"origin\t{OK}.git (fetch)", OK),
            (f"  origin\t{OK}   (fetch)   ", OK),
            (f"origin {OK} (fetch)", OK),
            (f"origin\t\t{OK}\t(fetch)", OK),
            (f"origin\t{OK}.git\t(fetch)\r\n", OK),
            ("a\thttps://a.example/x/y (fetch)\norigin\thttps://b.example/x/y (fetch)", "https://b.example/x/y"),
            ("a\thttps://a.example/x/y (fetch)\nb\thttps://b.example/x/y (fetch)", "https://a.example/x/y"),
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
