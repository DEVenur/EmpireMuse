"""Emojis de aplicação (#130), E6, E8, E9, E5 e as Infos do Vigil.

* E6: cada bot usa o PRÓPRIO mapa nos renderizadores do player (as 15 skins); E9: sem emojis de aplicação a saída é a de hoje (reserva Unicode).
* Webhook simples: emoji de aplicação só renderiza para a própria aplicação, então o aviso de entrada (``misc.send_hook``) e o relatório de erro
  ficam com Unicode.
* E8: nenhum literal ``<:nome:ID>``/``<a:nome:ID>`` em ``empiremuse/**``; o formato só é montado em ``app_emojis.py``.
* E5: integridade de ``assets/emojis/`` (``skip`` explícito por arquivo ausente).
"""

import ast
import hashlib
import re
import struct
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest

from tests.audio.test_md_link_rotulos_fixos import NOME_COM_BLOCO, servidor_com_nome
from tests.audio.test_skins_caracterizacao import NORMAL, STATIC, make_player
from tests.support.emojis_app import LADO, MAXIMO_BYTES, NOMES
from tests.support.marcas_md import textos_da_saida
from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

SKINS = [getattr(item, "values", (item,))[0] for item in NORMAL + STATIC]
ID_A, ID_B = 1111111111111111, 2222222222222222
PACOTE = RAIZ / "empiremuse"
ARQUIVO_DO_FORMATO = "empiremuse/utils/music/app_emojis.py"
ID_LITERAL = re.compile(r"<a?:\w{2,32}:\d{17,20}>")
FORMATO_DE_EMOJI = re.compile(r"<a?:\w{2,32}:(\d+)>")


def mapa_do_bot(id_base: int) -> dict[str, str]:
    return {nome: f"<:{nome}:{id_base + i}>" for i, nome in enumerate(NOMES)}


def ids_do_bot(id_base: int) -> set[str]:
    return {str(id_base + i) for i in range(len(NOMES))}


def componentes_com_emoji(componentes) -> list[str]:
    achados = []
    for linha in componentes or []:
        for item in linha if isinstance(linha, (list, tuple)) else [linha]:
            if getattr(item, "emoji", None) is not None:
                achados.append(str(item.emoji))
            for opcao in getattr(item, "options", None) or []:
                if getattr(opcao, "emoji", None) is not None:
                    achados.append(str(opcao.emoji))
    return achados


def tudo_o_que_a_skin_mostra(skin_cls, jogador) -> str:
    dados = skin_cls().load(jogador)
    return "\n".join(textos_da_saida(dados) + componentes_com_emoji(dados.get("components")))


def jogador_do_bot(mapa: dict[str, str]):
    jogador = make_player()
    jogador.bot.app_emojis = mapa
    jogador.bot.pool.emoji_data = {}
    return jogador


class TestCadaBotUsaOProprioMapa:
    def test_each_skin_shows_only_the_ids_of_the_bot_that_sends(self):
        for skin_cls in SKINS:
            do_a = tudo_o_que_a_skin_mostra(skin_cls, jogador_do_bot(mapa_do_bot(ID_A)))
            do_b = tudo_o_que_a_skin_mostra(skin_cls, jogador_do_bot(mapa_do_bot(ID_B)))

            assert not any(i in do_a for i in ids_do_bot(ID_B)), skin_cls.__name__
            assert not any(i in do_b for i in ids_do_bot(ID_A)), skin_cls.__name__

    def test_the_renderers_do_use_the_app_emojis_of_the_sending_bot(self):
        usados_a = set()
        for skin_cls in SKINS:
            texto = tudo_o_que_a_skin_mostra(skin_cls, jogador_do_bot(mapa_do_bot(ID_A)))
            usados_a.update(i for i in ids_do_bot(ID_A) if i in texto)

        assert usados_a, "nenhuma skin usou o emoji de aplicação do bot que envia"

    def test_the_queue_emoji_of_each_bot_reaches_its_own_players_message(self):
        mapa_a, mapa_b = mapa_do_bot(ID_A), mapa_do_bot(ID_B)
        esperado_a = re.search(r"\d+", mapa_a["music_queue"]).group()
        esperado_b = re.search(r"\d+", mapa_b["music_queue"]).group()
        com_fila_a = [s for s in SKINS if esperado_a in tudo_o_que_a_skin_mostra(s, jogador_do_bot(mapa_a))]
        com_fila_b = [s for s in SKINS if esperado_b in tudo_o_que_a_skin_mostra(s, jogador_do_bot(mapa_b))]

        assert com_fila_a and com_fila_a == com_fila_b


class TestSemRegressaoComAReservaUnicode:
    @pytest.mark.parametrize(
        "skin_cls", NORMAL + STATIC, ids=lambda c: c.__module__.rsplit(".", 1)[-1] + "-" + c.__name__
    )
    def test_without_app_emojis_no_custom_emoji_format_appears(self, skin_cls):
        texto = tudo_o_que_a_skin_mostra(skin_cls, jogador_do_bot({}))

        assert "<:" not in texto and "<a:" not in texto

    @pytest.mark.parametrize(
        "skin_cls", NORMAL + STATIC, ids=lambda c: c.__module__.rsplit(".", 1)[-1] + "-" + c.__name__
    )
    def test_a_bot_that_never_got_the_attribute_renders_with_unicode(self, skin_cls):
        jogador = make_player()
        jogador.bot = SimpleNamespace(
            get_color=lambda *a: 0, config={"HINT_RATE": 3}, pool=SimpleNamespace(emoji_data={})
        )

        assert "<:" not in tudo_o_que_a_skin_mostra(skin_cls, jogador)


class TestWebhookSimplesFicaComUnicode:
    @pytest.mark.asyncio
    async def test_the_join_notice_never_uses_application_emojis(self):
        from empiremuse.cogs.misc import GuildLog

        canal = MagicMock()
        canal.permissions_for.return_value.send_messages = False
        webhook = AsyncMock()
        dono = SimpleNamespace(
            hook_url="https://discord.com/api/webhooks/1/x",
            bot=SimpleNamespace(
                get_channel=lambda _id: None,
                config={"BOT_ADD_REMOVE_LOG_CHANNEL_ID": 0},
                owner_ids=[1],
                owner=SimpleNamespace(mention="<@1>"),
                user=SimpleNamespace(
                    name="bot", display_avatar=SimpleNamespace(replace=lambda **k: SimpleNamespace(url="https://x"))
                ),
                app_emojis=mapa_do_bot(ID_A),
                pool=SimpleNamespace(emoji_data={}),
            ),
        )
        enviados = []

        class FalsoWebhook:
            @staticmethod
            def from_url(*a, **k):
                return SimpleNamespace(send=AsyncMock(side_effect=lambda **kw: enviados.append(kw)))

        import empiremuse.cogs.misc as misc

        original = misc.disnake.Webhook
        misc.disnake.Webhook = FalsoWebhook
        try:
            await GuildLog.send_hook(dono, servidor_com_nome(NOME_COM_BLOCO), "Título", disnake.Color.green())
        finally:
            misc.disnake.Webhook = original

        texto = " ".join(str(e["embed"].to_dict()) for e in enviados)
        assert enviados and "<:" not in texto and "<a:" not in texto

    def test_the_error_handler_does_not_use_the_application_emoji_helper(self):
        arvore = ast.parse((PACOTE / "cogs" / "error_handler.py").read_text(encoding="utf-8"))
        nomes = {n.id for n in ast.walk(arvore) if isinstance(n, ast.Name)} | {
            n.attr for n in ast.walk(arvore) if isinstance(n, ast.Attribute)
        }
        importados = {a.name for n in ast.walk(arvore) if isinstance(n, ast.ImportFrom) for a in n.names}

        assert "emoji" not in nomes - {"emoji_data"} or "emoji" not in importados
        assert "app_emojis" not in nomes and "app_emojis" not in importados


# ============================================================================ E8 — guarda contra IDs literais


def literais_com_id(codigo: str) -> list[tuple[int, str]]:
    """``(linha, trecho)`` de cada string do código (inclusive partes literais de f-strings) com ``<:nome:ID>`` ou ``<a:nome:ID>``."""
    achados = []
    for no in ast.walk(ast.parse(codigo)):
        if isinstance(no, ast.Constant) and isinstance(no.value, str) and (m := ID_LITERAL.search(no.value)):
            achados.append((no.lineno, m.group()))
    return achados


class TestScannerDeIds:
    @pytest.mark.parametrize(
        "codigo",
        [
            'x = "<:fila:703761160679194734>"',
            'x = "<a:animado:703761160679194734>"',
            'x = f"antes <:fila:703761160679194734> {depois}"',
            'x = ["a", "<:um_nome:12345678901234567>"]',
            'def f():\n    """Doc com <:fila:703761160679194734> dentro."""',
            'x = "<:fila:70376116067919473490>"',
        ],
    )
    def test_it_finds_a_literal_id_in_any_string_constant(self, codigo):
        assert literais_com_id(codigo)

    @pytest.mark.parametrize(
        "codigo",
        [
            'x = f"<:{nome}:{id_}>"',
            'x = "<:fila:123>"',
            'x = "<@123456789012345678>"',
            'x = "<t:1234567890:R>"',
            'x = "</play:703761160679194734>"',
            'x = "<#703761160679194734>"',
            'x = "nome:703761160679194734"',
        ],
    )
    def test_it_ignores_the_format_without_an_id_and_other_mentions(self, codigo):
        assert literais_com_id(codigo) == []


class TestNenhumIdNoCodigo:
    def test_no_package_file_has_a_literal_emoji_id(self):
        achados = {}
        for caminho in sorted(PACOTE.rglob("*.py")):
            relativo = caminho.relative_to(RAIZ).as_posix()
            if lista := literais_com_id(caminho.read_text(encoding="utf-8")):
                achados[relativo] = lista

        assert achados == {}, achados

    def test_the_format_is_built_only_in_the_app_emojis_module(self):
        construtores = []
        for caminho in sorted(PACOTE.rglob("*.py")):
            relativo = caminho.relative_to(RAIZ).as_posix()
            for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
                if isinstance(no, ast.JoinedStr):
                    partes = "".join(p.value if isinstance(p, ast.Constant) else "\0" for p in no.values)
                    if re.search(r"<a?:\0:\0>", partes):
                        construtores.append(relativo)

        assert construtores == [] or set(construtores) == {ARQUIVO_DO_FORMATO}


# ============================================================================ E5 — integridade de assets/emojis


PASTA = RAIZ / "assets" / "emojis"


def tipo_e_lado(dados: bytes) -> tuple[str, int, int] | None:
    if dados.startswith(b"\x89PNG\r\n\x1a\n") and len(dados) >= 24:
        largura, altura = struct.unpack(">II", dados[16:24])
        return "png", largura, altura
    if dados[:6] in (b"GIF87a", b"GIF89a") and len(dados) >= 10:
        largura, altura = struct.unpack("<HH", dados[6:10])
        return "gif", largura, altura
    return None


def somas() -> dict[str, str]:
    arquivo = RAIZ / "assets" / "SHA256SUMS"
    if not arquivo.is_file():
        return {}
    pares = (linha.split(None, 1) for linha in arquivo.read_text(encoding="utf-8").splitlines() if linha.strip())
    return {nome.strip(): resumo for resumo, nome in pares}


def arquivo_do_emoji(nome: str):
    for extensao in ("png", "gif"):
        if (PASTA / f"{nome}.{extensao}").exists():
            return PASTA / f"{nome}.{extensao}"
    return None


class TestIntegridadeDosArquivos:
    @pytest.mark.parametrize("nome", NOMES)
    def test_each_emoji_file_is_a_regular_128_by_128_png_or_gif_within_the_size_limit(self, nome):
        arquivo = arquivo_do_emoji(nome)
        if arquivo is None:
            pytest.skip(f"assets/emojis/{nome}.png ainda não chegou (E5 vale quando o arquivo existir)")

        dados = arquivo.read_bytes()
        assert arquivo.is_file() and not arquivo.is_symlink() and len(dados) <= MAXIMO_BYTES
        assert tipo_e_lado(dados) is not None and tipo_e_lado(dados)[1:] == (LADO, LADO)

    @pytest.mark.parametrize("nome", NOMES)
    def test_each_emoji_file_matches_its_sha256sums_entry(self, nome):
        arquivo = arquivo_do_emoji(nome)
        if arquivo is None:
            pytest.skip(f"assets/emojis/{nome}.png ainda não chegou")

        esperado = somas().get(f"emojis/{arquivo.name}")
        assert esperado == hashlib.sha256(arquivo.read_bytes()).hexdigest()

    def test_the_folder_has_no_file_with_a_name_outside_the_25(self):
        if not PASTA.is_dir():
            pytest.skip("assets/emojis/ ainda não existe")

        estranhos = [p.name for p in PASTA.iterdir() if p.stem not in NOMES or p.suffix not in (".png", ".gif")]
        assert estranhos == []

    def test_the_checker_itself_reads_a_header(self):
        assert tipo_e_lado(b"\x89PNG\r\n\x1a\n" + bytes(8) + struct.pack(">II", 128, 128)) == ("png", 128, 128)
        assert tipo_e_lado(b"GIF89a" + struct.pack("<HH", 128, 128)) == ("gif", 128, 128)
        assert tipo_e_lado(b"nada") is None
