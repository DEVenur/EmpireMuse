"""Teste-guarda: sem emojis personalizados do Discord herdados do upstream (MuseHeart-MusicBot, zRitsu, GPL-2.0).

Os emojis `<:nome:id>` / `<a:nome:id>` do upstream ficam em servidores do autor original e não renderizam nos bots do
EmpireMuse; foram trocados por emojis Unicode equivalentes. Estes testes impedem a volta de qualquer emoji
personalizado no código de runtime e garantem que os emojis passados a botões/selects (`emoji=...`) são Unicode,
válidos para o disnake (`PartialEmoji.from_str` sem `id`), sem subir o bot.
"""
import ast
import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CUSTOM_EMOJI_RE = re.compile(r"<a?:\w+:\d{15,20}>")
RUNTIME_DIRS = ("modules/", "utils/", "panel/", "wavelink/")
RUNTIME_FILES = ("main.py", "app.py", "config_loader.py", "web_app.py")


def _runtime_py_files() -> list[str]:
    tracked = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"], cwd=ROOT,
                             capture_output=True, text=True, check=True).stdout.split("\0")
    return sorted(p for p in set(tracked)
                  if p.endswith(".py") and (p.startswith(RUNTIME_DIRS) or p in RUNTIME_FILES) and (ROOT / p).is_file())


def _component_emoji_literals():
    """(arquivo, linha, valor) de toda constante de texto passada como `emoji=` (botões, selects, opções)."""
    found = []
    for path in _runtime_py_files():
        tree = ast.parse((ROOT / path).read_text(encoding="utf-8"), filename=path)
        for node in ast.walk(tree):
            if isinstance(node, ast.keyword) and node.arg == "emoji" and isinstance(node.value, ast.Constant) \
                    and isinstance(node.value.value, str) and node.value.value:
                found.append((path, node.value.lineno, node.value.value))
    return found


def test_runtime_files_have_no_custom_discord_emoji():
    violations = []
    for path in _runtime_py_files():
        for lineno, line in enumerate((ROOT / path).read_text(encoding="utf-8").splitlines(), start=1):
            violations.extend(f"{path}:{lineno}: {m.group(0)}" for m in CUSTOM_EMOJI_RE.finditer(line))
    assert not violations, (f"{len(violations)} emoji(s) personalizado(s) do Discord em arquivos de runtime "
                            "(troque por Unicode):\n  " + "\n  ".join(violations))


def test_component_emoji_literals_are_found_so_the_guard_is_not_vacuous():
    assert len(_component_emoji_literals()) > 50


def test_component_emojis_are_unicode_emojis_valid_for_disnake():
    disnake = pytest.importorskip("disnake")
    invalid = []
    for path, lineno, value in _component_emoji_literals():
        emoji = disnake.PartialEmoji.from_str(value)
        if emoji.id is not None or not emoji.is_unicode_emoji():
            invalid.append(f"{path}:{lineno}: {value!r}")
    assert not invalid, "emoji(s) de componente que não são Unicode simples:\n  " + "\n  ".join(invalid)
