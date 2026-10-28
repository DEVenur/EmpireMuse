"""S-32 — o ``ytoauth`` nunca põe o refresh token (nem os dados da conta) numa mensagem de canal de servidor.

Opção A do contrato: a confirmação da conta (e-mail, nome, avatar e os botões Sim/Não) e o token vão só por DM ao dono que invocou, as duas DMs
com ``delete_after=600`` e o prazo dito em uma linha; o canal só manda olhar a DM. Se a DM de confirmação falhar (``Forbidden``), o fluxo aborta
antes de tocar no ``application.yml``, no nó LOCAL e no MongoDB. O token entra no redator ANTES de qualquer envio feito depois de obtido e não
aparece em registro de log. Tudo com fakes; os valores de token são montados em tempo de execução e não imitam um token real.
"""

import asyncio
import logging
from types import SimpleNamespace
from unittest.mock import AsyncMock

import disnake
import pytest

from empiremuse.cogs import ll_yt_oauth
from empiremuse.utils.music.errors import GenericError

pytestmark = pytest.mark.critical

REFRESH = "".join(["refresh-", "dm-teste-", "Zk4p7"])
ACCESS = "".join(["access-", "dm-teste-", "Wq9m2"])
EMAIL = "conta.descartavel@exemplo.invalido"
NOME_DA_CONTA = "Conta Descartavel"
AVATAR = "https://ok.exemplo/foto.png"
PRAZO_DA_DM = 600
DADOS_DA_CONTA = (EMAIL, NOME_DA_CONTA, AVATAR)
YML_ORIGINAL = "plugins:\n  youtube:\n    oauth:\n      enabled: false\n"


class ViewFalsa:
    def __init__(self, **kwargs):
        self.interaction = None
        self.exception_txt = None
        self.data = {"refresh_token": REFRESH, "access_token": ACCESS}

    async def wait(self):
        return None


def registrar(eventos: list[str], nome: str, retorno=None, falha_em: set[int] | None = None, erro=None) -> AsyncMock:
    """``AsyncMock`` que anota ``nome`` (a ORDEM dos envios); levanta ``erro`` nas chamadas de número ``falha_em`` (1-based)."""
    contador = {"n": 0}

    async def corpo(*args, **kwargs):
        contador["n"] += 1
        eventos.append(nome)
        if erro is not None and (falha_em is None or contador["n"] in falha_em):
            raise erro
        return retorno

    return AsyncMock(side_effect=corpo)


class ConfirmacaoFalsa:
    """``AskView`` já respondida com "sim" (o clique acontece na DM)."""

    eventos: list[str] = []
    selected = True

    def __init__(self, **kwargs):
        self.selected = type(self).selected
        self.interaction_resp = SimpleNamespace(
            response=SimpleNamespace(defer=AsyncMock(), edit_message=registrar(self.eventos, "dm:interacao")),
            edit_original_message=registrar(self.eventos, "dm:interacao"),
            followup=SimpleNamespace(send=registrar(self.eventos, "dm:interacao")),
            send=registrar(self.eventos, "dm:interacao"),
        )

    async def wait(self):
        return None


class RespostaHttp:
    status = 200

    async def json(self):
        return {"name": NOME_DA_CONTA, "email": EMAIL, "picture": AVATAR}

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False


class SessaoFalsa:
    def __init__(self):
        self.post = AsyncMock()

    def get(self, *args, **kwargs):
        return RespostaHttp()


def mostrar(chamada) -> str:
    """Texto de uma chamada, com o conteúdo dos embeds (o ``repr`` de um ``Embed`` não mostra a descrição)."""
    partes = []
    for valor in [*chamada.args, *chamada.kwargs.values()]:
        embeds = valor if isinstance(valor, (list, tuple)) else [valor]
        partes += [str(e.to_dict()) if isinstance(e, disnake.Embed) else str(e) for e in embeds]
    return " ".join(partes)


def descricao_crua(chamada) -> str:
    """Descrição dos embeds e ``content`` da chamada, com as quebras de linha."""
    partes = []
    for valor in [*chamada.args, *chamada.kwargs.values()]:
        if isinstance(valor, disnake.Embed):
            partes.append(valor.description or "")
        elif isinstance(valor, str):
            partes.append(valor)
    return "\n".join(partes)


class Cenario:
    def __init__(self, monkeypatch, tmp_path, *, dm_falha_em: set[int] | None = None, com_efeitos: bool = False):
        self.eventos: list[str] = []
        ConfirmacaoFalsa.eventos = self.eventos
        ConfirmacaoFalsa.selected = True
        monkeypatch.setattr(ll_yt_oauth, "YtOauthView", ViewFalsa)
        monkeypatch.setattr(ll_yt_oauth, "AskView", ConfirmacaoFalsa)
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        monkeypatch.setattr(ll_yt_oauth, "register_secret", lambda valor: self.eventos.append(f"registro:{valor}"))
        self.yml = tmp_path / "application.yml"
        self.mongo = SimpleNamespace(update_data=AsyncMock())
        self.sessao = SessaoFalsa()
        self.no_local = SimpleNamespace(
            info={"plugins": ["youtube-plugin"]},
            rest_uri="http://no.exemplo.invalido",
            _websocket=SimpleNamespace(headers={}),
        )
        if com_efeitos:
            self.yml.write_text(YML_ORIGINAL, encoding="utf-8")
        self.cog = ll_yt_oauth.YtOauthLL.__new__(ll_yt_oauth.YtOauthLL)
        self.cog.bot = SimpleNamespace(
            get_color=lambda *a: 0,
            session=self.sessao,
            pool=SimpleNamespace(mongo_database=self.mongo if com_efeitos else None),
            music=SimpleNamespace(nodes={"LOCAL": self.no_local} if com_efeitos else {}),
        )
        self.mensagem = SimpleNamespace(edit=registrar(self.eventos, "canal:edicao"))
        erro_dm = disnake.Forbidden(SimpleNamespace(status=403, reason="x"), "Cannot send messages to this user")
        self.dm = registrar(self.eventos, "dm", erro=erro_dm if dm_falha_em else None, falha_em=dm_falha_em)
        self.ctx = SimpleNamespace(
            guild=SimpleNamespace(me=None),
            author=SimpleNamespace(id=1, send=self.dm, mention="<@1>"),
            send=registrar(self.eventos, "canal:envio", retorno=self.mensagem),
            channel=SimpleNamespace(send=registrar(self.eventos, "canal:envio")),
        )
        self.erro: BaseException | None = None

    def rodar(self) -> None:
        try:
            asyncio.run(self.cog.oauth_command(self.ctx))
        except GenericError as erro:
            self.erro = erro

    def canal(self) -> str:
        """Tudo o que o CANAL pode ter recebido: envios, edições da mensagem e o texto de um erro genérico (as interações são da DM)."""
        chamadas = [self.ctx.send, self.mensagem.edit, self.ctx.channel.send]
        partes = [mostrar(c) for chamada in chamadas for c in chamada.call_args_list]
        if self.erro:
            partes += [str(self.erro), repr(getattr(self.erro, "args", ""))]
        return "\n".join(partes)

    def dm_texto(self) -> str:
        return "\n".join(mostrar(c) for c in self.dm.call_args_list)


@pytest.fixture
def cenario(monkeypatch, tmp_path) -> Cenario:
    return Cenario(monkeypatch, tmp_path)


@pytest.fixture
def cenario_dm_fechada(monkeypatch, tmp_path) -> Cenario:
    """A primeira DM (a de confirmação) falha."""
    return Cenario(monkeypatch, tmp_path, dm_falha_em={1, 2})


class TestConfirmacaoPorDm:
    """Opção A: a confirmação da conta é a primeira DM, com os botões; o canal não vê nada da conta."""

    def test_the_first_dm_is_the_confirmation_with_the_account_data_and_the_buttons(self, cenario):
        cenario.rodar()

        primeira = cenario.dm.call_args_list[0]
        assert all(dado in descricao_crua(primeira) for dado in (EMAIL, NOME_DA_CONTA)) and AVATAR in mostrar(primeira)
        assert isinstance(primeira.kwargs.get("view"), ConfirmacaoFalsa)

    def test_the_confirmation_dm_has_no_token(self, cenario):
        cenario.rodar()

        assert REFRESH not in mostrar(cenario.dm.call_args_list[0])

    def test_the_second_dm_carries_the_token(self, cenario):
        cenario.rodar()

        assert cenario.dm.await_count == 2 and REFRESH in mostrar(cenario.dm.call_args_list[1])

    def test_the_confirmation_dm_comes_before_the_token_dm_and_the_channel_only_points_to_the_dm(self, cenario):
        cenario.rodar()

        canal = cenario.canal()
        assert "DM" in canal and cenario.eventos.count("dm") == 2

    def test_a_refused_confirmation_sends_no_second_dm(self, monkeypatch, tmp_path):
        c = Cenario(monkeypatch, tmp_path)
        ConfirmacaoFalsa.selected = False

        c.rodar()

        assert c.dm.await_count == 1 and REFRESH not in c.dm_texto() + c.canal()


class TestNadaDoCanal:
    """Y1: NENHUMA mensagem do canal (confirmação ou final) tem token, e-mail, nome ou URL do avatar."""

    @pytest.mark.parametrize(
        "dado", [REFRESH, ACCESS, *DADOS_DA_CONTA], ids=["refresh", "access", "email", "nome", "avatar"]
    )
    def test_no_channel_message_has_it(self, cenario, dado):
        cenario.rodar()

        assert dado not in cenario.canal()

    @pytest.mark.parametrize("dado", [REFRESH, *DADOS_DA_CONTA], ids=["refresh", "email", "nome", "avatar"])
    def test_a_closed_dm_keeps_it_out_of_the_channel_too(self, cenario_dm_fechada, dado):
        cenario_dm_fechada.rodar()

        assert dado not in cenario_dm_fechada.canal()

    def test_the_dms_go_to_the_author_and_nobody_else(self, cenario):
        cenario.rodar()

        assert cenario.ctx.channel.send.await_count == 0


class TestPrazoDasDms:
    """Y2: as duas DMs somem sozinhas em 600 s, e a que traz o token diz o prazo em uma linha."""

    def test_both_dms_use_delete_after_600(self, cenario):
        cenario.rodar()

        assert [c.kwargs.get("delete_after") for c in cenario.dm.call_args_list] == [PRAZO_DA_DM, PRAZO_DA_DM]

    @pytest.mark.parametrize("indice", [0, 1], ids=["confirmacao", "token"])
    def test_each_dm_states_the_deadline_in_exactly_one_line(self, cenario, indice):
        cenario.rodar()

        linhas = [
            linha
            for linha in descricao_crua(cenario.dm.call_args_list[indice]).splitlines()
            if "10 minutos" in linha or "600" in linha
        ]
        assert len(linhas) == 1


class TestRegistroAntesDoEnvio:
    """Y4: o token entra no redator ANTES de qualquer envio feito depois de obtido (o convite inicial do ``ctx.send`` é anterior ao token)."""

    def test_the_token_is_registered_before_the_first_dm(self, cenario):
        cenario.rodar()

        assert cenario.eventos.index(f"registro:{REFRESH}") < cenario.eventos.index("dm")

    def test_the_token_is_registered_before_every_send_after_the_initial_invitation(self, cenario):
        cenario.rodar()

        eventos = cenario.eventos
        depois_do_convite = eventos[eventos.index("canal:envio") + 1 :]
        envios = [i for i, e in enumerate(depois_do_convite) if not e.startswith("registro:")]
        registro = depois_do_convite.index(f"registro:{REFRESH}")
        assert not envios or registro < envios[0]

    def test_the_access_token_is_registered_too(self, cenario):
        cenario.rodar()

        assert f"registro:{ACCESS}" in cenario.eventos

    def test_with_a_closed_dm_the_token_is_still_registered_before_the_attempt(self, cenario_dm_fechada):
        cenario_dm_fechada.rodar()

        assert cenario_dm_fechada.eventos.index(f"registro:{REFRESH}") < cenario_dm_fechada.eventos.index("dm")


class TestDmDeConfirmacaoFechada:
    """Y6: ``Forbidden`` na DM de confirmação aborta o fluxo; nada é alterado e o canal só recebe um aviso genérico."""

    @pytest.fixture
    def abortado(self, monkeypatch, tmp_path) -> Cenario:
        c = Cenario(monkeypatch, tmp_path, dm_falha_em={1}, com_efeitos=True)
        c.rodar()
        return c

    def test_application_yml_is_unchanged(self, abortado):
        assert abortado.yml.read_text(encoding="utf-8") == YML_ORIGINAL

    def test_the_local_node_is_not_touched(self, abortado):
        abortado.sessao.post.assert_not_awaited()

    def test_mongodb_is_not_touched(self, abortado):
        abortado.mongo.update_data.assert_not_awaited()

    def test_only_the_confirmation_dm_was_attempted(self, abortado):
        assert abortado.dm.await_count == 1

    def test_the_channel_gets_a_generic_notice_without_any_secret_or_account_data(self, abortado):
        canal = abortado.canal()

        assert "DM" in canal and "Cannot send messages" not in canal
        assert not any(dado in canal for dado in (REFRESH, ACCESS, *DADOS_DA_CONTA))

    def test_the_failure_is_not_logged_with_the_token(self, monkeypatch, tmp_path, caplog):
        c = Cenario(monkeypatch, tmp_path, dm_falha_em={1}, com_efeitos=True)

        with caplog.at_level(logging.DEBUG):
            c.rodar()

        assert all(REFRESH not in r.getMessage() + (r.exc_text or "") for r in caplog.records)


class TestDmDoTokenFechada:
    """A confirmação passou e a DM com o token falha: o canal continua sem o token e sem os dados da conta."""

    def test_the_channel_never_gets_the_token_or_the_account_data(self, monkeypatch, tmp_path):
        c = Cenario(monkeypatch, tmp_path, dm_falha_em={2})

        c.rodar()

        canal = c.canal()
        assert not any(dado in canal for dado in (REFRESH, *DADOS_DA_CONTA))

    def test_the_channel_asks_to_open_the_dms_in_a_generic_message(self, monkeypatch, tmp_path):
        c = Cenario(monkeypatch, tmp_path, dm_falha_em={2})

        c.rodar()

        canal = c.canal()
        assert "DM" in canal and "Cannot send messages" not in canal

    def test_an_unexpected_dm_error_also_keeps_the_token_out_of_the_channel(self, monkeypatch, tmp_path):
        c = Cenario(monkeypatch, tmp_path)
        c.dm.side_effect = RuntimeError("falha qualquer na entrega")

        try:
            c.rodar()
        except RuntimeError as erro:
            c.erro = erro

        assert not any(dado in c.canal() for dado in (REFRESH, *DADOS_DA_CONTA))


class TestTokenForaDosLogs:
    def test_the_token_never_appears_in_a_log_record(self, cenario, caplog):
        with caplog.at_level(logging.DEBUG):
            cenario.rodar()

        assert all(REFRESH not in r.getMessage() + (r.exc_text or "") for r in caplog.records)

    def test_the_token_never_appears_in_a_log_record_when_the_dm_fails(self, cenario_dm_fechada, caplog):
        with caplog.at_level(logging.DEBUG):
            cenario_dm_fechada.rodar()

        assert all(REFRESH not in r.getMessage() + (r.exc_text or "") for r in caplog.records)


class TestComandoNaoMudou:
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
