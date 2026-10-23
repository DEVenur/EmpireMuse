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
from empiremuse.utils.music.converters import fix_characters
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
    async def test_consulta_ao_spotify(self, caplog):
        caplog.set_level(logging.DEBUG)
        bot = ModalBot()
        bot.spotify = SimpleNamespace(get_user_info=explode()[0])
        inter = await adicionar_integracao(bot, url=URL_SPOTIFY)
        confere(inter, caplog)
        assert bot.salvos_usuario == []

    @pytest.mark.asyncio
    async def test_consulta_ao_deezer(self, caplog):
        caplog.set_level(logging.DEBUG)
        bot = ModalBot()
        bot.deezer = SimpleNamespace(get_user_info=explode()[0])
        inter = await adicionar_integracao(bot, url="https://www.deezer.com/br/profile/123456")
        confere(inter, caplog)
        assert bot.salvos_usuario == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url", ["https://www.youtube.com/@canal", "https://soundcloud.com/artista"], ids=["youtube", "soundcloud"]
    )
    async def test_leitura_da_url_pelo_ytdl(self, url, caplog):
        caplog.set_level(logging.DEBUG)
        bot = ModalBot()
        bot.pool = SimpleNamespace(ytdl=SimpleNamespace(extract_info=explode()[1]))
        inter = await adicionar_integracao(bot, url=url)
        confere(inter, caplog)
        assert bot.salvos_usuario == []

    @pytest.mark.asyncio
    async def test_atualizacao_da_mensagem_do_editor_de_skin(self, caplog):
        caplog.set_level(logging.DEBUG)
        inter = InteracaoFalsa()
        inter.response.edit_message = explode()[0]
        auto = SimpleNamespace(ctx=None, build_embeds=lambda: {})
        await SkinEditorMenu.update_message(auto, inter)
        confere(inter, caplog)

    @pytest.mark.asyncio
    async def test_cada_erro_leva_o_seu_codigo(self, monkeypatch, caplog):
        """Dois erros seguidos: o código de cada mensagem é o do seu próprio log."""
        caplog.set_level(logging.DEBUG)
        valores = iter(["aaaaaa", "bbbbbb"])
        monkeypatch.setattr(secrets, "token_hex", lambda nbytes=None: next(valores))
        textos = []
        for _ in range(2):
            bot = ModalBot()
            bot.spotify = SimpleNamespace(get_user_info=explode()[0])
            textos.append((await adicionar_integracao(bot, url=URL_SPOTIFY)).texto)
        assert "ERR-AAAAAA" in textos[0] and "ERR-BBBBBB" in textos[1]
        assert "ERR-AAAAAA" not in textos[1] and "ERR-BBBBBB" not in textos[0]


class TestErrosEsperadosSemCodigo:
    """GUARDA: JSON inválido e entrada ruim são erro esperado: sem código e sem registro de erro inesperado."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "modo",
        [ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager],
        ids=["fav", "srv", "itg"],
    )
    async def test_json_invalido_do_importador(self, modo):
        inter = await importar(ModalBot(), modo, "{isto não é json 12345678901234567890")
        assert "ERR-" not in inter.texto and "Código do erro" not in inter.texto

    @pytest.mark.asyncio
    async def test_json_invalido_da_skin_importada(self):
        inter = InteracaoFalsa()
        inter.custom_id = "skin_editor_import_skin"
        inter.text_values = {"skin": "{isto não é json"}
        await SkinEditorMenu.modal_handler(SimpleNamespace(ctx=None, message_data={}), inter)
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


class TestPerfilDoSpotifyIncompleto:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("imagens", [[], None, _AUSENTE], ids=["vazio", "none", "ausente"])
    async def test_sem_imagem_vira_integracao_sem_avatar(self, imagens):
        dados, inter = await consulta_spotify(perfil(images=imagens))
        assert dados is not None, inter.texto
        assert dados["title"] == "[SP]: Ana"
        assert not dados.get("avatar")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", [None, "", _AUSENTE], ids=["none", "vazio", "ausente"])
    async def test_sem_nome_usa_o_nome_padrao(self, nome):
        dados, inter = await consulta_spotify(perfil(display_name=nome))
        assert dados is not None, inter.texto
        assert dados["title"] == "[SP]: abc123", "nome padrão = o id do usuário do link"

    @pytest.mark.asyncio
    async def test_sem_nome_e_sem_imagem(self):
        dados, inter = await consulta_spotify(perfil(display_name=_AUSENTE, images=[]))
        assert dados is not None and dados["title"] == "[SP]: abc123" and not dados.get("avatar")

    @pytest.mark.asyncio
    async def test_imagem_sem_url_nao_quebra(self):
        dados, inter = await consulta_spotify(perfil(images=[{}]))
        assert dados is not None and not dados.get("avatar")

    @pytest.mark.asyncio
    async def test_fim_a_fim_a_integracao_e_salva_sem_avatar(self):
        bot = ModalBot()
        bot.spotify = SimpleNamespace(get_user_info=_devolve(perfil(images=[], display_name=_AUSENTE)))
        inter = await adicionar_integracao(bot, url=URL_SPOTIFY)
        assert len(bot.salvos_usuario) == 1, inter.texto
        [(nome, dados)] = bot.salvos_usuario[0]["integration_links"].items()
        assert nome == fix_characters("[SP]: abc123", 80), "o título é salvo com os colchetes trocados, como sempre"
        assert dados["url"] == URL_PERFIL and not dados.get("avatar")

    @pytest.mark.asyncio
    async def test_guarda_perfil_completo_continua_igual(self):
        dados, _ = await consulta_spotify(perfil())
        assert dados == {
            "title": "[SP]: Ana",
            "url": "https://open.spotify.com/user/abc123",
            "avatar": "https://exemplo.invalid/grande.png",
        }

    @pytest.mark.asyncio
    async def test_guarda_nome_longo_continua_cortado_em_90(self):
        dados, _ = await consulta_spotify(perfil(display_name="n" * 200))
        assert dados["title"] == "[SP]: " + "n" * 90


class TestPerfilDoSpotifyOutrasLacunas:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("links", [None, {}, {"spotify": ""}, {"spotify": None}, _AUSENTE], ids=repr)
    async def test_sem_link_do_perfil_usa_o_link_informado(self, links):
        dados, inter = await consulta_spotify(perfil(external_urls=links))
        assert dados is not None, inter.texto
        assert dados["url"] == URL_PERFIL

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("nome", "esperado"), [("   ", "abc123"), ("  Ana  ", "Ana"), (123, "123")], ids=repr)
    async def test_nome_so_de_espacos_cai_no_id_e_as_pontas_sao_aparadas(self, nome, esperado):
        dados, _ = await consulta_spotify(perfil(display_name=nome))
        assert dados["title"] == f"[SP]: {esperado}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("imagens", [["https://exemplo.invalid/a.png"], [None], [{"url": ""}]], ids=repr)
    async def test_imagem_que_nao_e_um_objeto_com_url_nao_vira_avatar(self, imagens):
        dados, inter = await consulta_spotify(perfil(images=imagens))
        assert dados is not None, inter.texto
        assert not dados.get("avatar")


URL_DEEZER = "https://www.deezer.com/br/profile/123456"


async def consulta_deezer(resultado):
    """Roda o ``_lookup_deezer`` REAL com a resposta devolvida pelo cliente falso; devolve ``(dict | None, interação)``."""
    bot = ModalBot()
    bot.deezer = SimpleNamespace(get_user_info=_devolve(resultado))
    auto = SimpleNamespace(view=modal_view(bot, ViewMode.integrations_manager), _profile_error=None)
    auto._profile_error = lambda inter, code="": FavModalAdd._profile_error(auto, inter, code)
    inter = ModalInteraction()
    return await FavModalAdd._lookup_deezer(auto, inter, URL_DEEZER), inter


class TestRespostaMalformadaDoPerfil:
    """N-9: resposta fora do formato esperado vira mensagem genérica com código, nunca exceção nem ``repr(e)``."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "resposta",
        [
            {"error": {"type": "DataException"}},
            {"name": "Ana"},
            {"name": "Ana", "link": "https://x.invalid"},
            [],
            "texto",
        ],
        ids=["erro-da-api", "sem-link", "sem-picture", "lista", "texto"],
    )
    async def test_deezer_com_resposta_incompleta(self, resposta):
        dados, inter = await consulta_deezer(resposta)

        assert dados is None
        assert "Ocorreu um erro ao obter as informações do perfil" in inter.texto
        sem_vazamento(inter.texto)
        assert "KeyError" not in inter.texto and "TypeError" not in inter.texto

    @pytest.mark.asyncio
    async def test_deezer_completo_continua_funcionando(self):
        resposta = {"name": "Ana", "link": "https://www.deezer.com/profile/1", "picture": "https://x.invalid/a.png"}

        dados, _ = await consulta_deezer(resposta)

        assert dados == {"title": "[DZ]: Ana", "url": resposta["link"], "avatar": resposta["picture"]}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("resposta", [["lista"], "texto", 42], ids=["lista", "texto", "numero"])
    async def test_spotify_com_resposta_que_nao_e_um_dict(self, resposta):
        bot = ModalBot()
        bot.spotify = SimpleNamespace(get_user_info=_devolve(resposta))
        auto = SimpleNamespace(view=modal_view(bot, ViewMode.integrations_manager))
        auto._profile_error = lambda inter, code="": FavModalAdd._profile_error(auto, inter, code)
        inter = ModalInteraction()

        dados = await FavModalAdd._lookup_spotify(auto, inter, URL_PERFIL)

        assert dados is None
        assert "Ocorreu um erro ao obter as informações do perfil" in inter.texto
        sem_vazamento(inter.texto)
