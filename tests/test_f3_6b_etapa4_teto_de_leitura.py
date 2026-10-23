"""F3-6b, etapa 4 — achado do AppSec: nenhuma leitura de arquivo de dados sem teto de tamanho.

A migração dos ``.pkl`` roda de forma síncrona em ``BotPool.setup``, antes do laço de eventos: um arquivo muito maior que o
teto não pode ser lido inteiro para a memória antes de ser recusado. Vale para o ``.pkl`` legado, para o JSON já existente que a
migração confere e para o que acabou de ser gravado. O arquivo que passa do teto FICA onde está. Padrão para as etapas
seguintes: ler no máximo ``teto + 1`` bytes (ou conferir ``lstat`` antes) e nunca ``read_bytes()`` sem limite.
"""

import ast
import importlib
import time
import tracemalloc
from pathlib import Path

import pytest

from empiremuse.serialization.legacy_pickle import MAX_RAW
from tests.helpers_f3_6b import DONO
from tests.test_f3_6b_etapa4_fila import caminho_json, codificar, escrever_pkl, faixas_validas, lendo
from tests.test_f3_6b_formato_fila_salva import caminho_da_fila
from tests.support.raiz import RAIZ

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


def medir(funcao):
    tracemalloc.start()
    inicio = time.perf_counter()
    try:
        resultado = funcao()
        return resultado, time.perf_counter() - inicio, tracemalloc.get_traced_memory()[1]
    finally:
        tracemalloc.stop()


class TestMigracaoComArquivoGigante:
    def test_pkl_de_dezenas_de_mib_e_recusado_sem_ser_lido_e_fica(self, tmp_path):
        pkl = arquivo_esparso(caminho_da_fila(tmp_path), 80 * MIB)
        convertidas, segundos, pico = medir(saved_queue.migrate_saved_queues)
        assert convertidas == 0 and pkl.is_file() and not caminho_json(tmp_path).exists()
        assert segundos < 1.0 and pico < 8 * MIB, f"{segundos:.2f} s, pico {pico / MIB:.0f} MiB"

    def test_pkl_um_byte_acima_do_teto_fica(self, tmp_path):
        acima = arquivo_esparso(caminho_da_fila(tmp_path), MAX_RAW["queue"] + 1)
        assert saved_queue.migrate_saved_queues() == 0 and acima.is_file()

    def test_json_existente_gigante_conta_como_invalido_e_o_pkl_valido_o_substitui(self, tmp_path):
        pkl = escrever_pkl(tmp_path)
        alvo = arquivo_esparso(caminho_json(tmp_path), 80 * MIB)
        convertidas, segundos, pico = medir(saved_queue.migrate_saved_queues)
        assert convertidas == 1 and not pkl.exists()
        assert len(lendo(alvo.read_bytes())["tracks"]) == 3
        assert segundos < 1.0 and pico < 8 * MIB, f"{segundos:.2f} s, pico {pico / MIB:.0f} MiB"

    def test_pkl_gigante_ao_lado_de_um_valido_nao_atrapalha_o_valido(self, tmp_path):
        gigante = arquivo_esparso(caminho_da_fila(tmp_path, DONO + 1), 80 * MIB)
        valido = escrever_pkl(tmp_path, usuario=DONO)
        convertidas, segundos, _ = medir(saved_queue.migrate_saved_queues)
        assert convertidas == 1 and gigante.is_file() and not valido.exists() and segundos < 1.0

    def test_link_simbolico_para_arquivo_gigante_continua_ignorado(self, tmp_path):
        alvo = arquivo_esparso(tmp_path / "fora" / "grande.bin", 80 * MIB)
        link = caminho_da_fila(tmp_path)
        link.parent.mkdir(parents=True, exist_ok=True)
        link.symlink_to(alvo)
        assert saved_queue.migrate_saved_queues() == 0 and link.is_symlink()


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


class TestPadraoSemLeituraIlimitada:
    ARQUIVOS = ["utils/music/saved_queue.py", "utils/music/json_cache.py", "utils/music/legacy_reader.py"]

    @pytest.mark.parametrize("arquivo", ARQUIVOS)
    def test_nenhuma_leitura_de_arquivo_sem_limite(self, arquivo):
        arvore = ast.parse((RAIZ / "empiremuse" / arquivo).read_text(encoding="utf-8"))
        sem_limite = []
        for no in ast.walk(arvore):
            if isinstance(no, ast.Call) and isinstance(no.func, ast.Attribute):
                nome = no.func.attr
                if nome in {"read_bytes", "read_text"} or (nome == "read" and not no.args and not no.keywords):
                    sem_limite.append((nome, no.lineno))
        assert not sem_limite, sem_limite

    def test_a_conferencia_de_json_gravado_tambem_e_limitada(self, tmp_path):
        """``_json_is_valid`` lê no máximo o teto do formato, mais um byte."""
        alvo = arquivo_esparso(caminho_json(tmp_path), 80 * MIB)
        assert saved_queue._json_is_valid(alvo) is False
        valido = tmp_path / "ok.json"
        valido.write_bytes(codificar(faixas_validas()))
        assert saved_queue._json_is_valid(valido) is True
