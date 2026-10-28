"""Teste do dono em produção 2.1.1, partes C3 e D1 — tamanhos em MiB e contadores no formato brasileiro (helpers puros de ``rules/text.py``)."""

import pytest

from empiremuse.rules import text

pytestmark = pytest.mark.critical


class TestFormatMib:
    def test_the_example_of_the_contract(self):
        assert text.format_mib(126_353_408) == "120,5 MiB"

    @pytest.mark.parametrize(
        ("num_bytes", "esperado"),
        [(0, "0,0 MiB"), (1_048_576, "1,0 MiB"), (52_428_800, "50,0 MiB"), (130_023_424, "124,0 MiB")],
    )
    def test_one_decimal_with_a_comma_and_binary_base(self, num_bytes, esperado):
        assert text.format_mib(num_bytes) == esperado

    def test_it_never_uses_a_decimal_point_nor_the_decimal_unit(self):
        resultado = text.format_mib(126_353_408)

        assert "." not in resultado and "MB" not in resultado


class TestFormatInt:
    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [(7, "7"), (0, "0"), (999, "999"), (1000, "1.000"), (1035, "1.035"), (1234567, "1.234.567")],
    )
    def test_the_thousands_separator_is_a_dot(self, valor, esperado):
        assert text.format_int(valor) == esperado
