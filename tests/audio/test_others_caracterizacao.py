"""KI-27 — caracterização de `empiremuse/utils/others.py` (utilitários de comandos: contexto, paginação, emojis de fonte, fila).

Fixa o comportamento atual, sem mudar produção. Sem Discord real: dublês (SimpleNamespace / MagicMock / AsyncMock).
"""

import argparse
import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import disnake
import pytest
from disnake.ext import commands

from empiremuse.utils import others
from empiremuse.utils.music.errors import ArgumentParsingError


def run(coro):
    return asyncio.run(coro)


# ============================================================================ funções puras


class TestSmallHelpers:
    def test_chunk_list(self):
        assert others.chunk_list([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]
        assert others.chunk_list([], 3) == []

    def test_string_to_file_from_dict_is_indented_json_without_ascii_escapes(self):
        arquivo = others.string_to_file({"nome": "é"})
        conteudo = arquivo.fp.read().decode("utf-8")
        assert json.loads(conteudo) == {"nome": "é"} and "é" in conteudo and "\n" in conteudo
        assert arquivo.filename == "result.txt"

    def test_pool_command_defaults(self):
        async def cmd(ctx):
            pass

        comando = others.PoolCommand(cmd)
        assert (comando.pool_return_first, comando.pool_only_voiced, comando.pool_check_player) == (False, False, True)


class TestSortDictRecursively:
    def test_sorts_nested_lists_of_scalars_and_dicts(self):
        dados = {"b": [3, 1, 2], "a": [{"z": 1, "a": 2}, {"a": 1}]}
        ordenado = others.sort_dict_recursively(dados)
        assert ordenado == {"b": [1, 2, 3], "a": [{"a": 1}, {"z": 1, "a": 2}]}

    def test_unsortable_list_keeps_its_order(self):
        assert others.sort_dict_recursively([1, "a", 2]) == [1, "a", 2]


class TestPaginator:
    def test_a_single_huge_line_is_cut_into_pieces(self):
        paginas = others.paginator("y" * 500, max_size=100)
        assert len(paginas) >= 5 and "".join(p.strip("\n") for p in paginas) == "y" * 500


# ============================================================================ emojis e fontes de música


class TestMusicSourceEmoji:
    def test_known_and_unknown_names(self):
        assert others.music_source_emoji("spotify") == "🟢"
        assert others.music_source_emoji("desconhecida") == "▶️"

    @pytest.mark.parametrize(
        ("url", "source"),
        [
            ("https://www.youtube.com/watch?v=x", "youtube"),
            ("https://youtu.be/x", "youtube"),
            ("https://soundcloud.com/a/b", "soundcloud"),
            ("https://open.spotify.com/track/x", "spotify"),
            ("https://www.deezer.com/br/track/123", "deezer"),
            ("https://www.twitch.tv/canal_legal", "twitch"),
            ("https://music.apple.com/br/album/x/123", "applemusic"),
            ("https://www.jiosaavn.com/song/x", None),
        ],
    )
    def test_music_source_emoji_url(self, url, source):
        emoji, nome = others.music_source_emoji_url(url)
        if source is None:
            assert (emoji, nome) == ("▶️", "Plat. Desconhecida")
        else:
            assert (emoji, nome) == (others.music_source_emoji_data[source], source)

    def test_saved_queue_marker(self):
        assert others.music_source_emoji_url(">> saved_queue <<") == ("💾", "")

    @pytest.mark.parametrize(
        ("id_", "source"),
        [
            ("【YT】: música", "youtube"),
            ("> fav: 【SC】: x", "soundcloud"),
            ("> itg: 【SP】: x", "spotify"),
            ("> svq: 【DZ】: x", "deezer"),
        ],
    )
    def test_music_source_emoji_id(self, id_, source):
        assert others.music_source_emoji_id(id_) == others.music_source_emoji_data[source]

    def test_music_source_emoji_id_unknown(self):
        assert others.music_source_emoji_id("> fav: qualquer coisa") == "▶️"


class TestGetSourceEmojiCfg:
    def bot(self, data):
        return SimpleNamespace(pool=SimpleNamespace(emoji_data=data))

    @pytest.mark.parametrize(
        ("url", "source"),
        [
            ("https://youtu.be/x", "youtube"),
            ("https://soundcloud.com/a/b", "soundcloud"),
            ("https://open.spotify.com/track/x", "spotify"),
            ("https://www.deezer.com/br/track/123", "deezer"),
            ("https://www.twitch.tv/canal_legal", "twitch"),
            ("https://music.apple.com/br/album/x/123", "applemusic"),
            ("https://www.jiosaavn.com/song/x-1", "jiosaavn"),
            ("https://listen.tidal.com/track/1", "tidal"),
            ("http://www.tidal.com/track/1", "tidal"),
        ],
    )
    def test_each_source_reads_its_configured_emoji(self, url, source):
        bot = self.bot({"music_sources": {source: f"<:{source}:1>"}})
        assert others.get_source_emoji_cfg(bot, url) == f"<:{source}:1>"

    def test_unknown_url_has_no_emoji(self):
        assert others.get_source_emoji_cfg(self.bot({}), "https://exemplo.test") is None

    def test_missing_configuration_returns_none(self):
        assert others.get_source_emoji_cfg(self.bot({}), "https://youtu.be/x") is None


# ============================================================================ listas de autocompletar


class TestAutocompleteLists:
    def inter(self, user_data=None, guild_data=None):
        bot = SimpleNamespace(
            get_global_data=AsyncMock(return_value=user_data), get_data=AsyncMock(return_value=guild_data)
        )
        return SimpleNamespace(bot=bot, author=SimpleNamespace(id=1), guild=SimpleNamespace(id=2))

    def test_fav_list_integrations_then_favorites_sorted_and_filtered(self):
        inter = self.inter({"integration_links": {"zeta": 1, "alfa": 1}, "fav_links": {"rock": 1, "Pop": 1}})
        assert run(others.fav_list(inter, "")) == ["> itg: alfa", "> itg: zeta", "> fav: Pop", "> fav: rock"]
        assert run(others.fav_list(inter, "RO")) == ["> fav: rock"]

    def test_fav_list_returns_only_integrations_when_there_are_more_than_twenty(self):
        inter = self.inter({"integration_links": {f"i{n:02}": 1 for n in range(21)}, "fav_links": {"f": 1}})
        resultado = run(others.fav_list(inter, ""))
        assert len(resultado) == 21 and all(r.startswith("> itg: ") for r in resultado)

    def test_pin_list_filters_prefixes_and_caps(self):
        pins = {f"pin{n:02}": 1 for n in range(30)}
        inter = self.inter(guild_data={"player_controller": {"fav_links": pins}})
        resultado = run(others.pin_list(inter, "", prefix="> pin: "))
        assert len(resultado) == 20 and resultado[0].startswith("> pin: pin")
        assert run(others.pin_list(inter, "PIN07")) == ["pin07"]


# ============================================================================ fila


def track(title, unique_id):
    return SimpleNamespace(title=title, unique_id=unique_id)


class TestQueueTrackIndex:
    def setup_method(self):
        self.player = SimpleNamespace(
            queue=[track("Imagine Dragons - Believer", "a"), track("Queen - Bohemian Rhapsody", "b")],
            queue_autoplay=[track("Queen - Under Pressure", "c")],
        )
        self.bot = SimpleNamespace(music=SimpleNamespace(players={1: self.player}))
        self.inter = SimpleNamespace(guild_id=1)

    def find(self, query, **kwargs):
        return others.queue_track_index(self.inter, self.bot, query, **kwargs)

    def test_substring_match_per_word(self):
        resultado = self.find("queen bohem")
        assert [(i, t.unique_id) for i, t in resultado] == [(1, "b")]

    def test_unique_id_returns_exactly_that_track(self):
        assert [(i, t.unique_id) for i, t in self.find("qualquer || ID > c")] == [(2, "c")]

    def test_case_sensitive_mode_compares_word_by_word_from_the_start(self):
        assert [t.unique_id for _, t in self.find("queen -", case_sensitive=True, match_count=5)] == ["b", "c"]


# ============================================================================ argparse, interações e paginador


class TestCommandArgparse:
    def make(self):
        parser = others.CommandArgparse()
        parser.add_argument("-n", "--nome", default="x")
        parser.add_argument("-f", "--flag", action="store_true")
        return parser

    def test_error_hook_raises_argument_parsing_error(self):
        with pytest.raises(ArgumentParsingError):
            others.CommandArgparse().error("falhou")

    def test_missing_required_argument_raises_argument_error(self):
        parser = others.CommandArgparse()
        parser.add_argument("-n", "--nome", required=True)
        with pytest.raises(argparse.ArgumentError):
            parser.parse_known_args([])

    def test_ignored_explicit_argument_is_retried_without_the_first_dash(self):
        # "--flag=algo" é recusado (flag não aceita valor); a nova tentativa vira "-flag=algo", lido como -f + resto
        namespace, extras = self.make().parse_known_args(["--flag=algo"])
        assert namespace.flag is True and extras == ["-lag=algo"]


class TestUpdateInter:
    def test_none_is_ignored(self):
        old = SimpleNamespace(token="a")
        others.update_inter(old, None)
        assert old.token == "a"

    def test_new_without_response_is_tolerated(self):
        old = SimpleNamespace(token="a", id=1)
        others.update_inter(old, SimpleNamespace(token="b", id=2))
        assert old.token == "b"

    def test_custom_context_receives_the_new_interaction(self):
        old = others.CustomContext.__new__(others.CustomContext)
        new = SimpleNamespace(token="b", id=2)
        others.update_inter(old, new)
        assert old.inter is new


class TestEmbedPaginator:
    """`disnake.ui.View` exige um loop em execução: cada cenário roda dentro de uma corrotina."""

    @staticmethod
    def scenario(body, pages=3):
        async def main():
            ctx = SimpleNamespace(author=SimpleNamespace(mention="<@1>"))
            view = others.EmbedPaginator(ctx, [disnake.Embed(title=str(n)) for n in range(pages)])
            return await body(view, ctx)

        return run(main())

    @staticmethod
    def interaction(author):
        return SimpleNamespace(
            author=author,
            send=AsyncMock(),
            message=SimpleNamespace(delete=AsyncMock()),
            response=SimpleNamespace(edit_message=AsyncMock()),
        )

    def test_only_the_author_can_use_the_buttons(self):
        async def body(view, ctx):
            intruso = self.interaction(SimpleNamespace(mention="<@2>"))
            assert await view.interaction_check(intruso) is False
            intruso.send.assert_awaited_once()
            assert await view.interaction_check(self.interaction(ctx.author)) is True

        self.scenario(body)

    def test_next_wraps_around_to_the_first_page(self):
        async def body(view, ctx):
            inter = self.interaction(ctx.author)
            await view.next.callback(inter)
            assert view.current == 1
            await view.next.callback(inter)
            assert view.current == 0
            assert inter.response.edit_message.await_args.kwargs["embed"].title == "0"

        self.scenario(body, pages=2)

    def test_back_wraps_around_to_the_last_page(self):
        async def body(view, ctx):
            inter = self.interaction(ctx.author)
            await view.back.callback(inter)
            assert view.current == 2
            await view.back.callback(inter)
            assert view.current == 1

        self.scenario(body)

    def test_close_deletes_the_message_and_stops(self):
        async def body(view, ctx):
            inter = self.interaction(ctx.author)
            await view.close.callback(inter)
            inter.message.delete.assert_awaited_once()
            assert view.is_finished()

        self.scenario(body)

    def test_timeout_deletes_the_message_and_tolerates_failures(self):
        async def body(view, ctx):
            view.message = SimpleNamespace(delete=AsyncMock(side_effect=RuntimeError("já apagada")))
            await view.on_timeout()
            assert view.is_finished()

        self.scenario(body)


# ============================================================================ CustomContext


def make_context(config=None, permissions=None, author_id=1, bot_id=99):
    channel = MagicMock()
    channel.id = 5
    channel.permissions_for.return_value = permissions or SimpleNamespace(
        send_messages=True, add_reactions=True, read_message_history=True
    )
    message = MagicMock()
    message.guild.id = 7
    message.guild.me = object()
    message.channel = channel
    message.author = SimpleNamespace(id=author_id, mention=f"<@{author_id}>")
    bot = SimpleNamespace(config=config or {"ENABLE_DEFER_TYPING": False}, user=SimpleNamespace(id=bot_id))
    ctx = others.CustomContext(prefix="!", view=MagicMock(), bot=bot, message=message)
    return ctx, message


class TestCustomContext:
    def test_init_exposes_interaction_like_attributes(self):
        ctx, _ = make_context()
        assert (ctx.guild_id, ctx.channel_id) == (7, 5)
        assert ctx.user is ctx.author and ctx.application_command is None and ctx.store_message is None
        assert ctx.response.is_done() is False and ctx.response.defer == ctx.defer

    def test_ephemeral_defer_does_nothing(self):
        ctx, message = make_context()
        message.add_reaction = AsyncMock()
        run(ctx.defer(ephemeral=True))
        message.add_reaction.assert_not_awaited()

    def test_defer_reacts_with_an_hourglass(self):
        ctx, message = make_context()
        message.add_reaction = AsyncMock()
        run(ctx.defer())
        message.add_reaction.assert_awaited_once_with("⌛")

    def test_defer_types_when_configured(self):
        ctx, _ = make_context(config={"ENABLE_DEFER_TYPING": True})
        ctx.trigger_typing = AsyncMock()
        run(ctx.defer())
        ctx.trigger_typing.assert_awaited_once()

    def test_send_drops_interaction_only_arguments(self, monkeypatch):
        spy = AsyncMock(return_value="enviada")
        monkeypatch.setattr(commands.Context, "send", spy)
        ctx, _ = make_context()
        assert run(ctx.send("oi", ephemeral=True, fail_if_not_exists=False, view=None, embed="e")) == "enviada"
        assert spy.await_args.kwargs == {"content": "oi", "embed": "e"}

    def test_send_keeps_a_real_view(self, monkeypatch):
        spy = AsyncMock()
        monkeypatch.setattr(commands.Context, "send", spy)
        ctx, _ = make_context()
        run(ctx.send("oi", view="v"))
        assert spy.await_args.kwargs["view"] == "v"

    def test_reply_without_history_permission_sends_with_a_mention(self, monkeypatch):
        sent = AsyncMock()
        monkeypatch.setattr(commands.Context, "send", sent)
        ctx, _ = make_context(permissions=SimpleNamespace(read_message_history=False))
        run(ctx.reply("texto", ephemeral=True))
        assert sent.await_args.kwargs["content"] == "<@1>. texto"

    def test_reply_uses_discord_reply_when_it_can(self, monkeypatch):
        reply = AsyncMock(return_value="resp")
        monkeypatch.setattr(commands.Context, "reply", reply)
        ctx, _ = make_context()
        assert run(ctx.reply("texto", view=None)) == "resp"
        assert reply.await_args.kwargs == {"fail_if_not_exists": False, "content": "texto"}

    def test_reply_to_the_bots_own_command_adds_the_mention(self, monkeypatch):
        reply = AsyncMock()
        monkeypatch.setattr(commands.Context, "reply", reply)
        ctx, _ = make_context(author_id=99, bot_id=99)
        run(ctx.reply("texto"))
        assert reply.await_args.kwargs["content"] == "<@99>. texto"


# ============================================================================ check_cmd / send_message


class TestCheckCmd:
    def cmd(self, checks=(), cooldown=False, retry_after=None):
        bucket = SimpleNamespace(update_rate_limit=lambda: retry_after)
        buckets = SimpleNamespace(_cooldown=cooldown, get_bucket=lambda inter: bucket, type=commands.BucketType.user)
        return SimpleNamespace(checks=list(checks), _buckets=buckets, can_run=AsyncMock())

    def test_custom_context_uses_can_run(self):
        cmd = self.cmd()
        ctx = others.CustomContext.__new__(others.CustomContext)
        run(others.check_cmd(cmd, ctx))
        cmd.can_run.assert_awaited_once_with(ctx)

    def test_a_falsy_check_raises_check_failure(self):
        with pytest.raises(commands.CheckFailure):
            run(others.check_cmd(self.cmd([lambda inter: False]), SimpleNamespace()))

    def test_cooldown_hit_raises(self):
        with pytest.raises(commands.CommandOnCooldown):
            run(others.check_cmd(self.cmd(cooldown=True, retry_after=3.0), SimpleNamespace()))

    def test_cooldown_not_hit_passes(self):
        run(others.check_cmd(self.cmd(cooldown=True, retry_after=None), SimpleNamespace()))


class TestSendMessage:
    def inter(self, **kwargs):
        base = dict(
            bot=SimpleNamespace(user=SimpleNamespace(id=9)),
            channel=SimpleNamespace(),
            response=SimpleNamespace(is_done=lambda: False, edit_message=AsyncMock()),
            edit_original_message=AsyncMock(),
            send=AsyncMock(),
        )
        base.update(kwargs)
        return SimpleNamespace(**base)

    def test_self_mod_interaction_edits_the_response(self):
        inter = self.inter(self_mod=True)
        run(others.send_message(inter, "oi", view=None, components=None))
        inter.response.edit_message.assert_awaited_once_with(content="oi", components=[])

    def test_self_mod_after_response_edits_the_original_message(self):
        inter = self.inter(self_mod=True, response=SimpleNamespace(is_done=lambda: True))
        run(others.send_message(inter, "oi"))
        inter.edit_original_message.assert_awaited_once_with(content="oi")

    def test_http_failure_falls_back_to_the_channel_when_allowed(self):
        channel = MagicMock(spec=disnake.TextChannel)
        channel.permissions_for.return_value = SimpleNamespace(send_messages=True)
        channel.send = AsyncMock()
        inter = self.inter(
            channel=channel,
            guild=SimpleNamespace(me=object()),
            send=AsyncMock(side_effect=disnake.InteractionTimedOut(MagicMock())),
        )
        run(others.send_message(inter, "oi"))
        channel.send.assert_awaited_once_with("oi")

    def test_http_failure_without_permission_gives_up_silently(self):
        channel = MagicMock(spec=disnake.TextChannel)
        channel.permissions_for.return_value = SimpleNamespace(send_messages=False)
        channel.send = AsyncMock()
        inter = self.inter(
            channel=channel,
            guild=SimpleNamespace(me=object()),
            send=AsyncMock(side_effect=disnake.InteractionTimedOut(MagicMock())),
        )
        run(others.send_message(inter, "oi"))
        channel.send.assert_not_awaited()

    def test_http_failure_in_a_thread_checks_the_parent_permission(self):
        thread = MagicMock(spec=disnake.Thread)
        thread.parent.permissions_for.return_value = SimpleNamespace(send_messages_in_threads=True)
        thread.send = AsyncMock()
        inter = self.inter(
            channel=thread,
            guild=SimpleNamespace(me=object()),
            send=AsyncMock(side_effect=disnake.InteractionTimedOut(MagicMock())),
        )
        run(others.send_message(inter, "oi"))
        thread.send.assert_awaited_once_with("oi")

    def test_http_failure_without_a_guild_gives_up(self):
        inter = self.inter(send=AsyncMock(side_effect=disnake.InteractionTimedOut(MagicMock())))
        run(others.send_message(inter, "oi"))  # AttributeError (sem guild) é engolido

    def test_archived_forum_post_owned_by_the_bot_is_unarchived(self):
        parent = MagicMock(spec=disnake.ForumChannel)
        channel = SimpleNamespace(
            parent=parent, locked=False, archived=True, owner_id=9, edit=AsyncMock(), guild=SimpleNamespace()
        )
        inter = self.inter(channel=channel)
        run(others.send_message(inter, "oi"))
        channel.edit.assert_awaited_once_with(archived=False)
        inter.send.assert_awaited_once()

    def test_locked_forum_post_is_reopened_with_manage_threads(self):
        parent = MagicMock(spec=disnake.ForumChannel)
        guild = SimpleNamespace(me=SimpleNamespace(guild_permissions=SimpleNamespace(manage_threads=True)))
        channel = SimpleNamespace(parent=parent, locked=True, archived=False, owner_id=1, edit=AsyncMock(), guild=guild)
        run(others.send_message(self.inter(channel=channel), "oi"))
        channel.edit.assert_awaited_once_with(locked=False, archived=False)
