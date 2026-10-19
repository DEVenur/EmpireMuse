"""F3-5b, etapa 0 — caracterização em VERDE das assimetrias A1 a A25 entre comandos/modais do bot e o painel.

Cada teste fixa o comportamento ATUAL, dos dois lados, chamando os callbacks reais com dublês (sem Discord real, sem
rede, sem ``.env``). Os que passam hoje e continuam passando depois da extração da etapa 1 provam que ela não mexe em
nada. Os marcados ``# MUDA (etapa N, A#)`` são invertidos pela etapa indicada; os demais devem continuar iguais.
Referência: KI-42 (docs/known-issues.md); as assimetrias estão numeradas A1 a A25.
"""

from types import SimpleNamespace

import pytest

import empiremuse.cogs.legacy_cmds as legacy_cmds
import empiremuse.cogs.music_settings as music_settings
from empiremuse.utils.music import interactions
from empiremuse.panel.services.account_base import AccountContext
from empiremuse.panel.services.account_misc import PrefixSection
from empiremuse.panel.services.appearance import allowed_skins, allowed_static_skins
from empiremuse.panel.services.base import FormContext
from empiremuse.panel.services.channel import FORUM_TITLE_MAX, FORUM_TITLE_MIN, MSG_TITLE
from empiremuse.panel.services.general import (
    VOICE_PLACEHOLDERS,
    VOICE_STATUS_MAX_LENGTH,
    PrefixForm,
    VoiceStatusForm,
)
from empiremuse.panel.services.player import MAX_DJ_ROLES, VOLUMES, DjForm, PlayerForm
from tests.helpers_modais import SERVIDOR_DO_COMANDO
from tests.test_request_channel_characterization import Scenario, click, modal_answer
from tests.helpers_f3_5b import (
    AUTOR,
    BotDeComandos,
    InteracaoFalsa,
    CargoFalso,
    GuildaFalsa,
    cargos,
    comando_de_dj,
    executar,
    STATUS_ANTIGO,
    opcoes_de_volume,
    opcoes_do_change_skin,
    status_no_comando,
    ContextoDoStatus,
    skins_do_bot,
)

# ============================================================================ painel: drivers diretos dos formulários


def args_de(**campos):
    return {nome: [valor] for nome, valor in campos.items()}


def prefixo_do_servidor_no_painel(texto):
    """(valor aceito ou ``None``, erro) do formulário de prefixo do servidor."""
    resultado = PrefixForm().parse(SimpleNamespace(), {"prefix": ""}, args_de(prefix=texto))
    return (None if resultado.errors else resultado.new["prefix"]), resultado.errors.get("prefix")


async def prefixo_do_usuario_no_painel(texto):
    contexto = AccountContext(pool=SimpleNamespace(), bot=SimpleNamespace(), user_id=900)
    resultado = await PrefixSection().parse(contexto, {"custom_prefix": ""}, "prefixo", args_de(custom_prefix=texto))
    return (None if resultado.errors else resultado.new["custom_prefix"]), resultado.errors.get("custom_prefix")


async def prefixo_no_comando(comando, texto):
    """(valor gravado ou ``None``, texto do erro) do comando de prefixo do servidor ou do usuário."""
    bot = BotDeComandos()
    resultado = await executar(bot, comando, texto)
    if resultado.recusado:
        return None, resultado.erro
    gravado = bot.ultimo_global
    return gravado["prefix"] if "prefix" in gravado else gravado["custom_prefix"], None


COMANDOS_DE_PREFIXO = [
    pytest.param(legacy_cmds.Owner.setprefix, id="setprefix"),
    pytest.param(legacy_cmds.Owner.setuserprefix, id="setuserprefix"),
]


@pytest.fixture
def world(monkeypatch):
    return Scenario(monkeypatch)


# ============================================================================ A17, A18, A25 — prefixos


class TestA17Prefixos:
    """Etapa 6a (A17/A25, D6): regra única de prefixo no comando (servidor e pessoal), no ``setguildprefix`` do dono e
    no painel: apara as pontas; depois 1 a 5 caracteres, sem espaço em branco nem ``Cc``/``Cf``. Vazio é "redefinir"
    no painel e recusa nos comandos ``set*`` (que têm ``reset*``)."""

    VALIDOS = [
        ("ab", "ab"),
        ("a" * 5, "a" * 5),
        ("😀" * 5, "😀" * 5),
        ("?", "?"),
        ("  ab  ", "ab"),
        (" " + "a" * 5 + " ", "a" * 5),
    ]
    INVALIDOS = [
        "a b",
        "a\tb",
        "a\u200bb",
        "a\x07b",
        "a\u2028b",
        "a" * 6,
        "😀" * 6,
        " " + "a" * 6,
        "a" * 500,
    ]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("comando", COMANDOS_DE_PREFIXO)
    @pytest.mark.parametrize(("entrada", "gravado"), VALIDOS)
    async def test_comando_aceita(self, comando, entrada, gravado):
        valor, erro = await prefixo_no_comando(comando, entrada)
        assert (valor, erro) == (gravado, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("comando", COMANDOS_DE_PREFIXO)
    @pytest.mark.parametrize("entrada", ["", "   ", *INVALIDOS], ids=repr)
    async def test_comando_recusa_vazio_espaco_interno_controle_e_acima_de_cinco(self, comando, entrada):
        valor, erro = await prefixo_no_comando(comando, entrada)
        assert valor is None and erro, f"{entrada!r} deveria ser recusado"

    @pytest.mark.asyncio
    @pytest.mark.parametrize("comando", COMANDOS_DE_PREFIXO)
    async def test_a_recusa_nao_toca_no_cache_nem_no_banco(self, comando):
        bot = BotDeComandos()
        resultado = await executar(bot, comando, "a b")
        assert resultado.recusado and bot.gravacoes == [] and bot.pool.guild_prefix_cache == {}
        assert bot.pool.user_prefix_cache == {}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("comando", COMANDOS_DE_PREFIXO)
    async def test_a25_a_mensagem_de_recusa_promete_sem_espacos_e_ate_cinco_caracteres(self, comando):
        _, erro = await prefixo_no_comando(comando, "a b")
        assert "espaços" in erro and "5 caracteres" in erro

    @pytest.mark.parametrize(("entrada", "aceito"), [*VALIDOS, ("", ""), ("   ", "")], ids=lambda valor: repr(valor))
    def test_painel_do_servidor_aceita(self, entrada, aceito):
        assert prefixo_do_servidor_no_painel(entrada) == (aceito, None)  # vazio = voltar ao prefixo padrão

    @pytest.mark.parametrize("entrada", INVALIDOS, ids=repr)
    def test_painel_do_servidor_recusa(self, entrada):
        valor, erro = prefixo_do_servidor_no_painel(entrada)
        assert valor is None and erro

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("entrada", "aceito"), [*VALIDOS, ("", "")], ids=lambda valor: repr(valor))
    async def test_painel_do_usuario_aceita(self, entrada, aceito):
        assert await prefixo_do_usuario_no_painel(entrada) == (aceito, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("entrada", INVALIDOS, ids=repr)
    async def test_painel_do_usuario_recusa(self, entrada):
        valor, erro = await prefixo_do_usuario_no_painel(entrada)
        assert valor is None and erro

    @pytest.mark.asyncio
    async def test_painel_guarda_o_prefixo_aparado_no_cache_com_chave_int(self):
        pool = SimpleNamespace(guild_prefix_cache={})
        ctx = SimpleNamespace(pool=pool, guild_id=SERVIDOR_DO_COMANDO)
        resultado = PrefixForm().parse(ctx, {"prefix": ""}, args_de(prefix="  >>  "))
        await PrefixForm().effects(ctx, {"prefix": ""}, resultado.new)
        assert pool.guild_prefix_cache == {SERVIDOR_DO_COMANDO: ">>"}


class TestA18PrefixoDoDono:
    """Etapa 6a (D6): ``setguildprefix`` obedece à mesma regra do prefixo; os prefixos já gravados continuam."""

    ALVO = 123456789012345678

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("prefixo", "gravado"), [(">>", ">>"), ("  >>  ", ">>"), ("a" * 5, "a" * 5), ("😀" * 5, "😀" * 5)]
    )
    async def test_aceita_o_que_a_regra_aceita_com_strip(self, prefixo, gravado):
        bot = BotDeComandos(dono=True)
        resultado = await executar(bot, legacy_cmds.Owner.setguildprefix, self.ALVO, prefixo)
        assert not resultado.recusado and bot.ultimo_global["prefix"] == gravado
        assert bot.pool.guild_prefix_cache == {self.ALVO: gravado}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefixo", ["x" * 50, "a" * 6, "a b", "a\u200bb", "a\x07b", "a\tb"], ids=repr)
    async def test_recusa_o_que_a_regra_recusa_e_nao_grava_nada(self, prefixo):
        bot = BotDeComandos(dono=True)
        bot.pool.guild_prefix_cache[self.ALVO] = "velho"
        resultado = await executar(bot, legacy_cmds.Owner.setguildprefix, self.ALVO, prefixo)
        assert resultado.recusado and bot.gravacoes == []
        assert bot.pool.guild_prefix_cache == {self.ALVO: "velho"}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefixo", [None, "", "   "])
    async def test_guarda_sem_prefixo_ou_em_branco_remove_o_prefixo(self, prefixo):
        bot = BotDeComandos(dono=True)
        bot.documento("global", "guilds", self.ALVO)["prefix"] = "x" * 20  # gravado antes da regra
        resultado = await executar(bot, legacy_cmds.Owner.setguildprefix, self.ALVO, prefixo)
        assert not resultado.recusado
        assert bot.ultimo_global["prefix"] == "" and bot.pool.guild_prefix_cache == {self.ALVO: ""}


# ============================================================================ A19 — status do canal de voz

PLACEHOLDERS = (
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


def status_no_painel(texto):
    resultado = VoiceStatusForm().parse(
        SimpleNamespace(), {"voice_channel_status": ""}, args_de(voice_channel_status=texto)
    )
    return (None if resultado.errors else resultado.new["voice_channel_status"]), resultado.errors


class TestA19StatusDoCanalDeVoz:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("placeholder", PLACEHOLDERS)
    async def test_cada_placeholder_e_aceito_sozinho_nos_dois(self, placeholder):
        no_comando, _ = await status_no_comando(BotDeComandos(), placeholder)
        no_painel, erros = status_no_painel(placeholder)
        assert no_comando == no_painel == placeholder and erros == {}

    def test_o_painel_tem_os_mesmos_nove_placeholders(self):
        assert VOICE_PLACEHOLDERS == PLACEHOLDERS

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "texto", ["Tocando agora", "{foo}", "{track.titulo}", "track.title", "{ track.title }", "{TRACK.TITLE}"]
    )
    async def test_sem_placeholder_valido_os_dois_recusam(self, texto):
        no_comando, mensagem = await status_no_comando(BotDeComandos(), texto)
        no_painel, erros = status_no_painel(texto)
        assert no_comando is None and "placeholder válido" in mensagem
        assert no_painel is None and erros

    @pytest.mark.asyncio
    async def test_placeholder_valido_ao_lado_de_chaves_desconhecidas_e_aceito(self):
        texto = "{foo} - {track.title}"
        no_comando, _ = await status_no_comando(BotDeComandos(), texto)
        assert no_comando == status_no_painel(texto)[0] == texto

    @pytest.mark.asyncio
    async def test_vazio_desativa_nos_dois(self):
        no_comando, _ = await status_no_comando(BotDeComandos(), "")
        assert no_comando == status_no_painel("")[0] == ""

    @pytest.mark.asyncio
    async def test_quebra_de_linha_vira_espaco_e_as_pontas_sao_aparadas(self):
        texto = "\n  Agora:\n{track.title}\n"
        no_comando, _ = await status_no_comando(BotDeComandos(), texto)
        assert no_comando == status_no_painel(texto)[0] == "Agora: {track.title}"

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "texto", ["Agora:\r\n{track.title}", "Agora:\r{track.title}", "\r\n Agora:\r\n{track.title}\r"]
    )
    async def test_o_retorno_de_carro_tambem_vira_espaco_no_comando(self, texto):
        """Etapa 6a (A19): a normalização do painel (``\\r\\n``, ``\\r`` e ``\\n`` viram espaço) vale no comando."""
        no_comando, _ = await status_no_comando(BotDeComandos(), texto)
        assert no_comando == status_no_painel(texto)[0] == "Agora: {track.title}"

    @pytest.mark.asyncio
    async def test_o_limite_de_496_conta_o_texto_normalizado_no_comando_e_no_painel(self):
        """Etapa 6a (A19): o comando também mede o texto normalizado (antes só o campo do Discord limitava o bruto)."""
        assert VOICE_STATUS_MAX_LENGTH == 496
        view = interactions.SetStageTitle(
            ContextoDoStatus(), BotDeComandos(), GuildaFalsa(), {"voice_channel_status": ""}
        )
        inter = InteracaoFalsa(guild_id=SERVIDOR_DO_COMANDO)
        await view.set_status_perm(inter)
        campo = inter.response.modais[0].components[0].children[0]
        assert (campo.custom_id, campo.max_length, campo.required) == ("status_voice_value", 496, False)
        emoji = "{track.emoji}"
        no_limite = "x" * (496 - len(emoji)) + emoji
        assert status_no_painel(no_limite)[0] == no_limite
        assert status_no_painel(no_limite + "x")[0] is None
        assert status_no_painel("  " + no_limite + "  ")[0] == no_limite  # as pontas não contam
        for texto, aceito in ((no_limite, True), ("  " + no_limite + "  ", True), (no_limite + "x", False)):
            salvo, mensagem = await status_no_comando(BotDeComandos(), texto)
            assert (salvo == no_limite) is aceito, (len(texto), mensagem)
            assert aceito or (salvo is None and mensagem)

    @pytest.mark.asyncio
    async def test_a_quebra_de_linha_que_vira_espaco_nao_estoura_o_limite_no_comando(self):
        emoji = "{track.emoji}"
        miolo = "x" * (496 - len(emoji) - 3)
        texto = "a\r\n" + miolo + "\r\n" + emoji  # normalizado: 496 caracteres; bruto: 498
        salvo, _ = await status_no_comando(BotDeComandos(), texto)
        assert salvo == "a " + miolo + " " + emoji and len(salvo) == 496


# ============================================================================ A20 — volume padrão


class TestA20VolumePadrao:
    ESPERADO = set(range(5, 101, 5)) | set(range(110, 151, 10))

    @pytest.mark.asyncio
    async def test_o_select_do_comando_oferece_exatamente_o_conjunto(self):
        oferecidos, padrao = await opcoes_de_volume(100)
        assert len(oferecidos) == 25 and set(oferecidos) == self.ESPERADO and padrao == [100]

    def test_o_painel_aceita_exatamente_o_mesmo_conjunto(self):
        assert set(VOLUMES) == self.ESPERADO

    @pytest.mark.parametrize("volume", [0, 4, 6, 105, 109, 111, 155, 200])
    def test_o_painel_recusa_o_que_o_comando_nao_oferece(self, volume):
        resultado = PlayerForm().parse(SimpleNamespace(), {}, args_de(default_player_volume=str(volume)))
        assert resultado.errors.get("default_player_volume")

    @pytest.mark.parametrize("volume", [5, 100, 110, 150])
    def test_o_painel_aceita_as_pontas_do_conjunto(self, volume):
        resultado = PlayerForm().parse(SimpleNamespace(), {}, args_de(default_player_volume=str(volume)))
        assert resultado.errors == {} and resultado.new["default_player_volume"] == volume


# ============================================================================ A21, A22 — cargos de DJ


TETO_DE_CARGOS_DJ = 25


class TestA21CargosDeDj:
    @pytest.mark.asyncio
    async def test_o_comando_recusa_o_26o_cargo_com_mensagem_clara(self, monkeypatch):
        """Etapa 6b (A21/D7): o teto de 25 também vale no comando; dados já acima de 25 ficam como estão."""
        existentes = cargos(TETO_DE_CARGOS_DJ)
        novo = CargoFalso(5000)
        bot = BotDeComandos()
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = [str(c.id) for c in existentes]
        guilda = GuildaFalsa([*existentes, novo])
        inter = await comando_de_dj(monkeypatch, "add_dj_role", bot, guilda, novo)
        assert bot.gravacoes == [], "nada pode ser gravado"
        assert "25" in inter.texto and "DJ" in inter.texto
        assert len(bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"]) == TETO_DE_CARGOS_DJ

    @pytest.mark.asyncio
    async def test_o_comando_aceita_o_25o_cargo(self, monkeypatch):
        existentes = cargos(TETO_DE_CARGOS_DJ - 1)
        novo = CargoFalso(5000)
        bot = BotDeComandos()
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = [str(c.id) for c in existentes]
        await comando_de_dj(monkeypatch, "add_dj_role", bot, GuildaFalsa([*existentes, novo]), novo)
        assert len(bot.ultimo_do_bot["djroles"]) == TETO_DE_CARGOS_DJ and bot.ultimo_do_bot["djroles"][-1] == "5000"

    @pytest.mark.asyncio
    async def test_guarda_dados_ja_acima_de_25_continuam_e_remover_funciona(self, monkeypatch):
        existentes = cargos(TETO_DE_CARGOS_DJ + 5)
        bot = BotDeComandos()
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = [str(c.id) for c in existentes]
        await comando_de_dj(monkeypatch, "remove_dj_role", bot, GuildaFalsa(existentes), existentes[0])
        assert len(bot.ultimo_do_bot["djroles"]) == TETO_DE_CARGOS_DJ + 4

    @pytest.mark.asyncio
    async def test_o_repetido_e_o_everyone_seguem_recusados_com_a_lista_cheia(self, monkeypatch):
        existentes = cargos(TETO_DE_CARGOS_DJ)
        bot = BotDeComandos()
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = [str(c.id) for c in existentes]
        guilda = GuildaFalsa(existentes)
        repetido = await comando_de_dj(monkeypatch, "add_dj_role", bot, guilda, existentes[0])
        everyone = await comando_de_dj(monkeypatch, "add_dj_role", bot, guilda, guilda.default_role)
        assert bot.gravacoes == [] and "já está na lista" in repetido.texto and "não pode adicionar" in everyone.texto

    @pytest.mark.asyncio
    async def test_o_comando_recusa_everyone_e_repetido_e_guarda_ids_em_texto(self, monkeypatch):
        cargo = CargoFalso(1001)
        guilda = GuildaFalsa([cargo])
        bot = BotDeComandos()
        inter = await comando_de_dj(monkeypatch, "add_dj_role", bot, guilda, guilda.default_role)
        assert bot.gravacoes == [] and "não pode adicionar" in inter.texto
        await comando_de_dj(monkeypatch, "add_dj_role", bot, guilda, cargo)
        assert bot.ultimo_do_bot["djroles"] == ["1001"]
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = ["1001"]
        repetido = await comando_de_dj(monkeypatch, "add_dj_role", bot, guilda, cargo)
        assert "já está na lista" in repetido.texto

    def contexto_do_painel(self, guilda):
        return FormContext(pool=SimpleNamespace(), bot=SimpleNamespace(), guild=guilda, guild_id=guilda.id, user_id="1")

    def test_o_painel_aceita_25_e_recusa_26(self):
        assert MAX_DJ_ROLES == TETO_DE_CARGOS_DJ
        existentes = cargos(TETO_DE_CARGOS_DJ + 1)
        guilda = GuildaFalsa(existentes)
        ctx = self.contexto_do_painel(guilda)
        ids = [str(c.id) for c in existentes]
        aceito = DjForm().parse(ctx, {"djroles": []}, {"djroles": ids[:TETO_DE_CARGOS_DJ]})
        recusado = DjForm().parse(ctx, {"djroles": []}, {"djroles": ids})
        assert aceito.errors == {} and recusado.new == {} and recusado.errors.get("djroles")

    def test_o_painel_recusa_repetido_everyone_e_cargo_inexistente(self):
        existentes = cargos(3)
        guilda = GuildaFalsa(existentes)
        ctx = self.contexto_do_painel(guilda)
        ids = [str(c.id) for c in existentes]
        for enviado in ([ids[0], ids[0]], [str(guilda.default_role.id)], ["999999"], ["abc"]):
            assert DjForm().parse(ctx, {"djroles": []}, {"djroles": enviado}).errors.get("djroles"), enviado

    def test_o_painel_preserva_a_ordem_do_que_ja_estava_gravado(self):
        existentes = cargos(3)
        ctx = self.contexto_do_painel(GuildaFalsa(existentes))
        a, b, c = (str(cargo.id) for cargo in existentes)
        resultado = DjForm().parse(ctx, {"djroles": [b, a]}, {"djroles": [c, a, b]})
        assert resultado.new["djroles"] == [b, a, c]


class TestA22RemoverCargoDeDj:
    @pytest.mark.asyncio
    async def test_a_lista_mostrada_usa_mencao_de_cargo(self, monkeypatch):
        """Etapa 6b (A22): a lista de cargos mostra ``<@&id>`` (antes ``<#id>``, menção de CANAL)."""
        a, b, ausente = CargoFalso(1001), CargoFalso(1002), CargoFalso(1003)
        bot = BotDeComandos()
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = ["1001", "1002"]
        inter = await comando_de_dj(monkeypatch, "remove_dj_role", bot, GuildaFalsa([a, b, ausente]), ausente)
        assert "não está na lista de DJ" in inter.texto
        assert "<@&1001> <@&1002>" in inter.texto and "<#1001>" not in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_remover_cargo_existente_grava_sem_ele(self, monkeypatch):
        a, b = CargoFalso(1001), CargoFalso(1002)
        bot = BotDeComandos()
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = ["1001", "1002"]
        inter = await comando_de_dj(monkeypatch, "remove_dj_role", bot, GuildaFalsa([a, b]), a)
        assert bot.ultimo_do_bot["djroles"] == ["1002"] and "foi removido" in inter.texto

    @pytest.mark.asyncio
    async def test_guarda_lista_vazia_avisa_e_nao_grava(self, monkeypatch):
        a = CargoFalso(1001)
        bot = BotDeComandos()
        inter = await comando_de_dj(monkeypatch, "remove_dj_role", bot, GuildaFalsa([a]), a)
        assert bot.gravacoes == [] and "Não há cargos" in inter.texto


# ============================================================================ A23 — skins permitidas


class TestA23SkinsPermitidas:
    @pytest.mark.asyncio
    async def test_o_comando_oferece_as_skins_menos_as_ignoradas_e_as_personalizadas_com_prefixo(self, monkeypatch):
        bot = BotDeComandos(config={"IGNORE_SKINS": "modern ghost", "IGNORE_STATIC_SKINS": "bar"})
        skins_do_bot(
            bot,
            ["classic", "modern", "compact"],
            ["simple", "bar"],
            personalizadas=["minha"],
            personalizadas_estaticas=["fixa"],
        )
        normal, estatico, global_normal, global_estatico = await opcoes_do_change_skin(monkeypatch, bot, GuildaFalsa())
        assert normal == global_normal == ["classic", "compact", "> custom_skin: minha"]
        assert estatico == global_estatico == ["simple", "> custom_skin: fixa"]

    def test_o_painel_oferece_as_mesmas_skins_sem_as_personalizadas(self):
        bot = BotDeComandos(config={"IGNORE_SKINS": "modern ghost", "IGNORE_STATIC_SKINS": "bar"})
        skins_do_bot(bot, ["classic", "modern", "compact"], ["simple", "bar"])
        assert allowed_skins(bot) == ("classic", "compact")
        assert allowed_static_skins(bot) == ("simple",)

    @pytest.mark.asyncio
    async def test_guarda_sem_ignoradas_todas_as_skins_aparecem(self, monkeypatch):
        bot = BotDeComandos()
        skins_do_bot(bot, ["classic", "modern"], ["simple"])
        normal, estatico, *_ = await opcoes_do_change_skin(monkeypatch, bot, GuildaFalsa())
        assert normal == ["classic", "modern"] and estatico == ["simple"]
        assert allowed_skins(bot) == ("classic", "modern") and allowed_static_skins(bot) == ("simple",)


# ============================================================================ A24 — título do post de fórum


class TestA24TituloDoPostDeForum:
    """O título do post tem 4 a 30 caracteres em dois modais do bot e no painel (hoje, três literais)."""

    def test_o_painel_usa_de_4_a_30(self):
        assert (FORUM_TITLE_MIN, FORUM_TITLE_MAX) == (4, 30)
        assert "4 a 30" in MSG_TITLE

    def test_o_modal_do_argumento_de_forum_pede_de_4_a_30(self, world):
        modal_answer(world, "Pedidos do bot")
        world.setup(target=world.forum)
        campo = world.j.of("response.send_modal")[0][2]["components"][0]
        assert (campo.custom_id, campo.min_length, campo.max_length) == ("forum_title", 4, 30)

    def test_o_modal_do_forum_escolhido_na_lista_pede_de_4_a_30(self, world):
        click(world, "existing_channel_777", values=["55"], event="dropdown")
        modal_answer(world, "Pedidos do bot", custom_id="modal_778")
        world.setup()
        campo = world.j.of("response.send_modal")[0][2]["components"][0]
        assert (campo.custom_id, campo.min_length, campo.max_length) == ("forum_title", 4, 30)


class TestEfeitosDosPrefixosNoPainel:
    """Depois de gravar, o painel atualiza o cache de prefixos do pool com a chave INT, como os comandos."""

    @pytest.mark.asyncio
    async def test_prefixo_do_servidor(self):
        pool = SimpleNamespace(guild_prefix_cache={})
        ctx = SimpleNamespace(pool=pool, guild_id=SERVIDOR_DO_COMANDO)
        await PrefixForm().effects(ctx, {"prefix": ""}, {"prefix": ">>"})
        assert pool.guild_prefix_cache == {SERVIDOR_DO_COMANDO: ">>"}
        assert all(isinstance(chave, int) for chave in pool.guild_prefix_cache)

    @pytest.mark.asyncio
    async def test_prefixo_do_usuario(self):
        pool = SimpleNamespace(user_prefix_cache={})
        ctx = AccountContext(pool=pool, bot=SimpleNamespace(), user_id=AUTOR)
        await PrefixSection().effects(ctx, {"custom_prefix": ">>"})
        assert pool.user_prefix_cache == {AUTOR: ">>"}
        assert all(isinstance(chave, int) for chave in pool.user_prefix_cache)
