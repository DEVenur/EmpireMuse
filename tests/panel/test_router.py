"""panel.make_router — separação entre /painel e o app atual."""

import tornado.web
from tornado.testing import AsyncHTTPTestCase

from tests.panel.helpers import require


class _Main(tornado.web.RequestHandler):
    def get(self, *_):
        self.write("main-app")


class _Panel(tornado.web.RequestHandler):
    def get(self, *_):
        self.write("panel-app")


def _main_app():
    return tornado.web.Application([(r"/", _Main), (r"/ws", _Main), (r"/(.*)", _Main)])


def _panel_app():
    return tornado.web.Application([(r"/painel(?:/.*)?", _Panel)])


class RouterWithPanelTest(AsyncHTTPTestCase):
    def setUp(self):
        require("panel")
        super().setUp()

    def get_app(self):
        return require("panel").make_router(_main_app(), _panel_app())

    def _body(self, path):
        return self.fetch(path, follow_redirects=False).body.decode()

    def test_root_and_ws_stay_with_main_app(self):
        assert self._body("/") == "main-app"
        assert self._body("/ws") == "main-app"

    def test_painel_paths_go_to_panel_app(self):
        for path in ("/painel", "/painel/", "/painel/saude", "/painel/static/css/x.css"):
            assert self._body(path) == "panel-app", path

    def test_prefix_lookalikes_go_to_main_app(self):
        for path in ("/painelx", "/painel-foo", "/PAINEL", "/outro/painel"):
            assert self._body(path) == "main-app", path


class RouterWithoutPanelTest(AsyncHTTPTestCase):
    def setUp(self):
        require("panel")
        super().setUp()

    def get_app(self):
        return require("panel").make_router(_main_app(), None)

    def test_everything_goes_to_main_app_when_panel_is_disabled(self):
        for path in ("/", "/ws", "/painel", "/painel/", "/painel/saude"):
            assert self.fetch(path, follow_redirects=False).body.decode() == "main-app", path


def test_build_panel_app_returns_none_when_disabled():
    from tests.panel.helpers import fake_pool, load_settings

    settings = load_settings({"PANEL_ENABLED": False})
    assert require("panel").build_panel_app(fake_pool(), settings) is None


def test_run_app_listens_through_the_router():
    source = (require("tests.panel.helpers").ROOT / "web_app.py").read_text(encoding="utf-8")
    assert "make_router" in source, "web_app.run_app deve escutar com panel.make_router"
