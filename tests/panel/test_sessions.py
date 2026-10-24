"""panel/sessions.py — SessionStore (TTL, ociosidade, limites) e modelos sem tokens.

ATENÇÃO (interpretação): o construtor do SessionStore não está no briefing; os testes o criam em `make_store`
como SessionStore(settings, clock=clock). Se a assinatura real for outra, ajustar só esta função.
"""

import dataclasses

import pytest

from tests.panel.helpers import https_config, load_settings, require
from tests.panel.helpers_login import FakeClock

pytestmark = pytest.mark.critical

HOUR, MINUTE = 3600, 60


def make_store(clock, **overrides):
    settings = load_settings(https_config(**overrides))
    return require("empiremuse.panel.sessions").SessionStore(settings, clock=clock)


def _user(user_id="1001"):
    sessions = require("empiremuse.panel.sessions")
    return sessions.PanelUser(id=user_id, username=f"user{user_id}", global_name=None, avatar=None)


def _guilds():
    sessions = require("empiremuse.panel.sessions")
    return (sessions.ManagedGuild(id="1", name="Servidor", icon=None, permissions=8, owner=False),)


def test_models_are_frozen_dataclasses_without_token_fields():
    sessions = require("empiremuse.panel.sessions")
    for model in (sessions.PanelUser, sessions.ManagedGuild):
        assert dataclasses.is_dataclass(model)
        with pytest.raises(dataclasses.FrozenInstanceError):
            setattr(model(**{f.name: None for f in dataclasses.fields(model)}), "id", "x")
    store = make_store(FakeClock())
    session = store.get(store.create(_user(), _guilds()))
    names = {f.name for f in dataclasses.fields(session)} if dataclasses.is_dataclass(session) else set(vars(session))
    assert not [n for n in names if any(w in n.lower() for w in ("token", "access", "refresh", "secret"))], names


@pytest.mark.smoke
def test_create_returns_long_random_unique_ids():
    store = make_store(FakeClock())
    ids = {store.create(_user(str(i)), _guilds()) for i in range(100)}
    assert len(ids) == 100
    assert all(isinstance(i, str) and len(i) >= 43 for i in ids), "id deve ter >= 32 bytes de entropia"


@pytest.mark.smoke
def test_get_returns_session_with_user_and_guilds():
    store = make_store(FakeClock())
    session = store.get(store.create(_user(), _guilds()))
    assert session is not None
    assert session.user == _user() and tuple(session.guilds) == _guilds()


@pytest.mark.parametrize("bad_id", ["", "x", "0" * 64, None])
def test_get_unknown_session_returns_none(bad_id):
    assert make_store(FakeClock()).get(bad_id) is None


def test_destroy_removes_session_and_is_idempotent():
    store = make_store(FakeClock())
    session_id = store.create(_user(), _guilds())
    store.destroy(session_id)
    store.destroy(session_id)
    store.destroy("inexistente")
    assert store.get(session_id) is None


def test_idle_timeout_expires_session_and_access_renews_it():
    clock = FakeClock()
    store = make_store(clock, PANEL_SESSION_IDLE_MINUTES=30)
    session_id = store.create(_user(), _guilds())
    clock.advance(29 * MINUTE)
    assert store.get(session_id) is not None, "dentro da ociosidade"
    clock.advance(29 * MINUTE)
    assert store.get(session_id) is not None, "o acesso anterior renovou o último acesso"
    clock.advance(30 * MINUTE + 1)
    assert store.get(session_id) is None, "ociosa além do limite deve expirar"


def test_absolute_ttl_expires_even_with_constant_activity():
    clock = FakeClock()
    store = make_store(clock, PANEL_SESSION_TTL_HOURS=2, PANEL_SESSION_IDLE_MINUTES=30)
    session_id = store.create(_user(), _guilds())
    for _ in range(4):  # 4 x 29 min = 1h56, sempre ativo (ociosidade de 30 min)
        clock.advance(29 * MINUTE)
        assert store.get(session_id) is not None
    clock.advance(29 * MINUTE)  # 2h25 desde a criação: passou das 2h absolutas
    assert store.get(session_id) is None


def test_per_user_limit_of_5_sessions_evicts_the_oldest():
    store = make_store(FakeClock())
    ids = [store.create(_user("42"), _guilds()) for _ in range(6)]
    other = store.create(_user("43"), _guilds())
    assert store.get(ids[0]) is None, "a 6ª sessão do mesmo usuário deve remover a mais antiga"
    assert all(store.get(i) is not None for i in ids[1:])
    assert store.get(other) is not None, "sessões de outros usuários não são afetadas"


def test_global_limit_is_enforced_and_the_newest_session_is_valid(monkeypatch):
    monkeypatch.setattr(require("empiremuse.panel.sessions"), "MAX_SESSIONS_TOTAL", 5)
    store = make_store(FakeClock(), PANEL_SESSION_TTL_HOURS=168)
    ids = [store.create(_user(str(i)), _guilds()) for i in range(6)]
    alive = sum(1 for i in ids if store.get(i) is not None)
    assert alive <= 5, f"{alive} sessões vivas (máx. 5 com o limite reduzido)"
    assert store.get(ids[-1]) is not None, "a sessão mais recente deve estar válida"
