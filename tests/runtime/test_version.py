"""A2 (item 18, P1) — a versão da imagem vem de ``EMPIREMUSE_VERSION``; ``dev``, vazio e inválido não são versão."""

import pytest

from empiremuse.rules.release import Version
from empiremuse.version import image_version, running_from_image

VARIAVEL = "EMPIREMUSE_VERSION"


def test_a_valid_version_is_parsed():
    assert image_version({VARIAVEL: "2.1.0"}) == Version(2, 1, 0)


@pytest.mark.parametrize("valor", ["dev", "", "2.1", "v2.1.0", "2.1.0-rc.1", "02.1.0", " 2.1.0", "nada"])
def test_dev_empty_and_invalid_values_are_not_a_version(valor):
    assert image_version({VARIAVEL: valor}) is None


def test_without_the_variable_there_is_no_version():
    assert image_version({}) is None


def test_the_default_environment_is_os_environ(monkeypatch):
    monkeypatch.setenv(VARIAVEL, "9.9.9")
    assert image_version() == Version(9, 9, 9)
    monkeypatch.delenv(VARIAVEL)
    assert image_version() is None


@pytest.mark.parametrize("valor", ["2.1.0", "dev", "", "lixo"])
def test_running_from_image_is_true_whenever_the_variable_exists(valor):
    assert running_from_image({VARIAVEL: valor}) is True


def test_running_from_image_is_false_without_the_variable():
    assert running_from_image({"PATH": "/usr/bin"}) is False
