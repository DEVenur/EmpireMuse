"""Guarda D5: esconde dos testes uma pasta que existe no disco do desenvolvedor.

A ``.runtime/`` de desenvolvimento (F3-7, D1) muda a decisão de ``paths.get_runtime_dir()`` quando existe em
``PROJECT_DIR``. Ela é ignorada pelo git e só existe no checkout principal, então um teste que chama
``get_runtime_dir()`` (ou ``enter_runtime_dir()``) sem ``EMPIREMUSE_HOME`` passaria na worktree e falharia, ou pior, leria
e gravaria no ``.env`` real do desenvolvedor, no checkout principal.

``PROJECT_DIR`` não pode ser trocado: ``branding``, ``lavalink_server_list`` e o painel guardam caminhos derivados dele na
importação, e testes comparam esses caminhos com ``paths.PROJECT_DIR``. Por isso a guarda faz o caminho exato parecer
ausente nas consultas de existência (``Path`` e ``os.path``), seja qual for o ponto de ``paths`` que o consulte.
"""

import os
from pathlib import Path

DEV_RUNTIME_DIRNAME = ".runtime"
REAL_PROJECT_DIR = Path(__file__).resolve().parent.parent


def hide_path(monkeypatch, hidden: Path) -> None:
    """Faz ``hidden`` parecer inexistente para ``exists``/``is_dir``/``is_file`` (``Path`` e ``os.path``)."""
    target = os.path.abspath(hidden)

    def is_hidden(candidate) -> bool:
        try:
            return os.path.abspath(candidate) == target
        except (TypeError, ValueError):
            return False

    def wrap_path_method(name: str) -> None:
        original = getattr(Path, name)

        def guarded(self, *args, **kwargs):
            return False if is_hidden(self) else original(self, *args, **kwargs)

        monkeypatch.setattr(Path, name, guarded)

    def wrap_os_path_function(name: str) -> None:
        original = getattr(os.path, name)

        def guarded(path, *args, **kwargs):
            return False if is_hidden(path) else original(path, *args, **kwargs)

        monkeypatch.setattr(os.path, name, guarded)

    for method in ("exists", "is_dir", "is_file"):
        wrap_path_method(method)
    for function in ("exists", "isdir", "isfile"):
        wrap_os_path_function(function)
