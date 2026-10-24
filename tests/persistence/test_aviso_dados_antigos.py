"""O aviso da subida sobre os dados do formato antigo (``.pkl``): só conta e nomeia, nunca abre nem apaga."""

import logging

import pytest

from empiremuse.utils.music.legacy_notice import log_ignored_legacy_data
from tests.support.avisos_no_log import avisos, log_sem_o_conteudo
from tests.support.serializacao_nucleo import SEGREDO

pytestmark = pytest.mark.critical


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


def gravar(caminho, conteudo=SEGREDO.encode()):
    caminho.parent.mkdir(parents=True, exist_ok=True)
    caminho.write_bytes(conteudo)
    return caminho


def test_sem_dados_antigos_nao_loga_nada(caplog):
    with caplog.at_level(logging.DEBUG):
        log_ignored_legacy_data()
    assert caplog.records == []


def test_avisa_com_a_contagem_por_pasta_sem_abrir_nem_apagar(tmp_path, caplog, capsys):
    base = tmp_path / "local_database"
    antigos = [
        gravar(base / "player_sessions" / "1" / "10.pkl"),
        gravar(base / "player_sessions" / "1" / "10.bak"),
        gravar(base / "player_sessions" / "2" / "20.pkl"),
        gravar(base / "saved_queues_v1" / "users" / "30.pkl"),
        gravar(base / "playlist_cache.pkl"),
        gravar(tmp_path / ".lastfm_cache"),
    ]
    novo = gravar(base / "player_sessions_json" / "1" / "10.json", b"{}")
    with caplog.at_level(logging.DEBUG):
        log_ignored_legacy_data()
    mensagens = avisos(caplog)
    assert any("3 arquivo(s)" in m and "player_sessions" in m for m in mensagens)
    assert any("1 arquivo(s)" in m and "saved_queues_v1" in m for m in mensagens)
    assert any("playlist_cache.pkl" in r.getMessage() and ".lastfm_cache" in r.getMessage() for r in caplog.records)
    assert not any("player_sessions_json" in m for m in mensagens)
    assert all(antigo.read_bytes() == SEGREDO.encode() for antigo in antigos) and novo.read_bytes() == b"{}"
    assert log_sem_o_conteudo(caplog, capsys)
