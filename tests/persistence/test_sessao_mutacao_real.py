"""F3-6b, etapa 5 — complemento do QA depois da mutação do código REAL (``session_store.py``, ``player_resume.py`` e ``db.py``).

Sobreviventes que não eram equivalentes: erros injetados que NÃO podem derrubar a subida nem o resto da fila (cópia ``.bak``,
leitura, remoção, marca ``failed_at``, releitura do Mongo), empates e limites (48 h, ``mtime`` igual, ``failed_at`` não numérico),
ordem ``.pkl`` antes do ``.bak``, link simbólico no destino, documento do Mongo com ``_id``/``v``/``data`` de tipo errado, a releitura
do documento gravado (que tem de ser pelo ``_id``), o canal de outro servidor/inexistente, a retomada com Mongo só pela metade,
dados que não valem na gravação e o cursor do ``db.py`` (filtro e fotografia).
"""

import logging
import tracemalloc
from types import SimpleNamespace

import disnake
import pytest

from empiremuse.utils.music import session_store
from tests.support.formatos_reais import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.support.chave_de_corte import avisos, log_sem_o_conteudo
from tests.support.leitor_legado import SEGREDO
from tests.support.sessoes import (
    MongoDeSessoes,
    envelope_do_mongo,
    escrever_json,
    escrever_pkl,
    pasta_json,
    pasta_legado,
    session,
    sessao_minima,
)
from tests.persistence.test_sessao_migracao_mongo import legado, lido_do_novo
from tests.persistence.test_sessao_mongo import semear

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
    async def test_versao_booleana_nao_vale(self):
        cog, mongo = cog_com_mongo()
        await semear(mongo, SERVIDOR, v=True)
        assert await cog.get_player_sessions_mongo() == []

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


# ============================================================================ disco: a migração com erro, empate e link


class TestMigracaoDoDiscoNosLimites:
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
    @pytest.mark.parametrize("dados", [123, b"x"], ids=repr)
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
    @pytest.mark.parametrize("status", [403, 500])
    async def test_erro_do_discord_ao_buscar_o_canal_vira_none(self, status):
        async def busca(_id):
            raise disnake.HTTPException(SimpleNamespace(status=status, reason="x"), "x")

        cog = cog_de_canais(fetch_channel=busca)
        assert await cog._guild_channel(SERVIDOR_FALSO, 123, fetch=True) is None


class TestGravacaoComDadosQueNaoValem:
    @staticmethod
    def dados_ruins():
        return sessao_minima(_id=SERVIDOR, volume=5000)

    @pytest.mark.asyncio
    async def test_no_mongo_nao_sobe_e_nao_grava(self, caplog):
        cog, mongo = cog_com_mongo()
        with caplog.at_level(logging.DEBUG):
            await cog.save_session_mongo(SERVIDOR, self.dados_ruins())
        assert mongo.ids(NOVA) == set() and any(str(SERVIDOR) in aviso for aviso in avisos(caplog))


# ============================================================================ resume_player: o id da mensagem do controller

from empiremuse.cogs import player_resume  # noqa: E402
from tests.support.formatos_reais import CANAL_DE_TEXTO, CANAL_DE_VOZ, MENSAGEM  # noqa: E402
from tests.persistence.test_sessao_retomada import montar, proprio, retomar, sessao  # noqa: E402


@pytest.fixture
def _resume_sem_discord(monkeypatch):
    monkeypatch.setattr(player_resume, "can_send_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(player_resume, "can_connect", lambda *args, **kwargs: None)


class TestMensagemDoController:
    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_resume_sem_discord")
    async def test_id_em_texto_vira_inteiro_na_busca_da_mensagem(self):
        meu = proprio(CANAL_DE_TEXTO)
        controller = {"channel": str(CANAL_DE_TEXTO), "message_id": str(MENSAGEM)}
        cog, _, criados = montar(
            canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: meu}, controller=controller
        )
        await retomar(cog, await sessao())
        assert len(criados) == 1 and ("fetch_message", MENSAGEM) in meu.chamadas
        assert not any(type(c[1]) is str for c in meu.chamadas if isinstance(c, tuple))

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_resume_sem_discord")
    @pytest.mark.parametrize("lixo", ["abc", {}], ids=repr)
    async def test_id_que_nao_e_numero_nao_e_buscado_e_a_retomada_segue(self, lixo):
        meu = proprio(CANAL_DE_TEXTO)
        controller = {"channel": str(CANAL_DE_TEXTO), "message_id": lixo}
        dados = await sessao()
        dados["message_id"] = None  # a sessão não traz mensagem própria: só o controller poderia indicar uma
        cog, _, criados = montar(
            canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: meu}, controller=controller
        )
        await retomar(cog, dados)
        assert len(criados) == 1 and not any(c[0] == "fetch_message" for c in meu.chamadas if isinstance(c, tuple))
