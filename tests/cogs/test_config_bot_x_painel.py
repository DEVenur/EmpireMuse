"""F3-5b, etapa 0 — caracterização em VERDE das assimetrias A1 a A25 entre comandos/modais do bot e o painel.

Cada teste fixa o comportamento ATUAL, dos dois lados, chamando os callbacks reais com dublês (sem Discord real, sem
rede, sem ``.env``). Os que passam hoje e continuam passando depois da extração da etapa 1 provam que ela não mexe em
nada. Os marcados ``# MUDA (etapa N, A#)`` são invertidos pela etapa indicada; os demais devem continuar iguais.
Referência: KI-42 (docs/known-issues.md); as assimetrias estão numeradas A1 a A25.
"""

from types import SimpleNamespace

import pytest

import empiremuse.cogs.legacy_cmds as legacy_cmds
from empiremuse.utils.music import interactions
from empiremuse.panel.services.base import FormContext
from empiremuse.panel.services.general import PrefixForm, VoiceStatusForm
from empiremuse.panel.services.player import DjForm
from empiremuse.rules.limits import VOICE_STATUS_MAX_LENGTH, VOLUMES
from tests.support.modais import SERVIDOR_DO_COMANDO
from tests.cogs.test_canal_de_pedidos_setup_reset import Scenario
from tests.support.drivers_de_regras import (
    BotDeComandos,
    InteracaoFalsa,
    CargoFalso,
    GuildaFalsa,
    cargos,
    comando_de_dj,
    executar,
    opcoes_de_volume,
    status_no_comando,
    ContextoDoStatus,
)

# ============================================================================ painel: drivers diretos dos formulários


def args_de(**campos):
    return {nome: [valor] for nome, valor in campos.items()}


def prefixo_do_servidor_no_painel(texto):
    """(valor aceito ou ``None``, erro) do formulário de prefixo do servidor."""
    resultado = PrefixForm().parse(SimpleNamespace(), {"prefix": ""}, args_de(prefix=texto))
    return (None if resultado.errors else resultado.new["prefix"]), resultado.errors.get("prefix")


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
    @pytest.mark.parametrize("comando", list(COMANDOS_DE_PREFIXO)[:2])
    @pytest.mark.parametrize(("entrada", "gravado"), VALIDOS)
    async def test_comando_aceita(self, comando, entrada, gravado):
        valor, erro = await prefixo_no_comando(comando, entrada)
        assert (valor, erro) == (gravado, None)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("comando", list(COMANDOS_DE_PREFIXO)[:2])
    @pytest.mark.parametrize("entrada", ["", "   ", *INVALIDOS], ids=repr)
    async def test_comando_recusa_vazio_espaco_interno_controle_e_acima_de_cinco(self, comando, entrada):
        valor, erro = await prefixo_no_comando(comando, entrada)
        assert valor is None and erro, f"{entrada!r} deveria ser recusado"

    @pytest.mark.parametrize(("entrada", "aceito"), [*VALIDOS, ("   ", "")], ids=lambda valor: repr(valor))
    def test_painel_do_servidor_aceita(self, entrada, aceito):
        assert prefixo_do_servidor_no_painel(entrada) == (aceito, None)  # vazio = voltar ao prefixo padrão


class TestA18PrefixoDoDono:
    """Etapa 6a (D6): ``setguildprefix`` obedece à mesma regra do prefixo; os prefixos já gravados continuam."""

    ALVO = 123456789012345678

    @pytest.mark.asyncio
    @pytest.mark.parametrize("prefixo", ["x" * 50, "a\tb"], ids=repr)
    async def test_recusa_o_que_a_regra_recusa_e_nao_grava_nada(self, prefixo):
        bot = BotDeComandos(dono=True)
        bot.pool.guild_prefix_cache[self.ALVO] = "velho"
        resultado = await executar(bot, legacy_cmds.Owner.setguildprefix, self.ALVO, prefixo)
        assert resultado.recusado and bot.gravacoes == []
        assert bot.pool.guild_prefix_cache == {self.ALVO: "velho"}


# ============================================================================ A19 — status do canal de voz


def status_no_painel(texto):
    resultado = VoiceStatusForm().parse(
        SimpleNamespace(), {"voice_channel_status": ""}, args_de(voice_channel_status=texto)
    )
    return (None if resultado.errors else resultado.new["voice_channel_status"]), resultado.errors


class TestA19StatusDoCanalDeVoz:
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


# ============================================================================ A20 — volume padrão


class TestA20VolumePadrao:
    ESPERADO = set(range(5, 101, 5)) | set(range(110, 151, 10))

    @pytest.mark.asyncio
    async def test_o_select_do_comando_oferece_exatamente_o_conjunto(self):
        oferecidos, padrao = await opcoes_de_volume(100)
        assert len(oferecidos) == 25 and set(oferecidos) == self.ESPERADO and padrao == [100]

    def test_o_painel_aceita_exatamente_o_mesmo_conjunto(self):
        assert set(VOLUMES) == self.ESPERADO


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
    async def test_guarda_dados_ja_acima_de_25_continuam_e_remover_funciona(self, monkeypatch):
        existentes = cargos(TETO_DE_CARGOS_DJ + 5)
        bot = BotDeComandos()
        bot.documento("bot", "guilds", SERVIDOR_DO_COMANDO)["djroles"] = [str(c.id) for c in existentes]
        await comando_de_dj(monkeypatch, "remove_dj_role", bot, GuildaFalsa(existentes), existentes[0])
        assert len(bot.ultimo_do_bot["djroles"]) == TETO_DE_CARGOS_DJ + 4

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

    def test_o_painel_recusa_repetido_everyone_e_cargo_inexistente(self):
        existentes = cargos(3)
        guilda = GuildaFalsa(existentes)
        ctx = self.contexto_do_painel(guilda)
        ids = [str(c.id) for c in existentes]
        for enviado in ([ids[0], ids[0]], [str(guilda.default_role.id)], ["999999"], ["abc"]):
            assert DjForm().parse(ctx, {"djroles": []}, {"djroles": enviado}).errors.get("djroles"), enviado


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
    async def test_guarda_lista_vazia_avisa_e_nao_grava(self, monkeypatch):
        a = CargoFalso(1001)
        bot = BotDeComandos()
        inter = await comando_de_dj(monkeypatch, "remove_dj_role", bot, GuildaFalsa([a]), a)
        assert bot.gravacoes == [] and "Não há cargos" in inter.texto
