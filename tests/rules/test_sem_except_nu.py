"""KI-28 (arquivos críticos): nenhum ``except:`` nu. Ele engolia ``KeyboardInterrupt``, ``SystemExit`` e o cancelamento de tasks."""

import ast

import pytest

from tests.support.raiz import RAIZ

ARQUIVOS = [
    "empiremuse/cogs/player_resume.py",
    "empiremuse/utils/client.py",
    "empiremuse/cogs/legacy_cmds.py",
    "empiremuse/web_app.py",
    "empiremuse/cogs/ll_yt_oauth.py",
    "empiremuse/utils/music/local_lavalink.py",
    "empiremuse/utils/db.py",
    "empiremuse/utils/music/youtube_trusted_session_generator.py",
    "empiremuse/utils/music/audio_sources/spotify.py",
    "empiremuse/config_loader.py",
]


@pytest.mark.parametrize("arquivo", ARQUIVOS)
def test_sem_except_nu(arquivo):
    arvore = ast.parse((RAIZ / arquivo).read_text(encoding="utf-8"))

    nus = [no.lineno for no in ast.walk(arvore) if isinstance(no, ast.ExceptHandler) and no.type is None]

    assert nus == [], f"except: nu em {arquivo}, linhas {nus}"
