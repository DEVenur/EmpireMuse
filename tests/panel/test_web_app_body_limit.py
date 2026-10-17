"""web_app.run_app: o HTTPServer da porta inteira limita o corpo a 64 KiB (MÉDIO-1 do QA / AppSec).

O limite vale antes de qualquer handler (XSRF, 413 do painel) e não pode quebrar `/` nem `/ws`.
"""

import asyncio
from types import SimpleNamespace

import pytest
import tornado.httpclient
import tornado.httpserver
import tornado.testing
import tornado.websocket

from tests.panel.helpers import local_config, require

LIMIT = 64 * 1024


def make_pool(config):
    config = {"ENABLE_RPC_AUTH": False, "DEFAULT_PREFIX": "!", **config}
    return SimpleNamespace(bots=[], database=None, config=config, killing_state=False, failed_bots={}, commit="")


def recording_server(monkeypatch, web_app, *, bind=False):
    """Troca o HTTPServer de web_app por um que registra os argumentos; com `bind`, escuta numa porta livre."""
    seen = {}
    real = tornado.httpserver.HTTPServer

    class Recorder(real):
        def __init__(self, request_callback, **kwargs):
            seen["kwargs"] = kwargs
            super().__init__(request_callback, **kwargs)

        def listen(self, port, address=""):
            if not bind:
                seen["port"] = port
                return
            sock, seen["port"] = tornado.testing.bind_unused_port()
            self.add_socket(sock)

    monkeypatch.setattr(web_app.tornado.httpserver, "HTTPServer", Recorder)
    return seen


class TestServerConfiguration:
    @pytest.mark.parametrize("panel_enabled", [True, False])
    def test_http_server_gets_max_body_size_64_kib_with_or_without_the_panel(self, monkeypatch, panel_enabled):
        web_app = require("empiremuse.web_app")
        seen = recording_server(monkeypatch, web_app)
        config = local_config(PANEL_ENABLED=panel_enabled, PORT=0)
        web_app.run_app(make_pool(config), config=make_pool(config).config)
        assert seen["kwargs"].get("max_body_size") == LIMIT, f"kwargs do HTTPServer: {seen['kwargs']}"

    def test_xheaders_behaviour_is_unchanged(self, monkeypatch):
        web_app = require("empiremuse.web_app")
        seen = recording_server(monkeypatch, web_app)
        config = local_config(PORT=0, PANEL_TRUST_PROXY=False)
        web_app.run_app(make_pool(config), config=make_pool(config).config)
        assert seen["kwargs"].get("xheaders") is False


def run_with_server(monkeypatch, scenario, **config_overrides):
    web_app = require("empiremuse.web_app")
    config = local_config(PORT=0, **config_overrides)

    async def main():
        seen = recording_server(monkeypatch, web_app, bind=True)
        web_app.run_app(make_pool(config), config=make_pool(config).config)
        base = f"http://127.0.0.1:{seen['port']}"
        return await scenario(base)

    return asyncio.run(main())


async def fetch(url, **kwargs):
    client = tornado.httpclient.AsyncHTTPClient()
    try:
        return await client.fetch(url, raise_error=False, follow_redirects=False, **kwargs)
    finally:
        client.close()


class TestRealServer:
    def test_post_over_64_kib_is_refused_before_reaching_any_handler(self, monkeypatch):
        async def scenario(base):
            small = await fetch(base + "/painel/login", method="POST", body="x=1")
            big = await fetch(base + "/painel/login", method="POST", body="x=" + "a" * (LIMIT + 1024))
            at_limit = await fetch(base + "/painel/login", method="POST", body="x=" + "a" * (LIMIT - 4096))
            return small, big, at_limit

        small, big, at_limit = run_with_server(monkeypatch, scenario)
        assert small.code == 403, f"controle: POST pequeno chega ao app e cai no XSRF (403), veio {small.code}"
        assert at_limit.code == 403, f"abaixo do limite ainda chega ao app, veio {at_limit.code}"
        assert big.code in (400, 413, 599), f"acima de 64 KiB deveria ser recusado pelo servidor, veio {big.code}"
        assert big.code != 403, "o corpo grande não pode chegar ao handler/XSRF"

    def test_post_over_64_kib_is_refused_on_the_main_port_routes_too(self, monkeypatch):
        async def scenario(base):
            return await fetch(base + "/", method="POST", body="x=" + "a" * (LIMIT + 1024))

        response = run_with_server(monkeypatch, scenario)
        assert response.code in (400, 413, 599), f"veio {response.code}"

    def test_index_and_websocket_still_work(self, monkeypatch):
        async def scenario(base):
            index = await fetch(base + "/")
            client = await tornado.websocket.websocket_connect(base.replace("http", "ws") + "/ws")
            await client.write_message('{"op": "ping"}')
            client.close()
            return index

        index = run_with_server(monkeypatch, scenario)
        assert index.code == 200, f"GET / deveria continuar 200, veio {index.code}"
