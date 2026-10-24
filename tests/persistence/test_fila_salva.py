"""F3-6b, etapa 4 (RED do Backend) — a fila salva do usuário em JSON: esquema, gravação atômica, leitura e migração do ``.pkl``.

* ``empiremuse/serialization/queue.py``: ``encode_saved_queue``, ``decode_saved_queue`` e ``normalize_legacy_queue``
  (documento ``{"v": 1, "tracks": [...], "created_at": ISO com offset, "guild_id": int}`` de até 4 MiB e 5 000 faixas);
* ``Music.save_queue`` grava ``local_database/saved_queues_json/users/<id>.json`` (0600, escrita atômica) e remove o ``.pkl``
  antigo do mesmo usuário; ``Music.play`` lê o JSON e, se só houver o ``.pkl`` legado, lê por ``load_legacy``, grava o JSON e
  só então apaga o ``.pkl``; a migração também roda na inicialização (``BotPool.setup``);
* fila ilegível (JSON ou ``.pkl``) vira ``GenericError`` com "incompatível" e o arquivo FICA.
"""

import copy
import importlib
import json
import logging
import os
import pickle
import time
import zlib
from datetime import datetime, timezone
from pathlib import Path

import disnake
import pytest

from empiremuse.utils.music.errors import GenericError
from tests.support.formatos_reais import DONO, INSTANTE, SERVIDOR, faixa_youtube
from tests.support.chave_de_corte import espionar_load_legacy
from tests.support.leitor_legado import SEGREDO
from tests.support.serializacao_nucleo import LENGTH, MISSING, RANGE, TYPE, falha, vazamentos
from tests.support.formato_fila_salva import (
    caminho_da_fila,
    infos,
    montar_leitura,
    salvar,
    tres_faixas,
)

pytestmark = pytest.mark.critical

UTC = timezone.utc


class _Modulo:
    """Importa sob demanda: sem o módulo cada teste falha no corpo, nunca na coleta."""

    def __init__(self, nome):
        self._nome = nome

    def __getattr__(self, atributo):
        return getattr(importlib.import_module(self._nome), atributo)


queue = _Modulo("empiremuse.serialization.queue")
files = _Modulo("empiremuse.serialization.files")
saved_queue = _Modulo("empiremuse.utils.music.saved_queue")


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def caminho_json(tmp_path, usuario=DONO) -> Path:
    return tmp_path / "local_database" / "saved_queues_json" / "users" / f"{usuario}.json"


def faixas_validas(quantas=3) -> list[dict]:
    resultado = []
    for n in range(quantas):
        faixa = faixa_youtube(n)
        faixa.info["id"] = faixa.id
        resultado.append(copy.deepcopy(faixa.info))
    return resultado


def codificar(faixas=None, criada=INSTANTE, servidor=SERVIDOR) -> bytes:
    return queue.encode_saved_queue(faixas_validas() if faixas is None else faixas, criada, servidor)


def documento(**mudancas) -> bytes:
    """JSON de uma fila com ``mudancas`` aplicadas por cima de um documento válido (para os casos ruins)."""
    base = json.loads(codificar())
    base.update(mudancas)
    return json.dumps(base, ensure_ascii=False).encode()


def lendo(raw: bytes):
    return queue.decode_saved_queue(raw)


# ============================================================================ o esquema


class TestCodificar:
    @pytest.mark.smoke
    def test_e_json_compacto_em_utf8_e_nao_pickle(self):
        bruto = codificar()
        assert bruto[:1] == b"{" and b"\\u" not in bruto and b": " not in bruto

    def test_data_sem_fuso_e_recusada(self):
        assert falha(codificar, criada=datetime(2026, 1, 1)).path == "created_at"

    def test_faixa_com_playlist_e_id_vazio_e_campos_desconhecidos_passam(self):
        faixas = faixas_validas()
        faixas[0]["playlist"] = {"name": "Minha Playlist", "url": "https://exemplo.invalid/playlist/1"}
        faixas[1]["id"] = ""
        faixas[2]["campo_novo"] = {"a": [1, 2]}
        assert lendo(codificar(faixas))["tracks"] == faixas

    def test_letra_grande_demais_e_descartada_e_a_fila_ainda_e_salva(self):
        faixas = faixas_validas()
        faixas[0]["extra"]["lyrics"] = {"lines": [{"text": "x"}] * 6000}
        lidas = lendo(codificar(faixas))["tracks"]
        assert "lyrics" not in lidas[0]["extra"] and lidas[0]["title"] == faixas[0]["title"]

    def test_o_erro_leva_o_caminho_e_nao_o_valor(self):
        faixas = faixas_validas()
        faixas[1]["title"] = SEGREDO.encode()
        erro = falha(codificar, faixas)
        assert erro.path == "tracks[1].title" and erro.code == TYPE and not vazamentos(erro)


class TestDecodificar:
    def test_o_limite_de_5000_faixas(self):
        base = faixas_validas(1)[0]
        assert len(lendo(codificar([copy.deepcopy(base) for _ in range(5000)]))["tracks"]) == 5000
        assert falha(codificar, [copy.deepcopy(base) for _ in range(5001)]).code == LENGTH

    @pytest.mark.parametrize(
        ("campo", "valor", "codigo"),
        [
            ("guild_id", -1, RANGE),
            ("tracks", [], LENGTH),
        ],
    )
    def test_campos_ruins_da_raiz(self, campo, valor, codigo):
        erro = falha(lendo, documento(**{campo: valor}))
        assert erro.path == campo and erro.code == codigo

    def test_faixa_sem_titulo_ou_sem_fonte_e_recusada(self):
        for campo in ("title", "sourceName"):
            bruto = json.loads(codificar())
            del bruto["tracks"][0][campo]
            erro = falha(lendo, json.dumps(bruto).encode())
            assert erro.code == MISSING and erro.path == f"tracks[0].{campo}"

    def test_requester_pode_ser_inteiro_ou_texto_mas_nao_bool(self):
        for bom in (DONO, "usuário"):
            bruto = json.loads(codificar())
            bruto["tracks"][0]["extra"]["requester"] = bom
            assert lendo(json.dumps(bruto).encode())["tracks"][0]["extra"]["requester"] == bom
        for ruim in (True, 1.5, None, [1], -4):
            bruto = json.loads(codificar())
            bruto["tracks"][0]["extra"]["requester"] = ruim
            assert falha(lendo, json.dumps(bruto).encode()).path.startswith("tracks[0].extra")

    def test_nada_do_conteudo_vaza_no_erro(self):
        bruto = json.loads(codificar())
        bruto["tracks"][0]["title"] = SEGREDO + "\ud800"
        assert not vazamentos(falha(lendo, json.dumps(bruto).encode()))


class TestLegado:
    def legado(self, **mudancas):
        base = {"tracks": faixas_validas(), "created_at": INSTANTE, "guild_id": SERVIDOR}
        base.update(mudancas)
        return base

    def test_data_sem_fuso_do_legado_conta_como_utc(self):
        convertido = queue.normalize_legacy_queue(self.legado(created_at=datetime(2026, 1, 1)))
        assert convertido["created_at"] == datetime(2026, 1, 1, tzinfo=UTC)

    def test_legado_sem_faixas_ou_com_campo_ruim_e_recusado(self):
        assert falha(queue.normalize_legacy_queue, {"created_at": INSTANTE, "guild_id": 1}).code == MISSING
        assert falha(queue.normalize_legacy_queue, self.legado(guild_id="x")).code == TYPE


# ============================================================================ gravação atômica e privada


class TestArquivosPrivados:
    def test_substitui_o_arquivo_existente_de_uma_vez(self, tmp_path):
        alvo = tmp_path / "x.json"
        alvo.write_bytes(b"antigo")
        files.write_private_atomic(alvo, b"novo")
        assert alvo.read_bytes() == b"novo"


def negar(*args, **kwargs):
    raise OSError("negado")


# ============================================================================ Music.save_queue


class TestSalvar:
    @pytest.mark.asyncio
    async def test_menos_de_3_faixas_continua_sem_gravar(self, tmp_path):
        with pytest.raises(GenericError, match="mínimo 3"):
            await salvar(tres_faixas()[1:2], atual=tres_faixas()[0])
        assert not caminho_json(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_fila_que_o_esquema_recusa_vira_erro_claro_e_nao_grava(self, tmp_path, caplog):
        faixas = tres_faixas()
        faixas[1].info["title"] = SEGREDO.encode()
        with caplog.at_level(logging.DEBUG), pytest.raises(GenericError, match="(?i)não foi possível") as erro:
            await salvar(faixas[1:], atual=faixas[0])
        assert SEGREDO not in erro.value.text and not caminho_json(tmp_path).exists()
        assert all(SEGREDO not in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_falha_ao_gravar_deixa_o_json_anterior_e_diz_o_erro(self, tmp_path, monkeypatch):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        antes = caminho_json(tmp_path).read_bytes()
        monkeypatch.setattr(files.os, "replace", negar)
        with pytest.raises(GenericError, match="(?i)não foi possível"):
            await salvar(faixas[1:], atual=faixas[0])
        assert caminho_json(tmp_path).read_bytes() == antes


# ============================================================================ Music.play


def escrever_pkl(tmp_path, conteudo=None, protocolo=4, usuario=DONO):
    if conteudo is None:
        faixas = tres_faixas()
        for faixa in faixas:
            faixa.info["id"] = faixa.id
        conteudo = {"tracks": infos(faixas), "created_at": INSTANTE, "guild_id": SERVIDOR}
    alvo = caminho_da_fila(tmp_path, usuario)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(zlib.compress(pickle.dumps(conteudo, protocol=protocolo)))
    return alvo


class TestLer:
    @pytest.mark.asyncio
    async def test_le_o_json_sem_passar_pelo_leitor_legado(self, tmp_path, monkeypatch):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        chamadas = espionar_load_legacy(monkeypatch)
        lidas = await montar_leitura(monkeypatch, None)()
        assert chamadas == [] and [f.info["title"] for f in lidas] == [f.info["title"] for f in faixas]

    @pytest.mark.asyncio
    async def test_o_json_vale_mais_que_o_pkl_antigo_quando_os_dois_existem(self, tmp_path, monkeypatch):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        escrever_pkl(tmp_path)
        chamadas = espionar_load_legacy(monkeypatch)
        assert len(await montar_leitura(monkeypatch, None)()) == 3 and chamadas == []


class TestMigracaoNoPrimeiroAcesso:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [0, 3])
    async def test_pkl_de_protocolo_antigo_continua_recusado_e_o_arquivo_fica(self, tmp_path, monkeypatch, protocolo):
        pkl = escrever_pkl(tmp_path, protocolo=protocolo)
        with pytest.raises(GenericError, match="incompatível"):
            await montar_leitura(monkeypatch, None).rodar()
        assert pkl.is_file() and not caminho_json(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_falha_ao_gravar_o_json_ainda_entrega_a_fila_e_mantem_o_pkl(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)
        monkeypatch.setattr(files.os, "replace", negar)
        lidas = await montar_leitura(monkeypatch, None)()
        assert len(lidas) == 3 and pkl.is_file() and not caminho_json(tmp_path).exists()


# ============================================================================ migração na inicialização


class TestMigracaoNaInicializacao:
    def test_converte_os_pkl_validos_e_apaga_depois_de_reler_o_json(self, tmp_path):
        a = escrever_pkl(tmp_path, usuario=DONO)
        b = escrever_pkl(tmp_path, usuario=DONO + 1)
        assert saved_queue.migrate_saved_queues() == 2
        assert not a.exists() and not b.exists()
        for usuario in (DONO, DONO + 1):
            assert len(lendo(caminho_json(tmp_path, usuario).read_bytes())["tracks"]) == 3

    def test_nome_de_arquivo_fora_do_padrao_e_ignorado(self, tmp_path):
        pasta = caminho_da_fila(tmp_path).parent
        pasta.mkdir(parents=True)
        conteudo = zlib.compress(
            pickle.dumps({"tracks": faixas_validas(), "created_at": INSTANTE, "guild_id": 1}, protocol=4)
        )
        nomes = ("abc.pkl", "12 3.pkl", ".pkl", "1" * 25 + ".pkl", "12.pkl.bak", "12.txt", "١٢٣.pkl")
        for nome in nomes:
            (pasta / nome).write_bytes(conteudo)
        assert saved_queue.migrate_saved_queues() == 0
        assert len(list(pasta.iterdir())) == len(nomes)
        assert not (tmp_path / "local_database" / "saved_queues_json").exists()

    def test_json_mais_novo_vence_e_o_pkl_velho_e_apagado(self, tmp_path):
        pkl = escrever_pkl(tmp_path)
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(codificar(faixas_validas(4)))
        agora = time.time()
        os.utime(pkl, (agora - 100, agora - 100))
        os.utime(alvo, (agora, agora))
        saved_queue.migrate_saved_queues()
        assert not pkl.exists() and len(lendo(alvo.read_bytes())["tracks"]) == 4


# ============================================================================ onde a existência da fila é testada


class TestExistenciaDaFila:
    def test_json_ou_pkl_contam_e_nada_nao(self, tmp_path):
        assert saved_queue.has_saved_queue(DONO) is False
        escrever_pkl(tmp_path)
        assert saved_queue.has_saved_queue(DONO) is True
        caminho_da_fila(tmp_path).unlink()
        assert saved_queue.has_saved_queue(DONO) is False
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(codificar())
        assert saved_queue.has_saved_queue(DONO) is True
