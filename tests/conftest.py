"""Fixtures globais da suíte.

Isolamento do ambiente real: ``config_loader.load_config()`` chama ``dotenv_values()`` sem caminho, e o python-dotenv
procura o ``.env`` a partir do DIRETÓRIO DO MÓDULO (não do cwd). Sem este fixture, qualquer teste que chame
``load_config()`` lê o ``.env`` REAL do desenvolvedor (tokens, segredos do painel) mesmo com ``monkeypatch.chdir``, o que
torna o teste não determinístico e pode imprimir segredos na saída de uma falha. Testes que precisam de um ``.env``
próprio substituem ``config_loader.dotenv_values`` por um leitor do ``tmp_path``.
"""
import pytest


@pytest.fixture(autouse=True)
def _isolate_real_dotenv(monkeypatch):
    try:
        import config_loader  # noqa: F401
    except ImportError:  # dependências de runtime ausentes: os testes que importam config_loader já falham sozinhos
        return
    monkeypatch.setattr("config_loader.dotenv_values", lambda *args, **kwargs: {})
