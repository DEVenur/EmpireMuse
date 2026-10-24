"""F3-6 (pós-merge) — código ``ERR-…`` nos erros inesperados de ``interactions.py`` e o N-4 do ``_lookup_spotify``.

A F3-5b (KI-48) trocou o ``repr(e)`` dessas mensagens por texto genérico e ``logger.exception``; o código curto de erro
nasceu na F3-6. Depois do merge, os 4 pontos de erro **inesperado** passam a usar o padrão do S-14 (``log_unexpected_error``
mais ``error_code_text``): consulta ao Spotify, ao Deezer e ao yt-dlp, e a atualização da mensagem do editor de skin. O
mesmo código vai na mensagem e no log. Os erros **esperados** (JSON inválido do importador e da skin) não ganham código.

N-4: um perfil do Spotify sem imagem (``images`` vazio ou ausente) ou sem ``display_name`` não pode dar ``IndexError`` nem
``KeyError``: vira integração sem avatar e com um nome padrão (o ``user_id`` do link).
"""

import logging
import secrets
from types import SimpleNamespace

import pytest

from empiremuse.utils.music import interactions
from empiremuse.utils.music.interactions import FavModalAdd, SkinEditorMenu, ViewMode
from tests.support.drivers_de_regras import InteracaoFalsa
from tests.support.modais import (
    ModalBot,
    ModalInteraction,
    adicionar_integracao,
    importar,
    modal_view,
    trocar_process_idle_embed,
)

CODIGO = "ERR-7F3A2C"
SEGREDO = "detalhe-interno /srv/empiremuse/segredo.json"
URL_SPOTIFY = "https://open.spotify.com/user/abc123"
URL_PERFIL = "https://open.spotify.com/user/abc123"


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)
    monkeypatch.setattr(secrets, "token_hex", lambda nbytes=None: "7f3a2c")


def explode(tipo=RuntimeError):
    async def _async(*args, **kwargs):
        raise tipo(SEGREDO)

    def _sync(*args, **kwargs):
        raise tipo(SEGREDO)

    return _async, _sync


def sem_vazamento(texto):
    for proibido in (SEGREDO, "segredo.json", "RuntimeError", "Traceback", "```py", "repr("):
        assert proibido not in texto, f"vazou para a tela: {proibido!r} em {texto!r}"


def registros_de_erro(caplog):
    return [r for r in caplog.records if r.name == interactions.__name__ and r.levelno >= logging.ERROR]


def confere(inter, caplog):
    texto = inter.texto
    sem_vazamento(texto)
    assert CODIGO in texto, f"a mensagem precisa levar o código: {texto!r}"
    [registro] = registros_de_erro(caplog)
    assert CODIGO in registro.getMessage(), "o log precisa levar o mesmo código"
    assert registro.exc_info and registro.exc_info[0] is RuntimeError, "o log mantém o traceback"
    assert SEGREDO in caplog.text, "o detalhe da exceção vai para o log"


class TestCodigoNosErrosInesperados:
    @pytest.mark.asyncio
    async def test_atualizacao_da_mensagem_do_editor_de_skin(self, caplog):
        caplog.set_level(logging.DEBUG)
        inter = InteracaoFalsa()
        inter.response.edit_message = explode()[0]
        auto = SimpleNamespace(ctx=None, build_embeds=lambda: {})
        await SkinEditorMenu.update_message(auto, inter)
        confere(inter, caplog)


class TestErrosEsperadosSemCodigo:
    """GUARDA: JSON inválido e entrada ruim são erro esperado: sem código e sem registro de erro inesperado."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "modo",
        [ViewMode.fav_manager, ViewMode.integrations_manager],
        ids=["fav", "itg"],
    )
    async def test_json_invalido_do_importador(self, modo):
        inter = await importar(ModalBot(), modo, "{isto não é json 12345678901234567890")
        assert "ERR-" not in inter.texto and "Código do erro" not in inter.texto

    @pytest.mark.asyncio
    async def test_perfil_do_spotify_sem_playlists_publicas(self):
        bot = ModalBot()
        bot.spotify = SimpleNamespace(get_user_info=_devolve(None))
        inter = await adicionar_integracao(bot, url=URL_SPOTIFY)
        assert "ERR-" not in inter.texto and "playlists públicas" in inter.texto


def _devolve(valor):
    async def _consulta(*args, **kwargs):
        return valor

    return _consulta


def perfil(**extra):
    base = {
        "display_name": "Ana",
        "external_urls": {"spotify": "https://open.spotify.com/user/abc123"},
        "images": [{"url": "https://exemplo.invalid/pequena.png"}, {"url": "https://exemplo.invalid/grande.png"}],
    }
    base.update(extra)
    return {k: v for k, v in base.items() if v is not _AUSENTE}


_AUSENTE = object()


async def consulta_spotify(resultado):
    """Roda o ``_lookup_spotify`` REAL com o perfil devolvido pelo cliente falso; devolve ``(dict | None, interação)``."""
    bot = ModalBot()
    bot.spotify = SimpleNamespace(get_user_info=_devolve(resultado))
    auto = SimpleNamespace(view=modal_view(bot, ViewMode.integrations_manager))
    inter = ModalInteraction()
    return await FavModalAdd._lookup_spotify(auto, inter, URL_PERFIL), inter


class TestPerfilDoSpotifyOutrasLacunas:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("links", [None, _AUSENTE], ids=repr)
    async def test_sem_link_do_perfil_usa_o_link_informado(self, links):
        dados, inter = await consulta_spotify(perfil(external_urls=links))
        assert dados is not None, inter.texto
        assert dados["url"] == URL_PERFIL
