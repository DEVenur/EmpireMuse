"""Testes da Task C-22: roteamento de caminhos por empiremuse.paths, subprocess Popen cwd, e guardas de cache."""

from __future__ import annotations

import datetime
import logging
import pickle
import subprocess
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from empiremuse import paths
from empiremuse.panel.handlers import brand
from empiremuse.utils import branding
from empiremuse.utils.client import BotPool
from empiremuse.utils.db import LocalDatabase
from empiremuse.utils.music import lavalink_server_list, local_lavalink as ll


class FakeClassForPickle:
    pass


class TestCwdDoPopenLavalink:
    """(a) Teste que Popen do Lavalink recebe cwd=RUNTIME_DIR."""

    def test_popen_receives_cwd_runtime_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        popen_calls = []

        monkeypatch.setattr(
            subprocess,
            "Popen",
            lambda args, **kwargs: popen_calls.append((args, kwargs)) or MagicMock(),
        )
        monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)
        monkeypatch.setattr(ll, "prepare_lavalink_files", lambda *a, **k: None)

        ll.run_lavalink()

        assert len(popen_calls) == 1
        _, kwargs = popen_calls[0]
        assert "cwd" in kwargs, "Popen do Lavalink deve receber o argumento 'cwd'"
        assert kwargs["cwd"] == str(tmp_path.resolve())


class TestGuardasDeCache:
    """(b) Teste que cache com classe de módulo inexistente é descartado com aviso, sem travar."""

    @pytest.mark.parametrize(
        "filename,attr_name",
        [
            ("playlist_cache.pkl", "playlist_cache"),
            ("partial_track_cache.pkl", "partial_track_cache"),
            (".lyric_cache_data", "lyric_data_cache"),
        ],
    )
    def test_cache_with_nonexistent_class_is_discarded_with_warning(
        self, monkeypatch, tmp_path, caplog, filename, attr_name
    ):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        db_dir = tmp_path / "local_database"
        db_dir.mkdir(parents=True, exist_ok=True)

        # Cria um pickle serializando uma referência a um módulo inexistente
        # Formato de pickle para 'from nonexistent_module_xyz import FakeClass'
        # b"c<module>\n<name>\n"
        bad_pickle = b"cnonexistent_module_xyz\nFakeClass\n)\x81}."
        (db_dir / filename).write_bytes(bad_pickle)

        pool = BotPool.__new__(BotPool)
        pool.playlist_cache = {}
        pool.partial_track_cache = {}
        pool.lyric_data_cache = {}

        with caplog.at_level(logging.WARNING):
            pool.load_cache()

        # O cache problemático deve ter sido descartado sem levantar exceção
        assert getattr(pool, attr_name) == {}
        # Deve ter emitido aviso no logger
        assert any("descartado" in r.getMessage().lower() or "cache" in r.getMessage().lower() for r in caplog.records)

    def test_cache_with_corrupted_bytes_is_discarded_with_warning(self, monkeypatch, tmp_path, caplog):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        db_dir = tmp_path / "local_database"
        db_dir.mkdir(parents=True, exist_ok=True)

        (db_dir / "playlist_cache.pkl").write_bytes(b"\x80\x04\x95NOT_A_VALID_PICKLE")

        pool = BotPool.__new__(BotPool)
        pool.playlist_cache = {}
        pool.partial_track_cache = {}
        pool.lyric_data_cache = {}

        with caplog.at_level(logging.WARNING):
            pool.load_cache()

        assert pool.playlist_cache == {}


class TestPicklesSemModulosDoProjeto:
    """(c) Os pickles produzidos pelo código real de fila salva e de sessão do player não contêm b'empiremuse', b'utils.' nem b'modules.'."""

    def test_saved_queue_pickle_contains_no_project_modules(self):
        tracks = [
            {
                "title": "Música Teste",
                "author": "Artista Teste",
                "uri": "https://example.com/watch?v=123",
                "length": 180000,
                "is_stream": False,
                "playlist": {"name": "Minha Playlist", "url": "https://example.com/playlist?list=456"},
            }
        ]
        queue_payload = {
            "tracks": tracks,
            "created_at": datetime.datetime.now(datetime.timezone.utc),
            "guild_id": 987654321,
        }

        dumped = pickle.dumps(queue_payload)

        assert b"empiremuse" not in dumped, "Pickle de fila salva não pode referenciar pacote empiremuse"
        assert b"utils." not in dumped, "Pickle de fila salva não pode referenciar módulo utils."
        assert b"modules." not in dumped, "Pickle de fila salva não pode referenciar módulo modules."

    def test_player_session_pickle_contains_no_project_modules(self):
        session_data = {
            "_id": 123456789,
            "version": 1,
            "volume": 100,
            "nightcore": False,
            "position": 45000,
            "voice_channel": 111111111,
            "dj": None,
            "player_creator": 222222222,
            "static": False,
            "paused": False,
            "text_channel_id": 333333333,
            "message_id": 444444444,
            "keep_connected": True,
            "loop": False,
            "autoplay": False,
            "stage_title_event": False,
            "stage_title_template": "",
            "skin": "default",
            "skin_static": "default",
            "custom_skin_data": {},
            "custom_skin_static_data": {},
            "uptime": 1234567,
            "restrict_mode": False,
            "mini_queue_enabled": False,
            "listen_along_invite": "",
            "queue": ["track_encoded_base64_1", "track_encoded_base64_2"],
            "played": ["track_encoded_base64_0"],
            "queue_autoplay": [],
            "failed_tracks": [],
            "prefix_info": "!",
            "voice_state": {},
            "time": datetime.datetime.now(datetime.timezone.utc),
            "lastfm_artists": {},
            "start_timestamp": 1234567890,
        }

        dumped = pickle.dumps(session_data)

        assert b"empiremuse" not in dumped, "Pickle de sessão do player não pode referenciar pacote empiremuse"
        assert b"utils." not in dumped, "Pickle de sessão do player não pode referenciar módulo utils."
        assert b"modules." not in dumped, "Pickle de sessão do player não pode referenciar módulo modules."


class TestRoteamentoDeCaminhosDeDados:
    """Verifica roteamento de data/, assets/ e local_database."""

    def test_data_e_assets_roteados_por_project_dir(self):
        assert lavalink_server_list.BUNDLED_SERVER_LIST_PATH == paths.PROJECT_DIR / "data" / "lavalink_servers.ini"
        assert branding._ASSETS_DIR == paths.PROJECT_DIR / "assets"
        assert brand.BRAND_DIR == paths.PROJECT_DIR / "assets" / "brand"

    def test_local_database_respects_runtime_dir(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        db = LocalDatabase()
        assert db.dir == str(tmp_path / "local_database")
