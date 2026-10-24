"""F3-6b, etapa 4 (RED do QA, achado da revisão) — data extrema da fila salva não pode escapar como ``OverflowError``.

``created_at`` é um ISO com offset ou um ``datetime`` do ``.pkl`` legado. ``astimezone(utc)`` de um instante perto de
``0001-01-01`` ou de ``9999-12-31`` com offset levanta ``OverflowError`` (não é ``ValueError`` nem ``SchemaError``). Um arquivo
plantado assim hoje:

* derruba a subida do bot: ``BotPool.setup`` chama ``migrate_saved_queues()`` sem proteção e a migração só captura
  ``OSError`` e ``SchemaError``;
* vira exceção crua em ``Music.play`` (em vez do ``GenericError`` "incompatível").

Esperado: ``SchemaError`` (nenhum código fixado além de ser do núcleo), ``GenericError`` ao tocar, arquivo mantido, e a
migração segue para os outros arquivos.
"""

import json
from datetime import datetime, timedelta, timezone

import pytest

from empiremuse.utils.music.errors import GenericError
from tests.support.formatos_reais import DONO, INSTANTE, SERVIDOR
from tests.support.serializacao_nucleo import falha
from tests.persistence.test_fila_salva import (
    _ambiente,  # noqa: F401 - fixture autouse do arquivo base (EMPIREMUSE_HOME e relógio fixo)
    caminho_json,
    codificar,
    escrever_pkl,
    faixas_validas,
    lendo,
    queue,
    saved_queue,
)

MAIS_CINCO = timezone(timedelta(hours=5))
MENOS_CINCO = timezone(timedelta(hours=-5))
DATAS_EXTREMAS = ["0001-01-01T00:00:00+05:00", "9999-12-31T23:59:59-05:00", "0001-01-01T00:00:00.000001+14:00"]
DATETIMES_EXTREMOS = [
    datetime(1, 1, 1, tzinfo=MAIS_CINCO),
    datetime(9999, 12, 31, 23, 59, 59, tzinfo=MENOS_CINCO),
]


def json_com_data(texto: str) -> bytes:
    base = json.loads(codificar())
    base["created_at"] = texto
    return json.dumps(base).encode()


def legado_com_data(data) -> dict:
    return {"tracks": faixas_validas(), "created_at": data, "guild_id": SERVIDOR}


class TestEsquema:
    @pytest.mark.parametrize("data", DATETIMES_EXTREMOS, ids=["ano-1", "ano-9999"])
    def test_codificar_recusa_datetime_fora_do_intervalo_como_erro_do_esquema(self, data):
        assert falha(queue.encode_saved_queue, faixas_validas(), data, SERVIDOR).path == "created_at"


class TestLerFilaPlantada:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", DATETIMES_EXTREMOS, ids=["ano-1", "ano-9999"])
    async def test_pkl_com_data_extrema_vira_erro_claro_e_o_arquivo_fica(self, tmp_path, data):
        pkl = escrever_pkl(tmp_path, legado_com_data(data))
        with pytest.raises(GenericError) as erro:
            await saved_queue.load_saved_queue(DONO, SERVIDOR)
        assert "incompatível" in str(erro.value) and pkl.is_file() and not caminho_json(tmp_path).exists()


class TestMigracaoNaInicializacaoComFilaPlantada:
    def test_json_existente_com_data_extrema_conta_como_invalido_e_o_pkl_valido_o_substitui(self, tmp_path):
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(json_com_data(DATAS_EXTREMAS[0]))
        pkl = escrever_pkl(tmp_path)
        assert saved_queue.migrate_saved_queues() == 1
        assert not pkl.exists() and lendo(alvo.read_bytes())["created_at"] == INSTANTE.astimezone(timezone.utc)
