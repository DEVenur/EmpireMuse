"""F3-6b, etapa 2b — complemento do QA depois da mutação do código real: o log do descarte do cache antigo leva só o nome."""

import logging
from pathlib import Path

import pytest

from empiremuse.utils.music.legacy_reader import discard_legacy_cache


def test_falha_ao_apagar_o_cache_antigo_registra_so_o_nome_e_o_tipo_da_falha(tmp_path, monkeypatch, caplog):
    alvo = tmp_path / "pasta-secreta-de-dados" / "playlist_cache.pkl"
    alvo.parent.mkdir()
    alvo.write_bytes(b"x")

    def negar(self, *args, **kwargs):
        raise PermissionError(f"sem permissão em {self} MENSAGEM-DO-SISTEMA")

    monkeypatch.setattr(Path, "unlink", negar)
    with caplog.at_level(logging.DEBUG):
        discard_legacy_cache(alvo)
    texto = " ".join(r.getMessage() for r in caplog.records)
    assert "playlist_cache.pkl" in texto and "PermissionError" in texto
    assert "pasta-secreta-de-dados" not in texto and "MENSAGEM-DO-SISTEMA" not in texto
    assert alvo.is_file() and pytest is not None
