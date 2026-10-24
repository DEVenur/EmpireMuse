"""Guarda D5 (F3-7): os testes nunca enxergam a ``.runtime/`` real do desenvolvedor.

A ``.runtime/`` fica em ``PROJECT_DIR``, é ignorada pelo git e só existe no checkout principal. Se um teste a enxergasse,
``paths.get_runtime_dir()`` e ``enter_runtime_dir()`` mudariam de resultado conforme o lugar onde a suíte roda, e o
``.env`` real do desenvolvedor poderia ser lido ou sobrescrito. A guarda mora em ``tests/conftest.py`` (fixture
autouse ``_hide_dev_runtime``) e em ``tests/support/runtime_guard.py``.
"""

from tests.support.runtime_guard import DEV_RUNTIME_DIRNAME, hide_path


def test_hide_path_so_esconde_o_caminho_exato(tmp_path, monkeypatch):
    escondida = tmp_path / "projeto" / DEV_RUNTIME_DIRNAME
    escondida.mkdir(parents=True)
    outra_com_mesmo_nome = tmp_path / "outro" / DEV_RUNTIME_DIRNAME
    outra_com_mesmo_nome.mkdir(parents=True)
    irma = tmp_path / "projeto" / "assets"
    irma.mkdir()
    arquivo_dentro = escondida / "marcador.txt"
    arquivo_dentro.write_text("x", encoding="utf-8")

    hide_path(monkeypatch, escondida)

    assert outra_com_mesmo_nome.is_dir()
    assert irma.is_dir()
    assert (tmp_path / "projeto").is_dir()
    assert arquivo_dentro.is_file(), "a guarda esconde a pasta, não o que há dentro dela"
