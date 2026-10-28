"""S-32 — o ``ytoauth`` nunca põe o refresh token do Google numa mensagem de canal de servidor.

O token vai só por DM ao dono que invocou; o canal recebe uma mensagem genérica sem ele. Se a DM falhar (DMs fechadas), o canal continua sem o token e
recebe um erro genérico que pede para abrir as DMs. O token também não aparece em nenhum registro de log. Tudo com fakes: view, sessão HTTP, confirmação
e DM; nada de rede nem de Discord. Os valores de token são montados em tempo de execução e não imitam um token real.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from empiremuse.cogs import ll_yt_oauth
from empiremuse.utils.music.errors import GenericError

pytestmark = pytest.mark.critical

REFRESH = "".join(["refresh-", "dm-teste-", "Zk4p7"])
ACCESS = "".join(["access-", "dm-teste-", "Wq9m2"])
EMAIL = "conta.descartavel@exemplo.invalido"


class ViewFalsa:
    def __init__(self, **kwargs):
        self.interaction = None
        self.exception_txt = None
        self.data = {"refresh_token": REFRESH, "access_token": ACCESS}

    async def wait(self):
        return None


class ConfirmacaoFalsa:
    """``AskView`` já respondida com "sim"."""

    def __init__(self, **kwargs):
        self.selected = True
        self.interaction_resp = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock(), edit_message=AsyncMock()),
            edit_original_message=AsyncMock(),
            followup=SimpleNamespace(send=AsyncMock()),
            send=AsyncMock(),
        )

    async def wait(self):
        return None


class RespostaHttp:
    status = 200

    async def json(self):
        return {"name": "Conta Descartavel", "email": EMAIL, "picture": "https://ok.exemplo/foto.png"}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class SessaoFalsa:
    def get(self, *args, **kwargs):
        return RespostaHttp()


def mostrar(chamada) -> str:
    """Texto de uma chamada, com o conteúdo dos embeds (o ``repr`` de um ``Embed`` não mostra a descrição)."""
    partes = []
    for valor in [*chamada.args, *chamada.kwargs.values()]:
        embeds = valor if isinstance(valor, (list, tuple)) else [valor]
        partes += [str(e.to_dict()) if isinstance(e, disnake.Embed) else str(e) for e in embeds]
    return " ".join(partes)


class Cenario:
    def __init__(self, monkeypatch, tmp_path, *, dm_fecha: bool = False):
        monkeypatch.setattr(ll_yt_oauth, "YtOauthView", ViewFalsa)
        monkeypatch.setattr(ll_yt_oauth, "AskView", ConfirmacaoFalsa)
        monkeypatch.setattr(ll_yt_oauth.paths, "RUNTIME_DIR", tmp_path)
        self.cog = ll_yt_oauth.YtOauthLL.__new__(ll_yt_oauth.YtOauthLL)
        self.cog.bot = SimpleNamespace(
            get_color=lambda *a: 0,
            session=SessaoFalsa(),
            pool=SimpleNamespace(mongo_database=None),
            music=SimpleNamespace(nodes={}),
        )
        self.mensagem = SimpleNamespace(edit=AsyncMock())
        if dm_fecha:
            self.dm = AsyncMock(
                side_effect=disnake.Forbidden(
                    SimpleNamespace(status=403, reason="x"), "Cannot send messages to this user"
                )
            )
        else:
            self.dm = AsyncMock()
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(me=None),
            author=SimpleNamespace(id=1, send=self.dm, mention="<@1>"),
            send=AsyncMock(return_value=self.mensagem),
            channel=SimpleNamespace(send=AsyncMock()),
        )
        self.erro: BaseException | None = None

    def rodar(self) -> None:
        try:
            asyncio.run(self.cog.oauth_command(self.ctx))
        except GenericError as erro:
            self.erro = erro

    def canal(self) -> str:
        """Tudo o que o canal pode ter recebido: envios, edições da mensagem e das interações, e o texto de um erro genérico."""
        chamadas = [self.ctx.send, self.mensagem.edit, self.ctx.channel.send]
        confirmacao = getattr(self.ctx, "inter", None)
        if confirmacao is not None:
            chamadas += [
                confirmacao.edit_original_message,
                confirmacao.response.edit_message,
                confirmacao.followup.send,
                confirmacao.send,
            ]
        partes = [mostrar(c) for chamada in chamadas for c in chamada.call_args_list]
        partes += [str(self.erro)] if self.erro else []
        partes += [repr(getattr(self.erro, "args", ""))] if self.erro else []
        return "\n".join(partes)

    def dm_texto(self) -> str:
        return "\n".join(mostrar(c) for c in self.dm.call_args_list)


@pytest.fixture
def cenario(monkeypatch, tmp_path) -> Cenario:
    return Cenario(monkeypatch, tmp_path)


@pytest.fixture
def cenario_dm_fechada(monkeypatch, tmp_path) -> Cenario:
    return Cenario(monkeypatch, tmp_path, dm_fecha=True)


class TestTokenSoPorDm:
    def test_the_token_goes_to_the_invoking_owner_by_dm(self, cenario):
        cenario.rodar()

        cenario.dm.assert_awaited_once()
        assert REFRESH in cenario.dm_texto()

    def test_no_channel_message_has_the_token(self, cenario):
        cenario.rodar()

        assert REFRESH not in cenario.canal()
        assert ACCESS not in cenario.canal()

    def test_the_channel_still_gets_a_confirmation_that_does_not_depend_on_the_token(self, cenario):
        cenario.rodar()

        canal = cenario.canal()
        assert "sucesso" in canal.lower() and ("DM" in canal or "mensagem direta" in canal.lower())

    def test_the_dm_goes_to_the_author_and_nobody_else(self, cenario):
        cenario.rodar()

        assert cenario.dm.await_count == 1 and cenario.ctx.channel.send.await_count == 0


class TestDmFechada:
    def test_a_closed_dm_never_sends_the_token_to_the_channel(self, cenario_dm_fechada):
        cenario_dm_fechada.rodar()

        assert REFRESH not in cenario_dm_fechada.canal()

    def test_a_closed_dm_tells_the_owner_to_open_the_dms_in_a_generic_message(self, cenario_dm_fechada):
        cenario_dm_fechada.rodar()

        canal = cenario_dm_fechada.canal()
        assert "DM" in canal and "Cannot send messages" not in canal

    def test_a_closed_dm_does_not_try_a_second_delivery_path(self, cenario_dm_fechada):
        cenario_dm_fechada.rodar()

        assert cenario_dm_fechada.dm.await_count == 1 and cenario_dm_fechada.ctx.channel.send.await_count == 0

    def test_an_unexpected_dm_error_also_keeps_the_token_out_of_the_channel(self, monkeypatch, tmp_path):
        c = Cenario(monkeypatch, tmp_path)
        c.dm.side_effect = RuntimeError("falha qualquer na entrega")

        try:
            c.rodar()
        except RuntimeError as erro:
            c.erro = erro

        assert REFRESH not in c.canal()


class TestTokenForaDosLogs:
    def test_the_token_never_appears_in_a_log_record(self, cenario, caplog):
        with caplog.at_level(logging.DEBUG):
            cenario.rodar()

        textos = [r.getMessage() + (r.exc_text or "") for r in caplog.records]
        assert all(REFRESH not in t and ACCESS not in t for t in textos)

    def test_the_token_never_appears_in_a_log_record_when_the_dm_fails(self, cenario_dm_fechada, caplog):
        with caplog.at_level(logging.DEBUG):
            cenario_dm_fechada.rodar()

        textos = [r.getMessage() + (r.exc_text or "") for r in caplog.records]
        assert all(REFRESH not in t and ACCESS not in t for t in textos)


class TestComandoNaoMudou:
    def test_a_cancelled_confirmation_sends_no_dm_and_no_token(self, monkeypatch, tmp_path):
        c = Cenario(monkeypatch, tmp_path)

        class Recusa(ConfirmacaoFalsa):
            def __init__(self, **kwargs):
                super().__init__(**kwargs)
                self.selected = False

        monkeypatch.setattr(ll_yt_oauth, "AskView", Recusa)
        c.rodar()

        assert c.dm.await_count == 0 and REFRESH not in c.canal()

    def test_an_expired_flow_still_raises_the_usual_error(self, monkeypatch, tmp_path):
        c = Cenario(monkeypatch, tmp_path)
        monkeypatch.setattr(
            ViewFalsa,
            "__init__",
            lambda self, **k: (
                setattr(self, "interaction", None),
                setattr(self, "exception_txt", None),
                setattr(self, "data", {}),
            )[0],
        )

        c.rodar()

        assert isinstance(c.erro, GenericError) and c.dm.await_count == 0
