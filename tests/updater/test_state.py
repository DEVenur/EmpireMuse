"""Item 18 (P2) — ``read_pending`` não confia no que está no lugar do arquivo: FIFO, link simbólico e datas no futuro.

O ``boot_guard`` lê o pendente antes de qualquer proteção, então a leitura não pode travar nem seguir um link.
"""

import json
import os
import threading
from pathlib import Path

import pytest

from empiremuse.rules.release import Version
from empiremuse.updater.state import PendingUpdate, parse_pending, pending_path, read_pending, write_pending

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


ESPERA_MAXIMA = 30  # só impede a suíte de pendurar se a leitura travar; o que se verifica é ter terminado sozinha


def ligar(link: Path, alvo: Path) -> None:
    """Cria o link simbólico ou pula o teste onde o sistema não deixa (Windows sem privilégio)."""
    try:
        link.symlink_to(alvo)
    except (OSError, NotImplementedError) as erro:
        pytest.skip(f"link simbólico indisponível: {erro}")


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="FIFO só existe em Unix")
def test_a_fifo_in_place_of_the_file_does_not_block_and_is_removed(tmp_path):
    os.mkfifo(pending_path(tmp_path))
    resultado = []
    leitura = threading.Thread(target=lambda: resultado.append(read_pending(tmp_path, AGORA)), daemon=True)

    leitura.start()
    leitura.join(timeout=ESPERA_MAXIMA)
    travou = leitura.is_alive()
    if travou:  # solta a leitura presa no open() para a thread não sobrar
        with open(pending_path(tmp_path), "wb"):
            pass
        leitura.join(timeout=ESPERA_MAXIMA)

    assert not travou
    assert resultado == [None] and not os.path.lexists(pending_path(tmp_path))


def test_a_symlink_in_place_of_the_file_is_discarded_without_touching_its_target(tmp_path):
    alvo = tmp_path / "alvo.json"
    write_pending(tmp_path, pendente(AGORA - 60))
    pending_path(tmp_path).rename(alvo)
    ligar(pending_path(tmp_path), alvo)

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
    ligar(pending_path(tmp_path), alvo)

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


@pytest.mark.parametrize("created_at", [10**400, -(10**400)], ids=["inteiro-gigante", "negativo-gigante"])
def test_a_created_at_too_big_for_a_float_is_invalid_and_does_not_crash(tmp_path, created_at):
    write_pending(tmp_path, pendente(AGORA - 60))
    dados = json.loads(pending_path(tmp_path).read_text(encoding="utf-8"))
    dados["created_at"] = created_at
    pending_path(tmp_path).write_text(json.dumps(dados), encoding="utf-8")

    assert read_pending(tmp_path, AGORA) is None

    assert not pending_path(tmp_path).exists()


@pytest.mark.parametrize(
    "created_at", [10**400, 2**63, 1e300, -1], ids=["gigante", "2-a-63", "float-gigante", "negativo"]
)
def test_parse_pending_rejects_a_created_at_out_of_range_without_raising(created_at):
    dados = pendente(AGORA - 60).to_json()
    dados["created_at"] = created_at

    assert parse_pending(dados) is None


@pytest.mark.parametrize("created_at", [AGORA - 60, 0], ids=["normal", "zero"])
def test_parse_pending_accepts_a_created_at_in_range(created_at):
    dados = pendente(created_at).to_json()

    assert parse_pending(dados) is not None
