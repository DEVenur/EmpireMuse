"""A26 (item 18, P4) — ``update_mode``: o proxy configurado em ``UPDATE_PROXY_SOCKET`` escolhe o modo ``docker`` antes de qualquer outro."""

from pathlib import Path

import pytest

from empiremuse.updater import mode
from empiremuse.updater.mode import MODE_GIT, MODE_MANUAL, MODE_PANEL, update_mode

pytestmark = pytest.mark.critical

SOCKET = {"UPDATE_PROXY_SOCKET": "/run/empiremuse/updater.sock"}
IMAGEM = {"EMPIREMUSE_VERSION": "2.1.0"}


def projeto(tmp_path: Path, *, com_git: bool) -> Path:
    if com_git:
        (tmp_path / ".git").mkdir()
    return tmp_path


@pytest.mark.parametrize("com_git", [False, True], ids=["sem-git", "com-git"])
@pytest.mark.parametrize("ambiente", [{}, IMAGEM], ids=["codigo-solto", "imagem"])
def test_a_configured_proxy_socket_wins_over_every_other_mode(tmp_path, ambiente, com_git):
    assert update_mode(SOCKET, ambiente, projeto(tmp_path, com_git=com_git)) == mode.MODE_DOCKER == "docker"


@pytest.mark.parametrize("config", [{}, {"UPDATE_PROXY_SOCKET": ""}], ids=["ausente", "vazio"])
@pytest.mark.parametrize(
    ("ambiente", "com_git", "esperado"),
    [(IMAGEM, False, MODE_PANEL), ({}, True, MODE_GIT), ({}, False, MODE_MANUAL)],
    ids=["painel", "git", "manual"],
)
def test_without_a_proxy_socket_the_previous_modes_are_unchanged(tmp_path, config, ambiente, com_git, esperado):
    assert update_mode(config, ambiente, projeto(tmp_path, com_git=com_git)) == esperado
