"""F3-6 — Spotify 429: a pausa é temporária e se desfaz sozinha (antes um 429 desligava o Spotify do bot até reiniciar).

* um 429 pausa o cliente só pelo tempo do ``Retry-After`` da resposta (inteiro de segundos, limitado entre 1 s e 1 h) ou,
  sem ele ou com valor inválido, por 60 s;
* passado o tempo, as requisições voltam a funcionar sozinhas;
* durante a pausa a requisição recebe um ``GenericError`` claro e **não chama a API** (nem pede token);
* o log registra só que entrou em pausa e por quanto tempo, sem token nem URL;
* a falta de credencial continua sendo outro motivo e permanente (o cliente nem é criado).

O relógio é injetável (``cliente.clock``) e a sessão HTTP é falsa: sem ``sleep`` real e sem rede.
"""

import logging
from unittest.mock import AsyncMock

import pytest

from empiremuse.utils.music.audio_sources import spotify as spotify_module
from empiremuse.utils.music.audio_sources.spotify import SpotifyClient
from empiremuse.utils.music.errors import GenericError

TOKEN = "token-secreto-do-teste"
PERFIL = {"display_name": "Ana"}


class Relogio:
    def __init__(self, agora=1000.0):
        self.agora = agora

    def __call__(self):
        return self.agora

    def avancar(self, segundos):
        self.agora += segundos


class RespostaFalsa:
    def __init__(self, status, headers=None, corpo=None):
        self.status, self.headers, self._corpo = status, headers or {}, corpo

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def json(self):
        return self._corpo

    def raise_for_status(self):
        raise AssertionError(f"status inesperado {self.status}")


class SessaoFalsa:
    """Entrega as respostas na ordem e registra cada ``GET`` feito à API."""

    def __init__(self, respostas, chamadas):
        self.respostas, self.chamadas = respostas, chamadas

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    def get(self, url, headers=None, params=None):
        self.chamadas.append(url)
        return self.respostas.pop(0)


@pytest.fixture
def api(monkeypatch, tmp_path):
    """Cliente com relógio e sessão falsos; ``cliente.responder(status, headers, corpo)`` enfileira a próxima resposta."""
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    cliente = SpotifyClient(client_id="id-de-teste", client_secret="segredo-de-teste")
    cliente.clock = Relogio()
    cliente.get_valid_access_token = AsyncMock(return_value=TOKEN)
    respostas, chamadas = [], []
    monkeypatch.setattr(spotify_module, "ClientSession", lambda *a, **k: SessaoFalsa(respostas, chamadas))

    def responder(status=200, headers=None, corpo=PERFIL):
        respostas.append(RespostaFalsa(status, headers, corpo))

    cliente.chamadas, cliente.responder = chamadas, responder
    return cliente


async def provocar_429(cliente, retry_after=None):
    cliente.responder(429, {"Retry-After": retry_after} if retry_after is not None else {})
    with pytest.raises(GenericError):
        await cliente.get_user_info("abc")


class TestPausaPeloRetryAfter:
    @pytest.mark.asyncio
    async def test_o_429_pausa_o_cliente_e_a_requisicao_recebe_um_erro_claro(self, api):
        cliente = api
        cliente.responder(429, {"Retry-After": "30"})
        with pytest.raises(GenericError) as erro:
            await cliente.get_user_info("abc")
        assert cliente.disabled is True
        assert "Spotify" in erro.value.text and "30" in erro.value.text

    @pytest.mark.asyncio
    async def test_durante_a_pausa_nada_chama_a_api_nem_pede_token(self, api):
        cliente = api
        await provocar_429(cliente, "30")
        feitas = len(cliente.chamadas)
        cliente.get_valid_access_token.reset_mock()
        for segundos in (0, 10, 19):
            cliente.clock.avancar(segundos)
            with pytest.raises(GenericError):
                await cliente.get_user_info("abc")
        assert len(cliente.chamadas) == feitas
        cliente.get_valid_access_token.assert_not_awaited()
        assert cliente.disabled is True

    @pytest.mark.asyncio
    async def test_a_mensagem_diz_quanto_falta(self, api):
        cliente = api
        await provocar_429(cliente, "30")
        cliente.clock.avancar(20)
        with pytest.raises(GenericError) as erro:
            await cliente.get_user_info("abc")
        assert "10" in erro.value.text

    @pytest.mark.asyncio
    async def test_passado_o_tempo_as_requisicoes_voltam_sozinhas(self, api):
        cliente = api
        await provocar_429(cliente, "30")
        cliente.clock.avancar(30)
        assert cliente.disabled is False
        cliente.responder(200, corpo={"display_name": "Ana"})
        assert await cliente.get_user_info("abc") == {"display_name": "Ana"}

    @pytest.mark.asyncio
    async def test_um_novo_429_depois_da_volta_abre_uma_nova_pausa(self, api):
        cliente = api
        await provocar_429(cliente, "5")
        cliente.clock.avancar(5)
        await provocar_429(cliente, "20")
        assert cliente.disabled is True
        cliente.clock.avancar(19)
        assert cliente.disabled is True
        cliente.clock.avancar(1)
        assert cliente.disabled is False

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("cabecalho", "segundos"),
        [
            (None, 60),
            ("", 60),
            ("abc", 60),
            ("-5", 60),
            ("3.7", 60),
            ("Wed, 21 Oct 2026 07:28:00 GMT", 60),
            ("0", 1),
            ("1", 1),
            ("90", 90),
            ("3600", 3600),
            ("3601", 3600),
            ("999999999999", 3600),
            (" 45 ", 45),
        ],
        ids=repr,
    )
    async def test_duracao_da_pausa_limitada_entre_1_s_e_1_h_e_60_s_sem_valor_valido(self, api, cabecalho, segundos):
        cliente = api
        await provocar_429(cliente, cabecalho)
        cliente.clock.avancar(segundos - 0.5)
        assert cliente.disabled is True, f"deveria seguir pausado aos {segundos - 0.5} s"
        cliente.clock.avancar(0.5)
        assert cliente.disabled is False, f"deveria voltar aos {segundos} s"

    @pytest.mark.asyncio
    async def test_a_mensagem_explica_a_pausa_e_arredonda_o_que_falta_para_cima(self, api):
        cliente = api
        await provocar_429(cliente, "30")
        cliente.clock.avancar(0.5)
        with pytest.raises(GenericError) as erro:
            await cliente.get_user_info("abc")
        assert "limitou" in erro.value.text and "pausa" in erro.value.text and "30 s" in erro.value.text
        cliente.clock.avancar(29.4)  # falta 0,1 s: ainda diz 1 s, nunca 0
        with pytest.raises(GenericError) as erro:
            await cliente.get_user_info("abc")
        assert "1 s" in erro.value.text and "0 s" not in erro.value.text

    def test_uma_pausa_nunca_encurta_outra_que_ainda_vale(self, api):
        """Duas respostas 429 em voo ao mesmo tempo: a do ``Retry-After`` menor não derruba a pausa da maior."""
        cliente = api
        cliente._pause("100")
        cliente._pause("5")
        cliente.clock.avancar(50)
        assert cliente.disabled is True
        cliente.clock.avancar(50)
        assert cliente.disabled is False


class TestLogDaPausa:
    @pytest.mark.asyncio
    async def test_registra_a_pausa_e_o_tempo_sem_token_nem_url(self, api, caplog):
        cliente = api
        with caplog.at_level(logging.INFO):
            await provocar_429(cliente, "30")
        registros = [r.getMessage() for r in caplog.records if "pausa" in r.getMessage().lower()]
        assert registros and "30" in registros[0]
        assert TOKEN not in caplog.text and "api.spotify.com" not in caplog.text and "users/abc" not in caplog.text
        assert "segredo-de-teste" not in caplog.text and "id-de-teste" not in caplog.text

    @pytest.mark.asyncio
    async def test_a_requisicao_recusada_na_pausa_nao_enche_o_log(self, api, caplog):
        cliente = api
        await provocar_429(cliente, "30")
        caplog.clear()
        with caplog.at_level(logging.INFO):
            for _ in range(5):
                with pytest.raises(GenericError):
                    await cliente.get_user_info("abc")
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


class TestRetryAfterPuro:
    @pytest.mark.parametrize(
        ("bruto", "esperado"),
        [(None, 60), ("", 60), ("x", 60), ("0", 1), ("30", 30), ("7200", 3600), ("-1", 60), (30, 30), (b"30", 60)],
        ids=repr,
    )
    def test_retry_after_seconds(self, bruto, esperado):
        from empiremuse.rules.ratelimit import retry_after_seconds

        assert retry_after_seconds(bruto) == esperado

    @pytest.mark.parametrize(
        ("bruto", "esperado"),
        [
            (True, 60),
            (False, 60),
            ("٣٠", 60),  # dígitos arábico-índicos: isdigit() é verdadeiro, mas não é um inteiro de cabeçalho HTTP
            ("1000", 1000),
            ("9" * 13, 3600),
            ("9" * 4000, 3600),
            (" 7\t", 7),
        ],
        ids=repr,
    )
    def test_retry_after_seconds_casos_de_borda(self, bruto, esperado):
        from empiremuse.rules.ratelimit import retry_after_seconds

        assert retry_after_seconds(bruto) == esperado

    def test_limites_e_padrao_configuraveis(self):
        from empiremuse.rules.ratelimit import retry_after_seconds

        assert retry_after_seconds(None, default=10) == 10
        assert retry_after_seconds("500", minimum=5, maximum=100) == 100
        assert retry_after_seconds("2", minimum=5, maximum=100) == 5


class TestGuardas:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [404, 403])
    async def test_guarda_outros_erros_nao_pausam_o_cliente(self, api, status):
        cliente = api
        cliente.responder(status)
        with pytest.raises(GenericError):
            await cliente.get_user_info("abc")
        assert cliente.disabled is False

    @pytest.mark.asyncio
    async def test_guarda_sucesso_devolve_o_json_e_nao_pausa(self, api):
        cliente = api
        cliente.responder(200, corpo={"display_name": "Ana"})
        assert await cliente.get_user_info("abc") == {"display_name": "Ana"}
        assert cliente.disabled is False

    @pytest.mark.parametrize("campo", ["client_id", "client_secret"])
    def test_guarda_falta_de_credencial_continua_impedindo_o_cliente(self, campo, monkeypatch, tmp_path):
        """Outro motivo, permanente: sem credencial o cliente nem existe (o BotPool fica com ``spotify = None``)."""
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        credenciais = {"client_id": "id-de-teste", "client_secret": "segredo-de-teste", campo: ""}
        with pytest.raises(Exception, match="não informado"):
            SpotifyClient(**credenciais)

    def test_guarda_o_relogio_padrao_e_monotonico(self, monkeypatch, tmp_path):
        import time

        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        cliente = SpotifyClient(client_id="id-de-teste", client_secret="segredo-de-teste")
        assert cliente.disabled is False
        assert cliente.clock is time.monotonic
