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
import pickle
import stat
import time
import tracemalloc
import zlib

import disnake
import pytest

from tests.helpers_f3_6b import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes
from tests.helpers_f3_6b_corte import (
    cargas_hostis,
    criar_armadilhas,
    espionar_load_legacy,
    log_sem_o_conteudo,
    registrou,
)
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_sessao import (
    com_idade,
    escrever_json,
    escrever_pkl,
    pasta_json,
    pasta_legado,
    pkl_bytes,
    session,
    sessao_legada,
    sessao_minima,
)

MIB = 1024 * 1024
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


def esperado_da_migracao(**mudancas) -> dict:
    return session.validate_session(sessao_legada(**mudancas))


# ============================================================================ o caminho feliz


class TestConversao:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [4, 5])
    async def test_pkl_valido_vira_json_validado_e_o_legado_some(self, tmp_path, protocolo):
        escrever_pkl(tmp_path, protocolo=protocolo)
        escrever_pkl(tmp_path, ext=".bak", protocolo=protocolo)
        await migrar()
        bruto = json_de(tmp_path).read_bytes()
        assert session.decode_session(bruto, expected_id=SERVIDOR) == esperado_da_migracao()
        assert SEGREDO.encode() not in bruto and b"voice_state" not in bruto and b"extra_info" not in bruto
        assert list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    @pytest.mark.skipif(not hasattr(os, "fchmod"), reason="modo de arquivo só em POSIX")
    async def test_o_json_novo_e_privado_0600(self, tmp_path):
        escrever_pkl(tmp_path)
        await migrar()
        assert stat.S_IMODE(json_de(tmp_path).stat().st_mode) == 0o600

    @pytest.mark.asyncio
    async def test_so_o_bak_tambem_migra_e_some(self, tmp_path):
        escrever_pkl(tmp_path, ext=".bak")
        await migrar()
        assert session.decode_session(json_de(tmp_path).read_bytes())["_id"] == SERVIDOR
        assert list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    async def test_pkl_estragado_e_bak_valido_migra_do_bak_e_remove_os_dois(self, tmp_path):
        escrever_pkl(tmp_path, bruto_=b"truncado-no-meio-da-gravacao")
        escrever_pkl(tmp_path, ext=".bak")
        await migrar()
        assert session.decode_session(json_de(tmp_path).read_bytes())["_id"] == SERVIDOR
        assert list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    async def test_dj_e_log_do_legado_viram_listas(self, tmp_path):
        escrever_pkl(tmp_path)
        await migrar()
        documento = json.loads(json_de(tmp_path).read_bytes())
        assert documento["dj"] == sorted(documento["dj"]) and len(documento["dj"]) == 2
        assert [e["text"] for e in documento["command_log_list"]] == ["Comando 0", "Comando 1", "Comando 2"]
        assert documento["v"] == 1

    @pytest.mark.asyncio
    async def test_cada_servidor_no_seu_json(self, tmp_path):
        for guild in (SERVIDOR, OUTRO):
            escrever_pkl(tmp_path, guild)
        await migrar()
        assert sorted(p.name for p in pasta_json(tmp_path).iterdir()) == sorted([f"{SERVIDOR}.json", f"{OUTRO}.json"])
        assert session.decode_session(json_de(tmp_path, OUTRO).read_bytes(), expected_id=OUTRO)["_id"] == OUTRO
        assert list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    async def test_sessao_antiga_mas_valida_tambem_migra(self, tmp_path):
        escrever_pkl(tmp_path, horas=100)
        escrever_pkl(tmp_path, ext=".bak", horas=100)
        await migrar()
        assert json_de(tmp_path).is_file() and list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    async def test_segunda_rodada_nao_muda_nada(self, tmp_path, caplog):
        escrever_pkl(tmp_path)
        await migrar()
        antes = (json_de(tmp_path).read_bytes(), json_de(tmp_path).stat().st_mtime_ns)
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert (json_de(tmp_path).read_bytes(), json_de(tmp_path).stat().st_mtime_ns) == antes
        assert not [r for r in caplog.records if r.levelno >= logging.WARNING]

    @pytest.mark.asyncio
    async def test_sem_pasta_do_legado_nao_cria_nada(self, tmp_path):
        await migrar()
        assert list(tmp_path.iterdir()) == []

    @pytest.mark.asyncio
    async def test_o_legado_so_e_lido_por_load_legacy_com_o_kind_session(self, tmp_path, monkeypatch):
        escrever_pkl(tmp_path)
        chamadas = espionar_load_legacy(monkeypatch)

        def proibido(*args, **kwargs):
            raise AssertionError("pickle.load(s) completo")

        monkeypatch.setattr(pickle, "loads", proibido)
        monkeypatch.setattr(pickle, "load", proibido)
        await migrar()
        assert chamadas == [("session", "bytes")] and json_de(tmp_path).is_file()

    @pytest.mark.asyncio
    async def test_migrar_nao_reproduz_o_rename_do_bak_sobre_o_pkl(self, tmp_path):
        escrever_pkl(tmp_path, bruto_=b"lixo")
        escrever_pkl(tmp_path, ext=".bak", bruto_=b"outro lixo")
        await migrar()
        assert (pasta_legado(tmp_path) / f"{SERVIDOR}.pkl").read_bytes() == b"lixo"
        assert (pasta_legado(tmp_path) / f"{SERVIDOR}.bak").read_bytes() == b"outro lixo"


# ============================================================================ o que não converte fica


class TestRecusadasFicam:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", HOSTIS)
    async def test_pickle_hostil_nao_executa_fica_e_nao_cria_json(self, tmp_path, armadilhas, caplog, capsys, nome):
        carga, codigo = cargas_hostis(armadilhas)[nome]
        pkl = escrever_pkl(tmp_path, bruto_=zlib.compress(carga))
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert pkl.is_file() and not pasta_json(tmp_path).exists() and armadilhas.intacto()
        assert registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [0, 1, 2, 3])
    async def test_protocolo_antigo_fica(self, tmp_path, caplog, protocolo):
        pkl = escrever_pkl(tmp_path, protocolo=protocolo)
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert pkl.is_file() and not json_de(tmp_path).exists() and registrou(caplog, SERVIDOR, "protocol")

    @pytest.mark.asyncio
    async def test_pickle_sem_zlib_fica(self, tmp_path):
        pkl = escrever_pkl(tmp_path, bruto_=pickle.dumps(sessao_legada(), protocol=4))
        await migrar()
        assert pkl.is_file() and not json_de(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_id_do_conteudo_diferente_do_nome_fica_e_nao_vira_json(self, tmp_path, caplog):
        pkl = escrever_pkl(tmp_path, OUTRO, sessao_legada(_id=SERVIDOR + 1))
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert pkl.is_file() and not json_de(tmp_path, OUTRO).exists() and not json_de(tmp_path, SERVIDOR + 1).exists()
        assert registrou(caplog, OUTRO, "id_mismatch")

    @pytest.mark.asyncio
    @pytest.mark.parametrize("quando", ["9999", "2100", "1999"])
    async def test_sessao_legada_com_time_fora_do_intervalo_fica(self, tmp_path, caplog, quando):
        from datetime import datetime, timezone

        ano = int(quando)
        pkl = escrever_pkl(tmp_path, dados=sessao_legada(time=datetime(ano, 6, 1, tzinfo=timezone.utc)))
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert pkl.is_file() and not json_de(tmp_path).exists() and registrou(caplog, SERVIDOR, "range")

    @pytest.mark.asyncio
    async def test_pkl_gigante_fica_sem_ser_lido(self, tmp_path):
        pasta_legado(tmp_path).mkdir(parents=True)
        gigante = pasta_legado(tmp_path) / f"{SERVIDOR}.pkl"
        with open(gigante, "wb") as arquivo:
            arquivo.truncate(80 * MIB)
        tracemalloc.start()
        inicio = time.perf_counter()
        try:
            await migrar()
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert gigante.is_file() and not json_de(tmp_path).exists()
        assert time.perf_counter() - inicio < 2.0 and pico < 16 * MIB

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome",
        ["abc.pkl", "12 3.pkl", ".pkl", "1" * 21 + ".pkl", "١٢٣.pkl", "nome qualquer.pkl", "12.pkl.bak", "12.txt"],
    )
    async def test_nome_fora_do_padrao_e_ignorado_e_nao_e_tocado(self, tmp_path, nome):
        escrever_pkl(tmp_path, SERVIDOR)
        estranho = pasta_legado(tmp_path) / nome
        estranho.write_bytes(pkl_bytes(sessao_legada()))
        await migrar()
        assert estranho.is_file() and json_de(tmp_path).is_file()
        assert sorted(p.name for p in pasta_json(tmp_path).iterdir()) == [f"{SERVIDOR}.json"]

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
    async def test_uma_sessao_ruim_nao_impede_as_outras(self, tmp_path, armadilhas):
        carga, _ = cargas_hostis(armadilhas)["execucao"]
        ruim = escrever_pkl(tmp_path, SERVIDOR, bruto_=zlib.compress(carga))
        escrever_pkl(tmp_path, OUTRO)
        await migrar()
        assert ruim.is_file() and json_de(tmp_path, OUTRO).is_file() and not json_de(tmp_path, SERVIDOR).exists()

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
    async def test_pkl_mais_novo_que_o_json_vence(self, tmp_path):
        escrever_json(tmp_path, SERVIDOR, volume=11, horas=3)
        escrever_pkl(tmp_path, dados=sessao_legada(volume=77), horas=1)
        await migrar()
        assert session.decode_session(json_de(tmp_path).read_bytes())["volume"] == 77
        assert list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    async def test_json_estragado_nao_vale_e_o_pkl_valido_o_substitui(self, tmp_path):
        ruim = escrever_json(tmp_path, SERVIDOR)
        ruim.write_bytes(b"{lixo")
        com_idade(ruim, 0.1)
        escrever_pkl(tmp_path, horas=5)
        await migrar()
        assert session.decode_session(json_de(tmp_path).read_bytes())["_id"] == SERVIDOR
        assert list(pasta_legado(tmp_path).iterdir()) == []

    @pytest.mark.asyncio
    async def test_falha_ao_gravar_o_json_mantem_o_pkl(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)

        def quebrar(*args, **kwargs):
            raise OSError("disco cheio")

        monkeypatch.setattr(os, "replace", quebrar)
        await migrar()
        assert pkl.is_file() and not json_de(tmp_path).exists()
        assert not pasta_json(tmp_path).exists() or list(pasta_json(tmp_path).iterdir()) == []

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

    @pytest.mark.asyncio
    async def test_json_que_saiu_com_outro_id_mantem_o_pkl(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)

        def gravar_de_outro(origem, destino):
            with open(destino, "wb") as arquivo:
                arquivo.write(session.encode_session(sessao_minima(_id=SERVIDOR + 99)))
            os.unlink(origem)

        monkeypatch.setattr(os, "replace", gravar_de_outro)
        await migrar()
        assert pkl.is_file()


# ============================================================================ janela de 48 h (só para o que FALHA)


class TestJanelaDe48Horas:
    @pytest.mark.asyncio
    async def test_falha_com_mais_de_48_horas_e_apagada_com_aviso_de_info(self, tmp_path, caplog):
        escrever_pkl(tmp_path, protocolo=3, horas=49)
        escrever_pkl(tmp_path, ext=".bak", protocolo=3, horas=49)
        with caplog.at_level(logging.DEBUG):
            await migrar()
        assert list(pasta_legado(tmp_path).iterdir()) == [] and not json_de(tmp_path).exists()
        assert [r for r in caplog.records if r.levelno == logging.INFO and str(SERVIDOR) in r.getMessage()]

    @pytest.mark.asyncio
    @pytest.mark.parametrize("horas", [0, 1, 24, 47])
    async def test_falha_com_menos_de_48_horas_fica(self, tmp_path, horas):
        pkl = escrever_pkl(tmp_path, protocolo=3, horas=horas)
        await migrar()
        assert pkl.is_file()

    @pytest.mark.asyncio
    @pytest.mark.parametrize("nome", HOSTIS)
    async def test_hostil_com_mais_de_48_horas_tambem_sai(self, tmp_path, armadilhas, nome):
        carga, _ = cargas_hostis(armadilhas)[nome]
        pkl = escrever_pkl(tmp_path, bruto_=zlib.compress(carga), horas=60)
        await migrar()
        assert not pkl.exists() and armadilhas.intacto()

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

    @pytest.mark.asyncio
    async def test_a_idade_conta_pelo_mtime_do_arquivo_e_nao_pelo_time_da_sessao(self, tmp_path):
        """Sessão com ``time`` de ontem, mas ``.pkl`` recém-tocado e quebrado: fica."""
        pkl = escrever_pkl(tmp_path, protocolo=3, horas=0.5)
        await migrar()
        assert pkl.is_file()
