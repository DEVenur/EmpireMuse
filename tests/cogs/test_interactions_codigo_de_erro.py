"""F3-6 (pós-merge) — código ``ERR-…`` nos erros inesperados de ``interactions.py`` e o N-4 do ``_lookup_spotify``.

A F3-5b (KI-48) trocou o ``repr(e)`` dessas mensagens por texto genérico e ``logger.exception``; o código curto de erro
nasceu na F3-6. Depois do merge, os 4 pontos de erro **inesperado** passam a usar o padrão do S-14 (``log_unexpected_error``
mais ``error_code_text``): consulta ao Spotify, ao Deezer e ao yt-dlp, e a atualização da mensagem do editor de skin. O
mesmo código vai na mensagem e no log. Os erros **esperados** (JSON inválido do importador e da skin) não ganham código.

N-4: um perfil do Spotify sem imagem (``images`` vazio ou ausente) ou sem ``display_name`` não pode dar ``IndexError`` nem
``KeyError``: vira integração sem avatar e com um nome padrão (o ``user_id`` do link).
"""

import secrets
from types import SimpleNamespace

import pytest

from empiremuse.utils.music.interactions import FavModalAdd, ViewMode
from tests.support.modais import ModalBot, ModalInteraction, importar, modal_view, trocar_process_idle_embed

URL_PERFIL = "https://open.spotify.com/user/abc123"


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)
    monkeypatch.setattr(secrets, "token_hex", lambda nbytes=None: "7f3a2c")


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
