"""Item 18 (P2) — ``read_pending`` não confia no que está no lugar do arquivo: FIFO, link simbólico e datas no futuro.

O ``boot_guard`` lê o pendente antes de qualquer proteção, então a leitura não pode travar nem seguir um link.
"""

import os
import threading
from pathlib import Path

import pytest

from empiremuse.rules.release import Version
from empiremuse.updater.state import PendingUpdate, pending_path, read_pending, write_pending

pytestmark = pytest.mark.critical

AGORA = 1_800_000_000.0


def pendente(created_at: float) -> PendingUpdate:
    return PendingUpdate(
        flow="git",
        from_version=Version(2, 0, 0),
        to_version=Version(2, 1, 0),
        bot_id=1,
        channel_id=2,
        requested_by=3,
        created_at=created_at,
        prev_sha="a" * 40,
    )


def test_a_fifo_in_place_of_the_file_does_not_block_and_is_removed(tmp_path):
    os.mkfifo(pending_path(tmp_path))
    resultado = []
    leitura = threading.Thread(target=lambda: resultado.append(read_pending(tmp_path, AGORA)), daemon=True)

    leitura.start()
    leitura.join(timeout=1)
    travou = leitura.is_alive()
    if travou:  # solta a leitura presa no open() para a thread não sobrar
        with open(pending_path(tmp_path), "wb"):
            pass
        leitura.join(timeout=1)

    assert not travou
    assert resultado == [None] and not os.path.lexists(pending_path(tmp_path))


def test_a_symlink_in_place_of_the_file_is_discarded_without_touching_its_target(tmp_path):
    alvo = tmp_path / "alvo.json"
    write_pending(tmp_path, pendente(AGORA - 60))
    pending_path(tmp_path).rename(alvo)
    pending_path(tmp_path).symlink_to(alvo)

    assert read_pending(tmp_path, AGORA) is None

    assert not os.path.lexists(pending_path(tmp_path)) and alvo.exists()


def test_a_date_too_far_in_the_future_is_discarded(tmp_path):
    write_pending(tmp_path, pendente(AGORA + 301))

    assert read_pending(tmp_path, AGORA) is None

    assert not pending_path(tmp_path).exists()


def test_a_small_clock_skew_into_the_future_is_still_valid(tmp_path):
    write_pending(tmp_path, pendente(AGORA + 299))

    assert read_pending(tmp_path, AGORA) is not None


@pytest.fixture
def sem_flags_do_posix(monkeypatch):
    """Windows não tem ``O_NONBLOCK``/``O_NOFOLLOW``/``O_CLOEXEC``: a leitura não pode depender deles."""
    for nome in ("O_NONBLOCK", "O_NOFOLLOW", "O_CLOEXEC"):
        monkeypatch.delattr(os, nome, raising=False)


def test_a_valid_pending_update_is_read_where_the_posix_open_flags_do_not_exist(tmp_path, sem_flags_do_posix):
    write_pending(tmp_path, pendente(AGORA - 60))

    lido = read_pending(tmp_path, AGORA)

    assert lido is not None and lido.to_version == Version(2, 1, 0)


def test_a_non_regular_file_is_still_discarded_where_the_posix_open_flags_do_not_exist(tmp_path, sem_flags_do_posix):
    pending_path(tmp_path).mkdir()

    assert read_pending(tmp_path, AGORA) is None


def test_a_symlink_is_refused_where_the_posix_open_flags_do_not_exist(tmp_path, sem_flags_do_posix):
    """Sem ``O_NOFOLLOW`` (Windows) o ``S_ISREG`` valeria para o alvo: o link precisa ser recusado antes do ``open``."""
    alvo = tmp_path / "alvo.json"
    write_pending(tmp_path, pendente(AGORA - 60))
    pending_path(tmp_path).rename(alvo)
    pending_path(tmp_path).symlink_to(alvo)

    assert read_pending(tmp_path, AGORA) is None

    assert alvo.exists() and not os.path.lexists(pending_path(tmp_path))


def test_a_reparse_point_is_refused_where_the_posix_open_flags_do_not_exist(tmp_path, sem_flags_do_posix, monkeypatch):
    """Junção/ponto de reanálise do Windows: ``lstat`` com ``FILE_ATTRIBUTE_REPARSE_POINT`` não vira leitura."""
    write_pending(tmp_path, pendente(AGORA - 60))
    real = os.lstat

    def lstat_com_reparse(caminho, *args, **kwargs):
        resultado = real(caminho, *args, **kwargs)
        if Path(caminho) != pending_path(tmp_path):
            return resultado
        return type("Stat", (), {"st_mode": resultado.st_mode, "st_file_attributes": 0x400})()

    monkeypatch.setattr(os, "lstat", lstat_com_reparse)

    assert read_pending(tmp_path, AGORA) is None
