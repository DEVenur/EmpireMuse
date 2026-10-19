"""F3-6b, etapa 2b (RED) — os 4 caches legados são APAGADOS SEM ABRIR e nunca lidos; o cache recomeça vazio.

Os arquivos: ``playlist_cache.pkl``, ``partial_track_cache.pkl`` e ``.lyric_cache_data`` (em ``local_database/``, tratados por
``BotPool.load_cache``) e ``.lastfm_cache`` (na raiz do diretório de dados, tratado por ``LastFM.scrobble_load_cache``).
Cache não é dado do usuário (decisão P3): a leitura de pickle sai, o arquivo antigo é removido e o cache começa do zero.

Conferido por EFEITO e por espião: nenhum ``open`` (``builtins``, ``io``, ``Path.open``, ``read_bytes``) toca nesses
arquivos, nenhum ``pickle.load/loads/Unpickler`` roda, uma carga hostil dentro do arquivo não executa (sentinela), e nenhum
outro arquivo da pasta é tocado. Falha ao apagar (permissão, diretório com o nome do cache) não derruba a inicialização.
"""

import asyncio
import builtins
import contextlib
import io
import logging
import os
import pickle
from pathlib import Path

import _pickle
import pytest

from empiremuse.utils.client import BotPool
from empiremuse.utils.music.lastfm_tools import LastFM
from tests.helpers_f3_6b_corte import criar_armadilhas
from tests.helpers_f3_6b_legado import SEGREDO, chamada, pickle_de, texto
from tests.test_f3_6b_formato_caches import (
    ARQUIVOS_DE_CACHE,
    CONTEUDOS_ILEGIVEIS,
    CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT,
    PLAYLIST,
    RESPOSTA_DE_PLAYLIST,
    gravar_o_cache_de_playlist,
    pasta_dos_caches,
    pool_vazio,
)

NOMES_DOS_CACHES = {arquivo for arquivo, _ in ARQUIVOS_DE_CACHE} | {".lastfm_cache"}


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


@pytest.fixture
def armadilhas(tmp_path, monkeypatch):
    return criar_armadilhas(tmp_path, monkeypatch)


class Vigia:
    """Controle dos espiões: só vigia DENTRO de ``ativar()`` (assim o teste monta os arquivos sem tropeçar nele)."""

    def __init__(self):
        self.ativo = False
        self.tentativas: list[str] = []

    @contextlib.contextmanager
    def ativar(self):
        self.ativo = True
        try:
            yield self
        finally:
            self.ativo = False

    def registrar(self, descricao: str) -> None:
        self.tentativas.append(descricao)
        raise AssertionError(descricao)


@pytest.fixture
def sem_abrir(monkeypatch):
    """Dentro de ``ativar()``: falha se alguém ABRIR ou LER (por qualquer caminho comum) um cache, ou chamar ``pickle.load*``."""
    vigia = Vigia()

    def eh_cache(arquivo) -> bool:
        return isinstance(arquivo, (str, bytes, Path)) and Path(str(arquivo)).name in NOMES_DOS_CACHES

    def vigiar_funcao(original, nome):
        def vigiado(arquivo, *args, **kwargs):
            if vigia.ativo and eh_cache(arquivo):
                vigia.registrar(f"{nome} abriu {Path(str(arquivo)).name}")
            return original(arquivo, *args, **kwargs)

        return vigiado

    monkeypatch.setattr(builtins, "open", vigiar_funcao(builtins.open, "open"))
    monkeypatch.setattr(io, "open", vigiar_funcao(io.open, "io.open"))
    for nome in ("open", "read_bytes", "read_text"):
        original = getattr(Path, nome)

        def vigiado(self, *args, _original=original, _nome=nome, **kwargs):
            if vigia.ativo and self.name in NOMES_DOS_CACHES:
                vigia.registrar(f"Path.{_nome} tocou {self.name}")
            return _original(self, *args, **kwargs)

        monkeypatch.setattr(Path, nome, vigiado)

    def espiao(modulo, nome):
        def registrar(*args, **kwargs):
            vigia.registrar(f"{modulo.__name__}.{nome} foi chamado")

        return registrar

    for modulo, nome in (
        (pickle, "load"),
        (pickle, "loads"),
        (pickle, "_load"),
        (pickle, "_loads"),
        (_pickle, "load"),
        (_pickle, "loads"),
    ):
        monkeypatch.setattr(modulo, nome, espiao(modulo, nome))
    return vigia


def caminho_do_cache(tmp_path, arquivo) -> Path:
    return tmp_path / arquivo if arquivo == ".lastfm_cache" else pasta_dos_caches(tmp_path) / arquivo


# ============================================================================ apagados sem abrir, nunca lidos


class TestApagadosSemAbrir:
    @pytest.mark.parametrize(("arquivo", "atributo"), ARQUIVOS_DE_CACHE)
    def test_cache_do_pool_e_apagado_sem_ser_aberto_e_recomeca_vazio(self, tmp_path, sem_abrir, arquivo, atributo):
        caminho = caminho_do_cache(tmp_path, arquivo)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(pickle.dumps({PLAYLIST: RESPOSTA_DE_PLAYLIST}, protocol=4))
        pool = pool_vazio()
        with sem_abrir.ativar():
            pool.load_cache()
        assert not caminho.exists()
        assert all(len(getattr(pool, nome)) == 0 for _, nome in ARQUIVOS_DE_CACHE)
        assert sem_abrir.tentativas == []

    def test_os_tres_do_pool_de_uma_vez(self, tmp_path, sem_abrir):
        for arquivo, _ in ARQUIVOS_DE_CACHE:
            caminho = caminho_do_cache(tmp_path, arquivo)
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(pickle.dumps({"k": arquivo}))
        pool = pool_vazio()
        with sem_abrir.ativar():
            pool.load_cache()
        assert [a for a, _ in ARQUIVOS_DE_CACHE if caminho_do_cache(tmp_path, a).exists()] == []
        assert sem_abrir.tentativas == []

    def test_cache_do_lastfm_e_apagado_sem_ser_aberto_e_recomeca_vazio(self, tmp_path, sem_abrir):
        caminho = tmp_path / ".lastfm_cache"
        caminho.write_bytes(pickle.dumps({"A - B": {"name": "B", "artist": "A", "album": ""}}, protocol=4))
        with sem_abrir.ativar():
            cache = LastFM("chave", "segredo").cache
        assert len(cache) == 0
        assert not caminho.exists() and sem_abrir.tentativas == []

    @pytest.mark.parametrize("protocolo", [0, 1, 2, 3, 4, 5])
    def test_qualquer_protocolo_e_descartado_do_mesmo_jeito(self, tmp_path, sem_abrir, protocolo):
        caminho = caminho_do_cache(tmp_path, "playlist_cache.pkl")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(pickle.dumps({"k": [1, 2]}, protocol=protocolo))
        pool = pool_vazio()
        with sem_abrir.ativar():
            pool.load_cache()
        assert not caminho.exists() and len(pool.playlist_cache) == 0 and sem_abrir.tentativas == []

    def test_sem_arquivos_nao_faz_nada_e_nao_cria_nada(self, tmp_path, sem_abrir):
        pool = pool_vazio()
        with sem_abrir.ativar():
            pool.load_cache()
            LastFM("chave", "segredo")
        assert sem_abrir.tentativas == [] and list(tmp_path.iterdir()) == []

    def test_pasta_local_database_ausente_nao_da_erro(self, tmp_path, sem_abrir):
        assert not (tmp_path / "local_database").exists()
        pool_vazio().load_cache()
        assert not (tmp_path / "local_database").exists()

    def test_o_gravador_deixa_json_e_o_reinicio_nao_cria_nem_le_pkl(self, tmp_path):
        """Desde a etapa 6 o gravador escreve JSON; o ``.pkl`` antigo é que não é mais lido nem recriado."""
        pool = pool_vazio()
        pool.playlist_cache[PLAYLIST] = RESPOSTA_DE_PLAYLIST
        asyncio.run(gravar_o_cache_de_playlist(pool))
        assert not caminho_do_cache(tmp_path, "playlist_cache.pkl").exists()
        novo = pool_vazio()
        novo.load_cache()
        assert novo.playlist_cache.get(PLAYLIST) == RESPOSTA_DE_PLAYLIST
        assert not caminho_do_cache(tmp_path, "playlist_cache.pkl").exists()


# ============================================================================ carga hostil e conteúdo ruim


class TestConteudoDoArquivoNaoImporta:
    def test_carga_hostil_dentro_do_cache_nao_executa(self, tmp_path, armadilhas, sem_abrir):
        hostil = pickle_de(chamada("posix", "system", texto(f"touch {armadilhas.alvo}")))
        for arquivo, _ in ARQUIVOS_DE_CACHE:
            caminho = caminho_do_cache(tmp_path, arquivo)
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(hostil)
        (tmp_path / ".lastfm_cache").write_bytes(hostil)
        with sem_abrir.ativar():
            pool_vazio().load_cache()
            LastFM("chave", "segredo")
        assert armadilhas.intacto() and sem_abrir.tentativas == []
        assert not any(caminho_do_cache(tmp_path, nome).exists() for nome in NOMES_DOS_CACHES)

    @pytest.mark.parametrize(
        "conteudo",
        list(CONTEUDOS_ILEGIVEIS.values()) + list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT.values()),
        ids=list(CONTEUDOS_ILEGIVEIS) + list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT),
    )
    @pytest.mark.parametrize(("arquivo", "atributo"), ARQUIVOS_DE_CACHE)
    def test_conteudo_ilegivel_de_qualquer_tipo_nao_derruba_e_o_arquivo_some(
        self, tmp_path, sem_abrir, arquivo, atributo, conteudo
    ):
        caminho = caminho_do_cache(tmp_path, arquivo)
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        pool = pool_vazio()
        with sem_abrir.ativar():
            pool.load_cache()
        assert len(getattr(pool, atributo)) == 0 and not caminho.exists() and sem_abrir.tentativas == []

    @pytest.mark.parametrize(
        "conteudo", list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT.values()), ids=list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT)
    )
    def test_lastfm_com_conteudo_que_o_except_de_hoje_nao_cobre(self, tmp_path, sem_abrir, conteudo):
        (tmp_path / ".lastfm_cache").write_bytes(conteudo)
        with sem_abrir.ativar():
            cache = LastFM("chave", "segredo").cache
        assert len(cache) == 0
        assert not (tmp_path / ".lastfm_cache").exists()

    def test_o_conteudo_do_arquivo_nunca_vai_para_o_log(self, tmp_path, caplog, capsys):
        for arquivo, _ in ARQUIVOS_DE_CACHE:
            caminho = caminho_do_cache(tmp_path, arquivo)
            caminho.parent.mkdir(parents=True, exist_ok=True)
            caminho.write_bytes(pickle_de(chamada(SEGREDO, SEGREDO, texto(SEGREDO))))
        (tmp_path / ".lastfm_cache").write_bytes(pickle_de(chamada(SEGREDO, SEGREDO, texto(SEGREDO))))
        with caplog.at_level(logging.DEBUG):
            pool_vazio().load_cache()
            LastFM("chave", "segredo")
        saida = capsys.readouterr()
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)
        assert SEGREDO not in saida.out and SEGREDO not in saida.err


# ============================================================================ só os caches legados são apagados


class TestSoOsCachesLegadosSaem:
    OUTROS = [
        "playlist_cache.json",
        "playlist_cache.pkl.bak",
        "global.json",
        "1149485958480285756.json",
        ".tinymongo.lock",
        "partial_track_cache.json",
        ".lyric_cache_data.json",
        "playlist_cache.pkl2",
    ]

    def test_nenhum_outro_arquivo_da_pasta_e_tocado(self, tmp_path):
        pasta = pasta_dos_caches(tmp_path)
        for nome in self.OUTROS:
            (pasta / nome).write_text(f"conteudo de {nome}", encoding="utf-8")
        for pasta_extra in ("player_sessions", "saved_queues_v1"):
            (pasta / pasta_extra).mkdir()
            (pasta / pasta_extra / "x.pkl").write_bytes(b"x")
        (tmp_path / ".lastfm_cache.json").write_text("{}", encoding="utf-8")
        for arquivo, _ in ARQUIVOS_DE_CACHE:
            caminho_do_cache(tmp_path, arquivo).write_bytes(pickle.dumps({"k": 1}))
        (tmp_path / ".lastfm_cache").write_bytes(pickle.dumps({"k": 1}))
        pool_vazio().load_cache()
        LastFM("chave", "segredo")
        for nome in self.OUTROS:
            assert (pasta / nome).read_text(encoding="utf-8") == f"conteudo de {nome}"
        assert (pasta / "player_sessions" / "x.pkl").is_file() and (pasta / "saved_queues_v1" / "x.pkl").is_file()
        assert (tmp_path / ".lastfm_cache.json").is_file()

    def test_o_cache_de_playlist_nao_e_apagado_a_cada_gravacao(self, tmp_path):
        """Só o ``load_cache`` (na subida) remove os arquivos antigos; o ``cache_updater`` grava o JSON a cada volta."""
        pool = pool_vazio()
        pool.playlist_cache["k"] = [1]
        asyncio.run(gravar_o_cache_de_playlist(pool))
        asyncio.run(gravar_o_cache_de_playlist(pool))
        assert (pasta_dos_caches(tmp_path) / "playlist_cache.json").is_file()

    def test_o_lastfm_grava_na_raiz_em_json(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["x"] = {}
        lastfm.scrobble_save_cache()
        assert (tmp_path / ".lastfm_cache.json").is_file() and not (tmp_path / ".lastfm_cache").exists()


# ============================================================================ falha ao apagar não derruba a inicialização


def impedir_apagar(monkeypatch):
    def negar(*args, **kwargs):
        raise PermissionError("negado")

    monkeypatch.setattr(Path, "unlink", negar)
    monkeypatch.setattr(os, "remove", negar)
    monkeypatch.setattr(os, "unlink", negar)


class TestFalhaAoApagar:
    def test_permissao_negada_ao_apagar_nao_derruba_e_o_cache_fica_vazio(self, tmp_path, monkeypatch):
        caminho = caminho_do_cache(tmp_path, "playlist_cache.pkl")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(pickle.dumps({"k": 1}))
        impedir_apagar(monkeypatch)
        pool = pool_vazio()
        pool.load_cache()
        assert len(pool.playlist_cache) == 0 and caminho.exists()

    def test_lastfm_com_permissao_negada_comeca_vazio(self, tmp_path, monkeypatch):
        (tmp_path / ".lastfm_cache").write_bytes(pickle.dumps({"k": 1}))
        impedir_apagar(monkeypatch)
        assert len(LastFM("chave", "segredo").cache) == 0

    def test_diretorio_com_o_nome_do_cache_nao_derruba(self, tmp_path):
        (pasta_dos_caches(tmp_path) / "playlist_cache.pkl").mkdir()
        (tmp_path / ".lastfm_cache").mkdir()
        pool = pool_vazio()
        pool.load_cache()
        assert len(pool.playlist_cache) == 0 and len(LastFM("chave", "segredo").cache) == 0

    def test_o_aviso_de_falha_ao_apagar_nao_leva_conteudo(self, tmp_path, monkeypatch, caplog):
        caminho = caminho_do_cache(tmp_path, "playlist_cache.pkl")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(pickle_de(chamada(SEGREDO, SEGREDO, texto(SEGREDO))))
        impedir_apagar(monkeypatch)
        with caplog.at_level(logging.DEBUG):
            pool_vazio().load_cache()
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)


# ============================================================================ a construção do BotPool também descarta


def test_a_construcao_do_botpool_chama_o_mesmo_descarte():
    """O ``BotPool.__init__`` chama ``load_cache`` (inalterado): o descarte vale já na subida do processo."""
    import ast

    from tests.test_f3_6b_inventario_pickle import PACOTE

    arvore = ast.parse((PACOTE / "utils" / "client.py").read_text(encoding="utf-8"))
    chamadas = [
        no.func.attr
        for classe in ast.walk(arvore)
        if isinstance(classe, ast.ClassDef) and classe.name == "BotPool"
        for no in ast.walk(classe)
        if isinstance(no, ast.Call)
        and isinstance(no.func, ast.Attribute)
        and isinstance(no.func.value, ast.Name)
        and no.func.value.id == "self"
    ]
    assert "load_cache" in chamadas and hasattr(BotPool, "load_cache")
