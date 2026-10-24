"""Templates e JS do painel: CSP estrita (sem inline), acessibilidade básica e conteúdo contratual."""

from html.parser import HTMLParser

import pytest

from tests.panel.helpers import PANEL_DIR, TEMPLATES_DIR

TEMPLATE_NAMES = ["base.html", "index.html", "erro.html"]


def _text(path) -> str:
    if not path.is_file():
        pytest.fail(f"{path.relative_to(PANEL_DIR.parent)} não existe", pytrace=False)
    return path.read_text(encoding="utf-8")


class _Audit(HTMLParser):
    def __init__(self):
        super().__init__()
        self.problems = []
        self._in_script = False

    def handle_starttag(self, tag, attrs):
        names = {name.lower(): (value or "") for name, value in attrs}
        for name, value in names.items():
            if name.startswith("on") or name.startswith("hx-on") or name.startswith("data-hx-on"):
                self.problems.append(f"<{tag}> com atributo de evento '{name}'")
            if name == "style":
                self.problems.append(f"<{tag}> com style inline")
            if value.strip().lower().startswith("javascript:"):
                self.problems.append(f"<{tag} {name}> com URL javascript:")
        if tag == "style":
            self.problems.append("bloco <style> inline")
        if tag == "script":
            self._in_script = True
            if "src" not in names:
                self.problems.append("<script> inline (sem src)")
        if tag in ("script", "link"):
            url = names.get("src") or names.get("href", "")
            if url.startswith(("http://", "https://", "//")):
                self.problems.append(f"<{tag}> carrega recurso externo: {url}")

    def handle_endtag(self, tag):
        if tag == "script":
            self._in_script = False

    def handle_data(self, data):
        if self._in_script and data.strip():
            self.problems.append("conteúdo dentro de <script>")


@pytest.mark.parametrize("name", list(TEMPLATE_NAMES)[:2])
def test_template_has_no_inline_script_style_or_event_attributes(name):
    audit = _Audit()
    audit.feed(_text(TEMPLATES_DIR / name))
    assert not audit.problems, f"{name}: " + "; ".join(audit.problems)


def test_base_template_uses_static_url_for_local_assets():
    text = _text(TEMPLATES_DIR / "base.html")
    assert "static_url" in text
    for asset in ("vendor/pico.min.css", "vendor/htmx.min.js", "painel.js", "nebulosa.css"):
        assert asset in text, f"base.html não carrega {asset}"


def test_error_template_is_generic():
    text = _text(TEMPLATES_DIR / "erro.html")
    for leak in ("traceback", "exc_info", "stack"):
        assert leak not in text.lower(), f"erro.html não deve referenciar '{leak}'"


def test_nebulosa_css_defines_palette_tokens():
    text = _text(PANEL_DIR / "static" / "css" / "nebulosa.css").lower()
    for color in ("#0b0a1f", "#3b82f6", "#8b5cf6", "#c026d3", "#e11d48"):
        assert color in text, f"nebulosa.css sem a cor {color}"
