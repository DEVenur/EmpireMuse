"""F3-5b — as regras centralizadas em ``empiremuse.rules``, chamadas DIRETAMENTE (funções puras, sem dublês).

Complementam a caracterização por comportamento dos comandos e do painel: se uma regra mudar aqui sem querer, os dois
lados mudam juntos, então cada função e cada limite têm o valor atual pinado com números literais (que não mudam
junto com a constante). Quando uma etapa seguinte alterar uma regra de propósito, o teste que a pina é invertido nela.
"""

from types import SimpleNamespace

import pytest

from empiremuse.panel.services.appearance import reload_skin
from empiremuse.rules import limits, quota, settings, text, urls
from tests.helpers_f3_5b import BotDoPainel, painel_favoritos

URL = "https://exemplo.invalid/a"


class TestLimites:
    def test_valores_atuais(self):
        assert (limits.FAV_NAME_MIN, limits.FAV_NAME_MAX) == (2, 25)
        assert (limits.FAV_URL_MIN, limits.FAV_URL_MAX) == (10, 200)
        assert (limits.ITG_TITLE_MAX, limits.ITG_URL_MAX, limits.ITG_AVATAR_MAX) == (90, 150, 250)
        assert limits.MAX_GUILD_LINKS == 25
        assert (limits.GUILD_LINK_NAME_MIN, limits.GUILD_LINK_NAME_MAX) == (2, 25)
        assert (limits.GUILD_LINK_URL_MIN, limits.GUILD_LINK_URL_MAX) == (10, 250)
        assert (limits.GUILD_LINK_DESCRIPTION_MIN, limits.GUILD_LINK_DESCRIPTION_MAX) == (3, 50)
        assert limits.PREFIX_MAX_LENGTH == 5
        assert limits.VOICE_STATUS_MAX_LENGTH == 496
        assert limits.MAX_DJ_ROLES == 25
        assert limits.CUSTOM_SKIN_PREFIX == "> custom_skin: "
        assert (limits.FORUM_TITLE_MIN, limits.FORUM_TITLE_MAX) == (4, 30)

    def test_placeholders_e_volumes(self):
        assert limits.VOICE_PLACEHOLDERS == (
            "{track.title}",
            "{track.timestamp}",
            "{track.emoji}",
            "{track.author}",
            "{track.duration}",
            "{track.source}",
            "{track.playlist}",
            "{requester.name}",
            "{requester.id}",
        )
        assert limits.VOLUMES == (
            *(5, 10, 15, 20, 25, 30, 35, 40, 45, 50, 55, 60, 65, 70, 75, 80, 85, 90, 95, 100),
            *(110, 120, 130, 140, 150),
        )


class TestTexto:
    @pytest.mark.parametrize("valor", [None, 123, b"ab", ["ab"], {"a": 1}])
    def test_clean_title_so_aceita_texto(self, valor):
        assert text.clean_title(valor, 1, 10) is None

    @pytest.mark.parametrize(
        ("entrada", "baixo", "alto", "esperado"),
        [
            ("  ab  ", 2, 5, "ab"),
            ("a", 2, 5, None),
            (" a ", 2, 5, None),
            ("abcde", 2, 5, "abcde"),
            ("abcdef", 2, 5, None),
            ("ab​", 2, 5, None),
            ("a\x07b", 2, 5, None),
            ("a\nb", 2, 5, None),
            ("a b", 2, 5, "a b"),
        ],
    )
    def test_clean_title(self, entrada, baixo, alto, esperado):
        assert text.clean_title(entrada, baixo, alto) == esperado

    def test_clean_import_name_recusa_repetido_sem_diferenciar_a_caixa(self):
        assert text.clean_import_name("Rock", 2, 25, {}) == "Rock"
        assert text.clean_import_name("Rock", 2, 25, {"rock": 1}) is None
        assert text.clean_import_name("rock", 2, 25, {"ROCK": 1}) is None
        assert text.clean_import_name("Pop", 2, 25, {"Rock": 1}) == "Pop"
        assert text.clean_import_name(" Rock ", 2, 25, {}) == "Rock"
        assert text.clean_import_name("x", 2, 25, {}) is None

    def test_drop_same_names_tira_as_chaves_iguais_sem_diferenciar_a_caixa(self):
        entradas = {"Rock": 1, "pop": 2, "Jazz": 3}
        text.drop_same_names(entradas, ["rock", "POP"])
        assert entradas == {"Jazz": 3}
        intactas = {"Rock": 1}
        text.drop_same_names(intactas, ["Pop"])
        assert intactas == {"Rock": 1}

    @pytest.mark.parametrize(
        ("entrada", "esperado"),
        [
            ("a\nb", "a b"),
            ("a\r\nb", "a b"),
            ("a\rb", "a b"),
            ("\n  a  \n", "a"),
            ("  a  ", "a"),
            ("a\n\nb", "a  b"),
            ("", ""),
        ],
    )
    def test_normalize_status(self, entrada, esperado):
        assert text.normalize_status(entrada) == esperado


class TestUrls:
    @pytest.mark.parametrize(
        "url",
        [
            "http://exemplo.invalid/a",
            "https://exemplo.invalid/a",
            "https://exemplo.invalid/a%20b",
            "https://exemplo.invalid/a(b)!*,",
            "https://exemplo.invalid/a?x=1&y=2+3",
            "https://exemplo.invalid/a%2",
            "https://exemplo.invalid/a<b>",  # `<` e `>` fazem parte da classe: é o resíduo do A2
            "https://exemplo.invalid/@user",
            "https://exemplo.invalid/a_b-c.d",
        ],
    )
    def test_url_inteira_e_limpa(self, url):
        assert urls.URL_REG.fullmatch(url) and urls.is_clean_url(url)

    @pytest.mark.parametrize(
        "url",
        [
            "ftp://exemplo.invalid/a",
            "exemplo.invalid/a",
            "https://",
            "https://exemplo.invalid/a texto",
            "https://exemplo.invalid/a\n",
            "https://exemplo.invalid/a[b",
            "https://exemplo.invalid/a]b",
            "https://exemplo.invalid/@everyone",
            "https://exemplo.invalid/@HERE",
            "https://exemplo.invalid/a#z",
            "https://exemplo.invalid/a~",
            "https://exemplo.invalid/a{b}",
            "",
        ],
    )
    def test_url_que_nao_e_inteira_e_limpa(self, url):
        assert not urls.is_clean_url(url)

    def test_extract_url_legacy_devolve_o_primeiro_trecho_em_qualquer_posicao(self):
        assert urls.extract_url_legacy(f"veja {URL} e https://outro.invalid/b agora") == URL
        assert urls.extract_url_legacy(f"<{URL}>") == f"{URL}>"
        assert urls.extract_url_legacy("sem link") is None
        assert urls.extract_url_legacy("") is None

    def test_url_prefix_legacy_devolve_so_o_prefixo(self):
        assert urls.url_prefix_legacy(f"{URL} lixo", 100) == URL
        assert urls.url_prefix_legacy(f"{URL}]x", 100) == f"{URL}]x"
        assert urls.url_prefix_legacy(f"veja {URL}", 100) is None
        assert urls.url_prefix_legacy(URL, len(URL)) == URL
        assert urls.url_prefix_legacy(URL, len(URL) - 1) is None
        assert urls.url_prefix_legacy(None, 100) is None
        assert urls.url_prefix_legacy(123, 100) is None
        assert urls.url_prefix_legacy({"url": URL}, 100) is None

    @pytest.mark.parametrize(
        ("avatar", "esperado"),
        [
            (None, ""),
            ("", ""),
            (f"  {URL}  ", URL),
            (URL, URL),
            (f"{URL} lixo", None),
            (f"{URL}]", None),
            (f"{URL}/@everyone", None),
            (123, None),
            (["x"], None),
            ("não é link", None),
            ("   ", None),
        ],
    )
    def test_clean_avatar(self, avatar, esperado):
        assert urls.clean_avatar(avatar) == esperado

    def test_clean_avatar_limite_de_250_depois_do_strip(self):
        base = "https://exemplo.invalid/"
        no_limite = base + "x" * (250 - len(base))
        assert urls.clean_avatar(no_limite) == no_limite
        assert urls.clean_avatar(f"  {no_limite}  ") == no_limite
        assert urls.clean_avatar(no_limite + "x") is None


class TestCota:
    @pytest.mark.parametrize(
        ("maximo", "dono", "esperado"),
        [(10, False, 10), (10, True, 0), (1, False, 1), (0, False, 0), (0, True, 0), (-1, False, 0), (-5, True, 0)],
    )
    def test_quota_limit(self, maximo, dono, esperado):
        assert quota.quota_limit(maximo, dono) == esperado


class TestSkinsPermitidas:
    def test_allowed_names(self):
        assert settings.allowed_names(["a", "b", "c"], "") == ("a", "b", "c")
        assert settings.allowed_names(["a", "b", "c"], "b") == ("a", "c")
        assert settings.allowed_names(["a", "b", "c"], "a  c") == ("b",)
        assert settings.allowed_names(["a", "b"], "a b") == ()
        assert settings.allowed_names({"x": 1, "y": 2}, "x") == ("y",)
        assert settings.allowed_names(["ab"], "a") == ("ab",)


class TestPontosDeUsoDasRegras:
    @pytest.mark.asyncio
    async def test_painel_aceita_url_de_favorito_de_exatamente_10_caracteres(self):
        curta = "http://a.b"
        assert len(curta) == limits.FAV_URL_MIN
        aceito = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome="novo", url=curta)
        recusado = await painel_favoritos(BotDoPainel(), "favorito_adicionar", {}, nome="novo", url="http://a.")
        assert aceito.errors == {} and aceito.new["fav_links"]["novo"] == curta
        assert recusado.errors.get("url")

    @pytest.mark.asyncio
    async def test_painel_nao_recarrega_skin_personalizada_e_recarrega_a_normal(self):
        chamadas = []

        async def destruir():
            chamadas.append("destruir")

        async def invocar(**kwargs):
            chamadas.append("invocar")

        def nada(*args, **kwargs):
            chamadas.append("ajuste")

        player = SimpleNamespace(
            static=False,
            skin="classic",
            skin_static="simple",
            destroy_message=destruir,
            invoke_np=invocar,
            setup_features=nada,
            setup_hints=nada,
            process_hint=nada,
            set_command_log=nada,
        )
        await reload_skin(player, "> custom_skin: minha", "simple", "texto")
        assert chamadas == [] and player.skin == "classic"
        await reload_skin(player, "modern", "simple", "texto")
        assert player.skin == "modern" and "destruir" in chamadas and "invocar" in chamadas
