"""F3-6b, etapa 6 — achado do AppSec: o cache do Last.fm não pode ser gravado (com ``fsync``) dentro do laço de eventos.

``scrobble_save_cache`` continua síncrono (para quem não está numa corrotina); o cog, que o chamava direto de dentro de
corrotinas, passa a usar ``scrobble_save_cache_async``, que tira a cópia dos itens no laço e grava em ``run_in_executor``.
"""

import ast
import json
import logging
import threading
from pathlib import Path

import pytest

from empiremuse.utils.music import lastfm_tools
from empiremuse.utils.music.lastfm_tools import LastFM
from tests.support.raiz import RAIZ

ENTRADA = {"name": "Música", "artist": "Artista", "album": "Álbum"}


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


class TestGravacaoForaDoLaco:
    @pytest.mark.asyncio
    async def test_a_versao_assincrona_grava_o_mesmo_arquivo(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["A - B"] = ENTRADA
        lastfm.cache["Sem - X"] = {}
        await lastfm.scrobble_save_cache_async()
        itens = json.loads((tmp_path / ".lastfm_cache.json").read_bytes())["items"]
        assert itens == [{"k": "A - B", "d": ENTRADA}, {"k": "Sem - X", "d": {}}]
        assert dict(LastFM("chave", "segredo").cache) == {"A - B": ENTRADA, "Sem - X": {}}

    @pytest.mark.asyncio
    async def test_a_escrita_roda_fora_do_laco_de_eventos(self, monkeypatch):
        threads = []
        original = lastfm_tools.save_json_cache

        def espiao(*args, **kwargs):
            threads.append(threading.get_ident())
            return original(*args, **kwargs)

        monkeypatch.setattr(lastfm_tools, "save_json_cache", espiao)
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["k"] = {}
        await lastfm.scrobble_save_cache_async()
        assert threads and threads[0] != threading.get_ident()

    @pytest.mark.asyncio
    async def test_a_copia_dos_itens_sai_no_laco_e_nao_na_thread(self, monkeypatch):
        quem_leu = []
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["k"] = {}

        class Espiao(type(lastfm.cache)):
            def items(self):
                quem_leu.append(threading.get_ident())
                return super().items()

        lastfm.cache = Espiao(maxsize=10, ttl=600)
        lastfm.cache["k"] = {}
        quem_leu.clear()
        await lastfm.scrobble_save_cache_async()
        assert quem_leu == [threading.get_ident()]

    @pytest.mark.asyncio
    async def test_falha_de_disco_vira_aviso_e_nao_levanta(self, monkeypatch, caplog):
        def negar(*args, **kwargs):
            raise OSError("negado")

        monkeypatch.setattr(lastfm_tools, "save_json_cache", negar)
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["k"] = {}
        with caplog.at_level(logging.WARNING):
            await lastfm.scrobble_save_cache_async()
        assert any("não gravado" in r.getMessage() for r in caplog.records)

    def test_a_versao_sincrona_continua_existindo(self, tmp_path):
        lastfm = LastFM("chave", "segredo")
        lastfm.cache["k"] = {}
        lastfm.scrobble_save_cache()
        assert (tmp_path / ".lastfm_cache.json").is_file()


class TestCogUsaAVersaoAssincrona:
    def chamadas(self):
        arvore = ast.parse((RAIZ / "empiremuse" / "cogs" / "lastfm.py").read_text(encoding="utf-8"))
        sincronas, esperadas = [], []
        for no in ast.walk(arvore):
            if isinstance(no, ast.Await) and isinstance(no.value, ast.Call):
                alvo = no.value.func
                if isinstance(alvo, ast.Attribute) and alvo.attr == "scrobble_save_cache_async":
                    esperadas.append(no.lineno)
            elif (
                isinstance(no, ast.Call)
                and isinstance(no.func, ast.Attribute)
                and no.func.attr == "scrobble_save_cache"
            ):
                sincronas.append(no.lineno)
        return sincronas, esperadas

    def test_nenhuma_chamada_sincrona_dentro_do_cog(self):
        sincronas, _ = self.chamadas()
        assert sincronas == []

    def test_as_duas_gravacoes_do_cog_esperam_a_versao_assincrona(self):
        _, esperadas = self.chamadas()
        assert len(esperadas) == 2
