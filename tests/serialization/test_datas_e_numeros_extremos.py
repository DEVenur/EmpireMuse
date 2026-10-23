"""F3-6b — número ou data extremo nunca escapa como ``OverflowError`` dos decodificadores (padrão achado na fila salva).

``time.time() - saved_at`` com um inteiro de centenas de dígitos (que o JSON aceita até 4300 dígitos) levanta
``OverflowError``; um ``saved_at`` fora de 0 a 9999-12-31 não é um instante. Um cache plantado assim não pode derrubar a
subida (``BotPool.load_cache`` e ``LastFM``), nem escapar de ``decode_cache`` fora de ``SchemaError``.
"""

import json

import pytest

from empiremuse.serialization import cache
from empiremuse.utils.music.json_cache import load_json_cache
from empiremuse.utils.music.lastfm_tools import LastFM
from tests.support.serializacao_nucleo import RANGE, falha

MIB = 1024 * 1024
EXTREMOS = [10**400, -(10**400), 10**30, -1, 253_402_300_800, 1e300, -1e300]


def documento(saved_at) -> bytes:
    return json.dumps({"v": 1, "saved_at": saved_at, "items": [{"k": "a", "d": 1}]}).encode()


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


class TestInstanteExtremo:
    @pytest.mark.parametrize("saved_at", EXTREMOS, ids=lambda v: repr(v)[:14])
    def test_decode_cache_recusa_como_erro_do_esquema(self, saved_at):
        erro = falha(cache.decode_cache, documento(saved_at), max_bytes=MIB, max_age=1800)
        assert (erro.path, erro.code) == ("saved_at", RANGE)

    @pytest.mark.parametrize("saved_at", [0, 1, 1_700_000_000, 1_700_000_000.5, 253_402_300_799])
    def test_instantes_dentro_do_intervalo_nao_sao_recusados(self, saved_at):
        assert cache.decode_cache(documento(saved_at), max_bytes=MIB, max_age=10**12, now=saved_at) == {"a": 1}

    @pytest.mark.parametrize("saved_at", EXTREMOS, ids=lambda v: repr(v)[:14])
    def test_o_arquivo_plantado_vira_cache_vazio_e_fica(self, tmp_path, saved_at):
        alvo = tmp_path / "cache.json"
        alvo.write_bytes(documento(saved_at))
        assert load_json_cache(alvo, max_bytes=MIB, max_age=1800) == {}
        assert alvo.is_file()

    @pytest.mark.parametrize("saved_at", EXTREMOS[:3], ids=lambda v: repr(v)[:14])
    def test_o_lastfm_sobe_com_o_arquivo_plantado(self, tmp_path, saved_at):
        (tmp_path / ".lastfm_cache.json").write_bytes(documento(saved_at))
        assert len(LastFM("chave", "segredo").cache) == 0

    @pytest.mark.parametrize("saved_at", EXTREMOS, ids=lambda v: repr(v)[:14])
    def test_gravar_com_instante_extremo_e_recusado_como_erro_do_esquema(self, saved_at):
        erro = falha(cache.encode_cache, [("a", 1)], max_bytes=MIB, saved_at=saved_at)
        assert (erro.path, erro.code) == ("saved_at", RANGE)
