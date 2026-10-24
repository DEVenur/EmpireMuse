"""F3-6b, etapa 6 — complemento do QA, parte 2, depois da mutação do código REAL (usos dos caches, descarte do legado e ``fixfavs``).

Sobreviventes que não eram equivalentes: o ``cache_updater`` entrega uma LISTA (cópia) à thread e um erro de disco não o mata; o
Last.fm não lê arquivo acima de 4 MiB nem entrega o ``ItemsView`` vivo à thread; ``discard_legacy_cache`` é silencioso quando o
arquivo não existe e avisa (INFO, só com o nome) quando apaga; e o ``fixfavs`` regrava o backup do zero a cada execução, segue
quando um servidor não tem ``player_controller`` e limpa os espaços dos favoritos dos USUÁRIOS.
"""

import logging

import pytest

from empiremuse.utils.music.legacy_reader import discard_legacy_cache


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


class TestDescarteDoCacheAntigo:
    def test_arquivo_ausente_nao_avisa_nada(self, tmp_path, caplog):
        with caplog.at_level(logging.DEBUG):
            discard_legacy_cache(tmp_path / "nao_existe.pkl")
        assert caplog.records == []
