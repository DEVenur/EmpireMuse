"""panel/settings.py — validação de PanelSettings."""

import dataclasses
import logging

import pytest

from tests.panel.helpers import COOKIE_SECRET, OAUTH_SECRET, https_config, load_settings, local_config, require


def _error_type():
    return require("empiremuse.panel.settings").PanelConfigError


def test_panel_config_error_is_a_value_error():
    assert issubclass(_error_type(), ValueError)


# ------------------------------------------------------------------ painel desligado


def test_disabled_panel_requires_no_other_settings():
    settings = load_settings({"PANEL_ENABLED": False})
    assert settings.enabled is False
    assert settings.base_url == ""


def test_disabled_panel_does_not_validate_invalid_values():
    settings = load_settings({"PANEL_ENABLED": False, "PANEL_BASE_URL": "lixo", "PANEL_COOKIE_SECRET": "curto"})
    assert settings.enabled is False
    assert settings.base_url == ""


# ------------------------------------------------------------------ válidos e derivados


def test_valid_https_settings_expose_derived_properties():
    settings = load_settings(https_config())
    assert settings.enabled is True
    assert settings.base_url == "https://painel.example.com"
    assert settings.redirect_uri == "https://painel.example.com/painel/callback"
    assert settings.is_https is True


def test_trailing_slash_is_stripped_from_base_url():
    settings = load_settings(https_config(PANEL_BASE_URL="https://painel.example.com/"))
    assert settings.base_url == "https://painel.example.com"
    assert settings.redirect_uri == "https://painel.example.com/painel/callback"


def test_base_url_keeps_port():
    settings = load_settings(https_config(PANEL_BASE_URL="https://painel.example.com:8443"))
    assert settings.redirect_uri == "https://painel.example.com:8443/painel/callback"


def test_defaults_when_optional_keys_are_missing():
    settings = load_settings(
        {
            "PANEL_ENABLED": True,
            "PANEL_BASE_URL": "https://painel.example.com",
            "PANEL_OAUTH_CLIENT_SECRET": OAUTH_SECRET,
            "PANEL_COOKIE_SECRET": COOKIE_SECRET,
        }
    )
    assert (settings.session_ttl_hours, settings.session_idle_minutes) == (12, 60)
    assert settings.trust_proxy is False
    assert settings.insecure_cookies is False
    assert settings.oauth_client_id == ""


@pytest.mark.parametrize("host", ["localhost", "127.0.0.1", "[::1]"])
def test_http_is_allowed_only_for_local_hosts_with_insecure_cookies(host):
    settings = load_settings(local_config(PANEL_BASE_URL=f"http://{host}:8080"))
    assert settings.is_https is False
    assert settings.insecure_cookies is True


def test_settings_are_immutable():
    settings = load_settings(https_config())
    with pytest.raises(dataclasses.FrozenInstanceError):
        settings.enabled = False


# ------------------------------------------------------------------ PANEL_BASE_URL inválida


@pytest.mark.parametrize(
    "base_url",
    [
        "",
        "painel.example.com",
        "ftp://painel.example.com",
        "https://",
        "//painel.example.com",
        "https://painel.example.com/painel",
        "https://painel.example.com/?a=1",
        "https://painel.example.com/#frag",
    ],
)
def test_invalid_base_url_raises(base_url):
    with pytest.raises(_error_type()):
        load_settings(https_config(PANEL_BASE_URL=base_url))


def test_missing_base_url_raises_when_enabled():
    config = https_config()
    del config["PANEL_BASE_URL"]
    with pytest.raises(_error_type()):
        load_settings(config)


# ------------------------------------------------------------------ HTTPS obrigatório


@pytest.mark.parametrize(
    "config",
    [
        local_config(PANEL_INSECURE_COOKIES=False),  # localhost sem a flag
        local_config(PANEL_BASE_URL="http://painel.example.com"),  # http em host público + flag
        local_config(PANEL_BASE_URL="http://painel.example.com", PANEL_INSECURE_COOKIES=False),
        https_config(PANEL_INSECURE_COOKIES=True),  # flag com host não local
    ],
)
def test_http_or_insecure_cookies_outside_local_host_raises(config):
    with pytest.raises(_error_type()):
        load_settings(config)


# ------------------------------------------------------------------ segredos


def test_oauth_client_secret_is_required():
    with pytest.raises(_error_type()):
        load_settings(https_config(PANEL_OAUTH_CLIENT_SECRET=""))


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


def test_short_cookie_secret_raises_without_leaking_it():
    short = "curto-SEGREDO-123"
    with pytest.raises(_error_type()) as excinfo:
        load_settings(https_config(PANEL_COOKIE_SECRET=short))
    assert short not in str(excinfo.value)


def test_cookie_secret_with_32_chars_is_kept():
    secret = "k" * 32
    assert load_settings(https_config(PANEL_COOKIE_SECRET=secret)).cookie_secret == secret


def test_secrets_are_not_in_repr_or_str():
    settings = load_settings(https_config())
    rendered = repr(settings) + str(settings)
    assert OAUTH_SECRET not in rendered
    assert COOKIE_SECRET not in rendered


def test_error_messages_never_contain_secrets():
    with pytest.raises(_error_type()) as excinfo:
        load_settings(https_config(PANEL_BASE_URL="lixo"))
    assert OAUTH_SECRET not in str(excinfo.value)
    assert COOKIE_SECRET not in str(excinfo.value)


# ------------------------------------------------------------------ limites numéricos


@pytest.mark.parametrize(
    "key,value",
    [
        ("PANEL_SESSION_TTL_HOURS", 0),
        ("PANEL_SESSION_TTL_HOURS", 169),
        ("PANEL_SESSION_TTL_HOURS", -1),
        ("PANEL_SESSION_IDLE_MINUTES", 4),
        ("PANEL_SESSION_IDLE_MINUTES", 1441),
        ("PANEL_SESSION_IDLE_MINUTES", 0),
    ],
)
def test_out_of_range_session_limits_raise(key, value):
    with pytest.raises(_error_type()):
        load_settings(https_config(**{key: value}))


@pytest.mark.parametrize(
    "key,value",
    [
        ("PANEL_SESSION_TTL_HOURS", 1),
        ("PANEL_SESSION_TTL_HOURS", 168),
        ("PANEL_SESSION_IDLE_MINUTES", 5),
        ("PANEL_SESSION_IDLE_MINUTES", 1440),
    ],
)
def test_session_limits_boundaries_are_accepted(key, value):
    settings = load_settings(https_config(**{key: value}))
    attr = "session_ttl_hours" if key.endswith("HOURS") else "session_idle_minutes"
    assert getattr(settings, attr) == value


def test_trust_proxy_flag_is_propagated():
    assert load_settings(https_config(PANEL_TRUST_PROXY=True)).trust_proxy is True
