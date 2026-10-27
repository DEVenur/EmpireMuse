"""Regressão (CodeRabbit, PR #109): atualizar o LL-binaries 0.0.4 -> 0.0.5 num host sem Docker deixava o plugin antigo.

O ``Lavalink.jar`` não muda entre as duas releases, então o hash dele já confere e a limpeza dos plugins não oficiais (que só
rodava ao baixar um jar novo) era pulada: ``plugins/`` ficava com ``lavalink-2.6.1.jar`` e ``lavalink-2.7.1.jar``, e o Lavalink
carrega todo .jar dali. A limpeza tem de rodar a cada preparo, só dentro de ``plugins/``.
"""

import hashlib

import pytest

from empiremuse.utils import branding
from empiremuse.utils.music import local_lavalink as ll

pytestmark = pytest.mark.regression

PLUGIN_ANTIGO = "lavalink-2.6.1.jar"


def sha(dados: bytes) -> str:
    return hashlib.sha256(dados).hexdigest()


@pytest.fixture
def instalacao(tmp_path, monkeypatch):
    """Pasta já na release atual (tudo com o hash oficial, nada a baixar) mais lixo de uma release anterior."""
    jar, yml = b"JAR", b"YML\n"
    plugins = {nome: f"plugin {nome}".encode() for nome in branding.LAVALINK_PLUGIN_SHA256}
    assert PLUGIN_ANTIGO not in plugins
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(jar))
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(yml))
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {nome: sha(dados) for nome, dados in plugins.items()})

    def sem_rede(*args, **kwargs):
        raise AssertionError("nada deveria ser baixado: os arquivos oficiais já estão na pasta")

    monkeypatch.setattr(ll.requests, "get", sem_rede)

    (tmp_path / "plugins").mkdir()
    (tmp_path / "Lavalink.jar").write_bytes(jar)
    (tmp_path / "application.yml").write_bytes(yml)
    for nome, dados in plugins.items():
        (tmp_path / "plugins" / nome).write_bytes(dados)
    (tmp_path / "plugins" / PLUGIN_ANTIGO).write_bytes(b"plugin da release anterior")
    (tmp_path / "plugins" / "notas.txt").write_text("não é jar", encoding="utf-8")
    (tmp_path / "extra.jar").write_bytes(b"fora de plugins/")
    return tmp_path, set(plugins)


def test_the_old_plugin_is_removed_even_though_the_lavalink_jar_did_not_change(instalacao):
    pasta, oficiais = instalacao

    ll.prepare_lavalink_files(str(pasta))

    jars = {p.name for p in (pasta / "plugins").glob("*.jar")}
    assert jars == oficiais


def test_only_jars_inside_plugins_are_touched(instalacao):
    pasta, _ = instalacao

    ll.prepare_lavalink_files(str(pasta))

    assert (pasta / "plugins" / "notas.txt").read_text(encoding="utf-8") == "não é jar"
    assert (pasta / "extra.jar").read_bytes() == b"fora de plugins/"
    assert (pasta / "Lavalink.jar").read_bytes() == b"JAR" and (pasta / "application.yml").read_bytes() == b"YML\n"
