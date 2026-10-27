"""Item 7 (P1, Turbine) — B1: ``parse_log_settings`` é pura (config e ``environ`` injetados) e devolve os avisos sem logar.

Os valores de config chegam como o ``config_loader`` os entrega: textos para ``LOG_*``, ``bool`` para ``ENABLE_LOGGER`` e ``int`` para
``METRICS_INTERVAL``. Chaves ausentes valem o padrão.
"""

import dataclasses
import logging

import pytest

from empiremuse.logs.settings import LogSettings, parse_log_settings

pytestmark = pytest.mark.critical

IMAGEM = {"EMPIREMUSE_VERSION": "2.1.0"}
G1, G2 = "123456789012345678", "987654321098765432"


def ler(config=None, ambiente=None):
    return parse_log_settings(config or {}, ambiente if ambiente is not None else {})


class TestPadroes:
    def test_defaults_outside_the_image(self):
        settings, avisos = ler()

        assert settings == LogSettings(
            level=logging.INFO, color=True, file=True, debug_guilds=frozenset(), metrics_interval=300
        )
        assert avisos == []

    def test_defaults_inside_the_image_turn_the_file_off(self):
        settings, avisos = ler(ambiente=IMAGEM)

        assert settings.file is False and settings.color is True and avisos == []

    def test_log_settings_is_frozen(self):
        settings, _ = ler()

        with pytest.raises(dataclasses.FrozenInstanceError):
            settings.level = logging.DEBUG  # type: ignore[misc]

    def test_the_parser_does_not_change_its_inputs(self):
        config, ambiente = {"LOG_LEVEL": "debug", "LOG_DEBUG_GUILDS": f"{G1}, lixo"}, {"NO_COLOR": "1"}
        antes = (dict(config), dict(ambiente))

        ler(config, ambiente)

        assert (config, ambiente) == antes

    def test_the_warnings_are_texts(self):
        _, avisos = ler({"LOG_LEVEL": "nada"})

        assert avisos and all(isinstance(aviso, str) for aviso in avisos)


class TestNivel:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [
            ("DEBUG", logging.DEBUG),
            ("debug", logging.DEBUG),
            ("INFO", logging.INFO),
            ("Info", logging.INFO),
            ("warning", logging.WARNING),
            ("WARNING", logging.WARNING),
            ("error", logging.ERROR),
            ("ERROR", logging.ERROR),
        ],
    )
    def test_valid_levels_ignore_case(self, valor, esperado):
        settings, avisos = ler({"LOG_LEVEL": valor})

        assert settings.level == esperado and avisos == []

    @pytest.mark.parametrize("valor", ["verbose", "CRITICAL", "10", "info!", "trace"])
    def test_an_invalid_level_falls_back_to_info_with_one_warning(self, valor):
        settings, avisos = ler({"LOG_LEVEL": valor})

        assert settings.level == logging.INFO
        assert len(avisos) == 1 and "LOG_LEVEL" in avisos[0]


class TestCor:
    @pytest.mark.parametrize(("valor", "esperado"), [("on", True), ("ON", True), ("off", False), ("OFF", False)])
    def test_log_color(self, valor, esperado):
        assert ler({"LOG_COLOR": valor})[0].color is esperado

    def test_no_color_set_turns_color_off_even_with_log_color_on(self):
        assert ler({"LOG_COLOR": "on"}, {"NO_COLOR": "1"})[0].color is False

    def test_any_non_empty_no_color_value_counts(self):
        assert ler(ambiente={"NO_COLOR": "qualquer coisa"})[0].color is False

    def test_an_empty_no_color_is_ignored(self):
        assert ler(ambiente={"NO_COLOR": ""})[0].color is True

    def test_no_color_is_read_only_from_the_environment_not_from_the_config(self):
        assert ler({"NO_COLOR": "1"})[0].color is True

    def test_there_is_no_tty_detection(self):
        assert ler(ambiente={"TERM": "dumb"})[0].color is True


class TestArquivo:
    def test_auto_outside_the_image_is_on(self):
        assert ler({"LOG_FILE": "auto"})[0].file is True

    def test_auto_inside_the_image_is_off(self):
        assert ler({"LOG_FILE": "auto"}, IMAGEM)[0].file is False

    def test_any_image_variable_value_counts_as_inside_the_image(self):
        assert ler(ambiente={"EMPIREMUSE_VERSION": "dev"})[0].file is False

    @pytest.mark.parametrize("ambiente", [{}, IMAGEM], ids=["fora", "dentro"])
    def test_on_and_off_are_explicit(self, ambiente):
        assert ler({"LOG_FILE": "on"}, ambiente)[0].file is True
        assert ler({"LOG_FILE": "off"}, ambiente)[0].file is False

    @pytest.mark.parametrize("log_file", [None, "auto"], ids=["ausente", "auto"])
    def test_the_legacy_enable_logger_equals_on_when_log_file_is_missing_or_auto(self, log_file):
        config = {"ENABLE_LOGGER": True} | ({"LOG_FILE": log_file} if log_file else {})

        assert ler(config, IMAGEM)[0].file is True

    def test_enable_logger_never_turns_anything_off(self):
        assert ler({"ENABLE_LOGGER": True, "LOG_FILE": "off"})[0].file is False
        assert ler({"ENABLE_LOGGER": False, "LOG_FILE": "on"}, IMAGEM)[0].file is True
        assert ler({"ENABLE_LOGGER": False})[0].file is True

    def test_enable_logger_false_inside_the_image_stays_off(self):
        assert ler({"ENABLE_LOGGER": False}, IMAGEM)[0].file is False


class TestServidoresEmDebug:
    def test_valid_ids_become_a_frozenset_of_ints(self):
        settings, avisos = ler({"LOG_DEBUG_GUILDS": f"{G1}, {G2}"})

        assert settings.debug_guilds == frozenset({int(G1), int(G2)}) and avisos == []

    def test_an_empty_value_means_none(self):
        assert ler({"LOG_DEBUG_GUILDS": ""})[0].debug_guilds == frozenset()

    def test_garbage_is_ignored_with_a_warning_that_does_not_echo_it(self):
        settings, avisos = ler({"LOG_DEBUG_GUILDS": f"abc-secreto,{G1}"})

        assert settings.debug_guilds == frozenset({int(G1)})
        assert len(avisos) == 1 and "abc-secreto" not in avisos[0]

    def test_fourteen_digits_are_too_short(self):
        curto = "1" * 14

        settings, avisos = ler({"LOG_DEBUG_GUILDS": f"{curto},{G1}"})

        assert settings.debug_guilds == frozenset({int(G1)}) and len(avisos) == 1 and curto not in avisos[0]

    def test_twenty_two_digits_are_too_long(self):
        longo = "1" * 22

        settings, avisos = ler({"LOG_DEBUG_GUILDS": f"{longo},{G1}"})

        assert settings.debug_guilds == frozenset({int(G1)}) and len(avisos) == 1 and longo not in avisos[0]

    @pytest.mark.parametrize("digitos", [15, 21])
    def test_the_boundaries_fifteen_and_twenty_one_digits_are_valid(self, digitos):
        valor = "1" * digitos

        settings, avisos = ler({"LOG_DEBUG_GUILDS": valor})

        assert settings.debug_guilds == frozenset({int(valor)}) and avisos == []

    def test_sixty_ids_keep_only_the_first_fifty_with_a_warning(self):
        ids = [str(10**16 + n) for n in range(60)]

        settings, avisos = ler({"LOG_DEBUG_GUILDS": ",".join(ids)})

        assert settings.debug_guilds == frozenset(int(i) for i in ids[:50])
        assert len(avisos) == 1 and not any(i in avisos[0] for i in ids)

    def test_exactly_fifty_ids_have_no_warning(self):
        ids = [str(10**16 + n) for n in range(50)]

        settings, avisos = ler({"LOG_DEBUG_GUILDS": ",".join(ids)})

        assert len(settings.debug_guilds) == 50 and avisos == []

    def test_non_ascii_digits_are_not_snowflakes(self):
        settings, avisos = ler({"LOG_DEBUG_GUILDS": "١٢٣٤٥٦٧٨٩٠١٢٣٤٥٦"})

        assert settings.debug_guilds == frozenset() and len(avisos) == 1


class TestIntervaloDasMetricas:
    @pytest.mark.parametrize(
        ("valor", "esperado"), [(0, 0), (1, 60), (30, 60), (59, 60), (60, 60), (300, 300), (3600, 3600)]
    )
    def test_metrics_interval(self, valor, esperado):
        settings, avisos = ler({"METRICS_INTERVAL": valor})

        assert settings.metrics_interval == esperado and avisos == []
