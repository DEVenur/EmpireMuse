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


# ============================================================================ K8 — código de erro (ERR-…) × agregação

E = logging.ERROR
MAX_CODED_REPEATS = 50


def exc_text_de(caminho: str = "A", mensagem: str = "boom", fonte: str = "chamar()") -> str:
    """``exc_text`` já redigido de um traceback: a impressão digital usa só as linhas ``  File "…", line N, in f``."""
    return (
        "Traceback (most recent call last):\n"
        f'  File "/app/{caminho}.py", line 10, in funcao\n    {fonte}\n'
        f'  File "/app/{caminho}.py", line 20, in interna\n    levantar()\n'
        f"ValueError: {mensagem}"
    )


def com_codigo(codigo="ERR-AAAAAA", *, caminho="A", mensagem="boom", fonte="chamar()", exc=True, nivel=E):
    """Registro de erro inesperado como o produtor o cria (``extra={"error_code": …}``) e o filtro de redação o deixa."""
    texto = "Erro inesperado em cmd" + (f" [{codigo}]" if isinstance(codigo, str) and codigo.startswith("ERR-") else "")
    record = registro(texto, nivel=nivel, nome="empiremuse.errors")
    record.empiremuse_template = "Erro inesperado em %s%s"
    record.empiremuse_exc_type = "builtins.ValueError" if exc else None
    record.empiremuse_redacted = True
    record.exc_text = exc_text_de(caminho, mensagem, fonte) if exc else None
    record.stack_info = "Stack (most recent call last):\n  File x" if exc else None
    if codigo is not None:
        record.error_code = codigo
    return record


class TestCodigoDeErro:
    def test_the_second_coded_error_of_the_same_path_is_one_line_with_its_code_and_a_pointer_to_the_first(
        self, agg, emitidos
    ):
        primeira = com_codigo("ERR-AAAAAA")
        segunda = com_codigo("ERR-BBBBBB", mensagem="boom B")

        assert agg.filter(primeira) is True
        assert primeira.exc_text.startswith("Traceback (most recent call last)")
        assert agg.filter(segunda) is True

        assert (
            segunda.getMessage()
            == "Erro inesperado em cmd [ERR-BBBBBB] — ValueError: boom B — traceback igual ao de ERR-AAAAAA"
        )
        assert segunda.exc_text is None and segunda.stack_info is None and not segunda.args
        agg.flush()
        assert emitidos == []  # as linhas com código não entram na contagem

    def test_the_last_line_of_the_original_traceback_is_cut_at_300_characters(self, agg):
        agg.filter(com_codigo("ERR-AAAAAA"))
        longa = com_codigo("ERR-BBBBBB", mensagem="x" * 1000)

        agg.filter(longa)

        mensagem = longa.getMessage()
        assert "x" * 100 in mensagem and "x" * 301 not in mensagem and "traceback igual ao de ERR-AAAAAA" in mensagem

    def test_the_first_occurrence_keeps_its_traceback_untouched(self, agg):
        primeira = com_codigo("ERR-AAAAAA")
        texto, pilha = primeira.exc_text, primeira.stack_info

        agg.filter(primeira)

        assert (primeira.exc_text, primeira.stack_info) == (
            texto,
            pilha,
        ) and "traceback igual" not in primeira.getMessage()

    def test_the_same_record_through_the_second_handler_is_not_rewritten_twice(self, agg):
        agg.filter(com_codigo("ERR-AAAAAA"))
        segunda = com_codigo("ERR-BBBBBB")

        agg.filter(segunda)
        primeira_leitura = segunda.getMessage()
        assert agg.filter(segunda) is True

        assert segunda.getMessage() == primeira_leitura and segunda.getMessage().count("traceback igual ao de") == 1

    def test_without_a_traceback_difference_a_different_call_site_is_a_different_key(self, agg, emitidos):
        a = com_codigo("ERR-AAAAAA", caminho="A")
        b = com_codigo("ERR-BBBBBB", caminho="B")

        assert agg.filter(a) is True and agg.filter(b) is True

        assert a.exc_text and b.exc_text
        assert "traceback igual" not in a.getMessage() and "traceback igual" not in b.getMessage()

    def test_k8b_without_codes_two_call_sites_with_the_same_template_and_type_are_both_full(self, agg):
        a, b = com_codigo(None, caminho="A"), com_codigo(None, caminho="B")

        assert agg.filter(a) is True and agg.filter(b) is True

        assert a.exc_text and b.exc_text

    def test_k8b_a_different_line_in_the_same_file_is_a_different_call_site(self, agg):
        a, b = com_codigo(None), com_codigo(None)
        b.exc_text = b.exc_text.replace("line 20", "line 21")

        assert agg.filter(a) is True and agg.filter(b) is True

    def test_k8c_same_path_with_different_exception_messages_is_the_same_key(self, agg, relogio, emitidos):
        assert agg.filter(com_codigo(None, mensagem="boom 1")) is True
        assert agg.filter(com_codigo(None, mensagem="boom 2")) is False
        assert agg.filter(com_codigo(None, mensagem="boom 3", fonte="outra()")) is False

        relogio.avancar(61)
        agg.tick()

        assert [r.getMessage() for r in emitidos] == ["↻ Erro inesperado em cmd — repetida 2× em 60 s"]

    def test_the_fingerprint_ignores_the_source_lines_and_the_final_message_line(self, agg):
        assert agg.filter(com_codigo(None, fonte="a()", mensagem="m1")) is True
        assert agg.filter(com_codigo(None, fonte="b(1, 2)", mensagem="m2")) is False

    def test_k8d_a_burst_of_sixty_coded_errors_gives_one_full_forty_nine_lines_and_a_summary_of_ten(
        self, agg, relogio, emitidos
    ):
        registros = [com_codigo(f"ERR-{n:06X}") for n in range(60)]

        resultados = [agg.filter(r) for r in registros]

        assert resultados == [True] * MAX_CODED_REPEATS + [False] * 10
        assert registros[0].exc_text and "traceback igual" not in registros[0].getMessage()
        for n, record in enumerate(registros[1:MAX_CODED_REPEATS], start=1):
            assert record.exc_text is None and f"ERR-{n:06X}" in record.getMessage()
            assert record.getMessage().endswith("traceback igual ao de ERR-000000")
        assert emitidos == []
        relogio.avancar(61)
        agg.tick()
        (resumo,) = emitidos
        assert resumo.getMessage() == (
            f"↻ {registros[0].getMessage()} — repetida 10× em 60 s (códigos omitidos; traceback igual ao de ERR-000000)"
        )

    def test_exactly_fifty_coded_errors_in_the_window_leave_no_summary(self, agg, relogio, emitidos):
        for n in range(MAX_CODED_REPEATS):
            assert agg.filter(com_codigo(f"ERR-{n:06X}")) is True

        relogio.avancar(61)
        agg.tick()
        agg.flush()

        assert emitidos == []

    def test_the_fifty_first_coded_error_is_suppressed_and_counted(self, agg, relogio, emitidos):
        for n in range(MAX_CODED_REPEATS):
            agg.filter(com_codigo(f"ERR-{n:06X}"))

        assert agg.filter(com_codigo("ERR-FFFFFF")) is False
        relogio.avancar(61)
        agg.tick()

        assert (
            emitidos[0]
            .getMessage()
            .endswith("repetida 1× em 60 s (códigos omitidos; traceback igual ao de ERR-000000)")
        )

    def test_a_new_window_starts_over_with_a_full_traceback_and_a_new_first_code(self, agg, relogio):
        agg.filter(com_codigo("ERR-AAAAAA"))
        agg.filter(com_codigo("ERR-BBBBBB"))
        relogio.avancar(61)

        nova = com_codigo("ERR-CCCCCC")
        depois = com_codigo("ERR-DDDDDD")

        assert agg.filter(nova) is True and nova.exc_text and "traceback igual" not in nova.getMessage()
        agg.filter(depois)
        assert depois.getMessage().endswith("traceback igual ao de ERR-CCCCCC")

    @pytest.mark.parametrize(
        "invalido",
        [
            "ERR-zzz",
            "x\nERR-AAAAAA",
            123,
            None,
            "",
            "ERR-AAAAA",
            "ERR-AAAAAAA",
            "err-aaaaaa",
            "ERR-AAAAAA\n",
            " ERR-AAAAAA",
        ],
        ids=repr,
    )
    def test_k8e_an_invalid_code_is_treated_as_no_code(self, agg, relogio, emitidos, invalido):
        primeira = com_codigo(None)
        segunda = com_codigo(invalido)
        if invalido is None:
            segunda.error_code = None  # atributo presente com None

        assert agg.filter(primeira) is True
        assert agg.filter(segunda) is False

        relogio.avancar(61)
        agg.tick()
        assert [r.getMessage() for r in emitidos] == ["↻ Erro inesperado em cmd — repetida 1× em 60 s"]

    def test_k8e_the_invalid_code_text_is_never_copied_into_the_output(self, agg, relogio, emitidos):
        agg.filter(com_codigo(None))
        agg.filter(com_codigo("x\nERR-AAAAAA"))
        relogio.avancar(61)
        agg.tick()

        assert all("ERR-AAAAAA" not in r.getMessage() for r in emitidos)

    def test_k8f_a_thousand_errors_without_a_code_give_one_full_and_a_summary_of_999(self, agg, relogio, emitidos):
        resultados = [agg.filter(com_codigo(None, mensagem=f"boom {n}")) for n in range(1000)]

        assert resultados[0] is True and not any(resultados[1:])
        relogio.avancar(61)
        agg.tick()
        assert [r.getMessage() for r in emitidos] == ["↻ Erro inesperado em cmd — repetida 999× em 60 s"]

    def test_info_and_debug_with_a_code_are_never_aggregated(self, agg):
        for nivel in (logging.INFO, logging.DEBUG):
            resultados = [agg.filter(com_codigo(f"ERR-{n:06X}", nivel=nivel)) for n in range(5)]

            assert all(resultados)
