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

    def test_conditional_get_returns_304_without_body_and_a_stale_etag_gets_the_whole_file(self):
        def check(nome):
            primeiro = self.get_page(f"/painel/marca/{nome}")
            etag = primeiro.headers.get("Etag")
            assert etag and etag == self.get_page(f"/painel/marca/{nome}").headers["Etag"]
            assert primeiro.headers.get("Cache-Control") == "public, max-age=86400"
            igual = self.fetch(f"/painel/marca/{nome}", headers={"If-None-Match": etag}, follow_redirects=False)
            assert igual.code == 304 and igual.body == b"" and igual.headers.get("Etag") == etag
            assert max_age(igual.headers.get("Cache-Control", "")) is not None
            outro = self.fetch(f"/painel/marca/{nome}", headers={"If-None-Match": '"outro"'}, follow_redirects=False)
            assert outro.code == 200 and outro.body == primeiro.body and len(outro.body) > 0

        self.assert_all(ARQUIVOS, check)


class PanelBrandColdBurstTest(PanelTestBase):
    """Rajada de primeiras requisições do mesmo arquivo: uma só leitura e um só hash (o logo.svg tem 6 MB e a rota é pública)."""

    RAJADA = 8
    TEMPO_MAXIMO_DA_ESPERA = 10  # segundos; limite de segurança, não é espera: o evento libera antes
    ESPERA_DA_LEITURA = 20  # a leitura presa desiste DEPOIS do limite acima (e antes do timeout do gen_test)
    TIMEOUT_DO_TESTE = 30  # maior que as duas esperas; o padrão do gen_test (5 s) cortaria o teste no meio

    def _contador(self, falhar_primeiro: bool = False):
        real, chamadas, solta = brand._load, [], threading.Event()

        def contado(nome):
            chamadas.append(nome)
            if len(chamadas) == 1 and falhar_primeiro:
                raise FileNotFoundError(nome)
            # segura a leitura até a rajada chegar; sem isso a primeira acabaria antes das outras. Sem o sinal, falha em vez de ler.
            if not solta.wait(timeout=self.ESPERA_DA_LEITURA):
                raise TimeoutError("a rajada não chegou ao handler a tempo")
            return real(nome)

        return chamadas, solta, contado

    def _chegadas(self):
        """Espia ``brand._entry``: ``todas`` dispara quando a rajada inteira já chegou ao handler (e passou pela checagem do cache)."""
        real, chegaram, todas = brand._entry, [], asyncio.Event()

        async def espiao(nome):
            chegaram.append(nome)
            if len(chegaram) == self.RAJADA:
                todas.set()
            return await real(nome)

        return todas, espiao

    @tornado.testing.gen_test(timeout=TIMEOUT_DO_TESTE)
    async def test_concurrent_first_requests_for_one_file_load_it_exactly_once(self):
        chamadas, solta, contado = self._contador()
        todas, espiao = self._chegadas()
        with (
            mock.patch.dict(brand._cache, clear=True),
            mock.patch.object(brand, "_load", contado),
            mock.patch.object(brand, "_entry", espiao),
        ):
            url = self.get_url("/painel/marca/logo.svg")
            tarefas = [
                asyncio.ensure_future(self.http_client.fetch(url, raise_error=False)) for _ in range(self.RAJADA)
            ]
            try:
                await asyncio.wait_for(todas.wait(), self.TEMPO_MAXIMO_DA_ESPERA)
            except BaseException:
                for tarefa in tarefas:
                    tarefa.cancel()
                raise
            finally:
                solta.set()  # nunca deixa a leitura presa, passe ou falhe o teste
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
