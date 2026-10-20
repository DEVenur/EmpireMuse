"""F3-6b, etapa 4 — complemento do QA depois da mutação do código real (sobreviventes que não eram equivalentes).

* ``decode_saved_queue`` devolve a data em UTC (não no fuso do arquivo) e sem o ``v``;
* ``encode_saved_queue`` recusa ``guild_id`` ruim e fila vazia (o que ele grava tem de ser legível pelo ``decode``);
* a migração relê o JSON gravado: se ele saiu corrompido, o ``.pkl`` FICA e a fila ainda é entregue;
* ``.pkl`` que é link simbólico não é migrado (nem lido) na inicialização;
* ``write_private_atomic`` apaga o temporário também para falha que não seja ``OSError``.
"""

import json
import os
from datetime import datetime, timedelta, timezone

import pytest

from empiremuse.serialization import files
from empiremuse.utils.music import saved_queue as modulo_real
from tests.helpers_f3_6b import DONO, INSTANTE, SERVIDOR
from tests.helpers_f3_6b_serializacao import LENGTH, RANGE, TYPE, falha
from tests.test_f3_6b_etapa4_fila import (
    _ambiente,  # noqa: F401 - fixture autouse do arquivo base (EMPIREMUSE_HOME e relógio fixo)
    caminho_json,
    codificar,
    escrever_pkl,
    faixas_validas,
    lendo,
    queue,
    saved_queue,
)
from tests.test_f3_6b_formato_fila_salva import caminho_da_fila

UTC = timezone.utc


class TestDecodificarNormaliza:
    def test_a_data_de_outro_fuso_volta_em_utc(self):
        base = json.loads(codificar())
        base["created_at"] = "2026-10-19T11:03:22-03:00"
        lida = lendo(json.dumps(base).encode())["created_at"]
        assert lida == datetime(2026, 10, 19, 14, 3, 22, tzinfo=UTC) and lida.utcoffset() == timedelta(0)

    def test_o_resultado_nao_leva_o_campo_v(self):
        assert set(lendo(codificar())) == {"tracks", "created_at", "guild_id"}


class TestCodificarRecusa:
    @pytest.mark.parametrize(
        ("servidor", "codigo"),
        [("abc", TYPE), (True, TYPE), (None, TYPE), (-1, RANGE), (2**63, RANGE)],
        ids=["texto", "bool", "none", "negativo", "acima-do-snowflake"],
    )
    def test_guild_id_ruim(self, servidor, codigo):
        erro = falha(queue.encode_saved_queue, faixas_validas(), INSTANTE, servidor)
        assert (erro.path, erro.code) == ("guild_id", codigo)

    def test_fila_vazia_nao_vira_um_documento_que_o_decodificador_recusa(self):
        erro = falha(queue.encode_saved_queue, [], INSTANTE, SERVIDOR)
        assert (erro.path, erro.code) == ("tracks", LENGTH)


class TestMigracaoRelendoOJson:
    @staticmethod
    def gravar_lixo(caminho, dados):
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(b'{"v": 1, "lixo"')

    @pytest.mark.asyncio
    async def test_json_gravado_corrompido_mantem_o_pkl_e_ainda_entrega_a_fila(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)
        monkeypatch.setattr(modulo_real, "write_private_atomic", self.gravar_lixo)
        dados = await saved_queue.load_saved_queue(DONO, SERVIDOR)
        assert len(dados["tracks"]) == 3 and pkl.is_file()

    def test_na_inicializacao_json_gravado_corrompido_mantem_o_pkl(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)
        monkeypatch.setattr(modulo_real, "write_private_atomic", self.gravar_lixo)
        assert saved_queue.migrate_saved_queues() == 0
        assert pkl.is_file()


class TestLinkSimbolicoNaMigracao:
    def test_pkl_que_e_link_nao_e_migrado_nem_apagado(self, tmp_path):
        alvo_real = escrever_pkl(tmp_path, usuario=DONO + 7)
        fora = tmp_path / "fora" / "real.pkl"
        fora.parent.mkdir()
        fora.write_bytes(alvo_real.read_bytes())
        link = caminho_da_fila(tmp_path, DONO)
        os.symlink(fora, link)
        assert saved_queue.migrate_saved_queues() == 1  # só o arquivo de verdade (DONO + 7)
        assert link.is_symlink() and fora.is_file() and not caminho_json(tmp_path, DONO).exists()
        assert caminho_json(tmp_path, DONO + 7).is_file()


class TestGravacaoAtomica:
    def test_falha_que_nao_e_oserror_tambem_apaga_o_temporario_e_deixa_o_antigo(self, tmp_path, monkeypatch):
        alvo = tmp_path / "dados" / "x.json"
        files.write_private_atomic(alvo, b"antigo")

        def quebrar(*args, **kwargs):
            raise RuntimeError("falha qualquer")

        monkeypatch.setattr(os, "replace", quebrar)
        with pytest.raises(RuntimeError):
            files.write_private_atomic(alvo, b"novo")
        assert alvo.read_bytes() == b"antigo" and [p.name for p in alvo.parent.iterdir()] == ["x.json"]
