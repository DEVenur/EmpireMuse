"""Item 7 (P1, Gambit) — ``empiremuse.logs.redact``: B2 (redação), B3 (saneamento), B4 (redator que levanta) e B20 (teto).

Funções puras sobre texto e o ``SanitizeAndRedact`` sobre ``LogRecord`` montados à mão. Sem rede, sem relógio, sem handler.
"""

import logging
import threading
from urllib.parse import quote

import pytest

from empiremuse.logs import redact as redact_modulo
from empiremuse.logs.redact import (
    MAX_MESSAGE_CHARS,
    MAX_TRACEBACK_CHARS,
    OMITTED,
    REDACTED,
    SanitizeAndRedact,
    cap,
    configure_secrets,
    redact,
    register_secret,
    sanitize_text,
    sanitize_value,
    scrub,
)
from tests.logs.apoio import excecao, registro, token_discord, token_webhook

pytestmark = pytest.mark.critical

PONTO = "…"


def passar(record: logging.LogRecord) -> logging.LogRecord:
    assert SanitizeAndRedact().filter(record) is True
    return record


def texto_final(record: logging.LogRecord) -> str:
    return "\n".join(filter(None, [record.getMessage(), record.exc_text, record.stack_info]))


def test_constants_have_the_contract_values():
    assert REDACTED == "***"
    assert OMITTED == "[registro omitido: falha ao redigir]"
    assert MAX_MESSAGE_CHARS == 8192 and MAX_TRACEBACK_CHARS == 32768


# ============================================================================ B2 — padrões


class TestPadroes:
    def test_discord_token(self):
        token = token_discord()

        assert redact(f"login com {token} ok") == f"login com {REDACTED} ok"

    def test_webhook_token_in_the_url(self):
        token = token_webhook()

        saida = redact(f"POST https://discord.com/api/v10/webhooks/123456789012345678/{token} 204")

        assert token not in saida and "/webhooks/123456789012345678/***" in saida

    @pytest.mark.parametrize(
        ("url", "esperada"),
        [
            (
                "mongodb+srv://usuario:senha-do-banco@cluster0.exemplo.net/db",
                "mongodb+srv://***@cluster0.exemplo.net/db",
            ),
            ("mongodb://u:p@h", "mongodb://***@h"),
            ("redis://default:s3gredo-redis@cache:6379/0", "redis://***@cache:6379/0"),
            ("https://admin:hunter2-longo@exemplo.org/path", "https://***@exemplo.org/path"),
            ("http://u:p@127.0.0.1:2333/v4/info", "http://***@127.0.0.1:2333/v4/info"),
        ],
    )
    def test_credentials_in_a_url_userinfo(self, url, esperada):
        assert redact(f"conectando em {url}") == f"conectando em {esperada}"

    def test_a_url_without_credentials_is_untouched(self):
        assert redact("GET https://exemplo.org/a/b?c=1") == "GET https://exemplo.org/a/b?c=1"

    @pytest.mark.parametrize(
        "nome",
        [
            "api_key",
            "apikey",
            "api_sig",
            "sk",
            "token",
            "access_token",
            "refresh_token",
            "client_secret",
            "password",
            "key",
            "signature",
        ],
    )
    def test_secret_query_parameters(self, nome):
        saida = redact(f"GET https://ws.exemplo.org/2.0/?method=x&{nome}=VALOR-SECRETO-9&format=json")

        assert "VALOR-SECRETO-9" not in saida
        assert f"{nome}=***" in saida and "method=x" in saida and "format=json" in saida

    def test_the_lastfm_style_query_with_api_key_and_sk(self):
        saida = redact("GET /2.0/?method=track.scrobble&api_key=chave-lastfm-1&sk=sessao-lastfm-2&api_sig=assinatura3")

        assert not any(valor in saida for valor in ("chave-lastfm-1", "sessao-lastfm-2", "assinatura3"))
        assert saida.count("=***") == 3

    @pytest.mark.parametrize(
        "texto",
        [
            "{'sk': 'VALOR-SECRETO-9'}",
            '{"sk": "VALOR-SECRETO-9"}',
            '{"sessionKey": "VALOR-SECRETO-9"}',
            "{'session_key': 'VALOR-SECRETO-9'}",
            '{"refresh_token": "VALOR-SECRETO-9"}',
            '{"client_secret": "VALOR-SECRETO-9"}',
            '{"password": "VALOR-SECRETO-9"}',
            "{'api_key': 'VALOR-SECRETO-9', 'x': 1}",
            '{"SESSIONKEY": "VALOR-SECRETO-9"}',
            "{'Access_Token': 'VALOR-SECRETO-9'}",
            '{"authorization": "VALOR-SECRETO-9"}',
        ],
    )
    def test_secret_values_of_dict_and_json_keys(self, texto):
        saida = redact(texto)

        assert "VALOR-SECRETO-9" not in saida and REDACTED in saida

    def test_the_key_and_the_other_values_survive_in_a_redacted_dict(self):
        saida = redact("{'user': 'ana', 'sk': 'VALOR-SECRETO-9', 'n': 3}")

        assert "'user': 'ana'" in saida and "'sk':" in saida and "'n': 3" in saida

    @pytest.mark.parametrize(
        "texto",
        [
            "Authorization: Bot VALOR-SECRETO-9",
            "authorization: Bearer VALOR-SECRETO-9",
            "{'Authorization': 'Bot VALOR-SECRETO-9'}",
            "headers={'Content-Type': 'x', 'Authorization': 'VALOR-SECRETO-9'}",
        ],
    )
    def test_authorization_header_forms(self, texto):
        saida = redact(texto)

        assert "VALOR-SECRETO-9" not in saida and REDACTED in saida

    def test_text_without_secrets_is_untouched(self):
        texto = "Nó LOCAL conectado (v4.0.8) em 12 ms — 3 players, versão 2.1.0, faixa 1.2.3"

        assert redact(texto) == texto


# ============================================================================ B2 — valores registrados


class TestValoresRegistrados:
    def test_configure_secrets_masks_exact_values_longest_first(self):
        configure_secrets(["valor-longo-9", "valor-longo-9-e-mais"])

        assert redact("a valor-longo-9-e-mais b valor-longo-9 c") == "a *** b *** c"

    def test_configure_secrets_replaces_the_previous_base_set(self):
        configure_secrets(["primeiro-valor-1"])
        configure_secrets(["segundo-valor-2"])

        assert redact("primeiro-valor-1 segundo-valor-2") == "primeiro-valor-1 ***"

    def test_register_secret_masks_the_value_and_its_url_encoded_form(self):
        senha = "p@ss/w%rd-nó#1"
        codificada = quote(senha, safe="")
        assert codificada != senha

        register_secret(senha)

        saida = redact(f"senha={senha} url=/x?p={codificada}")
        assert senha not in saida and codificada not in saida

    def test_register_secret_of_a_value_equal_to_its_encoded_form_registers_it_once(self):
        register_secret("simples-sem-especiais-7")

        assert redact("simples-sem-especiais-7") == REDACTED

    def test_registered_values_survive_a_new_configure_secrets(self):
        register_secret("aprendido-em-runtime-3")

        configure_secrets(["do-config-4-xyz"])

        assert redact("aprendido-em-runtime-3 do-config-4-xyz") == "*** ***"

    def test_a_five_character_value_is_not_masked_by_value_r1(self):
        configure_secrets(["abcde"])
        register_secret("fghij")

        assert redact("abcde fghij") == "abcde fghij"

    def test_a_six_character_value_is_masked(self):
        register_secret("abcdef")

        assert redact("x abcdef y") == "x *** y"

    def test_configure_secrets_ignores_values_shorter_than_the_floor(self):
        configure_secrets(["a1b2c", "a1b2c3d"])

        assert redact("a1b2c a1b2c3d") == "a1b2c ***"

    def test_register_secret_and_redact_are_safe_between_threads(self):
        valores = [f"segredo-concorrente-{n:03d}" for n in range(60)]
        erros: list[BaseException] = []

        def registrar(parte):
            try:
                for valor in parte:
                    register_secret(valor)
                    redact(valor)
            except BaseException as erro:  # noqa: BLE001 - o teste só quer ver se alguma thread quebrou
                erros.append(erro)

        fios = [threading.Thread(target=registrar, args=(valores[i::4],)) for i in range(4)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=10)

        assert erros == [] and all(redact(valor) == REDACTED for valor in valores)


# ============================================================================ B3 — saneamento

QUEBRAS = ["\r", "\n", " ", " "]
CONTROLES = ["\x1b", "\x00", "\x07", "\x08", "\x0b", "\x0c", "\x0e", "\x1f", "\x7f", "\x80", "\x85", "\x9b", "\x9f"]
BIDI = ["‪", "‫", "‬", "‭", "‮", "⁦", "⁧", "⁨", "⁩"]


class TestSaneamento:
    @pytest.mark.parametrize("quebra", QUEBRAS)
    def test_sanitize_value_turns_line_breaks_into_the_return_mark(self, quebra):
        assert sanitize_value(f"a{quebra}b") == "a⏎b"

    @pytest.mark.parametrize("controle", CONTROLES + BIDI)
    def test_sanitize_value_turns_control_and_bidi_characters_into_the_replacement_char(self, controle):
        assert sanitize_value(f"a{controle}b") == "a�b"

    def test_sanitize_value_keeps_the_tab_and_ordinary_text(self):
        assert sanitize_value("a\tb ção │ 🎵 — ok") == "a\tb ção │ 🎵 — ok"

    def test_sanitize_value_neutralises_a_terminal_clear_sequence(self):
        assert sanitize_value("\x1b[2J\x9b31m") == "�[2J�31m"

    @pytest.mark.parametrize("controle", CONTROLES + BIDI)
    def test_sanitize_text_also_replaces_controls_and_bidi(self, controle):
        assert sanitize_text(f"a{controle}b") == "a�b"

    def test_sanitize_text_keeps_the_line_feed_and_the_tab(self):
        assert sanitize_text("linha 1\n\tlinha 2") == "linha 1\n\tlinha 2"

    def test_sanitize_text_replaces_the_carriage_return(self):
        assert sanitize_text("a\rb") == "a�b"

    def test_a_forged_log_line_in_an_argument_stays_on_one_line(self):
        record = passar(registro("título: %s", "x\n2026-10-27 ERROR falso\r fim", nivel=logging.ERROR))

        assert record.getMessage() == "título: x⏎2026-10-27 ERROR falso⏎⏎fim"
        assert "\n" not in record.getMessage()

    def test_controls_and_bidi_in_arguments_never_reach_the_message(self):
        record = passar(registro("v=%s", "\x1b[2J\x9b‮ fim"))

        mensagem = record.getMessage()
        assert not any(c in mensagem for c in ("\x1b", "\x9b", "‮")) and mensagem.endswith(" fim")

    def test_the_message_template_itself_may_carry_a_line_feed_for_the_formatter_to_frame(self):
        record = passar(registro("linha 1\nlinha 2"))

        assert record.getMessage() == "linha 1\nlinha 2"

    def test_an_esc_in_the_formatted_message_is_replaced(self):
        record = passar(registro("a\x1b[31mb"))

        assert "\x1b" not in record.getMessage() and "�" in record.getMessage()


# ============================================================================ o filtro SanitizeAndRedact


class TestFiltro:
    def test_the_message_is_formatted_and_the_args_cleared(self):
        record = passar(registro("nó %s com %d players e %.1f%%", "LOCAL", 3, 99.5))

        assert record.args is None and record.getMessage() == "nó LOCAL com 3 players e 99.5%"

    def test_the_original_template_is_kept_for_the_aggregator(self):
        record = passar(registro("falha em %s", "a"))

        assert record.empiremuse_template == "falha em %s"

    def test_the_second_pass_does_nothing(self):
        record = passar(registro("falha em %s", "a"))
        antes = (record.msg, record.args, record.empiremuse_template)

        passar(record)

        assert (record.msg, record.args, record.empiremuse_template) == antes
        assert record.empiremuse_redacted is True

    def test_numbers_booleans_and_none_are_left_as_they_are(self):
        record = passar(registro("%d %s %s %s", 7, True, None, 2.5))

        assert record.getMessage() == "7 True None 2.5"

    def test_a_mapping_argument_is_sanitised_inside(self):
        record = passar(registro("%(a)s e %(b)d", {"a": "x\ny", "b": 4}))

        assert record.getMessage() == "x⏎y e 4"

    def test_a_secret_in_the_message_and_in_an_argument_is_masked(self):
        configure_secrets(["segredo-na-mensagem-1"])
        register_secret("segredo-no-argumento-2")

        record = passar(registro("usando segredo-na-mensagem-1 e %s", "segredo-no-argumento-2"))

        assert record.getMessage() == "usando *** e ***"

    def test_a_pattern_secret_in_an_argument_is_masked(self):
        token = token_discord("b")

        record = passar(registro("erro de login: %s", f"Bad token {token}"))

        assert token not in record.getMessage() and REDACTED in record.getMessage()

    def test_the_traceback_is_formatted_redacted_and_exc_info_is_cleared(self):
        configure_secrets(["segredo-no-traceback-9"])
        record = registro("falhou", exc_info=excecao("falha com segredo-no-traceback-9 dentro"))

        passar(record)

        assert record.exc_info is None
        assert "Traceback (most recent call last)" in record.exc_text and "ValueError" in record.exc_text
        assert "segredo-no-traceback-9" not in record.exc_text and REDACTED in record.exc_text
        assert record.empiremuse_exc_type.endswith("ValueError")

    def test_a_record_without_exception_has_no_exc_type(self):
        record = passar(registro("sem erro"))

        assert record.empiremuse_exc_type is None and not record.exc_text

    def test_stack_info_is_redacted(self):
        configure_secrets(["segredo-na-pilha-5"])
        record = registro("pilha", stack_info='File "x.py", line 1\n    senha = "segredo-na-pilha-5"')

        passar(record)

        assert "segredo-na-pilha-5" not in record.stack_info and REDACTED in record.stack_info

    def test_the_exc_type_of_a_custom_exception_is_its_qualified_name(self):
        class MeuErro(Exception):
            pass

        record = passar(registro("x", exc_info=excecao("m", MeuErro)))

        assert record.empiremuse_exc_type.endswith("MeuErro")

    def test_the_filter_is_total_for_anything_that_is_not_a_record(self):
        assert SanitizeAndRedact().filter(object()) is True  # type: ignore[arg-type]


# ============================================================================ B4 — redator que levanta


class TestRedatorQueLevanta:
    def _assert_omitido(self, record):
        assert record.getMessage() == OMITTED
        assert record.args is None and record.exc_info is None and record.exc_text is None and record.stack_info is None

    def test_a_raising_redactor_replaces_the_record_with_the_notice(self, monkeypatch):
        def quebrado(texto):
            raise RuntimeError("redator quebrou")

        monkeypatch.setattr(redact_modulo, "redact", quebrado)
        record = registro("segredo-que-nao-pode-vazar-1 %s", "arg", exc_info=excecao("segredo-que-nao-pode-vazar-1"))

        passar(record)

        self._assert_omitido(record)

    def test_a_message_that_cannot_be_formatted_is_omitted_not_dropped(self):
        record = registro("%d itens", "não-é-número")

        passar(record)

        self._assert_omitido(record)

    def test_an_argument_whose_str_raises_is_omitted(self):
        class Quebrado:
            def __str__(self):
                raise RuntimeError("não imprime")

        record = registro("valor %s", Quebrado())

        passar(record)

        self._assert_omitido(record)

    def test_the_omitted_notice_is_not_redacted_again_and_the_filter_still_returns_true(self, monkeypatch):
        monkeypatch.setattr(redact_modulo, "redact", lambda texto: 1 / 0)
        record = registro("x")

        assert SanitizeAndRedact().filter(record) is True
        assert record.msg == OMITTED


# ============================================================================ B20 — teto por registro


class TestTeto:
    def test_cap_below_the_limit_is_identity(self):
        assert cap("abc", 5) == "abc" and cap("abcde", 5) == "abcde"

    def test_cap_cuts_and_reports_how_many_characters_were_dropped(self):
        assert cap("a" * 10, 4) == f"aaaa{PONTO} [+6]"

    def test_a_one_megabyte_message_is_capped_with_the_right_count(self):
        record = passar(registro("x" * 1_000_000))

        mensagem = record.getMessage()
        assert mensagem == "x" * MAX_MESSAGE_CHARS + f"{PONTO} [+{1_000_000 - MAX_MESSAGE_CHARS}]"

    def test_a_two_hundred_kilobyte_traceback_is_capped_with_the_right_count(self):
        exc_info = excecao("y" * 200_000)
        completo = logging.Formatter().formatException(exc_info)
        record = registro("falhou", exc_info=exc_info)

        passar(record)

        assert record.exc_text == completo[:MAX_TRACEBACK_CHARS] + f"{PONTO} [+{len(completo) - MAX_TRACEBACK_CHARS}]"

    def test_the_cap_applies_after_the_redaction_so_a_secret_at_the_limit_is_never_left_half(self):
        segredo = "SegredoNoLimiteDoTeto-123456"
        register_secret(segredo)
        texto = "a" * (MAX_MESSAGE_CHARS - 3) + segredo + "b" * 50

        saida = scrub(texto, MAX_MESSAGE_CHARS)

        assert saida.startswith("a" * (MAX_MESSAGE_CHARS - 3) + REDACTED)
        assert "Segredo" not in saida and "Seg" not in saida.split(REDACTED, 1)[1].split(PONTO)[0]

    def test_the_dropped_count_is_taken_from_the_redacted_text(self):
        segredo = "Outro-Segredo-Bem-Comprido-Para-Contar-77"
        register_secret(segredo)
        texto = segredo + "x" * 100

        saida = scrub(texto, 10)

        assert saida == f"{REDACTED}{'x' * 7}{PONTO} [+93]"


# ============================================================================ scrub


class TestScrub:
    def test_scrub_sanitises_then_redacts_then_caps(self):
        register_secret("segredo-do-scrub-42")
        texto = "a\x1b[2J segredo-do-scrub-42\nlinha 2\t" + "z" * 50
        esperado = "a�[2J ***\nlinha 2\t" + "z" * 50

        saida = scrub(texto, 30)

        assert saida == esperado[:30] + f"{PONTO} [+{len(esperado) - 30}]"
        assert "\x1b" not in saida and "segredo-do-scrub-42" not in saida

    def test_scrub_keeps_line_feeds_and_tabs(self):
        assert scrub("a\n\tb", 100) == "a\n\tb"

    def test_scrub_of_clean_short_text_is_identity(self):
        assert scrub("tudo certo com a versão 2.1.0", 8192) == "tudo certo com a versão 2.1.0"


# ============================================================================ argumentos que não são texto nem número nativo (CodeRabbit r4393628119)


class Opaco:
    """Objeto qualquer cujo ``str()`` e ``repr()`` carregam controles e segredos diferentes."""

    def __init__(self, texto_str: str, texto_repr: str) -> None:
        self._s, self._r = texto_str, texto_repr

    def __str__(self) -> str:
        return self._s

    def __repr__(self) -> str:
        return self._r


class TestArgumentosNaoTexto:
    def test_percent_r_of_an_exception_keeps_the_repr(self):
        record = passar(registro("falha: %r", ValueError("msg")))

        assert record.getMessage() == "falha: ValueError('msg')"

    def test_percent_s_of_an_exception_keeps_the_text(self):
        record = passar(registro("falha: %s", ValueError("msg")))

        assert record.getMessage() == "falha: msg"

    def test_percent_d_of_a_decimal_formats_correctly(self):
        from decimal import Decimal

        record = passar(registro("%d itens", Decimal(3)))

        assert record.getMessage() == "3 itens" and record.msg != OMITTED

    def test_percent_dot_one_f_of_a_fraction_formats_correctly(self):
        from fractions import Fraction

        record = passar(registro("%.1f", Fraction(1, 2)))

        assert record.getMessage() == "0.5" and record.msg != OMITTED

    @pytest.mark.parametrize("formato", ["%d", "%i", "%5.2f", "%e", "%s", "%r"])
    def test_numeric_formats_give_what_plain_logging_gives_for_decimal_and_fraction(self, formato):
        from decimal import Decimal
        from fractions import Fraction

        for valor in (Decimal("2.50"), Fraction(3, 4)):
            try:
                esperado = formato % valor
            except TypeError:
                continue  # o formato não aceita o tipo nem no logging puro
            record = passar(registro(formato, valor))
            assert record.getMessage() == esperado and record.msg != OMITTED

    def test_the_arguments_are_not_turned_into_text_when_they_are_numbers_of_any_kind(self):
        from decimal import Decimal

        record = passar(registro("%d-%s", Decimal(7), Decimal("1.5")))

        assert record.getMessage() == "7-1.5"

    def test_a_secret_in_the_str_of_an_arbitrary_object_is_masked(self):
        register_secret("segredo-no-str-do-objeto-1")

        record = passar(registro("obj: %s", Opaco("tem segredo-no-str-do-objeto-1 aqui", "Opaco()")))

        assert record.getMessage() == "obj: tem *** aqui"

    def test_a_secret_in_the_repr_of_an_arbitrary_object_is_masked(self):
        register_secret("segredo-no-repr-do-objeto-2")

        record = passar(registro("obj: %r", Opaco("x", "Opaco(token='segredo-no-repr-do-objeto-2')")))

        assert "segredo-no-repr-do-objeto-2" not in record.getMessage() and REDACTED in record.getMessage()

    def test_control_characters_in_the_str_of_an_arbitrary_object_are_sanitised_like_any_value(self):
        record = passar(registro("obj: %s", Opaco("a\n2026-10-27 ERROR falso\x1b[2J", "Opaco()")))

        mensagem = record.getMessage()
        assert "\n" not in mensagem and "\x1b" not in mensagem and "⏎" in mensagem

    def test_control_characters_in_the_repr_of_an_arbitrary_object_are_sanitised_like_any_value(self):
        record = passar(registro("obj: %r", Opaco("x", "Opaco('a\nb\x9b‮')")))

        mensagem = record.getMessage()
        assert not any(c in mensagem for c in ("\n", "\x9b", "‮")) and "⏎" in mensagem

    def test_s_and_r_conversions_in_one_message_are_each_redacted(self):
        register_secret("segredo-nas-duas-formas-3")
        por_str = Opaco("str segredo-nas-duas-formas-3", "x")
        por_repr = Opaco("y", "repr segredo-nas-duas-formas-3")

        record = passar(registro("%s | %r", por_str, por_repr))

        assert "segredo-nas-duas-formas-3" not in record.getMessage() and record.getMessage().count(REDACTED) == 2

    def test_the_same_object_used_with_s_and_with_r_is_handled_per_conversion(self):
        register_secret("segredo-do-mesmo-objeto-4")
        objeto = Opaco("str segredo-do-mesmo-objeto-4\nlinha", "repr segredo-do-mesmo-objeto-4\nlinha")

        record = passar(registro("%(o)s | %(o)r", {"o": objeto}))

        mensagem = record.getMessage()
        assert "segredo-do-mesmo-objeto-4" not in mensagem and "\n" not in mensagem and mensagem.count("⏎") == 2

    def test_an_exception_message_with_a_line_break_is_sanitised_in_percent_s_and_percent_r(self):
        record = passar(registro("%s / %r", ValueError("a\nb"), ValueError("c\nd")))

        assert "\n" not in record.getMessage()

    def test_a_mapping_argument_with_non_text_values_keeps_their_conversions(self):
        from decimal import Decimal

        record = passar(registro("%(n)d e %(e)r", {"n": Decimal(4), "e": KeyError("k")}))

        assert record.getMessage() == "4 e KeyError('k')"

    def test_an_object_that_is_neither_text_nor_number_is_still_printed_by_the_message(self):
        record = passar(registro("lista: %s", ["a", 1, None]))

        assert record.getMessage() == "lista: ['a', 1, None]"
