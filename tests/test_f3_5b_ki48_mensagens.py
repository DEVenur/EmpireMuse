"""F3-5b, etapa 4 — KI-48: as mensagens de ``interactions.py`` não mostram ``repr(e)`` ao usuário.

Hoje o parse do JSON dos importadores, a consulta ao Spotify/Deezer, a leitura da URL pelo yt-dlp, a edição da mensagem
do editor de skin e a importação de skin devolvem ``repr(e)`` (nome da exceção e texto interno) em um bloco de código.
Esperado: mensagem genérica em português, sem o detalhe da exceção, e o detalhe (com traceback) vai para o log.
Os valores que identificam a exceção são montados em tempo de execução.
"""

import logging
import secrets
from types import SimpleNamespace

import pytest

from empiremuse.utils.music.interactions import SkinEditorMenu, ViewMode
from tests.helpers_f3_5b import InteracaoFalsa
from tests.helpers_modais import ModalBot, ModalInteraction, adicionar_integracao, importar

MARCADORES_DE_DETALHE_INTERNO = ("```py", "Traceback", "Error(", "Exception", "repr(")


def novo_segredo():
    return f"detalhe-interno-{secrets.token_hex(6)}"


def assert_generica(texto, segredo=None):
    assert texto.strip(), "o usuário precisa receber uma mensagem"
    assert segredo is None or segredo not in texto, "o detalhe da exceção vazou para o usuário"
    for marcador in MARCADORES_DE_DETALHE_INTERNO:
        assert marcador not in texto, f"{marcador!r} apareceu na mensagem ao usuário: {texto!r}"
    assert "erro" in texto.lower() or "inválid" in texto.lower()


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    from empiremuse.utils.music import interactions

    async def nada(*args, **kwargs):
        return None

    monkeypatch.setattr(interactions, "process_idle_embed", nada)


def explode(segredo, tipo=RuntimeError):
    async def _async(*args, **kwargs):
        raise tipo(segredo)

    def _sync(*args, **kwargs):
        raise tipo(segredo)

    return _async, _sync


class TestJsonInvalidoNosImportadores:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "modo",
        [ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager],
        ids=["fav", "srv", "itg"],
    )
    async def test_mensagem_generica_e_detalhe_no_log(self, modo, caplog):
        caplog.set_level(logging.DEBUG)
        bot = ModalBot()
        inter = await importar(bot, modo, "{isto não é json 12345678901234567890")
        assert_generica(inter.texto)
        assert "JSONDecodeError" not in inter.texto and "Expecting" not in inter.texto
        assert "json" in inter.texto.lower()
        assert "Expecting" in caplog.text, "o detalhe do parse deve ir para o log"
        assert bot.salvos_usuario == [] and bot.salvos_servidor == []


class TestConsultaDeIntegracoes:
    @pytest.mark.asyncio
    async def test_spotify_com_erro(self, caplog):
        caplog.set_level(logging.DEBUG)
        segredo = novo_segredo()
        bot = ModalBot()
        bot.spotify = SimpleNamespace(get_user_info=explode(segredo)[0])
        inter = await adicionar_integracao(bot, url="https://open.spotify.com/user/abc123")
        assert_generica(inter.texto, segredo)
        assert bot.salvos_usuario == []
        assert segredo in caplog.text, "o detalhe da exceção deve ir para o log"

    @pytest.mark.asyncio
    async def test_deezer_com_erro(self, caplog):
        caplog.set_level(logging.DEBUG)
        segredo = novo_segredo()
        bot = ModalBot()
        bot.deezer = SimpleNamespace(get_user_info=explode(segredo)[0])
        inter = await adicionar_integracao(bot, url="https://www.deezer.com/br/profile/123456")
        assert_generica(inter.texto, segredo)
        assert bot.salvos_usuario == []
        assert segredo in caplog.text

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url", ["https://www.youtube.com/@canal", "https://soundcloud.com/artista"], ids=["youtube", "soundcloud"]
    )
    async def test_leitura_da_url_pelo_ytdl_com_erro(self, url, caplog):
        caplog.set_level(logging.DEBUG)
        segredo = novo_segredo()
        bot = ModalBot()
        bot.pool = SimpleNamespace(ytdl=SimpleNamespace(extract_info=explode(segredo)[1]))
        inter = await adicionar_integracao(bot, url=url)
        assert_generica(inter.texto, segredo)
        assert bot.salvos_usuario == []
        assert segredo in caplog.text


class TestEditorDeSkin:
    @pytest.mark.asyncio
    async def test_erro_ao_atualizar_a_mensagem(self, caplog):
        caplog.set_level(logging.DEBUG)
        segredo = novo_segredo()
        inter = InteracaoFalsa()
        inter.response.edit_message = explode(segredo)[0]
        auto = SimpleNamespace(ctx=None, build_embeds=lambda: {})
        await SkinEditorMenu.update_message(auto, inter)
        assert_generica(inter.texto, segredo)
        assert segredo in caplog.text

    @pytest.mark.asyncio
    async def test_skin_importada_com_json_invalido(self, caplog):
        caplog.set_level(logging.DEBUG)
        inter = InteracaoFalsa()
        inter.custom_id = "skin_editor_import_skin"
        inter.text_values = {"skin": "{isto não é json"}
        auto = SimpleNamespace(ctx=None, message_data={})
        await SkinEditorMenu.modal_handler(auto, inter)
        assert_generica(inter.texto)
        assert "JSONDecodeError" not in inter.texto and "Expecting" not in inter.texto
        assert "skin" in inter.texto.lower()
        assert "Expecting" in caplog.text


def test_sanidade_do_dublê_de_interacao_modal():
    """O dublê de modal usado acima devolve o texto enviado (senão os testes passariam por texto vazio)."""
    assert ModalInteraction().texto == ""
