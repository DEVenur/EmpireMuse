"""Bibliotecas vendorizadas (htmx 2.0.10, Pico CSS 2.1.1) e ausência de CDN em panel/."""

import hashlib
import re

import pytest

from tests.panel.helpers import PANEL_DIR, VENDOR_DIR

VENDORED_FILES = ["htmx.min.js", "pico.min.css", "LICENSE-htmx.txt", "LICENSE-pico.txt"]
CDN_HOSTS = (
    "cdn.jsdelivr.net",
    "unpkg.com",
    "cdnjs.cloudflare.com",
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "ajax.googleapis.com",
    "stackpath.bootstrapcdn.com",
    "maxcdn.bootstrapcdn.com",
    "code.jquery.com",
    "cdn.tailwindcss.com",
    "use.fontawesome.com",
    "esm.sh",
    "cdn.skypack.dev",
)
TEXT_SUFFIXES = {".html", ".js", ".css", ".py", ".txt", ".svg", ".md"}


def _read(name: str) -> bytes:
    path = VENDOR_DIR / name
    if not path.is_file():
        pytest.fail(f"panel/static/vendor/{name} não existe", pytrace=False)
    return path.read_bytes()


def _sums() -> dict:
    entries = {}
    for lineno, line in enumerate(_read("SHA256SUMS").decode().splitlines(), start=1):
        if not line.strip():
            continue
        match = re.fullmatch(r"([0-9a-f]{64}) [ *](.+)", line.strip())
        assert match, f"SHA256SUMS:{lineno}: formato diferente de sha256sum: {line!r}"
        entries[match.group(2)] = match.group(1)
    return entries


def test_sha256sums_lists_the_vendored_libraries():
    missing = {"htmx.min.js", "pico.min.css"} - set(_sums())
    assert not missing, f"SHA256SUMS sem: {sorted(missing)}"


def test_sha256sums_hashes_match_files():
    wrong = [name for name, digest in _sums().items() if hashlib.sha256(_read(name)).hexdigest() != digest]
    assert not wrong, f"hash não confere: {wrong}"


def test_all_vendored_files_are_present_and_not_placeholders():
    for name in VENDORED_FILES:
        assert len(_read(name)) > 500, f"{name} parece vazio/placeholder"
    assert len(_read("htmx.min.js")) > 20_000
    assert len(_read("pico.min.css")) > 20_000


def test_htmx_is_version_2_0_10():
    assert b"2.0.10" in _read("htmx.min.js")


def test_pico_is_version_2_1_1():
    assert b"2.1.1" in _read("pico.min.css")[:1000]


def test_htmx_license_is_zero_clause_bsd_full_text():
    text = _read("LICENSE-htmx.txt").decode()
    assert "Permission to use, copy, modify, and/or distribute this software" in text
    assert "THE SOFTWARE IS PROVIDED" in text


def test_pico_license_is_mit_full_text():
    text = _read("LICENSE-pico.txt").decode()
    assert "Permission is hereby granted, free of charge" in text
    assert "THE SOFTWARE IS PROVIDED" in text
    assert "Copyright" in text


def _panel_text_files():
    if not PANEL_DIR.is_dir():
        pytest.fail("diretório panel/ não existe", pytrace=False)
    return [p for p in PANEL_DIR.rglob("*") if p.is_file() and p.suffix in TEXT_SUFFIXES and p.parent != VENDOR_DIR]


def test_panel_has_no_cdn_references():
    violations = []
    for path in _panel_text_files():
        for lineno, line in enumerate(path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
            violations += [f"{path.relative_to(PANEL_DIR)}:{lineno}: {host}" for host in CDN_HOSTS if host in line]
    assert not violations, "Referências a CDN em panel/:\n  " + "\n  ".join(violations)


def test_panel_has_files_to_scan_for_cdn():
    assert any(p.suffix == ".html" for p in _panel_text_files()), "panel/ ainda não tem templates"
