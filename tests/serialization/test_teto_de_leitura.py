"""F3-6b, etapa 4 — achado do AppSec: nenhuma leitura de arquivo de dados sem teto de tamanho.

A migração dos ``.pkl`` roda de forma síncrona em ``BotPool.setup``, antes do laço de eventos: um arquivo muito maior que o
teto não pode ser lido inteiro para a memória antes de ser recusado. Vale para o ``.pkl`` legado, para o JSON já existente que a
migração confere e para o que acabou de ser gravado. O arquivo que passa do teto FICA onde está. Padrão para as etapas
seguintes: ler no máximo ``teto + 1`` bytes (ou conferir ``lstat`` antes) e nunca ``read_bytes()`` sem limite.
"""

import importlib
import time
import tracemalloc
from pathlib import Path

import pytest

from tests.support.formatos_reais import DONO
from tests.support.formato_fila_salva import caminho_da_fila

MIB = 1024 * 1024
saved_queue = importlib.import_module("empiremuse.utils.music.saved_queue")


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


def arquivo_esparso(caminho: Path, tamanho: int) -> Path:
    caminho.parent.mkdir(parents=True, exist_ok=True)
    with open(caminho, "wb") as arquivo:
        arquivo.truncate(tamanho)
    return caminho


class TestLeituraNoPlay:
    @pytest.mark.asyncio
    async def test_pkl_gigante_no_primeiro_acesso_e_recusado_sem_ler_tudo_e_fica(self, tmp_path):
        pkl = arquivo_esparso(caminho_da_fila(tmp_path), 80 * MIB)
        tracemalloc.start()
        inicio = time.perf_counter()
        try:
            with pytest.raises(Exception, match="incompatível"):
                await saved_queue.load_saved_queue(DONO, 1)
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert pkl.is_file() and time.perf_counter() - inicio < 1.0 and pico < 16 * MIB
