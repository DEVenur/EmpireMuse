"""Fixtures globais da suíte.

Isolamento do ambiente real: ``config_loader.load_config()`` chama ``dotenv_values()`` sem caminho, e o python-dotenv
procura o ``.env`` a partir do DIRETÓRIO DO MÓDULO (não do cwd). Sem este fixture, qualquer teste que chame
``load_config()`` lê o ``.env`` REAL do desenvolvedor (tokens, segredos do painel) mesmo com ``monkeypatch.chdir``, o que
torna o teste não determinístico e pode imprimir segredos na saída de uma falha. Testes que precisam de um ``.env``
próprio substituem ``config_loader.dotenv_values`` por um leitor do ``tmp_path``.

Isolamento da ``.runtime/`` de desenvolvimento (F3-7, D5): a pasta ``PROJECT_DIR/.runtime`` muda a decisão de
``paths.get_runtime_dir()`` e guarda o ``.env`` real do desenvolvedor. Ela existe no checkout principal, mas não nas
worktrees, então a suíte se comportaria de um jeito num lugar e de outro no outro. A guarda a faz parecer ausente.
"""

import pytest

from tests.support.runtime_guard import DEV_RUNTIME_DIRNAME, REAL_PROJECT_DIR, hide_path


@pytest.fixture(autouse=True)
def _isolate_real_dotenv(monkeypatch):
    for mod in ("empiremuse.config_loader", "config_loader"):
        try:
            __import__(mod)
        except ImportError:
            continue
        monkeypatch.setattr(f"{mod}.dotenv_values", lambda *args, **kwargs: {})


@pytest.fixture(autouse=True)
def _hide_dev_runtime(monkeypatch):
    hide_path(monkeypatch, REAL_PROJECT_DIR / DEV_RUNTIME_DIRNAME)
