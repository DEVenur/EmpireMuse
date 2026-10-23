"""F3-7 (D1 a D4) — complemento do QA depois da mutação do código REAL (``paths.py``, ``__main__.py``, ``config_loader.py``).

Sobreviventes de ``tests/test_runtime_dir_dev.py`` que não eram equivalentes:

- ``enter_runtime_dir`` na ``.runtime/`` gravava ``EMPIREMUSE_HOME`` (o Docker e o Pterodactyl se reconhecem por ela);
- ``.runtime/`` como link simbólico não era resolvida (``RUNTIME_DIR`` apontava para o link, não para a pasta);
- a falha ao entrar na pasta de desenvolvimento dizia que a pasta vinha de ``EMPIREMUSE_HOME``;
- o ``.env`` lido vinha do ``RUNTIME_DIR`` (D4) e nenhum teste olhava de onde.

Mais a prova de que a guarda D5 cobre o caminho que o código usa (``PROJECT_DIR`` real, sem troca).
"""

import os

import pytest

from empiremuse import config_loader, paths
from tests.support.runtime_guard import REAL_PROJECT_DIR


@pytest.fixture
def main_module():
    import empiremuse.__main__ as main_module

    return main_module


@pytest.fixture
def projeto(monkeypatch, tmp_path):
    raiz = (tmp_path / "projeto").resolve()
    raiz.mkdir()
    cwd = (tmp_path / "cwd").resolve()
    cwd.mkdir()
    monkeypatch.setattr(paths, "PROJECT_DIR", raiz)
    monkeypatch.delenv("EMPIREMUSE_HOME", raising=False)
    monkeypatch.delenv("GIT_DIR", raising=False)
    monkeypatch.chdir(cwd)
    return raiz, cwd


@pytest.fixture
def runtime_dev(projeto):
    pasta = projeto[0] / ".runtime"
    pasta.mkdir()
    return pasta


class TestVariavelDeAmbiente:
    def test_entrar_na_runtime_nao_cria_empiremuse_home(self, projeto, runtime_dev, main_module):
        main_module.enter_runtime_dir()

        assert "EMPIREMUSE_HOME" not in os.environ

    def test_empiremuse_home_relativo_e_fixado_como_absoluto(self, monkeypatch, tmp_path, runtime_dev, main_module):
        (tmp_path / "container").mkdir()
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("EMPIREMUSE_HOME", "container")

        main_module.enter_runtime_dir()

        assert os.environ["EMPIREMUSE_HOME"] == str((tmp_path / "container").resolve())


class TestRuntimeComoLink:
    @pytest.fixture
    def runtime_link(self, projeto, tmp_path):
        alvo = (tmp_path / "disco_grande" / "dados").resolve()
        alvo.mkdir(parents=True)
        (projeto[0] / ".runtime").symlink_to(alvo, target_is_directory=True)
        return alvo

    def test_runtime_dir_e_a_pasta_apontada_pelo_link(self, runtime_link):
        assert paths.get_runtime_dir() == runtime_link

    def test_entra_na_pasta_apontada_pelo_link(self, runtime_link, main_module):
        main_module.enter_runtime_dir()

        assert os.path.samefile(os.getcwd(), runtime_link)

    def test_link_quebrado_cai_no_cwd(self, projeto, main_module):
        raiz, cwd = projeto
        (raiz / ".runtime").symlink_to(raiz / "nao_existe", target_is_directory=True)

        assert paths.get_runtime_dir() == cwd
        main_module.enter_runtime_dir()
        assert os.path.samefile(os.getcwd(), cwd)


class TestFalhaAoEntrar:
    @pytest.fixture
    def chdir_negado(self, monkeypatch):
        def recusa(_caminho):
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(os, "chdir", recusa)

    def test_falha_na_runtime_de_desenvolvimento_nomeia_a_runtime_e_nao_a_variavel(
        self, projeto, runtime_dev, chdir_negado, main_module
    ):
        with pytest.raises(SystemExit) as erro:
            main_module.enter_runtime_dir()

        mensagem = str(erro.value)
        assert "desenvolvimento" in mensagem
        assert str(runtime_dev) in mensagem
        assert "indicado por EMPIREMUSE_HOME" not in mensagem

    def test_falha_no_empiremuse_home_continua_nomeando_a_variavel(
        self, monkeypatch, tmp_path, runtime_dev, chdir_negado, main_module
    ):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))

        with pytest.raises(SystemExit) as erro:
            main_module.enter_runtime_dir()

        mensagem = str(erro.value)
        assert "indicado por EMPIREMUSE_HOME" in mensagem
        assert "desenvolvimento" not in mensagem


class TestRuntimeDirDinamico:
    def test_apagar_a_runtime_devolve_o_cwd(self, projeto, runtime_dev):
        _, cwd = projeto
        assert paths.get_runtime_dir() == runtime_dev

        runtime_dev.rmdir()

        assert paths.get_runtime_dir() == cwd


class TestOndeOEnvESaoLidos:
    """D4: ``.env`` e ``config.json`` do desenvolvedor moram na ``.runtime/``."""

    @pytest.fixture
    def leituras_de_env(self, monkeypatch):
        lidos = []

        def leitor(caminho=None, *args, **kwargs):
            lidos.append(caminho)
            return {"PREFIX": "env!"}

        monkeypatch.setattr(config_loader, "dotenv_values", leitor)
        return lidos

    def test_env_vem_da_runtime_de_desenvolvimento(self, projeto, runtime_dev, leituras_de_env):
        config = config_loader.load_config()

        assert [os.fspath(c) for c in leituras_de_env] == [str(runtime_dev / ".env")]
        assert config["PREFIX"] == "env!"

    def test_env_do_cwd_nao_e_lido_quando_a_runtime_existe(self, projeto, runtime_dev, leituras_de_env):
        _, cwd = projeto
        (cwd / ".env").write_text("PREFIX=do_cwd", encoding="utf-8")

        config_loader.load_config()

        assert str(cwd / ".env") not in [os.fspath(c) for c in leituras_de_env]

    def test_sem_a_runtime_o_env_continua_vindo_do_cwd(self, projeto, leituras_de_env):
        _, cwd = projeto

        config_loader.load_config()

        assert [os.fspath(c) for c in leituras_de_env] == [str(cwd / ".env")]

    def test_config_json_do_cwd_nao_vale_quando_a_runtime_existe(self, projeto, runtime_dev):
        _, cwd = projeto
        (cwd / "config.json").write_text('{"PREFIX": "do_cwd!"}', encoding="utf-8")

        assert config_loader.load_config().get("PREFIX") != "do_cwd!"


class TestGuardaD5CobreOCaminhoDoCodigo:
    """Sem trocar ``PROJECT_DIR``: se a ``.runtime/`` do checkout existir, a suíte não a enxerga."""

    @pytest.fixture
    def sem_projeto_falso(self, monkeypatch, tmp_path):
        assert paths.PROJECT_DIR == REAL_PROJECT_DIR, "este grupo precisa do PROJECT_DIR real"
        cwd = tmp_path.resolve()
        monkeypatch.chdir(cwd)
        monkeypatch.delenv("EMPIREMUSE_HOME", raising=False)
        monkeypatch.delenv("GIT_DIR", raising=False)
        return cwd

    def test_dev_runtime_dir_do_projeto_real_e_none(self, sem_projeto_falso):
        assert paths.dev_runtime_dir() is None

    def test_runtime_dir_do_projeto_real_e_o_cwd(self, sem_projeto_falso):
        assert paths.get_runtime_dir() == sem_projeto_falso

    def test_enter_runtime_dir_do_projeto_real_nao_muda_o_cwd(self, sem_projeto_falso, main_module):
        main_module.enter_runtime_dir()

        assert os.path.samefile(os.getcwd(), sem_projeto_falso)

    def test_git_dir_do_projeto_real_fica_sob_o_cwd(self, sem_projeto_falso):
        assert config_loader.load_config()["GIT_DIR"] == str(sem_projeto_falso / ".git")
