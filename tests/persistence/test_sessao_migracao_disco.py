"""F3-6b, etapa 5 (RED, commit 2) — a MIGRAÇÃO das sessões do disco: ``PlayerSession.migrate_legacy_sessions()``.

Plano, seções 3 e 4: na inicialização, antes de retomar, cada ``.pkl``/``.bak`` de ``player_sessions/<bot>/`` (nome ``[0-9]{1,20}``,
arquivo comum) passa por ``read_capped`` → ``load_legacy(raw, "session")`` → sem ``voice_state``/``extra_info`` →
``validate_session(expected_id=nome)`` → JSON atômico 0600 → RELÊ e valida → só então apaga o ``.pkl`` e o ``.bak`` do servidor.

* o que falhar (protocolo antigo, esquema, ``_id``, tamanho, pickle hostil) FICA, com aviso só com ``guild_id`` e ``code``, e é apagado
  só depois de 48 h de ``mtime``; erro transitório (I/O) nunca apaga; o resto da fila de migração segue;
* regra de ``mtime``: ``.json`` válido e mais novo que o ``.pkl`` → o ``.pkl`` é resto e sai; ``.pkl`` mais novo → vence o ``.pkl``;
* o código novo NÃO reproduz o ``os.rename(.bak -> .pkl)`` do legado.
"""

import json
import logging
import os
import stat
import zlib

import disnake
import pytest

from tests.support.formatos_reais import INSTANTE, SERVIDOR, cog_de_sessoes
from tests.support.chave_de_corte import cargas_hostis, criar_armadilhas, log_sem_o_conteudo, registrou
from tests.support.sessoes import escrever_json, escrever_pkl, pasta_json, pasta_legado, pkl_bytes, sessao_legada

pytestmark = pytest.mark.critical

OUTRO = SERVIDOR + 7
HOSTIS = ["execucao", "segredo-no-global", "protocolo-3", "truncada", "raiz-nao-dicionario"]


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


@pytest.fixture
def armadilhas(tmp_path, monkeypatch):
    return criar_armadilhas(tmp_path, monkeypatch)


async def migrar():
    await cog_de_sessoes().migrate_legacy_sessions()


def json_de(tmp_path, guild=SERVIDOR):
    return pasta_json(tmp_path) / f"{guild}.json"


# ============================================================================ o caminho feliz


class TestConversao:
    @pytest.mark.asyncio
    @pytest.mark.skipif(not hasattr(os, "fchmod"), reason="modo de arquivo só em POSIX")
    async def test_o_json_novo_e_privado_0600(self, tmp_path):
        escrever_pkl(tmp_path)
        await migrar()
        assert stat.S_IMODE(json_de(tmp_path).stat().st_mode) == 0o600

    @pytest.mark.asyncio
    async def test_dj_e_log_do_legado_viram_listas(self, tmp_path):
        escrever_pkl(tmp_path)
        await migrar()
        documento = json.loads(json_de(tmp_path).read_bytes())
        assert documento["dj"] == sorted(documento["dj"]) and len(documento["dj"]) == 2
        assert [e["text"] for e in documento["command_log_list"]] == ["Comando 0", "Comando 1", "Comando 2"]
        assert documento["v"] == 1

    @pytest.mark.asyncio
    async def test_sem_pasta_do_legado_nao_cria_nada(self, tmp_path):
        await migrar()
        assert list(tmp_path.iterdir()) == []


# ============================================================================ o que não converte fica


class TestRecusadasFicam:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", list(HOSTIS)[:2])
    async def test_pickle_hostil_nao_executa_fica_e_nao_cria_json(self, tmp_path, armadilhas, caplog, capsys, nome):
        carga, codigo = cargas_hostis(armadilhas)[nome]
        pkl = escrever_pkl(tmp_path, bruto_=zlib.compress(carga))
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert pkl.is_file() and not pasta_json(tmp_path).exists() and armadilhas.intacto()
        assert registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_id_do_conteudo_diferente_do_nome_fica_e_nao_vira_json(self, tmp_path, caplog):
        pkl = escrever_pkl(tmp_path, OUTRO, sessao_legada(_id=SERVIDOR + 1))
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert pkl.is_file() and not json_de(tmp_path, OUTRO).exists() and not json_de(tmp_path, SERVIDOR + 1).exists()
        assert registrou(caplog, OUTRO, "id_mismatch")

    @pytest.mark.asyncio
    async def test_link_simbolico_nao_e_seguido(self, tmp_path):
        fora = tmp_path / "fora" / "real.pkl"
        fora.parent.mkdir()
        fora.write_bytes(pkl_bytes(sessao_legada(_id=OUTRO)))
        pasta_legado(tmp_path).mkdir(parents=True)
        link = pasta_legado(tmp_path) / f"{OUTRO}.pkl"
        os.symlink(fora, link)
        await migrar()
        assert link.is_symlink() and fora.is_file() and not json_de(tmp_path, OUTRO).exists()

    @pytest.mark.asyncio
    async def test_erro_inesperado_em_um_arquivo_nao_derruba_a_subida_nem_as_outras(self, tmp_path, monkeypatch):
        """Um defeito que não é ``OSError`` nem ``SchemaError`` (aqui, no meio da troca atômica) fica contido naquele servidor."""
        escrever_pkl(tmp_path, SERVIDOR)
        escrever_pkl(tmp_path, OUTRO)
        trocar = os.replace
        chamadas = []

        def quebrar_a_primeira(origem, destino):
            chamadas.append(destino)
            if len(chamadas) == 1:
                raise RuntimeError("defeito inesperado")
            return trocar(origem, destino)

        monkeypatch.setattr(os, "replace", quebrar_a_primeira)
        await migrar()  # nenhuma exceção
        convertidos = [g for g in (SERVIDOR, OUTRO) if json_de(tmp_path, g).is_file()]
        mantidos = [g for g in (SERVIDOR, OUTRO) if (pasta_legado(tmp_path) / f"{g}.pkl").is_file()]
        assert len(convertidos) == 1 and len(mantidos) == 1 and convertidos != mantidos
        assert [p.name for p in pasta_json(tmp_path).iterdir() if p.name.endswith(".tmp")] == []


# ============================================================================ ordem, mtime e releitura


class TestOrdemEVerificacao:
    @pytest.mark.asyncio
    async def test_json_valido_e_mais_novo_o_pkl_e_so_resto_e_sai_sem_converter(self, tmp_path):
        escrever_pkl(tmp_path, horas=3)
        escrever_pkl(tmp_path, ext=".bak", horas=3)
        novo = escrever_json(tmp_path, SERVIDOR, volume=11, horas=1)
        antes = novo.read_bytes()
        await migrar()
        assert novo.read_bytes() == antes and list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    async def test_json_que_saiu_corrompido_da_gravacao_mantem_o_pkl(self, tmp_path, monkeypatch):
        """A releitura depois de gravar é o que autoriza apagar o legado."""
        pkl = escrever_pkl(tmp_path)

        def gravar_lixo(origem, destino):
            with open(destino, "wb") as arquivo:
                arquivo.write(b"{corrompido")
            os.unlink(origem)

        monkeypatch.setattr(os, "replace", gravar_lixo)
        await migrar()
        assert pkl.is_file()


# ============================================================================ janela de 48 h (só para o que FALHA)


class TestJanelaDe48Horas:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("horas", [0, 47])
    async def test_falha_com_menos_de_48_horas_fica(self, tmp_path, horas):
        pkl = escrever_pkl(tmp_path, protocolo=3, horas=horas)
        await migrar()
        assert pkl.is_file()

    @pytest.mark.asyncio
    async def test_id_divergente_com_mais_de_48_horas_sai(self, tmp_path):
        pkl = escrever_pkl(tmp_path, OUTRO, sessao_legada(_id=OUTRO + 1), horas=60)
        await migrar()
        assert not pkl.exists()

    @pytest.mark.asyncio
    @pytest.mark.skipif(
        not hasattr(os, "geteuid") or os.geteuid() == 0, reason="precisa de um usuário comum para negar leitura"
    )
    async def test_erro_transitorio_de_leitura_nunca_apaga_nem_com_mais_de_48_horas(self, tmp_path):
        pkl = escrever_pkl(tmp_path, horas=60)
        pkl.chmod(0)
        try:
            await migrar()
        finally:
            pkl.chmod(0o600)
        assert pkl.is_file() and not json_de(tmp_path).exists()
