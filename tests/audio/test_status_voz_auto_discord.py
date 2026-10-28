"""2.1.2 — o permanente no Discord (contrato I5): modal permanente (VD1/VD2), ``/setvoicestatus <modelo>`` (VD3), um valor por servidor para todos os
bots do pool (VG1), a leitura nova do documento no envio (V-S6/VG2), o embed do menu e o dado novo (I1).

Funções de produção reais (``SetStageTitle.modal_handler``, ``VoiceStatusMixin.set_voice_status``); bots, servidor e banco são dublês. O banco de dois bots
compartilha o documento GLOBAL do servidor (``get_global_data``) e mantém o documento por bot separado: gravar no lugar errado não aparece para o outro bot.
"""

import asyncio
import copy
import importlib
from types import ModuleType, SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from empiremuse.music_cog.voice_status import VoiceStatusMixin
from empiremuse.utils.db import DBModel, global_db_models, update_values
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.interactions import SetStageTitle
from tests.audio.test_status_voz_permissao import InteracaoEfemera, canal_de_voz, servidor_do_bot
from tests.support.drivers_de_regras import AUTOR, BotDeComandos, ContextoDoStatus
from tests.support.modais import SERVIDOR_DO_COMANDO as SERVIDOR
from tests.support.voz_auto import assentar

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

MODELO = "Ouvindo {track.title}"
OUTRO_MODELO = "{track.author} - {track.title}"
NOME_DA_PERMISSAO = "Definir status do canal de voz"


@pytest.fixture(autouse=True)
def _sem_espera_real(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())


def regras() -> ModuleType:
    return importlib.import_module("empiremuse.rules.voice_status")


class BotDoPool(BotDeComandos):
    """Um bot do pool: o documento GLOBAL do servidor é compartilhado; o documento por bot é só deste."""

    def __init__(self, global_compartilhado: dict[tuple[str, str], dict[str, Any]], **kw: Any) -> None:
        super().__init__(**kw)
        self._globais = global_compartilhado

    def _doc(self, id_: Any, db_name: Any, *, escopo: str) -> dict[str, Any]:
        if escopo != "global":
            return super()._doc(id_, db_name, escopo=escopo)
        chave = (str(db_name), str(id_))
        if chave not in self._globais:
            self._globais[chave] = copy.deepcopy(global_db_models[db_name])
        return self._globais[chave]


def jogador_do_bot(canal: Any, *, permitido: bool = True) -> SimpleNamespace:
    guilda = servidor_do_bot(canal, permitido=permitido)
    return SimpleNamespace(
        guild=guilda,
        stage_title_event=False,
        stage_title_template="",
        apply_permanent_voice_status=AsyncMock(),
        disable_voice_status=AsyncMock(),
        update_stage_topic=AsyncMock(),
        process_save_queue=AsyncMock(),
        set_command_log=MagicMock(),
        start_time=None,
        update=False,
    )


def pool_de(n: int, *, permissoes: list[bool] | None = None) -> tuple[list[BotDoPool], list[SimpleNamespace], dict]:
    """``n`` bots no mesmo servidor, cada um com o SEU player e canal; o primeiro é o que recebe o modal."""
    globais: dict[tuple[str, str], dict[str, Any]] = {}
    bots = [BotDoPool(globais) for _ in range(n)]
    permissoes = permissoes or [True] * n
    jogadores = []
    for i, (bot, ok) in enumerate(zip(bots, permissoes, strict=True)):
        jogador = jogador_do_bot(canal_de_voz(100 + i, permitido=ok), permitido=ok)
        bot.guilds[SERVIDOR] = jogador.guild
        bot.music.players[SERVIDOR] = jogador
        jogadores.append(jogador)
    for bot in bots:
        bot.pool.get_guild_bots = lambda _gid, todos=bots: list(todos)
    return bots, jogadores, globais


def documento_global(bot: BotDeComandos) -> dict[str, Any]:
    return bot.documento("global", DBModel.guilds, SERVIDOR)


def preparar_modal(
    bot: BotDeComandos, *, texto: str, aberto_com: dict[str, Any], autor_pode: bool = True, membro_nulo: bool = False
) -> tuple[SetStageTitle, InteracaoEfemera]:
    """A view e a interação do submit do modal permanente do ``SetStageTitle`` REAL; ``aberto_com`` é o documento do menu ao abrir."""
    guilda = bot.guilds[SERVIDOR]
    membro = SimpleNamespace(
        id=AUTOR, mention=f"<@{AUTOR}>", guild_permissions=SimpleNamespace(manage_guild=autor_pode)
    )
    guilda.get_member = lambda _uid: None if membro_nulo else membro
    view = SetStageTitle(ContextoDoStatus(), bot, guilda, copy.deepcopy(aberto_com))
    inter = InteracaoEfemera(guild_id=SERVIDOR, guild=guilda, custom_id="status_voice_channel_perm")
    inter.text_values = {"status_voice_value": texto}
    return view, inter


async def enviar_modal(
    bot: BotDeComandos, *, texto: str, aberto_com: dict[str, Any], autor_pode: bool = True, membro_nulo: bool = False
) -> InteracaoEfemera:
    view, inter = preparar_modal(
        bot, texto=texto, aberto_com=aberto_com, autor_pode=autor_pode, membro_nulo=membro_nulo
    )
    await view.modal_handler(inter)
    await assentar()  # os apply_permanent_voice_status são tarefas por player: deixa-as rodar
    return inter


def globais_gravados(bot: BotDeComandos) -> list[dict[str, Any]]:
    return [copia for escopo, _id, copia in bot.gravacoes if escopo == "global"]


# ============================================================================ I1 — o dado novo


class TestDadoNovo:
    def test_the_guild_model_has_the_new_key_on_version_1_5(self) -> None:
        modelo = global_db_models[DBModel.guilds]

        assert modelo["ver"] == 1.5
        assert modelo["voice_status_permanent"] is None and modelo["voice_channel_status"] == ""

    def test_an_old_document_migrates_to_none_and_resolves_to_on(self) -> None:
        antigo = {"ver": 1.4, "prefix": "?", "voice_channel_status": ""}

        migrado = update_values(copy.deepcopy(global_db_models[DBModel.guilds]), antigo)

        assert migrado["voice_status_permanent"] is None and migrado["prefix"] == "?"
        assert regras().resolve_voice_status(migrado).permanent is True

    def test_an_old_document_with_a_saved_template_keeps_it(self) -> None:
        migrado = update_values(
            copy.deepcopy(global_db_models[DBModel.guilds]), {"ver": 1.4, "voice_channel_status": MODELO}
        )

        assert regras().resolve_voice_status(migrado).template == MODELO


# ============================================================================ VD1 — modal permanente


class TestModalPermanente:
    async def test_a_text_turns_the_permanent_on_and_saves_the_model(self) -> None:
        (bot,), (jogador,), _ = pool_de(1)
        documento_global(bot).update({"voice_status_permanent": False, "voice_channel_status": "{track.title}"})

        await enviar_modal(bot, texto=MODELO, aberto_com=documento_global(bot))

        gravado = bot.ultimo_global
        assert (
            gravado is not None
            and gravado["voice_status_permanent"] is True
            and gravado["voice_channel_status"] == MODELO
        )

    async def test_the_same_text_as_the_saved_model_still_turns_the_permanent_on(self) -> None:
        """O modal vem preenchido com o modelo efetivo: reenviá-lo igual, com o permanente desligado, tem que ligar."""
        (bot,), _, _ = pool_de(1)
        documento_global(bot).update({"voice_status_permanent": False, "voice_channel_status": MODELO})

        await enviar_modal(bot, texto=MODELO, aberto_com=documento_global(bot))

        assert bot.ultimo_global is not None and bot.ultimo_global["voice_status_permanent"] is True

    async def test_an_empty_text_turns_the_permanent_off_and_keeps_the_model(self) -> None:
        (bot,), _, _ = pool_de(1)
        documento_global(bot).update({"voice_status_permanent": True, "voice_channel_status": MODELO})

        await enviar_modal(bot, texto="", aberto_com=documento_global(bot))

        gravado = bot.ultimo_global
        assert (
            gravado is not None
            and gravado["voice_status_permanent"] is False
            and gravado["voice_channel_status"] == MODELO
        )

    async def test_it_writes_once_and_only_for_the_guild_of_the_interaction(self) -> None:
        (bot,), _, _ = pool_de(1)

        await enviar_modal(bot, texto=MODELO, aberto_com=documento_global(bot))

        assert len(globais_gravados(bot)) == 1 and {i for e, i, _c in bot.gravacoes} == {str(SERVIDOR)}

    async def test_it_applies_the_new_permanent_to_the_player_of_every_bot_of_the_pool(self) -> None:
        bots, jogadores, _ = pool_de(3)

        await enviar_modal(bots[0], texto=MODELO, aberto_com=documento_global(bots[0]))

        for jogador in jogadores:
            jogador.apply_permanent_voice_status.assert_awaited_once()
            cfg = jogador.apply_permanent_voice_status.await_args.args[0]
            assert cfg.permanent is True and cfg.template == MODELO

    async def test_an_empty_text_applies_the_off_permanent_to_every_player(self) -> None:
        bots, jogadores, _ = pool_de(2)
        documento_global(bots[0]).update({"voice_status_permanent": True, "voice_channel_status": MODELO})

        await enviar_modal(bots[0], texto="", aberto_com=documento_global(bots[0]))

        for jogador in jogadores:
            cfg = jogador.apply_permanent_voice_status.await_args.args[0]
            assert cfg.permanent is False and cfg.template == MODELO

    async def test_the_player_never_gets_its_flag_changed_directly(self) -> None:
        bots, (jogador,), _ = pool_de(1)

        await enviar_modal(bots[0], texto=MODELO, aberto_com=documento_global(bots[0]))

        assert jogador.stage_title_event is False  # quem liga é o apply_permanent_voice_status

    async def test_a_player_without_the_permission_is_named_and_the_model_is_still_saved(self) -> None:
        bots, _, _ = pool_de(2, permissoes=[False, True])

        inter = await enviar_modal(bots[0], texto=MODELO, aberto_com=documento_global(bots[0]))

        assert "salvo, mas falta a permissão" in inter.texto and NOME_DA_PERMISSAO in inter.texto
        assert "<#100>" in inter.texto and "<#101>" not in inter.texto
        assert bots[0].ultimo_global["voice_channel_status"] == MODELO

    async def test_an_invalid_text_is_refused_and_nothing_is_saved_or_applied(self) -> None:
        bots, jogadores, _ = pool_de(1)

        inter = await enviar_modal(bots[0], texto="sem placeholder", aberto_com=documento_global(bots[0]))

        assert bots[0].gravacoes == [] and "placeholder" in inter.texto
        jogadores[0].apply_permanent_voice_status.assert_not_awaited()


# ============================================================================ VD2 — permissão no envio


class TestPermissaoNoEnvio:
    async def test_without_manage_guild_nothing_is_saved_or_applied(self) -> None:
        bots, jogadores, _ = pool_de(2)

        inter = await enviar_modal(bots[0], texto=MODELO, aberto_com=documento_global(bots[0]), autor_pode=False)

        assert bots[0].gravacoes == [] and "gerenciar servidor" in inter.texto
        for jogador in jogadores:
            jogador.apply_permanent_voice_status.assert_not_awaited()

    async def test_a_missing_member_fails_closed(self) -> None:
        bots, jogadores, _ = pool_de(1)

        await enviar_modal(bots[0], texto=MODELO, aberto_com=documento_global(bots[0]), membro_nulo=True)

        assert bots[0].gravacoes == []
        jogadores[0].apply_permanent_voice_status.assert_not_awaited()

    async def test_the_member_is_the_one_of_the_server_not_the_one_in_the_interaction(self) -> None:
        bots, _, _ = pool_de(1)
        guilda = bots[0].guilds[SERVIDOR]
        consultados: list[int] = []
        membro = SimpleNamespace(id=AUTOR, mention="<@900>", guild_permissions=SimpleNamespace(manage_guild=True))

        def get_member(uid: int) -> SimpleNamespace:
            consultados.append(uid)
            return membro

        view = SetStageTitle(ContextoDoStatus(), bots[0], guilda, copy.deepcopy(documento_global(bots[0])))
        inter = InteracaoEfemera(guild_id=SERVIDOR, guild=guilda, custom_id="status_voice_channel_perm")
        inter.author.guild_permissions = SimpleNamespace(manage_guild=True)  # a permissão "da interação" não vale
        guilda.get_member = get_member
        inter.text_values = {"status_voice_value": MODELO}

        await view.modal_handler(inter)
        await assentar()

        assert consultados == [AUTOR] and bots[0].ultimo_global is not None


# ============================================================================ VD3 — /setvoicestatus <modelo>


async def comando(template: str, *, canal: Any = None, sessao_desligada: bool = False) -> SimpleNamespace:
    canal = canal or canal_de_voz()
    guilda = servidor_do_bot(canal, permitido=True)
    jogador = jogador_do_bot(canal)
    jogador.guild = guilda
    bot = BotDeComandos()
    bot.music.players[SERVIDOR] = jogador
    bot.edit_voice_channel_status = AsyncMock()
    autor = SimpleNamespace(
        id=AUTOR, guild_permissions=SimpleNamespace(manage_guild=True), voice=SimpleNamespace(channel=canal)
    )
    canal.voice_states = {AUTOR: object()}
    guilda.get_member = lambda _uid: autor
    inter = SimpleNamespace(
        bot=bot,
        guild=guilda,
        guild_id=SERVIDOR,
        author=autor,
        response=SimpleNamespace(defer=AsyncMock()),
        edit_original_message=AsyncMock(),
    )
    erro = None
    try:
        await VoiceStatusMixin.set_voice_status.callback(self=VoiceStatusMixin(), inter=inter, template=template)
    except GenericError as e:
        erro = e.text
    return SimpleNamespace(jogador=jogador, bot=bot, erro=erro)


class TestComandoDeSessao:
    @pytest.mark.parametrize(
        "invalido",
        ["sem placeholder nenhum", "‮{track.title}", "{track.title}\x00", "{track.title}" + "x" * 500, "{foo} {bar}"],
    )
    async def test_an_invalid_model_is_refused_and_nothing_is_turned_on(self, invalido: str) -> None:
        r = await comando(invalido)

        assert r.erro is not None
        assert r.jogador.stage_title_event is False and r.jogador.stage_title_template == ""
        r.jogador.update_stage_topic.assert_not_awaited()
        r.jogador.apply_permanent_voice_status.assert_not_awaited()

    async def test_a_valid_model_is_session_only_and_writes_nothing_to_the_database(self) -> None:
        r = await comando(OUTRO_MODELO)

        assert r.erro is None
        assert r.jogador.stage_title_event is True and r.jogador.stage_title_template == OUTRO_MODELO
        assert r.bot.gravacoes == []

    async def test_a_model_with_line_breaks_is_normalised_like_the_modal(self) -> None:
        r = await comando("{track.title}\n{track.author}")

        assert r.erro is None and "\n" not in r.jogador.stage_title_template


# ============================================================================ VG1 — um valor por servidor para todo o pool


class TestPoolComUmValorSo:
    async def test_what_bot_a_saves_is_what_bot_b_reads_and_applies(self) -> None:
        bots, jogadores, _ = pool_de(2)
        a, b = bots

        await enviar_modal(a, texto=OUTRO_MODELO, aberto_com=documento_global(a))
        visto_por_b = regras().resolve_voice_status(await b.get_global_data(SERVIDOR, db_name=DBModel.guilds))

        assert (visto_por_b.permanent, visto_por_b.template) == (True, OUTRO_MODELO)
        cfg_b = jogadores[1].apply_permanent_voice_status.await_args.args[0]
        assert (cfg_b.permanent, cfg_b.template) == (True, OUTRO_MODELO)

    async def test_the_per_bot_document_is_not_the_place_where_the_status_lives(self) -> None:
        bots, _, _ = pool_de(2)

        await enviar_modal(bots[0], texto=MODELO, aberto_com=documento_global(bots[0]))

        por_bot = bots[1].documento("bot", DBModel.guilds, SERVIDOR)
        assert "voice_status_permanent" not in por_bot and por_bot.get("voice_channel_status", "") != MODELO
        assert all(escopo == "global" for escopo, _i, _c in bots[0].gravacoes)

    async def test_turning_it_off_through_bot_a_stops_bot_b(self) -> None:
        bots, jogadores, _ = pool_de(2)
        a, b = bots
        documento_global(a).update({"voice_status_permanent": True, "voice_channel_status": MODELO})

        await enviar_modal(a, texto="", aberto_com=documento_global(a))

        visto_por_b = regras().resolve_voice_status(await b.get_global_data(SERVIDOR, db_name=DBModel.guilds))
        assert visto_por_b.permanent is False
        assert jogadores[1].apply_permanent_voice_status.await_args.args[0].permanent is False


# ============================================================================ VG2 — V-S6: o painel muda algo entre abrir e enviar


class TestNaoPisaNoQueOPainelMudou:
    async def test_a_prefix_changed_by_the_panel_survives_the_modal_submit(self) -> None:
        (bot,), _, _ = pool_de(1)
        aberto = copy.deepcopy(documento_global(bot))  # o que o menu do Discord tinha ao abrir
        documento_global(bot)["prefix"] = "?"  # o painel mudou o prefixo no banco depois

        await enviar_modal(bot, texto=MODELO, aberto_com=aberto)

        gravado = bot.ultimo_global
        assert gravado["prefix"] == "?"
        assert gravado["voice_status_permanent"] is True and gravado["voice_channel_status"] == MODELO

    async def test_a_permanent_changed_by_the_panel_is_replaced_only_by_the_two_fields_of_the_modal(self) -> None:
        (bot,), _, _ = pool_de(1)
        aberto = copy.deepcopy(documento_global(bot))
        documento_global(bot).update(
            {"prefix": "%", "voice_status_permanent": False, "custom_skins": {"x": 1}, "global_skin": True}
        )

        await enviar_modal(bot, texto=MODELO, aberto_com=aberto)

        gravado = bot.ultimo_global
        assert gravado["prefix"] == "%" and gravado["custom_skins"] == {"x": 1} and gravado["global_skin"] is True
        assert gravado["voice_status_permanent"] is True and gravado["voice_channel_status"] == MODELO

    async def test_the_document_saved_is_not_the_partial_snapshot_of_the_menu(self) -> None:
        (bot,), _, _ = pool_de(1)

        await enviar_modal(bot, texto=MODELO, aberto_com={"voice_channel_status": ""})

        assert {"prefix", "custom_skins", "player_skin", "ver"} <= set(bot.ultimo_global)

    async def test_an_empty_submit_also_changes_only_the_two_fields(self) -> None:
        (bot,), _, _ = pool_de(1)
        aberto = copy.deepcopy(documento_global(bot))
        documento_global(bot).update({"prefix": "?", "voice_channel_status": MODELO, "voice_status_permanent": True})

        await enviar_modal(bot, texto="", aberto_com=aberto)

        gravado = bot.ultimo_global
        assert gravado["prefix"] == "?" and gravado["voice_status_permanent"] is False
        assert gravado["voice_channel_status"] == MODELO


# ============================================================================ o menu: embed e modal


def textos_dos_embeds(view: SetStageTitle) -> str:
    return "\n".join(f"{e.title or ''}\n{e.description or ''}" for e in view.build_embeds())


class TestMenu:
    async def test_an_old_document_shows_on_by_default_and_the_default_model_marked_as_such(self) -> None:
        view = SetStageTitle(
            ContextoDoStatus(), BotDeComandos(), SimpleNamespace(me=SimpleNamespace()), {"voice_channel_status": ""}
        )

        texto = textos_dos_embeds(view).lower()

        assert "ligado" in texto and "desligado" not in texto.replace("não desligado", "")
        assert regras().DEFAULT_VOICE_TEMPLATE.lower() in texto and "padrão" in texto

    async def test_a_permanent_saved_as_off_shows_off_and_keeps_showing_the_model(self) -> None:
        dados = {"voice_channel_status": MODELO, "voice_status_permanent": False}
        view = SetStageTitle(ContextoDoStatus(), BotDeComandos(), SimpleNamespace(me=SimpleNamespace()), dados)

        texto = textos_dos_embeds(view)

        assert "desligado" in texto.lower() and MODELO in texto

    async def test_the_menu_warns_that_the_requester_placeholders_are_public(self) -> None:
        view = SetStageTitle(
            ContextoDoStatus(), BotDeComandos(), SimpleNamespace(me=SimpleNamespace()), {"voice_channel_status": ""}
        )

        texto = textos_dos_embeds(view).lower()

        assert "público" in texto and "requester" in texto

    async def test_the_menu_explains_that_turning_it_off_only_for_the_session_comes_back(self) -> None:
        view = SetStageTitle(
            ContextoDoStatus(), BotDeComandos(), SimpleNamespace(me=SimpleNamespace()), {"voice_channel_status": ""}
        )

        texto = textos_dos_embeds(view).lower()

        assert "sessão" in texto and "reinicia" in texto and "permanente" in texto

    async def test_the_permanent_modal_opens_filled_with_the_effective_model(self) -> None:
        from tests.support.drivers_de_regras import InteracaoFalsa

        view = SetStageTitle(
            ContextoDoStatus(), BotDeComandos(), SimpleNamespace(me=SimpleNamespace()), {"voice_channel_status": ""}
        )
        inter = InteracaoFalsa(guild_id=SERVIDOR)

        await view.set_status_perm(inter)

        campo = inter.response.modais[0].components[0].children[0]
        assert campo.value == regras().DEFAULT_VOICE_TEMPLATE

    async def test_the_permanent_modal_opens_with_the_saved_model_when_there_is_one(self) -> None:
        from tests.support.drivers_de_regras import InteracaoFalsa

        view = SetStageTitle(
            ContextoDoStatus(), BotDeComandos(), SimpleNamespace(me=SimpleNamespace()), {"voice_channel_status": MODELO}
        )
        inter = InteracaoFalsa(guild_id=SERVIDOR)

        await view.set_status_perm(inter)

        assert inter.response.modais[0].components[0].children[0].value == MODELO


# ============================================================================ sessão: desligar passa por disable_voice_status


class TestSessaoDesliga:
    async def test_turning_the_session_off_with_the_temporary_modal_goes_through_disable_voice_status(self) -> None:
        (bot,), (jogador,), _ = pool_de(1)
        jogador.stage_title_event = True
        guilda = bot.guilds[SERVIDOR]
        guilda.me.voice.channel.voice_states = {AUTOR: object()}
        view = SetStageTitle(ContextoDoStatus(), bot, guilda, {"voice_channel_status": MODELO})
        inter = InteracaoEfemera(guild_id=SERVIDOR, guild=guilda, custom_id="status_voice_channel_temp")
        inter.text_values = {"status_voice_value": ""}

        await view.modal_handler(inter)

        jogador.disable_voice_status.assert_awaited_once()
        assert bot.gravacoes == []


# ============================================================================ I4 ajustado — o modal agenda o apply por player, sem esperá-lo


class TestApplyEmTarefaPorPlayer:
    async def test_the_submit_answers_while_every_apply_is_still_running(self) -> None:
        bots, jogadores, _ = pool_de(3)
        portao = asyncio.Event()
        iniciados: list[int] = []

        def preso(indice: int) -> Any:
            async def apply(cfg: Any, *, jitter: bool = False) -> None:
                iniciados.append(indice)
                await portao.wait()

            return apply

        for i, jogador in enumerate(jogadores):
            jogador.apply_permanent_voice_status = preso(i)
        view, inter = preparar_modal(bots[0], texto=MODELO, aberto_com=documento_global(bots[0]))
        envio = asyncio.ensure_future(view.modal_handler(inter))
        try:
            await assentar()

            assert envio.done(), "o modal esperou o apply em linha"
            assert "salvo" in inter.texto and bots[0].ultimo_global["voice_channel_status"] == MODELO
            assert sorted(iniciados) == [0, 1, 2], "um apply preso não pode segurar os dos outros players"
        finally:
            portao.set()
            await assentar()


# ============================================================================ gate #145 — "Usar modelo atual" e as recusas do modal de sessão


async def enviar_sessao(
    bot: BotDeComandos, *, custom_id: str, texto: str, aberto_com: dict[str, Any], autor_pode: bool = True
) -> InteracaoEfemera:
    """O modal/botão de SESSÃO do ``SetStageTitle`` REAL (``status_voice_channel_temp*``)."""
    guilda = bot.guilds[SERVIDOR]
    membro = SimpleNamespace(
        id=AUTOR, mention=f"<@{AUTOR}>", guild_permissions=SimpleNamespace(manage_guild=autor_pode)
    )
    guilda.get_member = lambda _uid: membro
    for jogador in bot.music.players.values():
        jogador.guild.get_member = lambda _uid: membro
    view = SetStageTitle(ContextoDoStatus(), bot, guilda, copy.deepcopy(aberto_com))
    inter = InteracaoEfemera(guild_id=SERVIDOR, guild=guilda, custom_id=custom_id)
    inter.text_values = {"status_voice_value": texto}
    await view.modal_handler(inter)
    await assentar()
    return inter


class TestSessaoManual:
    async def test_the_use_current_model_button_turns_the_session_on_with_the_saved_permanent_model(self) -> None:
        (bot,), (jogador,), _ = pool_de(1)
        jogador.guild.me.voice.channel.voice_states = {AUTOR: object()}
        view = SetStageTitle(
            ContextoDoStatus(),
            bot,
            bot.guilds[SERVIDOR],
            {"voice_channel_status": MODELO, "voice_status_permanent": False},
        )
        membro = SimpleNamespace(id=AUTOR, mention="<@900>", guild_permissions=SimpleNamespace(manage_guild=True))
        jogador.guild.get_member = bot.guilds[SERVIDOR].get_member = lambda _uid: membro
        inter = InteracaoEfemera(
            guild_id=SERVIDOR, guild=bot.guilds[SERVIDOR], custom_id="status_voice_channel_temp_current"
        )

        del inter.text_values  # o clique de botão não tem campos de modal: o valor vem do callback
        await view.setstatus_callback(inter)

        assert jogador.stage_title_event is True and jogador.stage_title_template == MODELO
        assert bot.gravacoes == []  # só esta sessão: o permanente não é gravado

    async def test_the_use_current_model_button_falls_back_to_the_default_model(self) -> None:
        (bot,), (jogador,), _ = pool_de(1)
        jogador.guild.me.voice.channel.voice_states = {AUTOR: object()}
        view = SetStageTitle(ContextoDoStatus(), bot, bot.guilds[SERVIDOR], {"voice_channel_status": ""})
        membro = SimpleNamespace(id=AUTOR, mention="<@900>", guild_permissions=SimpleNamespace(manage_guild=True))
        jogador.guild.get_member = bot.guilds[SERVIDOR].get_member = lambda _uid: membro
        inter = InteracaoEfemera(
            guild_id=SERVIDOR, guild=bot.guilds[SERVIDOR], custom_id="status_voice_channel_temp_current"
        )

        del inter.text_values  # o clique de botão não tem campos de modal: o valor vem do callback
        await view.setstatus_callback(inter)

        assert jogador.stage_title_template == regras().DEFAULT_VOICE_TEMPLATE

    async def test_the_session_modal_refuses_a_member_without_manage_guild(self) -> None:
        (bot,), (jogador,), _ = pool_de(1)
        jogador.guild.me.voice.channel.voice_states = {AUTOR: object()}

        inter = await enviar_sessao(
            bot, custom_id="status_voice_channel_temp", texto=MODELO, aberto_com={}, autor_pode=False
        )

        assert "gerenciar servidor" in inter.texto and jogador.stage_title_event is False


# ============================================================================ autorização da sessão: o autor tem que estar no canal de um player


def pool_com_autor(no_canal_de: int | None) -> tuple[list[BotDoPool], list[SimpleNamespace]]:
    """Dois bots no servidor; o autor (com manage_guild) está no canal do bot ``no_canal_de`` (0 ou 1) ou em nenhum (``None``)."""
    bots, jogadores, _ = pool_de(2)
    membro = SimpleNamespace(id=AUTOR, mention=f"<@{AUTOR}>", guild_permissions=SimpleNamespace(manage_guild=True))
    for i, (bot, jogador) in enumerate(zip(bots, jogadores, strict=True)):
        jogador.guild.me.voice.channel.voice_states = {AUTOR: object()} if i == no_canal_de else {}
        jogador.guild.get_member = bot.guilds[SERVIDOR].get_member = lambda _uid: membro
        jogador.stage_title_event = True  # sessão ligada com um modelo de antes: nada pode mudar sem autorização
        jogador.stage_title_template = "modelo de antes {track.title}"
    return bots, jogadores


async def usar_sessao(bot: BotDoPool, modo: str) -> InteracaoEfemera:
    """``modo``: ``texto`` (modal temporário com texto), ``vazio`` (modal temporário vazio) ou ``botao`` (Usar modelo atual)."""
    guilda = bot.guilds[SERVIDOR]
    view = SetStageTitle(ContextoDoStatus(), bot, guilda, {"voice_channel_status": MODELO})
    if modo == "botao":
        inter = InteracaoEfemera(guild_id=SERVIDOR, guild=guilda, custom_id="status_voice_channel_temp_current")
        del inter.text_values  # o clique de botão não tem campos de modal
        await view.setstatus_callback(inter)
    else:
        inter = InteracaoEfemera(guild_id=SERVIDOR, guild=guilda, custom_id="status_voice_channel_temp")
        inter.text_values = {"status_voice_value": OUTRO_MODELO if modo == "texto" else ""}
        await view.modal_handler(inter)
    await assentar()
    return inter


def intacto(jogador: SimpleNamespace) -> bool:
    return (
        jogador.stage_title_event is True
        and jogador.stage_title_template == "modelo de antes {track.title}"
        and not jogador.update_stage_topic.await_count
        and not jogador.disable_voice_status.await_count
        and not jogador.process_save_queue.await_count
        and not jogador.set_command_log.call_count
    )


MODOS = ["texto", "vazio", "botao"]


class TestSessaoSoComOAutorNoCanal:
    @pytest.mark.parametrize("modo", MODOS)
    async def test_an_author_in_no_player_channel_is_refused_and_nothing_changes(self, modo: str) -> None:
        bots, jogadores = pool_com_autor(None)

        inter = await usar_sessao(bots[0], modo)

        assert "Não estou tocando música em um canal de voz/palco" in inter.texto
        assert "sucesso" not in inter.texto
        assert all(intacto(j) for j in jogadores)
        assert bots[0].gravacoes == []

    @pytest.mark.parametrize("modo", MODOS)
    async def test_an_author_in_the_channel_of_the_second_bot_uses_the_second_player(self, modo: str) -> None:
        bots, (primeiro, segundo) = pool_com_autor(1)

        await usar_sessao(bots[0], modo)

        assert intacto(primeiro)
        assert not intacto(segundo)

    @pytest.mark.parametrize("modo", MODOS)
    async def test_an_author_in_the_channel_of_the_first_bot_uses_the_first_player(self, modo: str) -> None:
        bots, (primeiro, segundo) = pool_com_autor(0)

        await usar_sessao(bots[0], modo)

        assert not intacto(primeiro)
        assert intacto(segundo)

    async def test_the_chosen_player_gets_the_text_or_is_turned_off_through_disable(self) -> None:
        bots, (primeiro, segundo) = pool_com_autor(1)
        await usar_sessao(bots[0], "texto")
        assert segundo.stage_title_event is True and segundo.stage_title_template == OUTRO_MODELO

        bots, (primeiro, segundo) = pool_com_autor(1)
        await usar_sessao(bots[0], "vazio")
        assert segundo.disable_voice_status.await_count == 1 and primeiro.disable_voice_status.await_count == 0

    async def test_a_player_without_the_author_is_not_picked_even_when_it_comes_last_in_the_pool(self) -> None:
        bots, (primeiro, segundo) = pool_com_autor(0)

        inter = await usar_sessao(bots[0], "texto")

        assert "Não estou tocando" not in inter.texto
        assert segundo.stage_title_template == "modelo de antes {track.title}"
