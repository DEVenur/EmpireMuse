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
import pickle
import zlib
from datetime import datetime, timedelta, timezone

import pytest

from empiremuse.utils.music.errors import GenericError
from tests.support.formatos_reais import DONO, INSTANTE, SERVIDOR
from tests.support.serializacao_nucleo import falha, schema
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
    @pytest.mark.parametrize("data", DATAS_EXTREMAS)
    def test_decodificar_recusa_data_fora_do_intervalo_como_erro_do_esquema(self, data):
        erro = falha(queue.decode_saved_queue, json_com_data(data))
        assert erro.path == "created_at"

    @pytest.mark.parametrize("data", DATETIMES_EXTREMOS, ids=["ano-1", "ano-9999"])
    def test_codificar_recusa_datetime_fora_do_intervalo_como_erro_do_esquema(self, data):
        assert falha(queue.encode_saved_queue, faixas_validas(), data, SERVIDOR).path == "created_at"

    @pytest.mark.parametrize("data", DATETIMES_EXTREMOS, ids=["ano-1", "ano-9999"])
    def test_normalizar_o_legado_recusa_datetime_fora_do_intervalo(self, data):
        assert isinstance(falha(queue.normalize_legacy_queue, legado_com_data(data)), schema.SchemaError)

    def test_perto_do_limite_mas_dentro_do_intervalo_passa(self):
        assert lendo(json_com_data("0001-01-02T00:00:00+00:00"))["created_at"].year == 1


class TestLerFilaPlantada:
    @pytest.mark.asyncio
    async def test_json_com_data_extrema_vira_erro_claro_e_o_arquivo_fica(self, tmp_path):
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(json_com_data(DATAS_EXTREMAS[0]))
        with pytest.raises(GenericError) as erro:
            await saved_queue.load_saved_queue(DONO, SERVIDOR)
        assert "incompatível" in str(erro.value) and alvo.is_file()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("data", DATETIMES_EXTREMOS, ids=["ano-1", "ano-9999"])
    async def test_pkl_com_data_extrema_vira_erro_claro_e_o_arquivo_fica(self, tmp_path, data):
        pkl = escrever_pkl(tmp_path, legado_com_data(data))
        with pytest.raises(GenericError) as erro:
            await saved_queue.load_saved_queue(DONO, SERVIDOR)
        assert "incompatível" in str(erro.value) and pkl.is_file() and not caminho_json(tmp_path).exists()


class TestMigracaoNaInicializacaoComFilaPlantada:
    @pytest.mark.parametrize("data", DATETIMES_EXTREMOS, ids=["ano-1", "ano-9999"])
    def test_pkl_com_data_extrema_nao_derruba_a_migracao_e_fica(self, tmp_path, data):
        pkl = escrever_pkl(tmp_path, legado_com_data(data))
        assert saved_queue.migrate_saved_queues() == 0
        assert pkl.is_file() and not caminho_json(tmp_path).exists()

    def test_a_fila_plantada_nao_impede_a_migracao_das_outras(self, tmp_path):
        ruim = escrever_pkl(tmp_path, legado_com_data(DATETIMES_EXTREMOS[0]), usuario=DONO)
        boa = escrever_pkl(tmp_path, usuario=DONO + 1)
        assert saved_queue.migrate_saved_queues() == 1
        assert ruim.is_file() and not boa.exists() and caminho_json(tmp_path, DONO + 1).is_file()

    def test_json_existente_com_data_extrema_conta_como_invalido_e_o_pkl_valido_o_substitui(self, tmp_path):
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(json_com_data(DATAS_EXTREMAS[0]))
        pkl = escrever_pkl(tmp_path)
        assert saved_queue.migrate_saved_queues() == 1
        assert not pkl.exists() and lendo(alvo.read_bytes())["created_at"] == INSTANTE.astimezone(timezone.utc)

    def test_o_pkl_de_data_extrema_e_lido_pelo_leitor_legado_sem_executar_nada(self, tmp_path):
        """Controle: o pickle é bem-comportado; o problema não é o leitor legado, e sim a data."""
        conteudo = zlib.compress(pickle.dumps(legado_com_data(DATETIMES_EXTREMOS[0]), protocol=4))
        from empiremuse.serialization.legacy_pickle import load_legacy

        assert load_legacy(conteudo, "queue")["created_at"] == DATETIMES_EXTREMOS[0]
