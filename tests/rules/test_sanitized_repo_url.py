"""B1 (Vigil, item 18) — ``sanitized_repo_url``: o endereço do repositório que vai a embeds e à página de status nunca leva credencial."""

import pytest

from empiremuse.rules.git_remote import sanitized_repo_url

FALLBACK = "https://github.com/EmpireCommunity/EmpireMuse"


def test_credentials_and_the_git_suffix_are_removed():
    assert sanitized_repo_url("https://u:tok@github.com/o/r.git", FALLBACK) == "https://github.com/o/r"


@pytest.mark.parametrize("valor", ["https://tok@github.com/o/r", "http://u:tok@host.example/o/r.git"])
def test_no_credential_survives_in_the_result(valor):
    assert "tok" not in sanitized_repo_url(valor, FALLBACK)


@pytest.mark.parametrize(
    "valor", ["", "   ", "/srv/repositorio", "file:///srv/repositorio", "../repo", "relativo/repo"]
)
def test_empty_or_local_values_fall_back(valor):
    assert sanitized_repo_url(valor, FALLBACK) == FALLBACK
