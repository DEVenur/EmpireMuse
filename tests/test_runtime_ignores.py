"""F3-7 (AppSec A2) — a ``.runtime/`` e tudo dentro dela fica fora do git, da imagem Docker e do pacote da Discloud.

A pasta guarda ``.env``, ``config.json``, caches com tokens e ``guild_bots.json``. Um ``git add -A`` num dia em que ela
estiver cheia versionaria segredos. O padrão é ``.runtime`` SEM barra final: com barra, o git só casa diretório, e uma
``.runtime`` que seja link simbólico (o git a trata como arquivo) escaparia.

O git é consultado com ``git check-ignore`` num repositório descartável do ``tmp_path`` que recebe uma cópia do
``.gitignore`` do checkout. ``.dockerignore`` e ``.discloudignore`` são conferidos por leitura dos padrões.
"""

import os
import shutil
import subprocess
from pathlib import Path

import pytest
from tests.support.raiz import RAIZ

ROOT = RAIZ

DENTRO_DA_RUNTIME = [
    ".runtime/.env",
    ".runtime/config.json",
    ".runtime/local_database/x",
    ".runtime/guild_bots.json",
    ".runtime/.spotify_cache.json",
    ".runtime/.ytdl_cookie",
    ".runtime/Lavalink.jar",
]
PADROES_ACEITOS = {".runtime", "/.runtime"}  # sem barra final


def _linhas(nome: str) -> list[str]:
    texto = (ROOT / nome).read_text(encoding="utf-8")
    return [linha.strip() for linha in texto.splitlines() if linha.strip() and not linha.lstrip().startswith("#")]


class RepositorioDescartavel:
    """``git init`` no ``tmp_path`` com o ``.gitignore`` do checkout; o repositório real nunca é consultado."""

    def __init__(self, pasta: Path):
        self.pasta = pasta
        self.ambiente = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.ambiente.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_SYSTEM=os.devnull)
        pasta.mkdir()
        self.git("init", "-q")
        (pasta / ".gitignore").write_text((ROOT / ".gitignore").read_text(encoding="utf-8"), encoding="utf-8")

    def git(self, *argumentos: str) -> subprocess.CompletedProcess:
        return subprocess.run(["git", *argumentos], cwd=self.pasta, env=self.ambiente, capture_output=True, text=True)

    def ignorado(self, caminho: str) -> bool:
        resultado = self.git("check-ignore", "-q", "--", caminho)
        assert resultado.returncode in (0, 1), f"git check-ignore falhou: {resultado.stderr}"
        return resultado.returncode == 0

    def versionados_apos_add_all(self) -> list[str]:
        assert self.git("add", "-A").returncode == 0
        return self.git("ls-files").stdout.split()


@pytest.mark.skipif(shutil.which("git") is None, reason="git indisponível")
class TestGitignore:
    @pytest.fixture
    def repo(self, tmp_path):
        return RepositorioDescartavel(tmp_path / "repo")

    def test_a_pasta_runtime_e_ignorada(self, repo):
        (repo.pasta / ".runtime").mkdir()

        assert repo.ignorado(".runtime")

    @pytest.mark.parametrize("caminho", DENTRO_DA_RUNTIME)
    def test_arquivo_dentro_da_runtime_e_ignorado(self, repo, caminho):
        destino = repo.pasta / caminho
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_text("x", encoding="utf-8")

        assert repo.ignorado(caminho)

    def test_runtime_como_link_simbolico_e_ignorada(self, repo, tmp_path):
        """O git trata link simbólico como arquivo: um padrão com barra final (``.runtime/``) não o casa."""
        alvo = tmp_path / "dados_fora_do_repo"
        alvo.mkdir()
        (repo.pasta / ".runtime").symlink_to(alvo, target_is_directory=True)

        assert repo.ignorado(".runtime")

    def test_git_add_all_nao_versiona_nada_da_runtime(self, repo):
        for caminho in DENTRO_DA_RUNTIME:
            destino = repo.pasta / caminho
            destino.parent.mkdir(parents=True, exist_ok=True)
            destino.write_text("segredo", encoding="utf-8")

        assert repo.versionados_apos_add_all() == [".gitignore"]

    def test_git_add_all_nao_versiona_o_link_simbolico(self, repo, tmp_path):
        alvo = tmp_path / "dados_fora_do_repo"
        alvo.mkdir()
        (alvo / "config.json").write_text("segredo", encoding="utf-8")
        (repo.pasta / ".runtime").symlink_to(alvo, target_is_directory=True)

        assert repo.versionados_apos_add_all() == [".gitignore"]

    def test_padrao_sem_barra_final_e_sem_reinclusao(self):
        linhas = _linhas(".gitignore")

        assert PADROES_ACEITOS & set(linhas), ".gitignore precisa de '.runtime' (sem barra final)"
        assert not [linha for linha in linhas if linha.startswith("!") and ".runtime" in linha]


@pytest.mark.parametrize("arquivo", [".dockerignore", ".discloudignore"])
class TestIgnoresDeEmpacotamento:
    def test_tem_runtime_sem_barra_final(self, arquivo):
        linhas = _linhas(arquivo)

        assert PADROES_ACEITOS & set(linhas), f"{arquivo} precisa de '.runtime' (sem barra final)"

    def test_nao_reinclui_nada_da_runtime(self, arquivo):
        assert not [linha for linha in _linhas(arquivo) if linha.startswith("!") and ".runtime" in linha]
