"""Layout da raiz do repositório (F3-7): lista fechada do que pode ser versionado na raiz.

A raiz acumulava arquivos sem decisão. Estes testes fixam o que fica nela e por quê (plano F3-7, seção "Ficam na raiz");
acrescentar um arquivo ou pasta na raiz exige alterar a lista aqui, de propósito, num commit que explique o motivo.
Só olham o que o git versiona (``git ls-files``): ``.runtime/``, ``.env``, caches e afins são ignorados e não contam.
"""

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

# Documentos e identidade do projeto. LICENSE e CREDITS.md: atribuição GPL-2.0, exigida pela Discloud e pelo Dockerfile.
RAIZ_DOCUMENTOS = {"README.md", "LICENSE", "CHANGELOG.md", "CREDITS.md"}
# Instruções de agentes: as ferramentas procuram na raiz.
RAIZ_AGENTES = {"AGENTS.md", "CLAUDE.md"}
# Pontos de entrada e arquivos que a Discloud exige na raiz.
RAIZ_EXECUCAO = {"main.py", "requirements.txt", "discloud.config", ".discloudignore"}
# Convenção de ferramentas: build, container, editor, git e ambiente de exemplo.
RAIZ_FERRAMENTAS = {
    "pyproject.toml",
    "requirements-dev.txt",
    "Dockerfile",
    "docker-compose.yml",
    ".dockerignore",
    ".editorconfig",
    ".gitattributes",
    ".gitignore",
    ".git-blame-ignore-revs",
    ".example.env",
    "EmpireMuse.code-workspace",
}
ARQUIVOS_PERMITIDOS_NA_RAIZ = RAIZ_DOCUMENTOS | RAIZ_AGENTES | RAIZ_EXECUCAO | RAIZ_FERRAMENTAS

PASTAS_PERMITIDAS_NA_RAIZ = {".claude", ".github", "assets", "data", "deploy", "docs", "empiremuse", "tests"}

# Movidos na F3-7 (D6): não podem voltar para a raiz e precisam existir no destino.
MOVIDOS = {
    "CODE_OF_CONDUCT.md": ".github/CODE_OF_CONDUCT.md",
    "CONTRIBUTING.md": ".github/CONTRIBUTING.md",
    "SECURITY.md": ".github/SECURITY.md",
    "lavalink.ini.example": "deploy/lavalink.ini.example",
}


def _versionados() -> list[str]:
    try:
        saida = subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True, timeout=30
        ).stdout.decode("utf-8")
    except (OSError, subprocess.SubprocessError):
        pytest.skip("git indisponível ou fora de um repositório git")
    return [caminho for caminho in saida.split("\0") if caminho]


def _entradas_da_raiz() -> tuple[set[str], set[str]]:
    caminhos = _versionados()
    arquivos = {c for c in caminhos if "/" not in c}
    pastas = {c.split("/", 1)[0] for c in caminhos if "/" in c}
    return arquivos, pastas


def test_raiz_so_tem_arquivos_versionados_da_lista_fechada():
    arquivos, _ = _entradas_da_raiz()

    inesperados = sorted(arquivos - ARQUIVOS_PERMITIDOS_NA_RAIZ)

    assert not inesperados, (
        f"arquivos novos na raiz sem decisão: {inesperados}. Mova para a pasta do domínio (.github/, deploy/, docs/...) "
        "ou, se a raiz for mesmo o lugar, inclua na lista de tests/test_layout_raiz.py justificando."
    )


def test_raiz_so_tem_pastas_versionadas_da_lista_fechada():
    _, pastas = _entradas_da_raiz()

    inesperadas = sorted(pastas - PASTAS_PERMITIDAS_NA_RAIZ)

    assert not inesperadas, f"pastas novas na raiz sem decisão: {inesperadas}"


def test_todo_arquivo_permitido_na_raiz_continua_existindo():
    arquivos, _ = _entradas_da_raiz()

    ausentes = sorted(ARQUIVOS_PERMITIDOS_NA_RAIZ - arquivos)

    assert not ausentes, f"a lista permite arquivos que não existem mais (remova da lista): {ausentes}"


@pytest.mark.parametrize(("antigo", "novo"), sorted(MOVIDOS.items()))
def test_arquivo_movido_esta_no_destino_e_nao_na_raiz(antigo, novo):
    arquivos, _ = _entradas_da_raiz()

    assert antigo not in arquivos, f"{antigo} voltou para a raiz; o lugar dele é {novo}"
    assert (ROOT / novo).is_file(), f"{novo} não existe"
    assert not (ROOT / antigo).exists(), f"{antigo} ainda está no disco da raiz"


def test_codeowners_nao_aponta_para_arquivo_da_raiz_inexistente():
    linhas = (ROOT / ".github" / "CODEOWNERS").read_text(encoding="utf-8").splitlines()
    padroes = [linha.split()[0] for linha in linhas if linha.strip() and not linha.lstrip().startswith("#")]
    sem_curinga = [p for p in padroes if not any(c in p for c in "*?[")]

    quebrados = sorted(p for p in sem_curinga if not (ROOT / p.lstrip("/")).exists())

    assert not quebrados, f"CODEOWNERS aponta para caminhos que não existem: {quebrados}"
