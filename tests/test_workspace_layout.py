"""Testes de layout do workspace, pastas ignoradas e arquivo .code-workspace (Fase A).

Garante que repositórios irmãos e diretórios locais/arquivados estejam
devidamente ignorados pelo git, fora do contexto do Docker, omitidos
da cobertura e mapeados corretamente no workspace multipasta do VSCode/IDE.
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

REQUIRED_IGNORES = ("repos/", "worktrees/", ".arquivo/", ".local/")


def _normalize_ignore_entry(entry: str) -> str:
    cleaned = entry.strip()
    if not cleaned or cleaned.startswith("#"):
        return ""
    cleaned = cleaned.lstrip("/")
    if not cleaned.endswith("/"):
        cleaned += "/"
    return cleaned


def _get_ignore_entries(file_name: str) -> set[str]:
    path = ROOT / file_name
    if not path.is_file():
        return set()
    entries = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        norm = _normalize_ignore_entry(line)
        if norm:
            entries.add(norm)
    return entries


def test_gitignore_covers_required_directories():
    """Garante que repos/, worktrees/, .arquivo/ e .local/ estejam no .gitignore."""
    entries = _get_ignore_entries(".gitignore")
    missing = [req for req in REQUIRED_IGNORES if req not in entries]
    assert not missing, f".gitignore não cobre: {missing}"


def test_dockerignore_covers_required_directories():
    """Garante que repos/, worktrees/, .arquivo/ e .local/ estejam no .dockerignore."""
    entries = _get_ignore_entries(".dockerignore")
    missing = [req for req in REQUIRED_IGNORES if req not in entries]
    assert not missing, f".dockerignore não cobre: {missing}"


def test_coverage_omit_covers_required_directories():
    """Garante que pyproject.toml omita repos, worktrees, .arquivo e .local na cobertura."""
    pyproject_path = ROOT / "pyproject.toml"
    assert pyproject_path.is_file(), "pyproject.toml não encontrado"
    content = pyproject_path.read_text(encoding="utf-8")
    for req in ("repos/*", "worktrees/*", ".arquivo/*", ".local/*"):
        assert req in content, f"pyproject.toml deve omitir {req} na cobertura"


def test_code_workspace_file_exists_and_is_valid_json():
    """Garante que EmpireMuse.code-workspace existe e é um JSON válido."""
    workspace_file = ROOT / "EmpireMuse.code-workspace"
    assert workspace_file.is_file(), "EmpireMuse.code-workspace não existe na raiz"
    try:
        data = json.loads(workspace_file.read_text(encoding="utf-8"))
    except Exception as exc:
        raise AssertionError(f"EmpireMuse.code-workspace não é um JSON válido: {exc}") from exc
    assert isinstance(data, dict), "Estrutura do workspace deve ser um objeto JSON"


def test_code_workspace_folders_structure():
    """Garante que EmpireMuse.code-workspace contenha as 3 pastas com caminhos relativos."""
    workspace_file = ROOT / "EmpireMuse.code-workspace"
    assert workspace_file.is_file(), "EmpireMuse.code-workspace não existe"
    data = json.loads(workspace_file.read_text(encoding="utf-8"))

    folders = data.get("folders", [])
    assert isinstance(folders, list), "'folders' deve ser uma lista"

    folder_paths = [f.get("path") for f in folders if isinstance(f, dict)]

    expected_folders = [
        ".",
        "repos/EmpireMuse-LL-binaries",
        "repos/EmpireMuse-RPC-app",
    ]
    for expected in expected_folders:
        assert expected in folder_paths, f"Pasta {expected!r} não está listada em folders"

    # Todos os caminhos devem ser estritamente relativos
    for p in folder_paths:
        assert p and not Path(p).is_absolute() and not p.startswith("/") and not p.startswith("\\"), (
            f"Caminho no workspace não é relativo: {p!r}"
        )


def test_code_workspace_search_excludes():
    """Garante que a raiz exclua da busca pastas sensíveis e pesadas."""
    workspace_file = ROOT / "EmpireMuse.code-workspace"
    assert workspace_file.is_file(), "EmpireMuse.code-workspace não existe"
    data = json.loads(workspace_file.read_text(encoding="utf-8"))

    settings = data.get("settings", {})
    search_excludes = settings.get("search.exclude", {})

    expected_excludes = (
        ".venv",
        ".java",
        "local_database",
        "worktrees",
        "repos",
        ".arquivo",
        ".local",
    )
    for excl in expected_excludes:
        assert search_excludes.get(excl) is True or search_excludes.get(f"**/{excl}") is True, (
            f"search.exclude deve excluir {excl}"
        )
