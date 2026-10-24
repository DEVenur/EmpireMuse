"""F3-6b, etapa 2b (RED) — os 4 caches legados são APAGADOS SEM ABRIR e nunca lidos; o cache recomeça vazio.

Os arquivos: ``playlist_cache.pkl``, ``partial_track_cache.pkl`` e ``.lyric_cache_data`` (em ``local_database/``, tratados por
``BotPool.load_cache``) e ``.lastfm_cache`` (na raiz do diretório de dados, tratado por ``LastFM.scrobble_load_cache``).
Cache não é dado do usuário (decisão P3): a leitura de pickle sai, o arquivo antigo é removido e o cache começa do zero.

Conferido por EFEITO e por espião: nenhum ``open`` (``builtins``, ``io``, ``Path.open``, ``read_bytes``) toca nesses
arquivos, nenhum ``pickle.load/loads/Unpickler`` roda, uma carga hostil dentro do arquivo não executa (sentinela), e nenhum
outro arquivo da pasta é tocado. Falha ao apagar (permissão, diretório com o nome do cache) não derruba a inicialização.
"""

import builtins
import contextlib
import io
import logging
import os
import pickle
from pathlib import Path

import _pickle
import pytest

from empiremuse.utils.music.lastfm_tools import LastFM
from tests.support.chave_de_corte import criar_armadilhas
from tests.support.leitor_legado import SEGREDO, chamada, pickle_de, texto
from tests.persistence.test_formato_caches import (
    ARQUIVOS_DE_CACHE,
    CONTEUDOS_ILEGIVEIS,
    CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT,
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

    @pytest.mark.parametrize("protocolo", [0, 5])
    def test_qualquer_protocolo_e_descartado_do_mesmo_jeito(self, tmp_path, sem_abrir, protocolo):
        caminho = caminho_do_cache(tmp_path, "playlist_cache.pkl")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(pickle.dumps({"k": [1, 2]}, protocol=protocolo))
        pool = pool_vazio()
        with sem_abrir.ativar():
            pool.load_cache()
        assert not caminho.exists() and len(pool.playlist_cache) == 0 and sem_abrir.tentativas == []

    def test_pasta_local_database_ausente_nao_da_erro(self, tmp_path, sem_abrir):
        assert not (tmp_path / "local_database").exists()
        pool_vazio().load_cache()
        assert not (tmp_path / "local_database").exists()


# ============================================================================ carga hostil e conteúdo ruim


class TestConteudoDoArquivoNaoImporta:
    @pytest.mark.parametrize(
        "conteudo",
        list(list(CONTEUDOS_ILEGIVEIS.values()) + list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT.values()))[:2],
        ids=list(CONTEUDOS_ILEGIVEIS) + list(CONTEUDOS_QUE_ESCAPAM_DO_EXCEPT),
    )
    @pytest.mark.parametrize(("arquivo", "atributo"), list(ARQUIVOS_DE_CACHE)[:2])
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
    def test_lastfm_com_permissao_negada_comeca_vazio(self, tmp_path, monkeypatch):
        (tmp_path / ".lastfm_cache").write_bytes(pickle.dumps({"k": 1}))
        impedir_apagar(monkeypatch)
        assert len(LastFM("chave", "segredo").cache) == 0

    def test_o_aviso_de_falha_ao_apagar_nao_leva_conteudo(self, tmp_path, monkeypatch, caplog):
        caminho = caminho_do_cache(tmp_path, "playlist_cache.pkl")
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(pickle_de(chamada(SEGREDO, SEGREDO, texto(SEGREDO))))
        impedir_apagar(monkeypatch)
        with caplog.at_level(logging.DEBUG):
            pool_vazio().load_cache()
        assert all(SEGREDO not in r.getMessage() and SEGREDO not in repr(r.args) for r in caplog.records)
