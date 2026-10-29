"""Emojis de aplicação (#130), E3/E4 e o threat model do Vigil (TM-E2, TM-E3): ``sync_app_emojis`` com um cliente falso.

Nada de rede nem de sono (``sleep`` injetado). O sync nunca apaga nem edita, cria em série, respeita o 429 com teto, para no primeiro 401/403,
só envia arquivo válido (tipo pelos bytes, 128×128 pelo cabeçalho, tamanho por ``stat`` antes de ler), e só sobe nome das 37 constantes.
"""

import logging
import pathlib

import pytest

from empiremuse.utils.music.app_emojis import sync_app_emojis
from tests.support.emojis_app import (
    NOMES,
    ClienteFalso,
    SonoFalso,
    emoji_da_app,
    erro_http,
    escrever_emojis,
    escrever_somas,
)

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]


@pytest.fixture
def pasta(tmp_path) -> pathlib.Path:
    return tmp_path / "assets" / "emojis"


async def sincronizar(cliente, pasta, *, sono=None, com_somas=True, **kwargs):
    """Falha fechada (TM-E3): o sync exige ``assets/SHA256SUMS``; em pasta temporária o teste o escreve com o que há nela (se ainda não existir).

    Nos arquivos reais do repositório use ``com_somas=False``: o teste nunca escreve na árvore e a falta do manifesto reprova.
    """
    if com_somas and pasta.is_dir() and not pasta.is_symlink() and not (pasta.parent / "SHA256SUMS").exists():
        escrever_somas(pasta)
    return await sync_app_emojis(cliente, emojis_dir=pasta, sleep=sono or SonoFalso(), **kwargs)


def avisos(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("empiremuse") and r.levelno == logging.WARNING]


class TestIdempotencia:
    async def test_running_twice_creates_nothing_the_second_time(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        cliente = ClienteFalso()
        primeiro = await sincronizar(cliente, pasta)
        criados = len(cliente.criacoes)

        segundo = await sincronizar(cliente, pasta)

        assert len(cliente.criacoes) == criados and segundo == primeiro


class TestNuncaMexeNoQueNaoE:
    async def test_a_foreign_emoji_is_never_deleted_edited_or_returned(self, pasta):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso([emoji_da_app("logo_do_servidor", 900000000000000001)])

        mapa = await sincronizar(cliente, pasta)

        assert "logo_do_servidor" not in mapa and [e.name for e in cliente.existentes].count("logo_do_servidor") == 1

    async def test_a_remote_name_that_differs_only_by_case_is_not_ours(self, pasta):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso([emoji_da_app("Stop", 910000000000000001)])

        assert "Stop" not in await sincronizar(cliente, pasta) and "stop" not in await sincronizar(cliente, pasta)

    @pytest.mark.parametrize("id_", ["abc", "12ab", "", None, 1.5, [1], "1 2", "<x>"], ids=repr)
    async def test_a_non_integer_remote_id_is_ignored(self, pasta, id_):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso([emoji_da_app("stop", id_)])

        assert "stop" not in await sincronizar(cliente, pasta)

    async def test_a_numeric_string_id_is_accepted_as_an_integer(self, pasta):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso([emoji_da_app("stop", "920000000000000001")])

        assert (await sincronizar(cliente, pasta))["stop"] == "<:stop:920000000000000001>"

    async def test_the_animated_flag_is_read_as_a_boolean_only(self, pasta):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso([emoji_da_app("stop", 930000000000000001, "<script>")])

        valor = (await sincronizar(cliente, pasta))["stop"]

        assert valor in (f"<a:stop:{930000000000000001}>", f"<:stop:{930000000000000001}>") and "script" not in valor

    async def test_a_remote_emoji_cannot_inject_through_its_name(self, pasta):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso([emoji_da_app("stop:1> <@everyone", 940000000000000001)])

        mapa = await sincronizar(cliente, pasta)

        assert mapa == {} and "everyone" not in repr(mapa)


class TestTaxaDeRequisicoes:
    """§10 do contrato: um 429 espera ``min(retry_after, 60)`` UMA vez e tenta de novo; o segundo 429 encerra o sync daquele bot."""

    async def test_two_429s_stop_the_sync_for_that_bot(self, pasta, caplog):
        escrever_emojis(pasta)
        cliente = ClienteFalso(falhas={nome: [erro_http(429, retry_after=1.0)] * 5 for nome in NOMES})
        sono = SonoFalso()

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            mapa = await sincronizar(cliente, pasta, sono=sono)

        assert sum(cliente.tentativas.values()) == 2 and sono.duracoes == [1.0] and mapa == {}
        assert len(avisos(caplog)) == 1


class TestFalhasDePermissao:
    @pytest.mark.parametrize("status", [401, 403])
    async def test_the_first_401_or_403_stops_the_sync_for_that_bot(self, pasta, status):
        escrever_emojis(pasta)
        cliente = ClienteFalso(falhas={nome: [erro_http(status)] for nome in NOMES})

        await sincronizar(cliente, pasta)

        assert sum(cliente.tentativas.values()) == 1

    @pytest.mark.parametrize("status", [401, 403])
    async def test_a_401_or_403_on_the_listing_creates_nothing(self, pasta, status):
        escrever_emojis(pasta)
        cliente = ClienteFalso(fetch_falha=erro_http(status))

        mapa = await sincronizar(cliente, pasta)

        assert cliente.criacoes == [] and mapa == {}

    async def test_a_permission_failure_leaves_the_existing_ones_in_the_map(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        cliente = ClienteFalso([emoji_da_app("skip", 950000000000000001)], falhas={"stop": [erro_http(403)]})

        mapa = await sincronizar(cliente, pasta)

        assert mapa == {"skip": "<:skip:950000000000000001>"}
