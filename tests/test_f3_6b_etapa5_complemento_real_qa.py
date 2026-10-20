"""F3-6b, etapa 5 — complemento do QA depois da mutação do código REAL (``session_store.py``, ``player_resume.py`` e ``db.py``).

Sobreviventes que não eram equivalentes: erros injetados que NÃO podem derrubar a subida nem o resto da fila (cópia ``.bak``,
leitura, remoção, marca ``failed_at``, releitura do Mongo), empates e limites (48 h, ``mtime`` igual, ``failed_at`` não numérico),
ordem ``.pkl`` antes do ``.bak``, link simbólico no destino, documento do Mongo com ``_id``/``v``/``data`` de tipo errado, a releitura
do documento gravado (que tem de ser pelo ``_id``), o canal de outro servidor/inexistente, a retomada com Mongo só pela metade,
dados que não valem na gravação e o cursor do ``db.py`` (filtro e fotografia).
"""

import logging
import os
import time
import tracemalloc
import zlib
from types import SimpleNamespace

import disnake
import pytest

from empiremuse.utils.db import LocalDatabase
from empiremuse.utils.music import session_store
from tests.helpers_f3_6b import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.helpers_f3_6b_corte import avisos, log_sem_o_conteudo
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_sessao import (
    HORAS,
    MongoDeSessoes,
    com_idade,
    envelope_do_mongo,
    escrever_json,
    escrever_pkl,
    pasta_json,
    pasta_legado,
    session,
    sessao_minima,
)
from tests.test_f3_6b_etapa5_migracao_mongo import legado, lido_do_novo
from tests.test_f3_6b_etapa5_mongo import semear

NOVA, ANTIGA = "player_sessions_json", "player_sessions"
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

    @pytest.mark.asyncio
    async def test_arquivo_ilegivel_e_pulado_e_os_outros_voltam(self, tmp_path, monkeypatch, caplog):
        escrever_json(tmp_path, SERVIDOR, volume=11)
        escrever_json(tmp_path, OUTRO, volume=22)
        falhar_quando(
            monkeypatch, "read_capped", lambda caminho, *_: caminho.name == f"{SERVIDOR}.json", OSError(SEGREDO)
        )
        with caplog.at_level(logging.DEBUG):
            lidas = await cog_de_sessoes().get_player_sessions_local()
        assert [s["_id"] for s in lidas] == [OUTRO]
        assert any(f"{SERVIDOR}.json" in aviso for aviso in avisos(caplog))
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

    def test_apagar_o_que_nao_existe_nao_avisa_nada(self, caplog):
        with caplog.at_level(logging.DEBUG):
            session_store.delete_local_session(BOT_ID, SERVIDOR)
        assert avisos(caplog) == []

    def test_erro_ao_apagar_um_nao_impede_os_outros_e_nao_sobe(self, tmp_path, monkeypatch, caplog):
        escrever_json(tmp_path, SERVIDOR)
        escrever_pkl(tmp_path, SERVIDOR)
        original = type(pasta_json(tmp_path)).unlink

        def unlink(self, *args, **kwargs):
            if self.name == f"{SERVIDOR}.json":
                raise PermissionError(SEGREDO)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(type(pasta_json(tmp_path)), "unlink", unlink)
        with caplog.at_level(logging.DEBUG):
            session_store.delete_local_session(BOT_ID, SERVIDOR)  # nenhuma exceção
        assert (pasta_json(tmp_path) / f"{SERVIDOR}.json").is_file()
        assert not (pasta_legado(tmp_path) / f"{SERVIDOR}.pkl").exists()
        assert any(str(SERVIDOR) in aviso and "não removida" in aviso for aviso in avisos(caplog))
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)


# ============================================================================ Mongo: leitura de documento de tipo errado


class TestDocumentoDoMongoDeTipoErrado:
    @pytest.mark.asyncio
    async def test_id_inteiro_nao_vale(self):
        cog, mongo = cog_com_mongo()
        raw = session.encode_session(sessao_minima(_id=SERVIDOR))
        mongo.colecao(BOT_ID, NOVA)["a"] = {"_id": SERVIDOR, "v": 1, "data": envelope_do_mongo(raw)}
        assert await cog.get_player_sessions_mongo() == []

    @pytest.mark.asyncio
    async def test_versao_booleana_nao_vale(self):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR, v=True)
        assert await cog.get_player_sessions_mongo() == []

    @pytest.mark.asyncio
    async def test_id_que_nao_parece_servidor_nao_vai_para_o_log(self, caplog):
        cog, mongo = cog_com_mongo()
        mongo.colecao(BOT_ID, NOVA)[SEGREDO] = {"_id": SEGREDO, "v": 1, "data": "x"}
        with caplog.at_level(logging.DEBUG):
            assert await cog.get_player_sessions_mongo() == []
        assert avisos(caplog) and all(
            SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records
        )

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

    @pytest.mark.asyncio
    async def test_sem_mongo_na_configuracao_nao_le_nada_mesmo_com_banco_pendurado(self):
        cog, mongo = cog_com_mongo(MONGO="")
        await semear(mongo, SERVIDOR)
        assert await cog.get_player_sessions_mongo() == []
        assert mongo.eventos == []


# ============================================================================ disco: a migração com erro, empate e link


class TestMigracaoDoDiscoNosLimites:
    @pytest.mark.asyncio
    async def test_a_janela_e_de_48h_e_nao_de_49h(self, tmp_path):
        meio = escrever_pkl(tmp_path, SERVIDOR, bruto_=b"nao e uma sessao", horas=47)
        passou = escrever_pkl(tmp_path, OUTRO, bruto_=b"nao e uma sessao", horas=48.5)
        await cog_de_sessoes().migrate_legacy_sessions()
        assert meio.exists() and not passou.exists()

    @pytest.mark.asyncio
    async def test_json_com_o_mesmo_mtime_do_legado_o_legado_e_resto(self, tmp_path):
        pkl = escrever_pkl(tmp_path, SERVIDOR, horas=3)
        alvo = escrever_json(tmp_path, SERVIDOR, volume=5)
        os.utime(alvo, ns=(pkl.stat().st_mtime_ns, pkl.stat().st_mtime_ns))
        await cog_de_sessoes().migrate_legacy_sessions()
        assert not pkl.exists() and session.decode_session(alvo.read_bytes())["volume"] == 5

    @pytest.mark.asyncio
    async def test_destino_que_e_link_simbolico_nao_conta_como_json_valido(self, tmp_path):
        pkl = escrever_pkl(tmp_path, SERVIDOR, horas=3)
        pasta_json(tmp_path).mkdir(parents=True)
        real = pasta_json(tmp_path) / "alvo.dat"  # nome que a leitura não varre; o conteúdo vale para o servidor
        real.write_bytes(session.encode_session(sessao_minima(_id=SERVIDOR, volume=5)))
        destino = pasta_json(tmp_path) / f"{SERVIDOR}.json"
        destino.symlink_to(real)
        await cog_de_sessoes().migrate_legacy_sessions()
        assert not destino.is_symlink() and destino.is_file() and not pkl.exists()
        assert session.decode_session(destino.read_bytes(), expected_id=SERVIDOR)["volume"] != 5

    @pytest.mark.asyncio
    async def test_pkl_vale_antes_do_bak_quando_os_dois_convertem(self, tmp_path):
        escrever_pkl(tmp_path, SERVIDOR, sessao_minima_legada(volume=11))
        escrever_pkl(tmp_path, SERVIDOR, sessao_minima_legada(volume=22), ext=".bak")
        await cog_de_sessoes().migrate_legacy_sessions()
        lida = session.decode_session((pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes(), expected_id=SERVIDOR)
        assert lida["volume"] == 11

    @pytest.mark.asyncio
    async def test_erro_transitorio_de_leitura_do_pkl_nao_cai_para_o_bak_mais_velho(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path, SERVIDOR, sessao_minima_legada(volume=11))
        bak = escrever_pkl(tmp_path, SERVIDOR, sessao_minima_legada(volume=22), ext=".bak")
        falhar_quando(monkeypatch, "read_capped", lambda caminho, *_: caminho.suffix == ".pkl", OSError("disco"))
        await cog_de_sessoes().migrate_legacy_sessions()
        assert pkl.exists() and bak.exists() and not (pasta_json(tmp_path) / f"{SERVIDOR}.json").exists()

    @pytest.mark.asyncio
    async def test_falha_ao_gravar_o_json_nao_tenta_o_proximo_arquivo_e_nao_apaga_nada(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path, SERVIDOR, sessao_minima_legada(volume=11))
        bak = escrever_pkl(tmp_path, SERVIDOR, sessao_minima_legada(volume=22), ext=".bak")
        chamadas = []

        original = session_store.write_private_atomic

        def uma_falha(caminho, bruto):
            chamadas.append(caminho.name)
            if len(chamadas) == 1:
                raise OSError("disco cheio")
            return original(caminho, bruto)

        monkeypatch.setattr(session_store, "write_private_atomic", uma_falha)
        await cog_de_sessoes().migrate_legacy_sessions()
        assert chamadas == [f"{SERVIDOR}.json"] and pkl.exists() and bak.exists()
        assert not (pasta_json(tmp_path) / f"{SERVIDOR}.json").exists()

    @pytest.mark.asyncio
    async def test_gravacao_que_sai_ruim_e_apagada_e_o_legado_continua(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path, SERVIDOR)
        original = session_store.write_private_atomic

        def corrompe(caminho, bruto):
            return original(caminho, b'{"v": 1, "lixo"')

        monkeypatch.setattr(session_store, "write_private_atomic", corrompe)
        await cog_de_sessoes().migrate_legacy_sessions()
        assert pkl.exists() and not (pasta_json(tmp_path) / f"{SERVIDOR}.json").exists()

    @pytest.mark.asyncio
    async def test_erro_ao_descartar_o_velho_vira_aviso_proprio_e_nao_sobe(self, tmp_path, monkeypatch, caplog):
        velho = escrever_pkl(tmp_path, SERVIDOR, bruto_=b"nao e uma sessao", horas=60)
        original = type(velho).unlink

        def unlink(self, *args, **kwargs):
            if self.suffix == ".pkl":
                raise PermissionError(SEGREDO)
            return original(self, *args, **kwargs)

        monkeypatch.setattr(type(velho), "unlink", unlink)
        with caplog.at_level(logging.DEBUG):
            await cog_de_sessoes().migrate_legacy_sessions()
        assert velho.exists() and any("não descartada" in aviso for aviso in avisos(caplog))
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

    @pytest.mark.asyncio
    async def test_json_solto_na_pasta_do_legado_e_ignorado_sem_aviso(self, tmp_path, caplog):
        valido = escrever_json(
            tmp_path, SERVIDOR, volume=5
        )  # com um JSON válido do servidor, um "resto" mal agrupado quebraria
        pasta_legado(tmp_path).mkdir(parents=True)
        solto = pasta_legado(tmp_path) / f"{SERVIDOR}.json"
        solto.write_bytes(b"{}")
        with caplog.at_level(logging.DEBUG):
            await cog_de_sessoes().migrate_legacy_sessions()
        assert solto.read_bytes() == b"{}" and valido.is_file() and avisos(caplog) == []


def sessao_minima_legada(**mudancas):
    from tests.helpers_f3_6b_sessao import sessao_legada

    return sessao_legada(_id=SERVIDOR, **mudancas)


# ============================================================================ Mongo: a migração com erro e marca esquisita


class MongoQuePerde(MongoDeSessoes):
    """Aceita o ``update_data`` da coleção nova mas NÃO guarda (a gravação se perdeu); ``quem`` limita aos ids dados."""

    def __init__(self, quem=None, erro=None):
        super().__init__()
        self.quem, self.erro = quem, erro

    async def update_data(self, id_, data, *, db_name, collection, default_model=None):
        if collection == NOVA and (self.quem is None or str(id_) in self.quem):
            self.eventos.append(("update", collection, str(id_)))
            if self.erro is not None:
                raise self.erro
            return None
        return await super().update_data(id_, data, db_name=db_name, collection=collection, default_model=default_model)


class TestMigracaoDoMongoNosLimites:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("marca", [float("nan"), float("inf"), True, "ontem", None], ids=repr)
    async def test_failed_at_que_nao_e_um_numero_comum_e_remarcado_e_nao_apaga(self, marca):
        cog, mongo = cog_com_mongo()
        await legado(mongo, protocolo=3, failed_at=marca)
        await cog.migrate_legacy_sessions()
        documento = mongo.doc(ANTIGA, SERVIDOR)
        assert documento is not None and type(documento["failed_at"]) is float
        assert abs(documento["failed_at"] - time.time()) < 60

    @pytest.mark.asyncio
    @pytest.mark.parametrize("dados", [123, None, [1], {"a": 1}, b"x"], ids=repr)
    async def test_data_que_nao_e_texto_e_marcada_e_o_resto_da_fila_segue(self, dados):
        cog, mongo = cog_com_mongo()
        await mongo.update_data(SERVIDOR, {"data": dados}, db_name=BOT_ID, collection=ANTIGA)
        await legado(mongo, OUTRO)
        await cog.migrate_legacy_sessions()
        assert "failed_at" in mongo.doc(ANTIGA, SERVIDOR) and mongo.doc(ANTIGA, OUTRO) is None
        assert lido_do_novo(mongo, OUTRO)["_id"] == OUTRO

    @pytest.mark.asyncio
    async def test_erro_ao_marcar_nao_interrompe_o_resto_da_fila_e_nao_vaza(self, caplog):
        cog, mongo = cog_com_mongo()
        await legado(mongo, SERVIDOR, protocolo=3)
        await legado(mongo, OUTRO)
        mongo.falhas[f"update:{ANTIGA}"] = ConnectionError(SEGREDO)
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        assert mongo.doc(ANTIGA, SERVIDOR) is not None and mongo.doc(NOVA, OUTRO) is not None
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

    @pytest.mark.asyncio
    async def test_erro_ao_gravar_um_documento_nao_interrompe_os_outros_e_nao_marca(self, caplog):
        mongo = MongoQuePerde(quem={str(SERVIDOR)}, erro=ConnectionError(SEGREDO))
        cog = cog_de_sessoes(mongo=mongo)
        await legado(mongo, SERVIDOR)
        await legado(mongo, OUTRO)
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        documento = mongo.doc(ANTIGA, SERVIDOR)
        assert documento is not None and "failed_at" not in documento
        assert mongo.doc(ANTIGA, OUTRO) is None and mongo.doc(NOVA, OUTRO) is not None
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)

    @pytest.mark.asyncio
    async def test_a_releitura_e_pelo_id_gravacao_perdida_nao_apaga_o_legado(self, caplog):
        """Com outra sessão válida na coleção nova, uma releitura SEM filtro a confundiria com a gravada e apagaria o legado."""
        mongo = MongoQuePerde(quem={str(SERVIDOR)})
        cog = cog_de_sessoes(mongo=mongo)
        await semear(mongo, OUTRO)
        await legado(mongo, SERVIDOR)
        with caplog.at_level(logging.DEBUG):
            await cog.migrate_legacy_sessions()
        assert mongo.doc(ANTIGA, SERVIDOR) is not None and mongo.doc(NOVA, SERVIDOR) is None
        assert any(str(SERVIDOR) in aviso and "missing" in aviso for aviso in avisos(caplog))
        assert log_sem_o_conteudo.__name__  # o helper existe; o teste de vazamento está nos outros casos


# ============================================================================ cog: canal, gravação e remoção


def cog_de_canais(*, get_channel=None, fetch_channel=None):
    cog = cog_de_sessoes()

    async def sem_busca(_id):
        raise AssertionError("não era para buscar")

    cog.bot.get_channel = get_channel or (lambda _id: None)
    cog.bot.fetch_channel = fetch_channel or sem_busca
    return cog


SERVIDOR_FALSO = SimpleNamespace(id=SERVIDOR)


class TestCanalDaSessao:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [403, 404, 500])
    async def test_erro_do_discord_ao_buscar_o_canal_vira_none(self, status):
        async def busca(_id):
            raise disnake.HTTPException(SimpleNamespace(status=status, reason="x"), "x")

        cog = cog_de_canais(fetch_channel=busca)
        assert await cog._guild_channel(SERVIDOR_FALSO, 123, fetch=True) is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize("valor", ["abc", None, [], "1.5"], ids=repr)
    async def test_id_que_nao_e_numero_vira_none(self, valor):
        assert await cog_de_canais()._guild_channel(SERVIDOR_FALSO, valor, fetch=True) is None

    @pytest.mark.asyncio
    async def test_canal_do_mesmo_servidor_volta_e_o_de_outro_ou_sem_servidor_nao(self):
        canais = {
            1: SimpleNamespace(id=1, guild=SimpleNamespace(id=SERVIDOR)),
            2: SimpleNamespace(id=2, guild=SimpleNamespace(id=OUTRO)),
            3: SimpleNamespace(id=3),
        }
        cog = cog_de_canais(get_channel=canais.get)
        assert await cog._guild_channel(SERVIDOR_FALSO, 1) is canais[1]
        assert await cog._guild_channel(SERVIDOR_FALSO, 2) is None
        assert await cog._guild_channel(SERVIDOR_FALSO, 3) is None


class TestGravacaoComDadosQueNaoValem:
    @staticmethod
    def dados_ruins():
        return sessao_minima(_id=SERVIDOR, volume=5000)

    @pytest.mark.asyncio
    async def test_no_disco_nao_sobe_nao_grava_e_avisa_so_com_o_servidor(self, tmp_path, caplog):
        with caplog.at_level(logging.DEBUG):
            await cog_de_sessoes().save_session_local(SERVIDOR, self.dados_ruins())
        assert not (pasta_json(tmp_path) / f"{SERVIDOR}.json").exists()
        assert any(str(SERVIDOR) in aviso and "incompatíveis" in aviso for aviso in avisos(caplog))

    @pytest.mark.asyncio
    async def test_no_mongo_nao_sobe_e_nao_grava(self, caplog):
        cog, mongo = cog_com_mongo()
        with caplog.at_level(logging.DEBUG):
            await cog.save_session_mongo(SERVIDOR, self.dados_ruins())
        assert mongo.ids(NOVA) == set() and any(str(SERVIDOR) in aviso for aviso in avisos(caplog))

    @pytest.mark.asyncio
    async def test_mongo_na_metade_da_configuracao_a_remocao_vai_para_o_disco(self, tmp_path):
        cog, mongo = cog_com_mongo(MONGO="")
        cog.bot.config["PLAYER_SESSIONS_MONGODB"] = True
        alvo = escrever_json(tmp_path, SERVIDOR)
        await cog.delete_data(SERVIDOR)
        assert not alvo.exists() and mongo.eventos == []


# ============================================================================ db.py: o cursor do TinyMongo


class TestCursorDoBancoLocal:
    @pytest.mark.asyncio
    async def test_iter_data_respeita_o_filtro(self, tmp_path):
        banco = LocalDatabase(dir_=str(tmp_path))
        for n in range(20):
            await banco.update_data(id_=n, data={"par": n % 2 == 0}, db_name="guilds", collection="global")
        pares = [d async for d in banco.iter_data(db_name="guilds", collection="global", filter={"par": True})]
        assert len(pares) == 10 and all(d["par"] for d in pares)

    @pytest.mark.asyncio
    async def test_iter_data_aguenta_quem_apaga_enquanto_percorre(self, tmp_path):
        banco = LocalDatabase(dir_=str(tmp_path))
        for n in range(30):
            await banco.update_data(id_=n, data={"n": n}, db_name="guilds", collection="global")
        vistos = []
        async for documento in banco.iter_data(db_name="guilds", collection="global"):
            vistos.append(documento["_id"])
            await banco.delete_data(id_=documento["_id"], db_name="guilds", collection="global")
        assert len(vistos) == 30 and len(set(vistos)) == 30


def test_o_arquivo_compactado_do_teste_de_bomba_cabe():  # a bomba de 64 MiB comprimida é pequena (sanidade do teste)
    assert len(zlib.compress(b" " * (64 * MIB))) < 200 * 1024 and HORAS == 3600
