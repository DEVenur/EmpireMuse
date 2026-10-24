"""KI-27 — caracterização das 15 skins do player (10 normais e 5 estáticas) em `empiremuse/utils/music/skins/`.

Cada skin é carregada com um player falso em vários estados (tocando, pausado, livestream, recomendação automática, fila vazia,
só fila automática, sem dica, com log de comando). Confere o contrato com o Discord, não o desenho: `load` devolve um dicionário
com `embeds` (ou `content`), `components` válidos (ids únicos, até 25 opções por select) e embeds dentro dos limites da API; `setup_features`
liga o modo certo (controlador/estático) no player.
"""

import importlib
import pkgutil
from unittest.mock import MagicMock

import pytest

import empiremuse.utils.music.skins.normal_player as normal_pkg


def skin_classes(package):
    classes = []
    for info in pkgutil.iter_modules(package.__path__):
        module = importlib.import_module(f"{package.__name__}.{info.name}")
        for obj in vars(module).values():
            if isinstance(obj, type) and obj.__module__ == module.__name__ and hasattr(obj, "load"):
                classes.append(pytest.param(obj, id=f"{package.__name__.rsplit('.', 1)[-1]}.{info.name}"))
    return classes


NORMAL = skin_classes(normal_pkg)


def make_track(**overrides):
    track = MagicMock()
    values = dict(
        title="Título da música",
        uri="https://exemplo.test/a",
        search_uri="https://exemplo.test/s",
        thumb="https://exemplo.test/t.png",
        duration=185000,
        author="Autor",
        requester=1,
        autoplay=False,
        is_stream=False,
        playlist_name="Lista",
        playlist_url="https://exemplo.test/p",
        info={"sourceName": "youtube", "extra": {}},
        album_name="Álbum",
        album_url="https://exemplo.test/al",
        ytid="dQw4w9WgXcQ",
        single_title="Título da música",
        lyrics=None,
    )
    values.update(overrides)
    for key, value in values.items():
        setattr(track, key, value)
    return track


def make_player(**overrides):
    player = MagicMock()
    values = dict(
        current=make_track(),
        queue=[make_track(title=f"Fila {n}") for n in range(5)],
        queue_autoplay=[make_track(title="Auto")],
        paused=False,
        volume=100,
        loop=False,
        command_log="Alguém pausou a música.",
        command_log_emoji="🔹",
        current_hint="Use /ajuda",
        mini_queue_enabled=True,
        nightcore=False,
        autoplay=False,
        restrict_mode=False,
        keep_connected=False,
        has_thread=False,
        static=False,
        position=1000,
    )
    values.update(overrides)
    for key, value in values.items():
        setattr(player, key, value)
    player.bot.get_color.return_value = 0x5865F2
    player.bot.config = {"HINT_RATE": 3}
    player.__str__ = lambda self: "player"
    return player


@pytest.mark.parametrize("skin_cls", NORMAL)
def test_normal_skins_turn_off_static_mode(skin_cls):
    player = make_player(static=True)
    skin_cls().setup_features(player)
    assert player.static is False
