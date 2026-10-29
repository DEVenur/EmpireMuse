"""F3-6 — ``config_loader.load_config``: um ``0`` inteiro vindo do ``config.json`` não pode virar o valor padrão.

O laço dos inteiros testava ``if not CONFIG[i]`` para cair no padrão quando o valor está ausente ou vazio; só que ``0``
(inteiro, como o JSON entrega) também é "falso", então ``LAVALINK_RECONNECT_RETRIES=0`` no ``config.json`` virava 30,
``MAX_USER_FAVS=0`` (sem limite) virava 10 e assim por diante. Pelo ``.env`` ou pelo ambiente o valor chega como texto
(``"0"``), que é verdadeiro, e já funcionava. O oráculo dos testes é justamente esse caminho: o resultado vindo do
``config.json`` tem de ser igual ao do ambiente. Ausente ou vazio continua caindo no padrão.
Sem rede, sem ``.env`` real (o ``conftest`` neutraliza o ``dotenv_values``) e com ``EMPIREMUSE_HOME`` em ``tmp_path``.
"""

import json

import pytest

from empiremuse import config_loader

pytestmark = pytest.mark.critical

# Chaves que o laço dos inteiros converte (as demais com padrão inteiro não são convertidas).
CHAVES_INTEIRAS = [
    "BOT_ADD_REMOVE_LOG_CHANNEL_ID",
    "PRESENCE_INTERVAL",
    "INVITE_PERMISSIONS",
    "PREFIXED_POOL_TIMEOUT",
    "MONGO_TIMEOUT",
    "LAVALINK_RECONNECT_RETRIES",
    "VOTE_SKIP_AMOUNT",
    "IDLE_TIMEOUT",
    "WAIT_FOR_MEMBERS_TIMEOUT",
    "MAX_USER_FAVS",
    "USER_FAV_MAX_NAME_LENGTH",
    "USER_FAV_MAX_URL_LENGTH",
    "MAX_USER_INTEGRATIONS",
    "HINT_RATE",
    "PLAYER_INFO_BACKUP_INTERVAL",
    "PLAYER_INFO_BACKUP_INTERVAL_MONGO",
    "QUEUE_MAX_ENTRIES",
    "VOICE_CHANNEL_LATENCY_RECONNECT",
    "PLAYLIST_CACHE_SIZE",
    "PLAYLIST_CACHE_TTL",
    "SPOTIFY_PLAYLIST_EXTRA_PAGE_LIMIT",
    "PANEL_SESSION_TTL_HOURS",
    "PANEL_SESSION_IDLE_MINUTES",
    "LAVALINK_ADDITIONAL_SLEEP",
    "LAVALINK_INITIAL_RAM",
    "LAVALINK_RAM_LIMIT",
    "LAVALINK_CPU_CORES",
    "YOUTUBE_TRACK_COOLDOWN",
    "DBCACHE_SIZE",
    "DBCACHE_TTL",
    "METRICS_INTERVAL",
]


@pytest.fixture
def home(monkeypatch, tmp_path):
    """RUNTIME_DIR isolado e cwd em outra pasta; devolve a pasta onde o ``config.json`` é lido."""
    pasta, cwd = tmp_path / "home", tmp_path / "cwd"
    pasta.mkdir()
    cwd.mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(pasta))
    monkeypatch.chdir(cwd)
    return pasta


def pelo_config_json(home, chave, valor):
    (home / "config.json").write_text(json.dumps({chave: valor}), encoding="utf-8")
    return config_loader.load_config()[chave]


def pelo_ambiente(monkeypatch, chave, texto):
    monkeypatch.setenv(chave, texto)
    try:
        return config_loader.load_config()[chave]
    finally:
        monkeypatch.delenv(chave)


def pelo_dotenv(monkeypatch, chave, texto):
    monkeypatch.setattr(config_loader, "dotenv_values", lambda *args, **kwargs: {chave: texto})
    return config_loader.load_config()[chave]


class TestZeroInteiroDoConfigJson:
    def test_o_exemplo_do_bug_retries_zero_no_config_json(self, home):
        assert pelo_config_json(home, "LAVALINK_RECONNECT_RETRIES", 0) == 0, "0 = sem limite, e não o padrão 30"

    @pytest.mark.parametrize("chave", list(CHAVES_INTEIRAS)[:2])
    def test_zero_do_config_json_tem_o_mesmo_resultado_que_pelo_ambiente(self, home, monkeypatch, chave):
        esperado = pelo_ambiente(monkeypatch, chave, "0")
        assert pelo_config_json(home, chave, 0) == esperado, f"{chave}: 0 do config.json foi trocado pelo padrão"


class TestAusenteOuVazioCaiNoPadrao:
    """GUARDA: só o ausente e o vazio usam o padrão."""

    def test_vazio_no_ambiente_e_no_dotenv(self, home, monkeypatch):
        assert pelo_ambiente(monkeypatch, "LAVALINK_RECONNECT_RETRIES", "") == 30
        assert pelo_dotenv(monkeypatch, "LAVALINK_RECONNECT_RETRIES", "") == 30
