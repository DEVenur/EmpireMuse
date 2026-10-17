"""Testes-guarda da Fase 1.1 (convite de suporte, identidade visual e governança).

Escritos a partir do contrato (BRIEFING-FASE1_1.md), antes da implementação (RED).
"""

import logging
import re
import struct
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
INVITE = "https://discord.gg/KgtyNg9U6H"
PALETTE = ("#0B0A1F", "#3B82F6", "#8B5CF6", "#C026D3", "#E11D48")
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
MB = 1024 * 1024


def _read(rel: str) -> str:
    path = ROOT / rel
    if not path.is_file():
        pytest.fail(f"{rel} não existe", pytrace=False)
    return path.read_text(encoding="utf-8")


def _branding():
    try:
        from empiremuse.utils import branding
    except ImportError as exc:
        pytest.fail(f"utils.branding não importa: {exc}", pytrace=False)
    return branding


def _config_loader(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    import empiremuse.config_loader as config_loader

    return config_loader


# --------------------------------------------------------------------------- 1. branding


def test_branding_support_server_url_matches_contract():
    assert getattr(_branding(), "SUPPORT_SERVER_URL", None) == INVITE


def test_branding_embed_color_hex_is_violet_of_palette():
    assert getattr(_branding(), "EMBED_COLOR_HEX", None) == "8B5CF6"


# --------------------------------------------------------------------------- 2. DEFAULT_CONFIG


def test_default_config_support_server_uses_branding_constant(monkeypatch, tmp_path):
    config = _config_loader(monkeypatch, tmp_path)
    assert config.DEFAULT_CONFIG["SUPPORT_SERVER"] == INVITE


def test_default_config_embed_color_uses_branding_constant(monkeypatch, tmp_path):
    config = _config_loader(monkeypatch, tmp_path)
    assert config.DEFAULT_CONFIG["EMBED_COLOR"] == "8B5CF6"


# --------------------------------------------------------------------------- 3. parse_embed_color


def _parse(monkeypatch, tmp_path, value):
    config = _config_loader(monkeypatch, tmp_path)
    parse = getattr(config, "parse_embed_color", None)
    if parse is None:
        pytest.fail("config_loader.parse_embed_color ainda não existe (RED esperado)", pytrace=False)
    return parse(value)


@pytest.mark.parametrize("value", ["8B5CF6", "8b5cf6", "#8B5CF6", "#8b5cf6"])
def test_parse_embed_color_accepts_valid_hex(monkeypatch, tmp_path, value):
    import disnake

    assert _parse(monkeypatch, tmp_path, value) == disnake.Color(0x8B5CF6)


@pytest.mark.parametrize("value", [None, "", "none", "None"])
def test_parse_embed_color_returns_none_silently_for_empty_values(monkeypatch, tmp_path, caplog, value):
    with caplog.at_level(logging.WARNING):
        result = _parse(monkeypatch, tmp_path, value)
    assert result is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], "valor vazio não deve gerar aviso"


@pytest.mark.parametrize("value", ["zzz", "12345", "1234567", "#GGGGGG"])
def test_parse_embed_color_returns_none_and_warns_for_invalid_values(monkeypatch, tmp_path, caplog, value):
    with caplog.at_level(logging.WARNING):
        result = _parse(monkeypatch, tmp_path, value)
    assert result is None
    assert [r for r in caplog.records if r.levelno == logging.WARNING], f"valor inválido {value!r} deve emitir WARNING"


def test_parse_embed_color_whitespace_only_returns_none_silently(monkeypatch, tmp_path, caplog):
    with caplog.at_level(logging.WARNING):
        result = _parse(monkeypatch, tmp_path, "  ")
    assert result is None
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], "valor só com espaços não deve gerar aviso"


def test_parse_embed_color_warning_does_not_leak_invalid_value(monkeypatch, tmp_path, caplog):
    marker = "zz-SEGREDO-zz"
    with caplog.at_level(logging.WARNING):
        result = _parse(monkeypatch, tmp_path, marker)
    assert result is None
    warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
    assert warnings, "valor inválido deve emitir WARNING"
    leaked = [
        r.getMessage()
        for r in caplog.records
        if marker.lower() in (r.getMessage() + str(r.args) + str(r.exc_info)).lower()
    ]
    assert not leaked, f"o valor inválido vazou no log: {leaked}"


# --------------------------------------------------------------------------- 4. .example.env


def test_example_env_has_support_server_invite():
    assert f"SUPPORT_SERVER='{INVITE}'" in _read(".example.env").splitlines()


def test_example_env_has_default_embed_color():
    assert "EMBED_COLOR=8B5CF6" in _read(".example.env").splitlines()


# --------------------------------------------------------------------------- 5. logo.svg


def _svg_root():
    path = ROOT / "assets/brand/logo.svg"
    if not path.is_file():
        pytest.fail("assets/brand/logo.svg não existe", pytrace=False)
    try:
        return ET.fromstring(path.read_bytes()), path.read_text(encoding="utf-8")
    except ET.ParseError as exc:
        pytest.fail(f"logo.svg não é XML válido: {exc}", pytrace=False)


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def test_logo_svg_is_valid_xml_with_svg_root():
    root, _ = _svg_root()
    assert _local(root.tag) == "svg", f"raiz deve ser <svg>, é <{_local(root.tag)}>"


@pytest.mark.parametrize("forbidden", ["script", "foreignObject"])
def test_logo_svg_has_no_active_content(forbidden):
    root, _ = _svg_root()
    found = [e for e in root.iter() if _local(e.tag).lower() == forbidden.lower()]
    assert not found, f"logo.svg não pode conter <{forbidden}>"


def test_logo_svg_has_no_external_href():
    root, _ = _svg_root()
    external = [
        value
        for el in root.iter()
        for key, value in el.attrib.items()
        if _local(key) == "href" and re.match(r"\s*(https?:)?//", value, re.IGNORECASE)
    ]
    assert not external, f"href externo em logo.svg: {external}"


def test_logo_svg_has_no_external_imports_or_urls():
    _, text = _svg_root()
    assert "@import" not in text, "logo.svg não pode usar @import"
    assert not re.search(r"url\(\s*['\"]?\s*(https?:)?//", text, re.IGNORECASE), "logo.svg com url() externo"


# --------------------------------------------------------------------------- 6/7. PNGs


def _png_size(rel: str, max_bytes: int):
    path = ROOT / rel
    if not path.is_file():
        pytest.fail(f"{rel} não existe", pytrace=False)
    data = path.read_bytes()
    assert data[:8] == PNG_SIGNATURE, f"{rel} não tem assinatura PNG"
    assert data[12:16] == b"IHDR", f"{rel}: primeiro chunk deve ser IHDR"
    assert len(data) <= max_bytes, f"{rel} tem {len(data)} bytes (máx. {max_bytes})"
    return struct.unpack(">II", data[16:24])


def test_avatar_png_is_1024_square_under_2mb():
    assert _png_size("assets/brand/avatar.png", 2 * MB) == (1024, 1024)


def test_banner_png_is_1500_by_600_under_4mb():
    assert _png_size("assets/brand/banner.png", 4 * MB) == (1500, 600)


# --------------------------------------------------------------------------- 8-11. docs e governança


def test_readme_has_invite_and_logo_without_todo():
    text = _read("README.md")
    assert INVITE in text, "README.md sem o convite do Discord"
    assert "assets/brand/logo.svg" in text, "README.md deve referenciar assets/brand/logo.svg"
    assert "TODO(dono): convite" not in text, "README.md ainda tem o TODO do convite"


def test_readme_logo_path_exists_in_repository():
    match = re.search(r'src="(assets/brand/logo\.svg)"', _read("README.md"))
    assert match, "README.md deve referenciar assets/brand/logo.svg em um <img src=...>"
    assert (ROOT / match.group(1)).is_file(), f"README.md aponta para {match.group(1)}, que não existe"


def test_code_of_conduct_has_invite_without_todo():
    text = _read("CODE_OF_CONDUCT.md")
    assert INVITE in text, "CODE_OF_CONDUCT.md sem o convite"
    assert "TODO(dono)" not in text, "CODE_OF_CONDUCT.md ainda tem TODO(dono)"


def test_security_md_has_no_pending_maintainers_comment():
    assert "PENDÊNCIA (mantenedores)" not in _read("SECURITY.md")


def test_issue_template_config_links_support_and_security_advisory():
    text = _read(".github/ISSUE_TEMPLATE/config.yml")
    assert INVITE in text, "config.yml sem o convite"
    assert "security/advisories/new" in text, "config.yml sem link de relato privado de vulnerabilidade"


# --------------------------------------------------------------------------- 12. CODEOWNERS

CODEOWNERS_SENSITIVE_PATHS = [
    "/data/",
    "/empiremuse/utils/branding.py",
    "/empiremuse/utils/music/local_lavalink.py",
    "/empiremuse/utils/music/lavalink_server_list.py",
    "/requirements*.txt",
    "/.github/",
    "/LICENSE",
    "/SECURITY.md",
    "/empiremuse/config_loader.py",
    "/empiremuse/web_app.py",
    "/empiremuse/cogs/legacy_cmds.py",
    "/empiremuse/utils/owner_panel.py",
    "/empiremuse/utils/db.py",
    "/pyproject.toml",
]


@pytest.mark.parametrize("pattern", CODEOWNERS_SENSITIVE_PATHS)
def test_codeowners_covers_sensitive_path_with_owner(pattern):
    lines = [
        l.split() for l in _read(".github/CODEOWNERS").splitlines() if l.strip() and not l.lstrip().startswith("#")
    ]
    owners = [parts[1:] for parts in lines if parts[0] == pattern]
    assert owners, f"CODEOWNERS não cobre {pattern}"
    assert "@Or4cu1o" in owners[0], f"{pattern} sem @Or4cu1o em CODEOWNERS"


# --------------------------------------------------------------------------- 13. docs


@pytest.mark.parametrize("color", PALETTE)
def test_identity_doc_lists_palette_color(color):
    assert color.lower() in _read("docs/identidade-visual.md").lower(), f"docs/identidade-visual.md sem {color}"
