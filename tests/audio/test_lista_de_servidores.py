"""Testes do contrato de utils/music/lavalink_server_list.py (validação da lista de servidores Lavalink)."""

import configparser

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


def test_returns_content_when_status_200_and_ini_valid():
    assert _module().validated_server_list(200, VALID_INI) == VALID_INI


@pytest.mark.parametrize(
    "status,content",
    [
        (404, VALID_INI),
        (None, None),
    ],
)
def test_falls_back_to_bundled_for_bad_input(status, content):
    assert _module().validated_server_list(status, content) == _bundled_bytes()
