"""panel/settings.py — validação de PanelSettings."""

import logging

import pytest

from tests.panel.helpers import COOKIE_SECRET, OAUTH_SECRET, https_config, load_settings, local_config, require

pytestmark = pytest.mark.critical


def _error_type():
    return require("empiremuse.panel.settings").PanelConfigError


# ------------------------------------------------------------------ painel desligado


def test_disabled_panel_requires_no_other_settings():
    settings = load_settings({"PANEL_ENABLED": False})
    assert settings.enabled is False
    assert settings.base_url == ""


# ------------------------------------------------------------------ válidos e derivados


@pytest.mark.smoke
def test_valid_https_settings_expose_derived_properties():
    settings = load_settings(https_config())
    assert settings.enabled is True
    assert settings.base_url == "https://painel.example.com"
    assert settings.redirect_uri == "https://painel.example.com/painel/callback"
    assert settings.is_https is True


def test_base_url_keeps_port():
    settings = load_settings(https_config(PANEL_BASE_URL="https://painel.example.com:8443"))
    assert settings.redirect_uri == "https://painel.example.com:8443/painel/callback"


@pytest.mark.parametrize("host", ["localhost", "[::1]"])
def test_http_is_allowed_only_for_local_hosts_with_insecure_cookies(host):
    settings = load_settings(local_config(PANEL_BASE_URL=f"http://{host}:8080"))
    assert settings.is_https is False
    assert settings.insecure_cookies is True


# ------------------------------------------------------------------ PANEL_BASE_URL inválida


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "https://painel.example.com/#frag",
    ],
)
def test_invalid_base_url_raises(base_url):
    with pytest.raises(_error_type()):
        load_settings(https_config(PANEL_BASE_URL=base_url))


# ------------------------------------------------------------------ HTTPS obrigatório


@pytest.mark.parametrize(
    "config",
    [
        local_config(PANEL_INSECURE_COOKIES=False),  # localhost sem a flag
        https_config(PANEL_INSECURE_COOKIES=True),  # flag com host não local
    ],
)
def test_http_or_insecure_cookies_outside_local_host_raises(config):
    with pytest.raises(_error_type()):
        load_settings(config)


# ------------------------------------------------------------------ segredos


def test_empty_cookie_secret_is_generated_randomly_with_warning(caplog):
    with caplog.at_level(logging.WARNING):
        first = load_settings(https_config(PANEL_COOKIE_SECRET=""))
        second = load_settings(https_config(PANEL_COOKIE_SECRET=""))
    assert len(first.cookie_secret) >= 32
    assert first.cookie_secret != second.cookie_secret
    assert [r for r in caplog.records if r.levelno == logging.WARNING], (
        "deve avisar que as sessões não sobrevivem ao restart"
    )
    assert first.cookie_secret not in caplog.text, "o segredo gerado não pode aparecer no log"


def test_cookie_secret_with_32_chars_is_kept():
    secret = "k" * 32
    assert load_settings(https_config(PANEL_COOKIE_SECRET=secret)).cookie_secret == secret


def test_error_messages_never_contain_secrets():
    with pytest.raises(_error_type()) as excinfo:
        load_settings(https_config(PANEL_BASE_URL="lixo"))
    assert OAUTH_SECRET not in str(excinfo.value)
    assert COOKIE_SECRET not in str(excinfo.value)


# ------------------------------------------------------------------ limites numéricos


@pytest.mark.parametrize(
    "key,value",
    [
        ("PANEL_SESSION_TTL_HOURS", 1),
        ("PANEL_SESSION_IDLE_MINUTES", 1440),
    ],
)
def test_session_limits_boundaries_are_accepted(key, value):
    settings = load_settings(https_config(**{key: value}))
    attr = "session_ttl_hours" if key.endswith("HOURS") else "session_idle_minutes"
    assert getattr(settings, attr) == value
