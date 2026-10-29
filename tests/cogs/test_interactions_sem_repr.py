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

from tests.support.modais import ModalBot, adicionar_integracao, trocar_process_idle_embed

pytestmark = pytest.mark.regression

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

    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


def explode(segredo, tipo=RuntimeError):
    async def _async(*args, **kwargs):
        raise tipo(segredo)

    def _sync(*args, **kwargs):
        raise tipo(segredo)

    return _async, _sync


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
