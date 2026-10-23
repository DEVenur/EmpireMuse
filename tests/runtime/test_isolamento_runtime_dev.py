"""Guarda D5 (F3-7): os testes nunca enxergam a ``.runtime/`` real do desenvolvedor.

A ``.runtime/`` fica em ``PROJECT_DIR``, é ignorada pelo git e só existe no checkout principal. Se um teste a enxergasse,
``paths.get_runtime_dir()`` e ``enter_runtime_dir()`` mudariam de resultado conforme o lugar onde a suíte roda, e o
``.env`` real do desenvolvedor poderia ser lido ou sobrescrito. A guarda mora em ``tests/conftest.py`` (fixture
autouse ``_hide_dev_runtime``) e em ``tests/helpers_runtime_guard.py``.
"""

import os
from pathlib import Path

from empiremuse import paths
from tests.support.runtime_guard import DEV_RUNTIME_DIRNAME, REAL_PROJECT_DIR, hide_path


def test_guarda_esta_ligada_em_todo_teste(request):
    assert "_hide_dev_runtime" in request.fixturenames


def test_runtime_dev_real_parece_ausente_para_path_e_os_path():
    real = REAL_PROJECT_DIR / DEV_RUNTIME_DIRNAME

    assert not real.exists()
    assert not real.is_dir()
    assert not real.is_file()
    assert not os.path.exists(real)
    assert not os.path.isdir(real)
    assert not os.path.isfile(real)
    assert not os.path.isdir(str(real))
    assert not os.path.isdir(os.fspath(real) + os.sep + ".." + os.sep + DEV_RUNTIME_DIRNAME)


def test_hide_path_esconde_diretorio_que_existe(tmp_path, monkeypatch):
    escondida = tmp_path / DEV_RUNTIME_DIRNAME
    escondida.mkdir()
    assert escondida.is_dir()  # pré-condição: sem a guarda ela é visível

    hide_path(monkeypatch, escondida)

    assert not escondida.exists()
    assert not escondida.is_dir()
    assert not os.path.isdir(escondida)
    assert not os.path.exists(str(escondida))


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


def test_hide_path_restaura_o_comportamento_ao_fim_do_teste(tmp_path):
    escondida = tmp_path / DEV_RUNTIME_DIRNAME
    escondida.mkdir()

    assert escondida.is_dir(), "o teste anterior vazou a guarda: a fixture precisa desfazer o patch"
    assert os.path.isdir(escondida)


def test_get_runtime_dir_ignora_runtime_escondida_do_projeto(tmp_path, monkeypatch):
    projeto = tmp_path / "projeto"
    (projeto / DEV_RUNTIME_DIRNAME).mkdir(parents=True)
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    monkeypatch.delenv("EMPIREMUSE_HOME", raising=False)
    monkeypatch.setattr(paths, "PROJECT_DIR", projeto)
    monkeypatch.chdir(cwd)
    hide_path(monkeypatch, projeto / DEV_RUNTIME_DIRNAME)

    assert paths.get_runtime_dir() == Path(cwd).resolve()
