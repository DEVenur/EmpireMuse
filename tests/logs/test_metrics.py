"""Item 7 (P3, Gambit) — ``empiremuse.logs.metrics``: B13 (``MetricsCollector``) e ``format_summary`` (3.9 / 3.12).

Tudo em memória e puro: nenhum relógio real (``snapshot_and_reset`` recebe o ``now``), nenhum I/O.
"""

import dataclasses
import re
import threading

import pytest

from empiremuse.logs.metrics import ERROR_KINDS, MetricsCollector, MetricsSnapshot, NodeSample, format_summary

pytestmark = pytest.mark.critical


def test_the_error_kinds_are_the_contract_ones():
    assert tuple(ERROR_KINDS) == ("track_exception", "track_stuck", "node_unavailable", "command_error")


class TestColetor:
    def test_track_starts_are_counted(self):
        coletor = MetricsCollector()
        for guild in (1, 2, 3, 1):
            coletor.track_started(guild)

        assert coletor.snapshot_and_reset(100.0).tracks_started == 4

    def test_track_ended_does_not_count_as_started_and_never_raises(self):
        coletor = MetricsCollector()
        coletor.track_started(1)
        coletor.track_ended(1, "FINISHED")
        coletor.track_ended(2, "STOPPED")
        coletor.track_ended(3, "texto estranho\nsem restrição")

        assert coletor.snapshot_and_reset(100.0).tracks_started == 1

    def test_the_peak_is_the_maximum_sampled_value(self):
        coletor = MetricsCollector()
        for ativos in (3, 10, 7, 0):
            coletor.sample_players(ativos)

        assert coletor.snapshot_and_reset(100.0).players_peak == 10

    def test_errors_are_counted_by_kind(self):
        coletor = MetricsCollector()
        for tipo in ("track_exception", "track_exception", "track_stuck", "node_unavailable", "command_error"):
            coletor.error(tipo)

        assert dict(coletor.snapshot_and_reset(100.0).errors) == {
            "track_exception": 2,
            "track_stuck": 1,
            "node_unavailable": 1,
            "command_error": 1,
        }

    def test_a_kind_outside_the_list_becomes_other_and_free_text_never_becomes_a_key(self):
        coletor = MetricsCollector()
        coletor.error("tipo_inventado")
        coletor.error("Traceback (most recent call last)\nValueError: segredo-no-erro-1")
        coletor.error("track_stuck")

        erros = dict(coletor.snapshot_and_reset(100.0).errors)

        assert erros == {"other": 2, "track_stuck": 1}

    def test_snapshot_and_reset_clears_everything_and_the_interval_is_measured_from_the_previous_snapshot(self):
        coletor = MetricsCollector()
        coletor.track_started(1)
        coletor.sample_players(9)
        coletor.error("track_stuck")
        primeiro = coletor.snapshot_and_reset(100.0)

        segundo = coletor.snapshot_and_reset(160.0)

        assert (primeiro.tracks_started, primeiro.players_peak, dict(primeiro.errors)) == (1, 9, {"track_stuck": 1})
        assert (segundo.tracks_started, segundo.players_peak, dict(segundo.errors)) == (0, 0, {})
        assert segundo.interval == 60.0

    def test_a_snapshot_is_not_changed_by_what_happens_after_it(self):
        coletor = MetricsCollector()
        coletor.error("track_stuck")
        foto = coletor.snapshot_and_reset(100.0)

        coletor.error("track_stuck")
        coletor.error("command_error")

        assert dict(foto.errors) == {"track_stuck": 1}

    def test_the_snapshot_is_frozen(self):
        foto = MetricsCollector().snapshot_and_reset(1.0)

        assert isinstance(foto, MetricsSnapshot)
        with pytest.raises(dataclasses.FrozenInstanceError):
            foto.tracks_started = 5  # type: ignore[misc]

    def test_concurrent_increments_lose_nothing(self):
        coletor = MetricsCollector()

        def contar():
            for n in range(1000):
                coletor.track_started(n % 7)
                coletor.error("track_stuck")

        fios = [threading.Thread(target=contar) for _ in range(4)]
        for fio in fios:
            fio.start()
        for fio in fios:
            fio.join(timeout=10)
        foto = coletor.snapshot_and_reset(1.0)

        assert foto.tracks_started == 4000 and dict(foto.errors) == {"track_stuck": 4000}

    def test_five_hundred_guilds_only_cost_two_increments_each(self):
        coletor = MetricsCollector()
        for guild in range(500):
            coletor.track_started(guild)
            coletor.track_ended(guild, "FINISHED")

        assert coletor.snapshot_and_reset(1.0).tracks_started == 500


# ============================================================================ format_summary


def foto(**campos) -> MetricsSnapshot:
    coletor = MetricsCollector()
    for _ in range(campos.pop("iniciadas", 0)):
        coletor.track_started(1)
    coletor.sample_players(campos.pop("pico", 0))
    for tipo, vezes in campos.pop("erros", {}).items():
        for _ in range(vezes):
            coletor.error(tipo)
    return coletor.snapshot_and_reset(300.0)


def resumo(snapshot=None, **sobrescreve):
    base = {
        "guilds": 500,
        "players_active": 480,
        "gateway_ms": [50.0],
        "voice_ms": [float(n) for n in range(1, 101)],
        "cpu_percent": 12.5,
        "rss_mib": 345.6,
        "nodes": [],
    }
    return format_summary(
        snapshot or foto(iniciadas=37, pico=490, erros={"track_exception": 2}), **{**base, **sobrescreve}
    )


class TestResumo:
    def test_without_nodes_it_is_one_line_with_the_documented_fields(self):
        (linha,) = resumo()

        assert linha.startswith("📊") and "\n" not in linha
        assert re.search(r"servidores 500", linha) and re.search(r"players ativos 480 \(pico 490\)", linha)
        assert re.search(r"faixas iniciadas 37", linha)
        assert re.search(r"erros.*track_exception\W+2", linha)
        assert re.search(r"gateway 50\s?ms \(máx 50\s?ms\)", linha)
        assert re.search(r"voz p95 9[5-6]\s?ms", linha)
        assert re.search(r"processo CPU 1[23](\.\d)?%", linha) and re.search(r"RSS 34[56](\.\d)?\s?MiB", linha)

    @pytest.mark.parametrize("quantos", [0, 1, 2, 5])
    def test_with_n_nodes_it_is_exactly_one_plus_n_lines(self, quantos):
        nos = [NodeSample(f"NO{n}", 3, 1.5, 200.0) for n in range(quantos)]

        linhas = resumo(nodes=nos)

        assert len(linhas) == 1 + quantos and all(linha.startswith("📊") for linha in linhas)

    def test_a_node_line_has_the_identifier_players_cpu_and_memory(self):
        linhas = resumo(nodes=[NodeSample("LOCAL", 12, 3.5, 210.0)])

        assert re.search(r"nó LOCAL", linhas[1]) and re.search(r"players 12", linhas[1])
        assert re.search(r"CPU 3\.5%", linhas[1]) and re.search(r"memória 210(\.\d)?\s?MiB", linhas[1])

    def test_a_node_with_every_field_none_is_unavailable(self):
        linhas = resumo(nodes=[NodeSample("MORTO", None, None, None)])

        assert "nó MORTO" in linhas[1] and "indisponível" in linhas[1] and "players" not in linhas[1]

    def test_a_node_with_some_fields_missing_shows_a_dash_for_them(self):
        linhas = resumo(nodes=[NodeSample("PARCIAL", 5, None, 100.0)])

        assert "players 5" in linhas[1] and "—" in linhas[1] and "indisponível" not in linhas[1]

    def test_missing_process_figures_show_a_dash(self):
        (linha,) = resumo(cpu_percent=None, rss_mib=None)

        assert "—" in linha and "CPU None" not in linha and "RSS None" not in linha

    def test_no_gateway_or_voice_samples_show_a_dash(self):
        (linha,) = resumo(gateway_ms=[], voice_ms=[])

        assert linha.count("—") >= 2 and "nan" not in linha.lower()

    def test_no_errors_still_gives_a_clean_line(self):
        (linha,) = resumo(foto(iniciadas=1, pico=1))

        assert "\n" not in linha and "Traceback" not in linha

    def test_the_summary_is_pure(self):
        a, b = resumo(), resumo()

        assert a == b

    def test_a_node_identifier_with_control_characters_never_adds_a_line(self):
        linhas = resumo(nodes=[NodeSample("N\nERROR falso", 1, 1.0, 1.0)])

        assert len(linhas) == 2 and "\n" not in linhas[1]
