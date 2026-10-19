"""F3-6 — painel: o 500 real mostra o código curto de erro e o mesmo código vai para o log; 4xx não têm código.

Desenho: o código nasce em ``PanelResponseMixin.log_exception`` (só para exceção que NÃO é
``tornado.web.HTTPError``) e ``write_error`` o mostra na página genérica; a mensagem da exceção nunca aparece.
"""

import re
import secrets
from unittest import mock

import tornado.web

from empiremuse.panel.handlers.pages import IndexHandler
from tests.panel.test_app import PanelTestBase

LOGGER = "empiremuse.panel.handlers.base"
CODIGO = re.compile(r"ERR-[0-9A-F]{6}")
SEGREDO = "detalhe-interno /srv/empiremuse/segredo.json"


def explode(self, *args, **kwargs):
    raise RuntimeError(SEGREDO)


def proibe(self, *args, **kwargs):
    raise tornado.web.HTTPError(403)


def fixa_codigo(valor):
    return mock.patch.object(secrets, "token_hex", lambda nbytes=None: valor)


def sem_entropia():
    def quebra(nbytes=None):
        raise RuntimeError("sem entropia (simulado)")

    return mock.patch.object(secrets, "token_hex", quebra)


class PanelErrorCodeTest(PanelTestBase):
    def test_o_500_real_mostra_o_codigo_e_o_mesmo_codigo_vai_para_o_log(self):
        with mock.patch.object(IndexHandler, "get", explode), fixa_codigo("7f3a2c"):
            with self.assertLogs(LOGGER, "ERROR") as logs:
                response = self.get_page("/painel/")
        body = response.body.decode("utf-8")
        assert response.code == 500
        assert "ERR-7F3A2C" in body and "Código do erro" in body
        assert "ERR-7F3A2C" in "\n".join(logs.output), "o log precisa levar o mesmo código"

    def test_a_pagina_nao_mostra_a_mensagem_da_excecao_nem_o_traceback(self):
        with mock.patch.object(IndexHandler, "get", explode):
            with self.assertLogs(LOGGER, "ERROR"):
                response = self.get_page("/painel/")
        body = response.body.decode("utf-8")
        for proibido in (SEGREDO, "segredo.json", "RuntimeError", "Traceback", "detalhe-interno"):
            assert proibido not in body, f"vazou na página: {proibido}"
        assert CODIGO.search(body)

    def test_o_log_continua_levando_o_traceback_completo(self):
        with mock.patch.object(IndexHandler, "get", explode):
            with self.assertLogs(LOGGER, "ERROR") as logs:
                self.get_page("/painel/")
        assert any(registro.exc_info and registro.exc_info[0] is RuntimeError for registro in logs.records)

    def test_cada_erro_recebe_o_seu_codigo(self):
        with mock.patch.object(IndexHandler, "get", explode):
            with self.assertLogs(LOGGER, "ERROR"):
                primeiro = CODIGO.search(self.get_page("/painel/").body.decode("utf-8"))
                segundo = CODIGO.search(self.get_page("/painel/").body.decode("utf-8"))
        assert primeiro and segundo

    def test_falhar_ao_gerar_o_codigo_nao_causa_novo_erro(self):
        with mock.patch.object(IndexHandler, "get", explode), sem_entropia():
            with self.assertLogs(LOGGER, "ERROR"):
                response = self.get_page("/painel/")
        body = response.body.decode("utf-8")
        assert response.code == 500 and "Erro interno" in body and "ERR-" not in body

    def test_se_a_pagina_de_erro_falhar_o_corpo_de_emergencia_tambem_leva_o_codigo(self):
        with mock.patch.object(IndexHandler, "get", explode), fixa_codigo("7f3a2c"):
            with mock.patch.object(tornado.web.RequestHandler, "render", explode):
                with self.assertLogs(LOGGER, "ERROR"):
                    response = self.get_page("/painel/")
        body = response.body.decode("utf-8")
        assert response.code == 500 and "ERR-7F3A2C" in body and SEGREDO not in body

    def test_os_cabecalhos_de_seguranca_continuam_na_pagina_de_erro(self):
        with mock.patch.object(IndexHandler, "get", explode):
            with self.assertLogs(LOGGER, "ERROR"):
                response = self.get_page("/painel/")
        assert response.headers["X-Frame-Options"] == "DENY"
        assert response.headers["Cache-Control"] == "no-store"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]

    def test_404_nao_tem_codigo(self):
        response = self.get_page("/painel/nao-existe")
        assert response.code == 404 and "ERR-" not in response.body.decode("utf-8")

    def test_403_nao_tem_codigo_nem_log_de_erro(self):
        with mock.patch.object(IndexHandler, "get", proibe):
            with self.assertNoLogs(LOGGER, "ERROR"):
                response = self.get_page("/painel/")
        assert response.code == 403 and "ERR-" not in response.body.decode("utf-8")

    def test_o_corpo_de_emergencia_escapa_o_codigo(self):
        """O código é aleatório e só tem hexadecimal; mesmo assim vai escapado para dentro do HTML."""
        with mock.patch.object(IndexHandler, "get", explode), fixa_codigo("<b>"):
            with mock.patch.object(tornado.web.RequestHandler, "render", explode):
                with self.assertLogs(LOGGER, "ERROR"):
                    response = self.get_page("/painel/")
        body = response.body.decode("utf-8")
        assert "&lt;B&gt;" in body and "<B>" not in body
