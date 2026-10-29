"""Complemento do QA depois da mutação do código REAL (``session_store.py``, ``player_resume.py`` e ``db.py``).

Sobreviventes que não eram equivalentes: erros injetados que NÃO podem derrubar a subida nem o resto da fila (cópia ``.bak``,
leitura, remoção), documento do Mongo com ``_id``/``v``/``data`` de tipo errado, o canal de outro servidor/inexistente, a retomada
com Mongo só pela metade, dados que não valem na gravação e o cursor do ``db.py`` (filtro e fotografia).
"""

import logging
import tracemalloc
from types import SimpleNamespace

import disnake
import pytest

from empiremuse.utils.music import session_store
from tests.support.formatos_reais import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.support.avisos_no_log import avisos
from tests.support.serializacao_nucleo import SEGREDO
from tests.support.sessoes import (
    MongoDeSessoes,
    envelope_do_mongo,
    escrever_json,
    pasta_json,
    sessao_minima,
)
from tests.persistence.test_sessao_mongo import semear

NOVA = "player_sessions_json"
OUTRO = SERVIDOR + 7
MIB = 1024 * 1024


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def cog_com_mongo(**config):
    mongo = MongoDeSessoes()
    return cog_de_sessoes(mongo=mongo, **config), mongo


def falhar_quando(monkeypatch, nome, quando, erro):
    """Troca ``session_store.<nome>`` por uma cópia que levanta ``erro`` quando ``quando(*args)`` e, senão, chama o original."""
    original = getattr(session_store, nome)

    def trocada(*args, **kwargs):
        if quando(*args, **kwargs):
            raise erro
        return original(*args, **kwargs)

    monkeypatch.setattr(session_store, nome, trocada)


# ============================================================================ disco: gravação, leitura e remoção


class TestDiscoComErroInjetado:
    @pytest.mark.asyncio
    async def test_falha_so_na_copia_bak_nao_derruba_a_gravacao_e_o_aviso_nao_vaza(self, tmp_path, monkeypatch, caplog):
        falhar_quando(
            monkeypatch,
            "write_private_atomic",
            lambda caminho, *_: caminho.name.endswith(".bak"),
            OSError(f"disco cheio {SEGREDO}"),
        )
        with caplog.at_level(logging.DEBUG):
            await cog_de_sessoes().save_session_local(SERVIDOR, sessao_minima(_id=SERVIDOR))
        assert (pasta_json(tmp_path) / f"{SERVIDOR}.json").is_file()
        assert not (pasta_json(tmp_path) / f"{SERVIDOR}.json.bak").exists()
        assert any(str(SERVIDOR) in aviso and "Cópia" in aviso for aviso in avisos(caplog))
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)


# ============================================================================ Mongo: leitura de documento de tipo errado


class TestDocumentoDoMongoDeTipoErrado:
    @pytest.mark.asyncio
    async def test_bomba_de_compressao_para_no_teto_sem_inflar_na_memoria(self):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR)
        mongo.colecao(BOT_ID, NOVA)[str(SERVIDOR)]["data"] = envelope_do_mongo(b" " * (64 * MIB))
        tracemalloc.start()
        try:
            sessoes = await cog.get_player_sessions_mongo()
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert sessoes == [] and pico < 24 * MIB


# ============================================================================ cog: canal, gravação e remoção


# ============================================================================ resume_player: o id da mensagem do controller

from empiremuse.cogs import player_resume  # noqa: E402
from tests.support.formatos_reais import CANAL_DE_TEXTO, CANAL_DE_VOZ, MENSAGEM  # noqa: E402
from tests.persistence.test_sessao_retomada import montar, proprio, retomar, sessao  # noqa: E402
