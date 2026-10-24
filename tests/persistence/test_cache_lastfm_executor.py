"""F3-6b, etapa 6 — achado do AppSec: o cache do Last.fm não pode ser gravado (com ``fsync``) dentro do laço de eventos.

``scrobble_save_cache`` continua síncrono (para quem não está numa corrotina); o cog, que o chamava direto de dentro de
corrotinas, passa a usar ``scrobble_save_cache_async``, que tira a cópia dos itens no laço e grava em ``run_in_executor``.
"""

import ast
import threading

import pytest

from empiremuse.utils.music import lastfm_tools
from empiremuse.utils.music.lastfm_tools import LastFM
from tests.support.raiz import RAIZ


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


class TestGravacaoForaDoLaco:
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
