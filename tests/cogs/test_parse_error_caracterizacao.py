"""KI-27 — caracterização de `errors.parse_error` e dos auxiliares de código de erro (`empiremuse/utils/music/errors.py`).

Fixa o texto mostrado ao usuário para cada tipo de erro conhecido, o tratamento de `.original` e o contrato de log.
"""

import logging
from types import SimpleNamespace
from unittest.mock import MagicMock

import disnake
import pytest
from disnake.ext import commands

from empiremuse.utils.music import errors
from empiremuse.wavelink import MissingSessionID, TrackNotFound, WavelinkException

CTX = SimpleNamespace(author=SimpleNamespace(mention="<@1>", voice=None))


def parse(error, ctx=CTX, **kwargs):
    return errors.parse_error(ctx, error, **kwargs)


def text(error, ctx=CTX):
    return parse(error, ctx)[0]


class TestKnownErrors:
    @pytest.mark.parametrize(
        ("error", "fragment"),
        [
            (errors.NotDJorStaff(), "lista de DJ"),
            (commands.NotOwner(), "desenvolvedor"),
            (errors.NotRequester(), "pular músicas"),
            (errors.DiffVoiceChannel(), "meu canal de voz"),
            (errors.NoSource(), "Não há músicas"),
            (errors.NoVoice(), "entrar em um canal de voz"),
            (errors.MissingSpotifyClient(), "spotify"),
            (commands.NoPrivateMessage(), "mensagens privadas"),
            (TrackNotFound(), "Não houve resultados"),
            (errors.YoutubeSourceDisabled(), "youtube está desativado"),
        ],
    )
    def test_message(self, error, fragment):
        assert fragment in text(error)

    def test_missing_voice_perms_names_the_channel(self):
        channel = SimpleNamespace(mention="<#5>")
        assert "<#5>" in text(errors.MissingVoicePerms(channel))

    def test_bot_missing_permissions_are_translated(self):
        out = text(commands.BotMissingPermissions(["manage_messages"]))
        assert "Não tenho as seguintes permissões" in out and "Gerenciar Mensagens" in out

    def test_user_missing_permissions_are_translated(self):
        out = text(commands.MissingPermissions(["administrator"]))
        assert "Você não possui" in out and "Administrador" in out

    def test_unknown_permission_name_is_kept_as_is(self):
        assert "permissao_inexistente" in text(commands.MissingPermissions(["permissao_inexistente"]))

    def test_missing_session_id_names_the_node(self):
        assert "no-1" in text(MissingSessionID(SimpleNamespace(identifier="no-1")))


class TestNoPlayer:
    def test_with_voice_channel_mentions_it(self):
        ctx = SimpleNamespace(author=SimpleNamespace(voice=SimpleNamespace(channel=SimpleNamespace(mention="<#9>"))))
        assert "<#9>" in text(errors.NoPlayer(), ctx)

    def test_without_voice_uses_the_generic_text(self):
        assert "player inicializado" in text(errors.NoPlayer())


class TestGenericError:
    def test_text_components_and_full_traceback(self):
        components = [object()]
        out, full, kill, comps, mention = parse(errors.GenericError("**ops**", components=components))
        assert out == "**ops**" and comps is components
        assert "GenericError" in full  # send_error: traceback completo vai ao log, não ao usuário
        assert kill is False and mention is False

    def test_empty_text_is_treated_as_unknown(self, capsys):
        out, full, *_ = parse(errors.GenericError(""))
        assert not out and "GenericError" in full
        assert "GenericError" in capsys.readouterr().out

    def test_str_and_repr_escape_markdown(self):
        error = errors.GenericError("*negrito*")
        assert str(error) == repr(error) == disnake.utils.escape_markdown("*negrito*")


class TestUnwrapping:
    def test_original_error_is_unwrapped(self):
        wrapped = SimpleNamespace(original=errors.NoSource())
        assert "Não há músicas" in text(wrapped)


class TestUsage:
    def ctx(self, usage):
        command = SimpleNamespace(usage=usage, name="play", full_parent_name="")
        return SimpleNamespace(command=command, prefix="!", me=SimpleNamespace(id=1, display_name="Bot"))

    def test_usage_is_expanded_with_prefix_and_command(self):
        out = text(commands.UserInputError("x"), self.ctx("{prefix}{cmd} [música]"))
        assert "!play [música]" in out and "Como Usar" in out

    def test_mention_prefix_uses_the_display_name(self):
        ctx = self.ctx("{prefix}{cmd}")
        ctx.prefix = "<@1> "
        assert "@Bot play" in text(commands.MissingRequiredArgument(MagicMock()), ctx)

    def test_command_without_usage_is_not_explained(self, capsys):
        assert text(commands.UserInputError("x"), self.ctx(None)) is None


class TestCooldownAndConcurrency:
    def test_cooldown_shows_the_remaining_time(self):
        error = commands.CommandOnCooldown(commands.Cooldown(1, 30), 12.4, commands.BucketType.user)
        assert "aguardar" in text(error)

    def test_cooldown_never_shows_zero_seconds(self):
        error = commands.CommandOnCooldown(commands.Cooldown(1, 30), 0.2, commands.BucketType.user)
        assert "1 segundo" in text(error)

    @pytest.mark.parametrize(
        ("bucket", "fragment"),
        [
            (commands.BucketType.member, "no servidor"),
            (commands.BucketType.guild, "no servidor"),
            (commands.BucketType.user, "você já usou"),
            (commands.BucketType.channel, "no canal atual"),
            (commands.BucketType.category, "na categoria"),
            (commands.BucketType.role, "cargo permitido"),
            (commands.BucketType.default, "por alguém"),
        ],
    )
    def test_max_concurrency_per_bucket(self, bucket, fragment):
        out = text(commands.MaxConcurrencyReached(1, bucket))
        assert fragment in out and "<@1>" in out

    def test_max_concurrency_pluralises_for_more_than_one_use(self):
        out = text(commands.MaxConcurrencyReached(2, commands.BucketType.user))
        assert "2 vezes" in out and "usos finalizados" in out


class TestEmptyFavIntegration:
    def test_button_interaction_asks_to_register_one(self):
        ctx = MagicMock(spec=disnake.MessageInteraction)
        out, _, _, components, mention = parse(errors.EmptyFavIntegration(), ctx)
        assert "Você não possui favorito/integração" in out
        assert components[0].custom_id == "musicplayer_fav_manager" and mention is True

    def test_command_variant_has_its_own_text(self):
        out, _, _, components, mention = parse(errors.EmptyFavIntegration())
        assert "sem incluir um nome ou link" in out and mention is True and components


class TestWavelinkErrors:
    @pytest.mark.parametrize(
        ("raw", "fragment"),
        [
            ("Unknown file format", "Não há suporte para o link especificado"),
            ("No supported audio format", "Não há suporte para o link informado"),
            ("This video is not available", "indisponível ou privado"),
            ("This playlist type is unviewable", "parâmetro/id não suportado"),
            ("The playlist does not exist", "não existe"),
            ("not made this video available in your country", "região"),
            ("Who has blocked it in your country on copyright grounds", "região"),
        ],
    )
    def test_known_lavalink_messages(self, raw, fragment):
        assert fragment in text(WavelinkException(raw))

    def test_unknown_lavalink_message_is_logged_not_shown(self, capsys):
        out, full, *_ = parse(WavelinkException("falha estranha"))
        assert out is None and "falha estranha" in full
        assert "falha estranha" in capsys.readouterr().out

    def test_no_log_flag_silences_the_print(self, capsys):
        parse(WavelinkException("falha estranha"), no_log=True)
        assert capsys.readouterr().out == ""


class TestErrorCodeHelpers:
    def test_error_code_text(self):
        assert "ERR-1" in errors.error_code_text("ERR-1")
        assert errors.error_code_text("") == ""

    def test_code_suffix(self):
        assert errors.code_suffix("ERR-1") == " (código do erro: `ERR-1`)"
        assert errors.code_suffix("") == ""

    def test_log_unexpected_error_logs_with_traceback_and_returns_the_code(self, caplog, monkeypatch):
        monkeypatch.setattr(errors, "safe_error_code", lambda: "ERR-ABC")
        log = logging.getLogger("teste.parse_error")
        try:
            raise ValueError("interno")
        except ValueError as exc:
            with caplog.at_level(logging.ERROR, logger=log.name):
                code = errors.log_unexpected_error(log, exc, "uma operação")
        assert code == "ERR-ABC"
        record = caplog.records[-1]
        assert "uma operação" in record.getMessage() and "[ERR-ABC]" in record.getMessage()
        assert record.exc_info[0] is ValueError

    def test_log_unexpected_error_unwraps_the_original(self, caplog, monkeypatch):
        monkeypatch.setattr(errors, "safe_error_code", lambda: "")
        inner = KeyError("k")
        wrapped = SimpleNamespace(original=inner, __traceback__=None)
        with caplog.at_level(logging.ERROR):
            assert errors.log_unexpected_error(logging.getLogger("teste.parse_error"), wrapped, "x") == ""
        assert caplog.records[-1].exc_info[0] is KeyError


def test_argument_parsing_error_escapes_mentions():
    assert "@everyone" not in str(errors.ArgumentParsingError("oi @everyone"))
