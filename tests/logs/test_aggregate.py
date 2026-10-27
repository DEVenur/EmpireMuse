"""Item 7 (P1, Gambit) — B7: ``RepeatAggregator`` com ``emit`` e relógio falsos.

Os registros chegam como saem do ``SanitizeAndRedact``: a chave do agregador é o TEMPLATE original (``empiremuse_template``) e o tipo da
exceção (``empiremuse_exc_type``), nunca a mensagem já redigida. Nada dorme: o tempo só anda com ``Relogio.avancar``.
"""

import logging
import threading

import pytest

from empiremuse.logs.aggregate import AGGREGATE_WINDOW, MAX_KEYS, RepeatAggregator
from tests.logs.apoio import ESPERA_MAXIMA, Relogio, registro

pytestmark = pytest.mark.critical

W, E, I, D = logging.WARNING, logging.ERROR, logging.INFO, logging.DEBUG


def ocorrencia(
    template="nó %s caiu", valor="A", *, nivel=W, nome="empiremuse.wavelink", tipo=None, **extra
) -> logging.LogRecord:
    """Registro já redigido: ``msg`` formatada, ``args`` vazios, template e tipo de exceção gravados pelo filtro de redação."""
    record = registro(template % valor if "%" in template else template, nivel=nivel, nome=nome, **extra)
    record.empiremuse_template = template
    record.empiremuse_exc_type = tipo
    record.empiremuse_redacted = True
    return record


@pytest.fixture
def relogio():
    return Relogio()


@pytest.fixture
def emitidos():
    return []


@pytest.fixture
def agg(relogio, emitidos):
    return RepeatAggregator(emitidos.append, clock=relogio)


def linhas(emitidos) -> list[str]:
    return [r.getMessage() for r in emitidos]


def test_the_contract_constants():
    assert AGGREGATE_WINDOW == 60.0 and MAX_KEYS == 500


# ============================================================================ janela e contagem


class TestJanela:
    def test_a_thousand_equal_warnings_give_the_first_plus_one_summary_of_999(self, agg, relogio, emitidos):
        passaram = [agg.filter(ocorrencia(valor=str(n))) for n in range(1000)]

        assert passaram[0] is True and not any(passaram[1:]) and emitidos == []
        relogio.avancar(61)
        agg.tick()

        (resumo,) = emitidos
        assert resumo.getMessage() == "↻ nó 0 caiu — repetida 999× em 60 s"

    def test_the_summary_keeps_the_name_the_level_and_the_context_of_the_first_occurrence(self, agg, relogio, emitidos):
        agg.filter(ocorrencia(nome="empiremuse.player", nivel=E, bot="Alfa", guild=77))
        agg.filter(ocorrencia(nome="empiremuse.player", nivel=E, bot="Beta", guild=88))
        relogio.avancar(61)

        agg.tick()

        (resumo,) = emitidos
        assert (resumo.name, resumo.levelno, resumo.bot, resumo.guild) == ("empiremuse.player", E, "Alfa", 77)

    def test_the_summary_is_marked_as_final_and_carries_no_traceback_or_args(self, agg, relogio, emitidos):
        agg.filter(ocorrencia())
        agg.filter(ocorrencia())
        relogio.avancar(61)

        agg.tick()

        (resumo,) = emitidos
        assert resumo.empiremuse_redacted is True and resumo.empiremuse_emit is True
        assert not resumo.args and not resumo.exc_info and not resumo.exc_text

    def test_a_summary_that_comes_back_to_the_filter_passes_without_counting(self, agg, relogio, emitidos):
        agg.filter(ocorrencia())
        agg.filter(ocorrencia())
        relogio.avancar(61)
        agg.tick()
        (resumo,) = emitidos

        for _ in range(5):
            assert agg.filter(resumo) is True
        relogio.avancar(61)
        agg.tick()
        agg.flush()

        assert len(emitidos) == 1

    def test_nothing_is_emitted_before_the_window_closes(self, agg, relogio, emitidos):
        agg.filter(ocorrencia())
        agg.filter(ocorrencia())
        relogio.avancar(59)

        agg.tick()

        assert emitidos == []

    def test_a_single_occurrence_never_produces_a_summary(self, agg, relogio, emitidos):
        assert agg.filter(ocorrencia()) is True
        relogio.avancar(120)

        agg.tick()
        agg.flush()

        assert emitidos == []

    def test_the_next_record_of_the_same_key_after_the_window_closes_the_old_one_and_opens_a_new_one(
        self, agg, relogio, emitidos
    ):
        for n in range(5):
            agg.filter(ocorrencia(valor=str(n)))
        relogio.avancar(61)

        assert agg.filter(ocorrencia(valor="novo")) is True

        assert linhas(emitidos) == ["↻ nó 0 caiu — repetida 4× em 60 s"]
        assert agg.filter(ocorrencia(valor="outro")) is False

    def test_the_tick_closes_the_expired_windows_of_every_key(self, agg, relogio, emitidos):
        for chave in ("a", "b"):
            agg.filter(ocorrencia(template=f"falha {chave}"))
            agg.filter(ocorrencia(template=f"falha {chave}"))
            agg.filter(ocorrencia(template=f"falha {chave}"))
        relogio.avancar(61)

        agg.tick()

        assert sorted(linhas(emitidos)) == ["↻ falha a — repetida 2× em 60 s", "↻ falha b — repetida 2× em 60 s"]
        agg.tick()
        assert len(emitidos) == 2

    def test_flush_emits_every_pending_count_at_once_and_only_once(self, agg, emitidos):
        for _ in range(3):
            agg.filter(ocorrencia())

        agg.flush()
        agg.flush()

        assert linhas(emitidos) == ["↻ nó A caiu — repetida 2× em 60 s"]


# ============================================================================ chave


class TestChave:
    def test_different_args_with_the_same_template_aggregate(self, agg):
        assert agg.filter(ocorrencia(valor="A")) is True
        assert agg.filter(ocorrencia(valor="B")) is False

    def test_the_key_is_the_template_not_the_redacted_message(self, agg):
        primeira = ocorrencia(valor="A")
        segunda = ocorrencia(valor="B")
        primeira.msg = segunda.msg = "texto redigido igual nos dois"

        assert agg.filter(primeira) is True
        assert agg.filter(segunda) is False

    def test_the_same_message_with_different_templates_does_not_aggregate(self, agg):
        um, dois = ocorrencia(template="um %s", valor="x"), ocorrencia(template="dois %s", valor="x")
        um.msg = dois.msg = "mesma mensagem"

        assert agg.filter(um) is True and agg.filter(dois) is True

    def test_different_exception_types_do_not_aggregate(self, agg):
        assert agg.filter(ocorrencia(tipo="builtins.ValueError")) is True
        assert agg.filter(ocorrencia(tipo="builtins.KeyError")) is True
        assert agg.filter(ocorrencia(tipo="builtins.ValueError")) is False

    def test_with_and_without_an_exception_are_different_keys(self, agg):
        assert agg.filter(ocorrencia(tipo=None)) is True
        assert agg.filter(ocorrencia(tipo="builtins.ValueError")) is True

    def test_different_loggers_and_levels_do_not_aggregate(self, agg):
        assert agg.filter(ocorrencia(nome="empiremuse.a")) is True
        assert agg.filter(ocorrencia(nome="empiremuse.b")) is True
        assert agg.filter(ocorrencia(nivel=E)) is True
        assert agg.filter(ocorrencia(nivel=W)) is True
        assert agg.filter(ocorrencia(nivel=W)) is False

    def test_the_summary_has_the_level_of_the_key(self, agg, relogio, emitidos):
        agg.filter(ocorrencia(nivel=E))
        agg.filter(ocorrencia(nivel=E))
        relogio.avancar(61)

        agg.tick()

        assert emitidos[0].levelno == E

    @pytest.mark.parametrize("nivel", [I, D])
    def test_info_and_debug_never_aggregate(self, agg, relogio, emitidos, nivel):
        resultado = [agg.filter(ocorrencia(nivel=nivel)) for _ in range(10)]

        relogio.avancar(120)
        agg.tick()
        agg.flush()

        assert all(resultado) and emitidos == []

    @pytest.mark.parametrize("nivel", [W, E, logging.CRITICAL])
    def test_warning_and_above_aggregate(self, agg, nivel):
        assert agg.filter(ocorrencia(nivel=nivel)) is True
        assert agg.filter(ocorrencia(nivel=nivel)) is False


# ============================================================================ teto de chaves


class TestTetoDeChaves:
    def test_the_501st_key_flushes_the_oldest_one_first(self, agg, emitidos):
        for n in range(MAX_KEYS):
            agg.filter(ocorrencia(template=f"chave {n}"))
            agg.filter(ocorrencia(template=f"chave {n}"))
        assert emitidos == []

        agg.filter(ocorrencia(template="chave nova"))

        assert linhas(emitidos) == ["↻ chave 0 — repetida 1× em 60 s"]

    def test_a_flushed_key_starts_over_if_it_comes_back(self, agg, emitidos):
        for n in range(MAX_KEYS + 1):
            agg.filter(ocorrencia(template=f"chave {n}"))
            agg.filter(ocorrencia(template=f"chave {n}"))

        assert agg.filter(ocorrencia(template="chave 0")) is True

    def test_the_number_of_pending_summaries_never_exceeds_the_cap(self, agg, emitidos):
        for n in range(MAX_KEYS + 50):
            agg.filter(ocorrencia(template=f"chave {n}"))
            agg.filter(ocorrencia(template=f"chave {n}"))

        agg.flush()

        assert len(emitidos) == MAX_KEYS + 50  # as 50 descarregadas antes + as 500 pendentes, cada uma uma vez
        assert len(set(linhas(emitidos))) == MAX_KEYS + 50


# ============================================================================ uma decisão por registro (V-L6)


class TestUmaDecisaoPorRegistro:
    def test_the_same_record_through_two_handlers_counts_once(self, agg, emitidos):
        primeira = ocorrencia()
        repetida = ocorrencia()

        assert agg.filter(primeira) is True and agg.filter(primeira) is True
        assert agg.filter(repetida) is False and agg.filter(repetida) is False
        agg.flush()

        assert linhas(emitidos) == ["↻ nó A caiu — repetida 1× em 60 s"]

    def test_the_decision_is_written_on_the_record(self, agg):
        primeira, repetida = ocorrencia(), ocorrencia()

        agg.filter(primeira)
        agg.filter(repetida)

        assert primeira.empiremuse_emit is True and repetida.empiremuse_emit is False

    def test_the_second_pass_reads_the_decision_even_if_the_window_closed_in_between(self, agg, relogio):
        agg.filter(ocorrencia())
        suprimida = ocorrencia()
        assert agg.filter(suprimida) is False
        relogio.avancar(61)

        assert agg.filter(suprimida) is False

    def test_a_record_that_already_carries_emit_true_passes_without_counting(self, agg, emitidos):
        pronta = ocorrencia()
        pronta.empiremuse_emit = True

        resultado = [agg.filter(pronta) for _ in range(4)]
        agg.flush()

        assert all(resultado) and emitidos == []


# ============================================================================ trava e robustez


class TestTrava:
    def test_emit_runs_outside_the_internal_lock_so_it_can_come_back_to_the_filter(self, relogio):
        recebidos: list[logging.LogRecord] = []
        agregador: list[RepeatAggregator] = []

        def emitir(record):
            recebidos.append(record)
            agregador[0].filter(record)  # os handlers devolvem o resumo ao filtro; com a trava presa isto pendura

        agregador.append(RepeatAggregator(emitir, clock=relogio))
        agregador[0].filter(ocorrencia())
        agregador[0].filter(ocorrencia())
        relogio.avancar(61)

        fio = threading.Thread(target=agregador[0].tick)
        fio.start()
        fio.join(timeout=ESPERA_MAXIMA)

        assert not fio.is_alive() and len(recebidos) == 1

    def test_the_filter_is_total_for_anything_that_is_not_a_record(self, agg):
        assert agg.filter(object()) in (True, False)  # type: ignore[arg-type]

    def test_a_record_without_the_redaction_attributes_does_not_break_the_filter(self, agg):
        crua = registro("sem atributos do filtro de redação", nivel=W)

        assert agg.filter(crua) in (True, False)

    def test_many_threads_counting_the_same_key_lose_no_occurrence(self, agg, emitidos):
        def contar():
            for _ in range(100):
                agg.filter(ocorrencia())

        fios = [threading.Thread(target=contar) for _ in range(4)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=ESPERA_MAXIMA)
        agg.flush()

        assert linhas(emitidos) == ["↻ nó A caiu — repetida 399× em 60 s"]
