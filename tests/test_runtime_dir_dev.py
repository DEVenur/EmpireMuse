"""F3-7 (D1 a D3) — pasta de execução de desenvolvimento ``.runtime/``.

Sem ``EMPIREMUSE_HOME``, o bot gravava Lavalink.jar, JDK, ``local_database/``, caches e ``.env`` no cwd, que em
desenvolvimento é a raiz do repositório. Agora, se ``PROJECT_DIR/.runtime`` existir como diretório, ela vira o
``RUNTIME_DIR`` e o cwd do processo. O ``GIT_DIR`` padrão continua ``RUNTIME_DIR/.git`` (AppSec A1): apontá-lo para
``PROJECT_DIR/.git`` com o cwd na ``.runtime`` faz o git tratar a ``.runtime`` como árvore de trabalho e o
``exportsource`` listar o ``.env`` e o ``config.json`` reais.
Produção não muda: Docker e Pterodactyl definem ``EMPIREMUSE_HOME``; a Discloud não recebe ``.runtime/``.

Os testes trocam ``paths.PROJECT_DIR`` por uma pasta do ``tmp_path`` e nunca tocam a ``.runtime`` real.
"""

import os

import pytest

from empiremuse import config_loader, paths


@pytest.fixture
def projeto(monkeypatch, tmp_path):
    """Projeto falso: PROJECT_DIR no tmp_path, cwd numa pasta à parte, sem EMPIREMUSE_HOME nem GIT_DIR."""
    raiz = (tmp_path / "projeto").resolve()
    raiz.mkdir()
    cwd = (tmp_path / "cwd").resolve()
    cwd.mkdir()
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz)
    monkeypatch.delenv("EMPIREMUSE_HOME", raising=False)
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.chdir(cwd)  # também garante que o chdir do enter_runtime_dir não vaza para outros testes
    return raiz, cwd


@pytest.fixture
def runtime_dev(projeto):
    raiz, _ = projeto
    pasta = raiz / ".runtime"
    pasta.mkdir()
    return pasta


# --------------------------------------------------------------------------------------------------------------
# D1 — get_runtime_dir()
# --------------------------------------------------------------------------------------------------------------


class TestGetRuntimeDir:
    def test_empiremuse_home_tem_precedencia_sobre_a_runtime(self, monkeypatch, tmp_path, runtime_dev):
        home = (tmp_path / "container").resolve()
        home.mkdir()
        monkeypatch.setenv("EMPIREMUSE_HOME", str(home))

        assert paths.get_runtime_dir() == home

    def test_runtime_existente_sem_env_e_o_runtime_dir(self, projeto, runtime_dev):
        assert paths.get_runtime_dir() == runtime_dev

    def test_runtime_dir_dinamico_acompanha_a_runtime(self, projeto, runtime_dev):
        assert paths.RUNTIME_DIR == runtime_dev

    def test_runtime_ausente_cai_no_cwd(self, projeto):
        _, cwd = projeto

        assert paths.get_runtime_dir() == cwd

    def test_runtime_que_e_arquivo_cai_no_cwd(self, projeto):
        raiz, cwd = projeto
        (raiz / ".runtime").write_text("não sou uma pasta", encoding="utf-8")

        assert paths.get_runtime_dir() == cwd

    def test_empiremuse_home_vazio_conta_como_ausente(self, monkeypatch, projeto, runtime_dev):
        monkeypatch.setenv("EMPIREMUSE_HOME", "")

        assert paths.get_runtime_dir() == runtime_dev


# --------------------------------------------------------------------------------------------------------------
# D2 — enter_runtime_dir()
# --------------------------------------------------------------------------------------------------------------


class TestEnterRuntimeDir:
    @pytest.fixture
    def main_module(self):
        import empiremuse.__main__ as main_module

        return main_module

    def test_entra_na_runtime_quando_ela_e_a_escolhida(self, projeto, runtime_dev, main_module):
        main_module.enter_runtime_dir()

        assert os.path.samefile(os.getcwd(), runtime_dev)

    def test_runtime_ausente_mantem_o_cwd(self, projeto, main_module):
        _, cwd = projeto

        main_module.enter_runtime_dir()

        assert os.path.samefile(os.getcwd(), cwd)

    def test_runtime_que_e_arquivo_mantem_o_cwd(self, projeto, main_module):
        raiz, cwd = projeto
        (raiz / ".runtime").write_text("não sou uma pasta", encoding="utf-8")

        main_module.enter_runtime_dir()

        assert os.path.samefile(os.getcwd(), cwd)

    def test_empiremuse_home_vence_a_runtime_na_entrada(self, monkeypatch, tmp_path, runtime_dev, main_module):
        home = (tmp_path / "container").resolve()
        home.mkdir()
        monkeypatch.setenv("EMPIREMUSE_HOME", str(home))

        main_module.enter_runtime_dir()

        assert os.path.samefile(os.getcwd(), home)

    def test_runtime_dir_continua_o_mesmo_depois_da_entrada(self, projeto, runtime_dev, main_module):
        antes = paths.get_runtime_dir()

        main_module.enter_runtime_dir()

        assert paths.get_runtime_dir() == antes == runtime_dev


# --------------------------------------------------------------------------------------------------------------
# D3 — GIT_DIR padrão
# --------------------------------------------------------------------------------------------------------------


class TestGitDirPadrao:
    def test_com_a_runtime_de_desenvolvimento_continua_sob_o_runtime_dir(self, projeto, runtime_dev):
        assert config_loader.load_config()["GIT_DIR"] == str(runtime_dev / ".git")

    def test_com_a_runtime_de_desenvolvimento_nunca_aponta_para_o_git_do_projeto(self, projeto, runtime_dev):
        raiz, _ = projeto

        assert config_loader.load_config()["GIT_DIR"] != str(raiz / ".git")

    @pytest.mark.parametrize("cenario", ["runtime_dev", "sem_runtime", "empiremuse_home"])
    def test_git_dir_padrao_e_sempre_o_runtime_dir(self, monkeypatch, tmp_path, projeto, request, cenario):
        if cenario == "runtime_dev":
            request.getfixturevalue("runtime_dev")
        elif cenario == "empiremuse_home":
            home = (tmp_path / "container").resolve()
            home.mkdir()
            monkeypatch.setenv("EMPIREMUSE_HOME", str(home))

        assert config_loader.load_config()["GIT_DIR"] == str(paths.get_runtime_dir() / ".git")

    def test_sem_a_runtime_continua_sob_o_runtime_dir(self, projeto):
        _, cwd = projeto

        assert config_loader.load_config()["GIT_DIR"] == str(cwd / ".git")

    def test_com_empiremuse_home_continua_sob_o_home(self, monkeypatch, tmp_path, runtime_dev):
        home = (tmp_path / "container").resolve()
        home.mkdir()
        monkeypatch.setenv("EMPIREMUSE_HOME", str(home))

        assert config_loader.load_config()["GIT_DIR"] == str(home / ".git")

    def test_git_dir_configurado_pelo_usuario_e_respeitado_com_a_runtime(self, monkeypatch, runtime_dev):
        monkeypatch.setenv("GIT_DIR", "/opt/meu/repo/.git")

        assert config_loader.load_config()["GIT_DIR"] == "/opt/meu/repo/.git"

    def test_config_json_da_runtime_e_lido_do_diretorio_dela(self, projeto, runtime_dev):
        (runtime_dev / "config.json").write_text('{"PREFIX": "dev!"}', encoding="utf-8")

        assert config_loader.load_config()["PREFIX"] == "dev!"
