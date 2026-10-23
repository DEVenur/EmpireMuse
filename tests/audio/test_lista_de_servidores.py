"""Testes do contrato de utils/music/lavalink_server_list.py (validação da lista de servidores Lavalink)."""

import configparser
from pathlib import Path

import pytest
from tests.support.raiz import RAIZ

ROOT = RAIZ
VALID_INI = (
    b"[node1]\nhost = lavalink.example\nport = 443\npassword = secret\n\n"
    b"[node2]\nhost = other.example\nport = 2333\npassword = youshallnotpass\n"
)


def _module():
    try:
        from empiremuse.utils.music import lavalink_server_list
    except ImportError as exc:
        pytest.fail(
            f"empiremuse/utils/music/lavalink_server_list.py ainda não existe (RED esperado): {exc}", pytrace=False
        )
    return lavalink_server_list


def _bundled_bytes() -> bytes:
    return (ROOT / "data" / "lavalink_servers.ini").read_bytes()


def test_bundled_path_points_to_repo_data_file_independent_of_cwd(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    module = _module()
    assert Path(module.BUNDLED_SERVER_LIST_PATH).resolve() == (ROOT / "data" / "lavalink_servers.ini").resolve()


def test_bundled_file_is_valid_for_the_consumer_parser_with_required_keys():
    parser = configparser.ConfigParser()  # mesmo parser do consumidor (BasicInterpolation)
    parser.read_string(_bundled_bytes().decode("utf-8"))
    assert parser.sections(), "arquivo bundled precisa de ao menos 1 seção"
    problems = []
    for section in parser.sections():
        try:
            values = dict(parser[section].items())  # materializa valores (interpolação)
        except configparser.Error as exc:
            problems.append(f"{section}: {exc}")
            continue
        problems += [f"{section}: sem '{key}'" for key in ("host", "port", "password") if key not in values]
    assert not problems, f"problemas no arquivo bundled: {problems}"


def test_bundled_file_passes_its_own_validation():
    content = _bundled_bytes()
    assert _module().validated_server_list(200, content) == content


def test_returns_content_when_status_200_and_ini_valid():
    assert _module().validated_server_list(200, VALID_INI) == VALID_INI


@pytest.mark.parametrize(
    "status,content",
    [
        (404, VALID_INI),
        (404, b"404: Not Found"),
        (500, VALID_INI),
        (200, b"404: Not Found"),
        (200, b"[node1]\nport = 443\n"),
        (200, b"[node1]\nhost = x.example\n"),
        (200, b"[node1]\nhost = x.example\nport = 443\n"),
        (200, b"[node1]\nhost = x.example\nport = 443\npassword = a%b\n"),
        (200, b"[ok]\nhost = a\nport = 1\npassword = p\n\n[ruim]\nhost = b\nport = 2\n"),
        (200, b"# so comentario\n"),
        (200, b""),
        (200, b"\xff\xfe\x00invalid"),
        (None, VALID_INI),
        (200, None),
        (None, None),
    ],
)
def test_falls_back_to_bundled_for_bad_input(status, content):
    assert _module().validated_server_list(status, content) == _bundled_bytes()


def test_accepts_escaped_percent_in_values():
    content = b"[node1]\nhost = x.example\nport = 443\npassword = a%%b\n"
    assert _module().validated_server_list(200, content) == content
