"""Emojis de aplicação (#130), E3/E4 e o threat model do Vigil (TM-E2, TM-E3): ``sync_app_emojis`` com um cliente falso.

Nada de rede nem de sono (``sleep`` injetado). O sync nunca apaga nem edita, cria em série, respeita o 429 com teto, para no primeiro 401/403,
só envia arquivo válido (tipo pelos bytes, 128×128 pelo cabeçalho, tamanho por ``stat`` antes de ler), e só sobe nome das 37 constantes.
"""

import asyncio
import builtins
import logging
import pathlib
import sys

import pytest

from empiremuse.utils.music.app_emojis import APP_EMOJIS, sync_app_emojis
from tests.support.raiz import RAIZ
from tests.support.emojis_app import (
    MAXIMO_BYTES,
    NOMES,
    ClienteFalso,
    SonoFalso,
    emoji_da_app,
    erro_http,
    escrever_emojis,
    escrever_somas,
    gif,
    gif_animado,
    jpeg,
    png,
    png_so_cabecalho,
)

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

CORPO_PRIVADO = "".join(["corpo-da-resposta-", "nao-pode-sair"])


@pytest.fixture
def pasta(tmp_path) -> pathlib.Path:
    return tmp_path / "assets" / "emojis"


async def sincronizar(cliente, pasta, *, sono=None, com_somas=True, **kwargs):
    """Falha fechada (TM-E3): o sync exige ``assets/SHA256SUMS``; por padrão o teste o escreve com o que há na pasta (se ainda não existir)."""
    if com_somas and pasta.is_dir() and not pasta.is_symlink() and not (pasta.parent / "SHA256SUMS").exists():
        escrever_somas(pasta)
    return await sync_app_emojis(cliente, emojis_dir=pasta, sleep=sono or SonoFalso(), **kwargs)


def avisos(caplog) -> list[logging.LogRecord]:
    return [r for r in caplog.records if r.name.startswith("empiremuse") and r.levelno == logging.WARNING]


class TestCriacao:
    async def test_an_app_without_emojis_gets_the_ones_that_have_a_file_in_series(self, pasta):
        escrever_emojis(pasta, ["stop", "skip", "play"])
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert sorted(nome for nome, _ in cliente.criacoes) == ["play", "skip", "stop"]
        assert cliente.pico_em_voo == 1
        assert sorted(mapa) == ["play", "skip", "stop"] and all(v.startswith("<:") for v in mapa.values())

    async def test_the_value_is_built_from_our_constant_and_the_integer_id(self, pasta):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert mapa["stop"] == f"<:stop:{cliente.existentes[0].id}>"

    async def test_all_25_with_files_are_created_and_only_those_names_appear(self, pasta):
        escrever_emojis(pasta)
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert sorted(mapa) == sorted(NOMES) == sorted(APP_EMOJIS)

    async def test_an_animated_result_uses_the_animated_format(self, pasta):
        pasta.mkdir(parents=True)
        (pasta / "play.gif").write_bytes(gif())
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert mapa["play"] == f"<a:play:{cliente.existentes[0].id}>"


class TestIdempotencia:
    async def test_running_twice_creates_nothing_the_second_time(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        cliente = ClienteFalso()
        primeiro = await sincronizar(cliente, pasta)
        criados = len(cliente.criacoes)

        segundo = await sincronizar(cliente, pasta)

        assert len(cliente.criacoes) == criados and segundo == primeiro

    async def test_when_all_already_exist_nothing_is_created(self, pasta):
        escrever_emojis(pasta)
        existentes = [emoji_da_app(nome, 500000000000000000 + i) for i, nome in enumerate(NOMES)]
        cliente = ClienteFalso(existentes)

        mapa = await sincronizar(cliente, pasta)

        assert cliente.criacoes == [] and mapa["stop"] == f"<:stop:{500000000000000000 + NOMES.index('stop')}>"

    async def test_an_existing_emoji_is_used_even_without_a_local_file(self, pasta):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso([emoji_da_app("stop", 600000000000000001)])

        assert (await sincronizar(cliente, pasta))["stop"] == "<:stop:600000000000000001>"

    async def test_the_same_name_with_another_image_is_used_as_is(self, pasta):
        escrever_emojis(pasta, ["stop"], conteudo=png())
        cliente = ClienteFalso([emoji_da_app("stop", 700000000000000001)])

        mapa = await sincronizar(cliente, pasta)

        assert cliente.criacoes == [] and mapa["stop"] == "<:stop:700000000000000001>"

    async def test_an_existing_animated_emoji_keeps_the_animated_format(self, pasta):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso([emoji_da_app("play", 800000000000000001, True)])

        assert (await sincronizar(cliente, pasta))["play"] == "<a:play:800000000000000001>"


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

    async def test_one_429_waits_the_retry_after_once_and_then_creates(self, pasta):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso(falhas={"stop": [erro_http(429, retry_after=2.5)]})
        sono = SonoFalso()

        mapa = await sincronizar(cliente, pasta, sono=sono)

        assert "stop" in mapa and sono.duracoes == [2.5] and cliente.tentativas["stop"] == 2

    async def test_a_429_without_retry_after_waits_five_seconds_once(self, pasta):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso(falhas={"stop": [erro_http(429)]})
        sono = SonoFalso()

        mapa = await sincronizar(cliente, pasta, sono=sono)

        assert sono.duracoes == [5] and "stop" in mapa

    async def test_a_retry_after_of_300_seconds_waits_60(self, pasta):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso(falhas={"stop": [erro_http(429, retry_after=300.0)]})
        sono = SonoFalso()

        mapa = await sincronizar(cliente, pasta, sono=sono)

        assert sono.duracoes == [60] and "stop" in mapa

    async def test_a_negative_retry_after_never_gives_a_negative_sleep(self, pasta):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso(falhas={"stop": [erro_http(429, retry_after=-5.0)]})
        sono = SonoFalso()

        await sincronizar(cliente, pasta, sono=sono)

        assert all(d >= 0 for d in sono.duracoes)

    async def test_two_429s_stop_the_sync_for_that_bot(self, pasta, caplog):
        escrever_emojis(pasta)
        cliente = ClienteFalso(falhas={nome: [erro_http(429, retry_after=1.0)] * 5 for nome in NOMES})
        sono = SonoFalso()

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            mapa = await sincronizar(cliente, pasta, sono=sono)

        assert sum(cliente.tentativas.values()) == 2 and sono.duracoes == [1.0] and mapa == {}
        assert len(avisos(caplog)) == 1

    async def test_the_names_created_before_the_second_429_stay_in_the_map(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        cliente = ClienteFalso(
            falhas={"skip": [erro_http(429, retry_after=1.0)] * 5, "stop": [erro_http(429, retry_after=1.0)] * 5}
        )
        cliente.existentes.append(emoji_da_app("play", 990000000000000001))

        mapa = await sincronizar(cliente, pasta)

        assert mapa == {"play": "<:play:990000000000000001>"}

    async def test_a_global_429_stops_without_waiting(self, pasta):
        escrever_emojis(pasta)
        cliente = ClienteFalso(falhas={nome: [erro_http(429, retry_after=1.0, global_=True)] for nome in NOMES})
        sono = SonoFalso()

        mapa = await sincronizar(cliente, pasta, sono=sono)

        assert sum(cliente.tentativas.values()) == 1 and sono.duracoes == [] and mapa == {}


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


class TestCondicaoDeCorrida:
    async def test_400_with_code_50035_refetches_once_and_does_not_retry(self, pasta):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso(falhas={"stop": [erro_http(400, codigo=50035)]})
        cliente_fetch = cliente.fetch_application_emojis

        async def fetch_depois_da_corrida():
            if cliente.fetches >= 1 and not any(e.name == "stop" for e in cliente.existentes):
                cliente.existentes.append(emoji_da_app("stop", 960000000000000001))
            return await cliente_fetch()

        cliente.fetch_application_emojis = fetch_depois_da_corrida

        mapa = await sincronizar(cliente, pasta)

        assert cliente.tentativas["stop"] == 1 and cliente.fetches == 2
        assert mapa["stop"] == "<:stop:960000000000000001>"

    async def test_the_refetch_happens_at_most_once_per_sync(self, pasta):
        escrever_emojis(pasta, ["stop", "skip", "play"])
        cliente = ClienteFalso(falhas={nome: [erro_http(400, codigo=50035)] * 2 for nome in ("stop", "skip", "play")})

        await sincronizar(cliente, pasta)

        assert cliente.fetches <= 2 and all(vezes == 1 for vezes in cliente.tentativas.values())


class TestAvisoUnico:
    async def test_a_missing_file_gives_one_warning_with_the_name_and_no_api_call(self, pasta, caplog):
        pasta.mkdir(parents=True)
        cliente = ClienteFalso()

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            mapa = await sincronizar(cliente, pasta)

        assert mapa == {} and cliente.criacoes == [] and len(avisos(caplog)) == 1
        assert "stop" in avisos(caplog)[0].getMessage()

    async def test_several_failures_still_give_a_single_warning_per_bot(self, pasta, caplog):
        escrever_emojis(pasta, ["stop", "skip"])
        cliente = ClienteFalso(falhas={"stop": [erro_http(500)], "skip": [erro_http(500)]})

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await sincronizar(cliente, pasta)

        assert len(avisos(caplog)) == 1

    async def test_the_warning_has_names_and_the_error_kind_but_never_the_body_or_the_image(self, pasta, caplog):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso(falhas={"stop": [erro_http(500, corpo=CORPO_PRIVADO)]})

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await sincronizar(cliente, pasta)

        (aviso,) = avisos(caplog)
        texto = aviso.getMessage() + (aviso.exc_text or "")
        assert "stop" in texto and ("500" in texto or "HTTPException" in texto)
        assert CORPO_PRIVADO not in texto and "iVBOR" not in texto and "\\x89PNG" not in texto

    async def test_a_successful_sync_logs_no_warning_and_info_lists_created_and_reused(self, pasta, caplog):
        escrever_emojis(pasta, [n for n in NOMES if n != "skip"])
        cliente = ClienteFalso([emoji_da_app("skip", 970000000000000001)])

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await sincronizar(cliente, pasta)

        info = " ".join(
            r.getMessage() for r in caplog.records if r.name.startswith("empiremuse") and r.levelno == logging.INFO
        )
        assert avisos(caplog) == [] and "stop" in info and "skip" in info


class TestValidacaoDeArquivo:
    """E4 e TM-E3: só entra o arquivo que passa em tudo; um arquivo inválido nunca provoca chamada à API."""

    async def enviar(self, pasta, nome_do_arquivo: str, dados: bytes):
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / nome_do_arquivo).write_bytes(dados)
        cliente = ClienteFalso()
        mapa = await sincronizar(cliente, pasta)
        return cliente, mapa

    @pytest.mark.parametrize(
        ("rotulo", "dados"),
        [
            ("jpeg", jpeg()),
            ("texto", b"nao e imagem"),
            ("vazio", b""),
            ("png-64", png(64, 64)),
            ("png-129x128", png(129, 128)),
            ("png-128x127", png(128, 127)),
            ("png-zero", png(0, 0)),
            ("gif-64", gif(64, 64)),
            ("gif-128x129", gif_animado(128, 129)),
            ("gif-animado-grande", gif_animado(quadros=3) + b"\x00" * MAXIMO_BYTES),
            ("png-truncado-na-assinatura", b"\x89PNG\r\n"),
            ("gif-versao-errada", gif(versao=b"GIF90a")),
            ("png-grande", png(extra=MAXIMO_BYTES)),
            ("gif-grande", gif(extra=MAXIMO_BYTES)),
        ],
    )
    async def test_an_invalid_file_is_never_uploaded(self, pasta, rotulo, dados):
        cliente, mapa = await self.enviar(pasta, "stop.png", dados)

        assert cliente.criacoes == [] and sum(cliente.tentativas.values()) == 0 and "stop" not in mapa

    @pytest.mark.parametrize(
        "dados",
        [png(), png_so_cabecalho(), png(extra=MAXIMO_BYTES - 2000)],
        ids=["completo", "so-cabecalho", "perto-do-teto"],
    )
    async def test_a_png_is_accepted_by_signature_and_header_size(self, pasta, dados):
        cliente, mapa = await self.enviar(pasta, "stop.png", dados)

        assert [nome for nome, _ in cliente.criacoes] == ["stop"] and "stop" in mapa

    @pytest.mark.parametrize("versao", [b"GIF87a", b"GIF89a"])
    async def test_a_gif_87a_or_89a_is_accepted(self, pasta, versao):
        cliente, mapa = await self.enviar(pasta, "play.gif", gif(versao=versao))

        assert [nome for nome, _ in cliente.criacoes] == ["play"] and mapa["play"].startswith("<a:")

    async def test_the_type_comes_from_the_bytes_not_the_extension(self, pasta):
        cliente, _ = await self.enviar(pasta, "stop.png", jpeg())

        assert cliente.criacoes == []

    async def test_a_png_with_a_gif_extension_is_judged_by_its_bytes(self, pasta):
        cliente, mapa = await self.enviar(pasta, "stop.gif", png())

        assert [nome for nome, _ in cliente.criacoes] == ["stop"] and mapa["stop"].startswith("<:")

    async def test_the_dimensions_are_read_from_the_header_without_pillow(self, pasta, monkeypatch):
        monkeypatch.setitem(sys.modules, "PIL", None)
        monkeypatch.setitem(sys.modules, "PIL.Image", None)

        cliente, _ = await self.enviar(pasta, "stop.png", png_so_cabecalho())

        assert [nome for nome, _ in cliente.criacoes] == ["stop"]

    async def test_an_oversized_file_is_refused_by_stat_before_it_is_read(self, pasta, monkeypatch):
        pasta.mkdir(parents=True)
        grande = pasta / "stop.png"
        grande.write_bytes(png(extra=MAXIMO_BYTES))
        escrever_somas(pasta)  # antes dos espiões: o que se vigia é o sync, não o apoio do teste
        lidos: list[str] = []
        abrir, ler_bytes, abrir_path = builtins.open, pathlib.Path.read_bytes, pathlib.Path.open

        def espia_open(arquivo, *a, **k):
            lidos.append(str(arquivo))
            return abrir(arquivo, *a, **k)

        def espia_bytes(self, *a, **k):
            lidos.append(str(self))
            return ler_bytes(self, *a, **k)

        def espia_path(self, *a, **k):
            lidos.append(str(self))
            return abrir_path(self, *a, **k)

        monkeypatch.setattr(builtins, "open", espia_open)
        monkeypatch.setattr(pathlib.Path, "read_bytes", espia_bytes)
        monkeypatch.setattr(pathlib.Path, "open", espia_path)

        cliente = ClienteFalso()
        await sincronizar(cliente, pasta)

        assert cliente.criacoes == [] and str(grande) not in lidos

    async def test_a_name_outside_the_25_constants_is_never_uploaded(self, pasta):
        escrever_emojis(pasta, ["stop"])
        (pasta / "emoji_extra.png").write_bytes(png())
        (pasta / "Stop-Maiusculo.png").write_bytes(png())
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert [nome for nome, _ in cliente.criacoes] == ["stop"] and sorted(mapa) == ["stop"]

    async def test_a_directory_with_a_valid_name_is_not_a_file(self, pasta):
        (pasta / "stop.png").mkdir(parents=True)
        cliente = ClienteFalso()

        assert cliente.criacoes == [] and "stop" not in await sincronizar(cliente, pasta)


class TestSomenteArquivosRegulares:
    async def test_a_symlink_to_a_valid_png_outside_the_folder_is_not_uploaded(self, pasta, tmp_path):
        pasta.mkdir(parents=True)
        fora = tmp_path / "fora.png"
        fora.write_bytes(png())
        (pasta / "stop.png").symlink_to(fora)
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert cliente.criacoes == [] and "stop" not in mapa

    async def test_a_symlink_to_another_file_inside_the_folder_is_not_uploaded_either(self, pasta):
        escrever_emojis(pasta, ["skip"])
        (pasta / "stop.png").symlink_to(pasta / "skip.png")
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert [nome for nome, _ in cliente.criacoes] == ["skip"] and "stop" not in mapa

    async def test_a_folder_that_is_itself_a_symlink_outside_is_not_followed(self, tmp_path):
        real = tmp_path / "real"
        escrever_emojis(real, ["stop"])
        elo = tmp_path / "assets" / "emojis"
        elo.parent.mkdir()
        elo.symlink_to(real)
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, elo)

        assert cliente.criacoes == [] and mapa == {}


class TestGifAnimado:
    """O ``headset`` é um GIF89a ANIMADO 128×128: entra, e sai no formato ``<a:nome:id>``."""

    async def test_an_animated_gif_89a_128_by_128_is_uploaded_and_comes_out_animated(self, pasta):
        pasta.mkdir(parents=True)
        (pasta / "headset.gif").write_bytes(gif_animado(quadros=4))
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert mapa["headset"] == f"<a:headset:{cliente.existentes[0].id}>"
        assert cliente.criacoes[0][1].startswith(b"GIF89a")

    async def test_the_real_headset_comes_out_animated_and_the_other_files_as_static(self):
        real = RAIZ / "assets" / "emojis"
        assert (real / "headset.gif").is_file(), "assets/emojis/headset.gif ainda não chegou (§12 do contrato)"
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, real)

        assert mapa["headset"].startswith("<a:headset:")
        assert all(valor.startswith("<:") for nome, valor in mapa.items() if nome != "headset")

    async def test_all_37_real_files_are_uploaded_when_the_app_has_none(self):
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, RAIZ / "assets" / "emojis")

        assert sorted(mapa) == sorted(NOMES)


class TestSomasDeIntegridade:
    async def test_a_file_whose_hash_differs_from_sha256sums_is_not_uploaded(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        escrever_somas(pasta, errado=("stop.png",))
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert [nome for nome, _ in cliente.criacoes] == ["skip"] and "stop" not in mapa

    async def test_files_that_match_sha256sums_are_uploaded(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        escrever_somas(pasta)
        cliente = ClienteFalso()

        assert sorted(await sincronizar(cliente, pasta)) == ["skip", "stop"]

    async def test_the_mismatch_is_reported_by_name_only(self, pasta, caplog):
        escrever_emojis(pasta, ["stop"])
        escrever_somas(pasta, errado=("stop.png",))

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await sincronizar(ClienteFalso(), pasta)

        (aviso,) = avisos(caplog)
        assert "stop" in aviso.getMessage() and "iVBOR" not in aviso.getMessage()


class TestFalhaFechadaSemSomas:
    """TM-E3: sem ``assets/SHA256SUMS`` (ou sem a linha do arquivo) nada é enviado; um WARNING 'SHA256SUMS ausente' por bot."""

    async def test_without_sha256sums_nothing_is_created_and_no_create_call_is_made(self, pasta):
        escrever_emojis(pasta, ["stop", "skip", "play"])
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta, com_somas=False)

        assert cliente.criacoes == [] and sum(cliente.tentativas.values()) == 0 and mapa == {}

    async def test_without_sha256sums_one_warning_says_so(self, pasta, caplog):
        escrever_emojis(pasta, ["stop", "skip"])

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await sincronizar(ClienteFalso(), pasta, com_somas=False)

        (aviso,) = avisos(caplog)
        assert "SHA256SUMS ausente" in aviso.getMessage()

    async def test_without_sha256sums_the_remote_emojis_that_already_exist_stay_in_the_map(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        cliente = ClienteFalso([emoji_da_app("skip", 980000000000000001)])

        mapa = await sincronizar(cliente, pasta, com_somas=False)

        assert mapa == {"skip": "<:skip:980000000000000001>"} and cliente.criacoes == []

    async def test_an_empty_sha256sums_creates_nothing(self, pasta):
        escrever_emojis(pasta, ["stop"])
        (pasta.parent / "SHA256SUMS").write_text("", encoding="utf-8")
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert cliente.criacoes == [] and mapa == {}

    async def test_a_file_without_its_line_in_sha256sums_is_not_uploaded_but_the_others_are(self, pasta):
        escrever_emojis(pasta, ["stop", "skip"])
        soma = escrever_somas(pasta)
        soma.write_text(
            "".join(l for l in soma.read_text().splitlines(keepends=True) if "stop.png" not in l), encoding="utf-8"
        )
        cliente = ClienteFalso()

        mapa = await sincronizar(cliente, pasta)

        assert [nome for nome, _ in cliente.criacoes] == ["skip"] and "stop" not in mapa

    async def test_a_sha256sums_with_only_other_paths_creates_nothing(self, pasta):
        escrever_emojis(pasta, ["stop"])
        (pasta.parent / "SHA256SUMS").write_text("0" * 64 + "  providers/provider_spotify_icon.png\n", encoding="utf-8")
        cliente = ClienteFalso()

        assert await sincronizar(cliente, pasta) == {} and cliente.criacoes == []

    async def test_a_sha256sums_that_is_a_directory_creates_nothing_and_never_raises(self, pasta):
        escrever_emojis(pasta, ["stop"])
        (pasta.parent / "SHA256SUMS").mkdir()
        cliente = ClienteFalso()

        assert await sincronizar(cliente, pasta) == {} and cliente.criacoes == []

    async def test_the_warning_for_a_missing_sums_file_never_has_the_image_bytes(self, pasta, caplog):
        escrever_emojis(pasta, ["stop"])

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            await sincronizar(ClienteFalso(), pasta, com_somas=False)

        assert all("iVBOR" not in r.getMessage() and "\\x89PNG" not in r.getMessage() for r in caplog.records)


class TestSemFalhaGeral:
    async def test_an_unexpected_error_listing_the_emojis_never_raises(self, pasta, caplog):
        escrever_emojis(pasta, ["stop"])
        cliente = ClienteFalso(fetch_falha=RuntimeError("falha qualquer"))

        with caplog.at_level(logging.DEBUG, logger="empiremuse"):
            mapa = await sincronizar(cliente, pasta)

        assert mapa == {} and cliente.criacoes == []

    async def test_a_missing_folder_never_raises(self, tmp_path):
        assert await sincronizar(ClienteFalso(), tmp_path / "nao_existe") == {}

    async def test_the_task_can_be_cancelled(self, pasta):
        escrever_emojis(pasta)
        cliente = ClienteFalso()
        tarefa = asyncio.ensure_future(sincronizar(cliente, pasta))
        await asyncio.sleep(0)
        tarefa.cancel()

        with pytest.raises(asyncio.CancelledError):
            await tarefa
