"""V-AS-L1 (Vigil, Médio) — ``/painel/marca/*`` é público e os arquivos são grandes (logo 6 MB, avatar 2,5 MB, favicon 432 KB): lidos UMA vez e servidos da
memória (sem ler o disco a cada GET), com ETag e GET condicional (304 sem corpo), ``Cache-Control`` longo (nomes fixos) e recusa de arquivo de marca que
seja link simbólico. Reaproveita a base do painel de ``test_app.py``.
"""

import asyncio
import builtins
import importlib
import threading
import pathlib
import re
import tempfile
from unittest import mock

import pytest
import tornado.testing
from tornado import httputil
from tornado.http1connection import HTTP1Connection

from empiremuse.panel.handlers import brand
from tests.panel.test_app import PanelTestBase

pytestmark = pytest.mark.critical

ARQUIVOS = ["logo-256.png", "logo.svg", "avatar.png", "favicon.ico"]


def max_age(cabecalho: str) -> int | None:
    achado = re.search(r"max-age=(\d+)", cabecalho)
    return int(achado.group(1)) if achado else None


class PanelBrandCacheTest(PanelTestBase):
    def _lidos_da_marca(self, chamadas):
        return [c for c in chamadas if "assets/brand" in c.replace("\\", "/")]

    def test_the_brand_files_are_read_at_most_once_and_then_served_from_memory(self):
        lidos: list[str] = []
        abrir, ler_bytes, abrir_path = builtins.open, pathlib.Path.read_bytes, pathlib.Path.open

        def espia_open(arquivo, *a, **k):
            lidos.append(str(arquivo))
            return abrir(arquivo, *a, **k)

        def espia_bytes(self_, *a, **k):
            lidos.append(str(self_))
            return ler_bytes(self_, *a, **k)

        def espia_path(self_, *a, **k):
            lidos.append(str(self_))
            return abrir_path(self_, *a, **k)

        for nome in ARQUIVOS:  # aquece: a primeira leitura pode acontecer aqui
            self.get_page(f"/painel/marca/{nome}")
        with (
            mock.patch.object(builtins, "open", espia_open),
            mock.patch.object(pathlib.Path, "read_bytes", espia_bytes),
            mock.patch.object(pathlib.Path, "open", espia_path),
        ):
            for _ in range(3):
                for nome in ARQUIVOS:
                    assert self.get_page(f"/painel/marca/{nome}").code == 200

        assert self._lidos_da_marca(lidos) == []

    def test_repeated_requests_return_identical_bodies(self):
        def check(nome):
            primeiro, segundo = self.get_page(f"/painel/marca/{nome}"), self.get_page(f"/painel/marca/{nome}")
            assert primeiro.body == segundo.body and len(primeiro.body) > 0

        self.assert_all(ARQUIVOS, check)

    def test_each_brand_file_carries_a_stable_etag(self):
        def check(nome):
            a, b = self.get_page(f"/painel/marca/{nome}"), self.get_page(f"/painel/marca/{nome}")
            assert a.headers.get("Etag") and a.headers["Etag"] == b.headers["Etag"]

        self.assert_all(ARQUIVOS, check)

    def test_the_etags_of_different_files_differ(self):
        etags = {nome: self.get_page(f"/painel/marca/{nome}").headers.get("Etag") for nome in ARQUIVOS}

        assert len(set(etags.values())) == len(ARQUIVOS) and all(etags.values())

    def test_a_conditional_get_with_the_current_etag_returns_304_without_a_body(self):
        def check(nome):
            etag = self.get_page(f"/painel/marca/{nome}").headers["Etag"]
            resposta = self.fetch(
                f"/painel/marca/{nome}".replace("/painel", "/painel", 1),
                headers={"If-None-Match": etag},
                follow_redirects=False,
            )
            assert resposta.code == 304 and resposta.body == b""
            assert resposta.headers.get("Etag") == etag

        self.assert_all(ARQUIVOS, check)

    def test_a_conditional_get_with_another_etag_returns_the_whole_file(self):
        def check(nome):
            resposta = self.fetch(f"/painel/marca/{nome}", headers={"If-None-Match": '"outro"'}, follow_redirects=False)
            assert resposta.code == 200 and len(resposta.body) > 0

        self.assert_all(ARQUIVOS, check)

    def test_the_304_keeps_the_cache_control_header(self):
        etag = self.get_page("/painel/marca/logo.svg").headers["Etag"]

        resposta = self.fetch("/painel/marca/logo.svg", headers={"If-None-Match": etag}, follow_redirects=False)

        assert resposta.code == 304 and max_age(resposta.headers.get("Cache-Control", "")) is not None

    def test_the_cache_control_is_public_for_one_day(self):
        def check(nome):
            controle = self.get_page(f"/painel/marca/{nome}").headers.get("Cache-Control", "")
            assert controle == "public, max-age=86400", controle

        self.assert_all(ARQUIVOS, check)

    def test_a_head_request_also_gets_the_headers_without_reading_the_disk_again(self):
        resposta = self.fetch("/painel/marca/logo.svg", method="HEAD", follow_redirects=False)

        assert resposta.code in (200, 405) and resposta.body == b""


class PanelBrandColdBurstTest(PanelTestBase):
    """Rajada de primeiras requisições do mesmo arquivo: uma só leitura e um só hash (o logo.svg tem 6 MB e a rota é pública)."""

    RAJADA = 8
    PASSOS_DO_LACO = 3000  # voltas do laço (sem relógio) para a rajada inteira chegar ao handler

    def _contador(self, falhar_primeiro: bool = False):
        real, chamadas, solta = brand._load, [], threading.Event()

        def contado(nome):
            chamadas.append(nome)
            if len(chamadas) == 1 and falhar_primeiro:
                raise FileNotFoundError(nome)
            solta.wait(timeout=5)  # segura a leitura até a rajada chegar; sem isso a primeira acabaria antes das outras
            return real(nome)

        return chamadas, solta, contado

    @tornado.testing.gen_test
    async def test_concurrent_first_requests_for_one_file_load_it_exactly_once(self):
        chamadas, solta, contado = self._contador()
        with mock.patch.dict(brand._cache, clear=True), mock.patch.object(brand, "_load", contado):
            url = self.get_url("/painel/marca/logo.svg")
            tarefas = [
                asyncio.ensure_future(self.http_client.fetch(url, raise_error=False)) for _ in range(self.RAJADA)
            ]
            for _ in range(self.PASSOS_DO_LACO):
                if len(chamadas) >= self.RAJADA:
                    break
                await asyncio.sleep(0)
            solta.set()
            respostas = await asyncio.gather(*tarefas)

        assert len(chamadas) == 1, f"{len(chamadas)} leituras para {self.RAJADA} requisições simultâneas"
        assert {r.code for r in respostas} == {200}
        assert len({r.body for r in respostas}) == 1 and len({r.headers["Etag"] for r in respostas}) == 1

    @tornado.testing.gen_test
    async def test_a_failed_load_is_not_cached_and_the_next_request_retries(self):
        chamadas, solta, contado = self._contador(falhar_primeiro=True)
        solta.set()
        with mock.patch.dict(brand._cache, clear=True), mock.patch.object(brand, "_load", contado):
            url = self.get_url("/painel/marca/logo.svg")
            primeira = await self.http_client.fetch(url, raise_error=False)
            segunda = await self.http_client.fetch(url, raise_error=False)

        assert primeira.code == 404 and segunda.code == 200 and len(chamadas) == 2


class PanelBrandLogoPequenoTest(PanelTestBase):
    """O logo da interface é o ``logo-256.png`` (pequeno, da lista fechada); o SVG de 6 MB deixa de ir para a tela."""

    def test_the_small_logo_is_served_as_png(self):
        resposta = self.get_page("/painel/marca/logo-256.png")

        assert resposta.code == 200 and resposta.headers["Content-Type"] == "image/png"
        assert resposta.body.startswith(b"\x89PNG\r\n\x1a\n") and len(resposta.body) < 100 * 1024

    def test_the_panel_home_references_the_small_logo_and_not_the_svg(self):
        corpo = self.get_page("/painel/").body.decode("utf-8")

        assert "/painel/marca/logo-256.png" in corpo and "logo.svg" not in corpo


class PanelBrandWritePathTest(PanelTestBase):
    """V-AS-L1 (seguimento): a resposta 200 não monta um ``bytes`` novo de cabeçalho+corpo por requisição.

    O Tornado concatena quando o corpo vai junto do cabeçalho (``finish(data)`` sem flush prévio). O contrato: ``Content-Length`` definido, cabeçalhos
    enviados sozinhos e o corpo em cache escrito depois. Observado no caminho de escrita da conexão (espiões), sem medir memória.
    """

    def _espiar(self, nome: str):
        cabecalhos: list[bytes] = []
        corpos: list[bytes] = []
        escrever_cabecalhos, escrever = HTTP1Connection.write_headers, HTTP1Connection.write

        def espia_cabecalhos(conexao, linha_inicial, headers, chunk=None):
            if isinstance(linha_inicial, httputil.ResponseStartLine):
                cabecalhos.append(bytes(chunk or b""))
            return escrever_cabecalhos(conexao, linha_inicial, headers, chunk)

        def espia_escrita(conexao, chunk):
            corpos.append(chunk)
            return escrever(conexao, chunk)

        with (
            mock.patch.object(HTTP1Connection, "write_headers", espia_cabecalhos),
            mock.patch.object(HTTP1Connection, "write", espia_escrita),
        ):
            resposta = self.get_page(f"/painel/marca/{nome}")
        return resposta, cabecalhos, corpos

    def test_the_headers_leave_alone_and_the_cached_body_is_written_afterwards(self):
        def check(nome):
            self.get_page(f"/painel/marca/{nome}")  # aquece o cache
            resposta, cabecalhos, corpos = self._espiar(nome)
            em_cache = brand._cache[nome][0]

            assert resposta.code == 200 and cabecalhos == [b""], "o corpo não pode ir junto do cabeçalho"
            assert any(c is em_cache for c in corpos), "o corpo escrito deve ser o próprio objeto em cache"

        self.assert_all(ARQUIVOS, check)

    def test_the_response_is_not_chunked_and_declares_the_exact_length(self):
        def check(nome):
            resposta, _, _ = self._espiar(nome)

            assert resposta.headers.get("Transfer-Encoding") is None
            assert resposta.headers.get("Content-Length") == str(len(resposta.body))

        self.assert_all(ARQUIVOS, check)

    def test_the_304_path_carries_no_body_at_all(self):
        etag = self.get_page("/painel/marca/logo.svg").headers["Etag"]
        resposta = self.fetch("/painel/marca/logo.svg", headers={"If-None-Match": etag}, follow_redirects=False)

        assert resposta.code == 304 and resposta.body == b""


class PanelBrandSymlinkTest(PanelTestBase):
    """Um arquivo de marca que é link simbólico é recusado (o resto da lista fechada continua servido)."""

    def get_app(self):
        self._tmp = tempfile.TemporaryDirectory()
        raiz = pathlib.Path(self._tmp.name)
        pasta = raiz / "assets" / "brand"
        pasta.mkdir(parents=True)
        alvo = raiz / "fora.svg"
        alvo.write_bytes(b"<svg xmlns='http://www.w3.org/2000/svg'/>")
        (pasta / "logo.svg").symlink_to(alvo)
        (pasta / "avatar.png").write_bytes(b"\x89PNG\r\n\x1a\nxxxx")
        (pasta / "favicon.ico").write_bytes(b"\x00\x00\x01\x00\x01\x00" + bytes(20))
        self._patch = mock.patch("empiremuse.paths.PROJECT_DIR", raiz)
        self._patch.start()
        importlib.reload(brand)
        return super().get_app()

    def tearDown(self):
        super().tearDown()
        self._patch.stop()
        importlib.reload(brand)
        self._tmp.cleanup()

    def test_a_symlinked_brand_file_is_refused(self):
        resposta = self.get_page("/painel/marca/logo.svg")

        assert resposta.code in (403, 404) and b"<svg" not in resposta.body

    def test_the_regular_brand_files_are_still_served(self):
        assert self.get_page("/painel/marca/avatar.png").code == 200
        assert self.get_page("/painel/marca/favicon.ico").code == 200
