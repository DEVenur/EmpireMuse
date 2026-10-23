"""F3-6b, etapa 5 (RED, commit 2) — as sessões no DISCO: ``save_session_local``, ``get_player_sessions_local``, ``delete_data_local``.

Formato novo: ``local_database/player_sessions_json/<bot>/<guild>.json`` (JSON puro, escrita atômica, 0600) e uma cópia
``<guild>.json.bak``. A leitura devolve só dicionários do JSON validado: nome só ``[0-9]{1,20}.json`` de arquivo comum (sem link
simbólico, sem pasta), tamanho conferido antes de ler, ``_id`` do conteúdo igual ao do nome (condição 2 do 5.1). Tudo o que falhar
FICA onde está, com um aviso só com ``guild_id`` e ``code``. A migração do ``.pkl`` está em ``..._migracao_disco.py``.
"""

import contextlib
import logging
import os
import stat
import time
import tracemalloc

import disnake
import pytest

from tests.support.formatos_reais import BOT_ID, INSTANTE, SERVIDOR, cog_de_sessoes, jogador_falso, faixa_youtube
from tests.support.chave_de_corte import log_sem_o_conteudo, registrou
from tests.support.leitor_legado import SEGREDO
from tests.support.serializacao_nucleo import schema
from tests.support.sessoes import (
    escrever_json,
    escrever_pkl,
    pasta_json,
    pasta_legado,
    session,
    sessao_minima,
)
from tests.persistence.test_formato_sessao import gravar, jogador_completo

MIB = 1024 * 1024
OUTRO = SERVIDOR + 7


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


# ============================================================================ o que o save_info e o save_session_local gravam


class TestGravacao:
    @pytest.mark.asyncio
    async def test_o_save_info_nao_leva_voice_state_nem_extra_info(self):
        dados = await gravar(cog_de_sessoes(), jogador_completo())
        assert "voice_state" not in dados and "extra_info" not in dados

    @pytest.mark.asyncio
    async def test_grava_json_no_caminho_novo_e_nao_cria_nada_do_legado(self, tmp_path):
        await cog_de_sessoes().save_info(jogador_completo())
        assert (pasta_json(tmp_path) / f"{SERVIDOR}.json").is_file()
        assert not pasta_legado(tmp_path).exists()
        assert not list(pasta_json(tmp_path).glob("*.pkl")) and not list(pasta_json(tmp_path).glob("*.tmp"))

    @pytest.mark.asyncio
    async def test_o_arquivo_e_o_json_do_encode_session(self, tmp_path):
        cog = cog_de_sessoes()
        dados = await gravar(cog, jogador_completo())
        await cog.save_session_local(SERVIDOR, dados)
        bruto = (pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes()
        assert bruto == session.encode_session(dados) and bruto[:1] == b"{"
        assert session.decode_session(bruto, expected_id=SERVIDOR)["_id"] == SERVIDOR

    @pytest.mark.asyncio
    @pytest.mark.skipif(not hasattr(os, "fchmod"), reason="modo de arquivo só em POSIX")
    async def test_o_arquivo_e_privado_0600(self, tmp_path):
        await cog_de_sessoes().save_info(jogador_completo())
        modo = stat.S_IMODE((pasta_json(tmp_path) / f"{SERVIDOR}.json").stat().st_mode)
        assert modo == 0o600

    @pytest.mark.asyncio
    async def test_guarda_uma_copia_json_bak_igual_ao_arquivo(self, tmp_path):
        cog = cog_de_sessoes()
        await cog.save_info(jogador_completo())
        await cog.save_info(jogador_falso(atual=faixa_youtube(9)))
        atual = (pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes()
        assert (pasta_json(tmp_path) / f"{SERVIDOR}.json.bak").read_bytes() == atual

    @pytest.mark.asyncio
    async def test_falha_na_troca_atomica_deixa_o_antigo_sem_temporario_e_sem_derrubar(
        self, tmp_path, monkeypatch, caplog
    ):
        cog = cog_de_sessoes()
        await cog.save_session_local(SERVIDOR, sessao_minima(volume=11))
        antigo = (pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes()

        def quebrar(*args, **kwargs):
            raise OSError("disco cheio")

        monkeypatch.setattr(os, "replace", quebrar)
        with caplog.at_level(logging.DEBUG):
            await cog.save_session_local(SERVIDOR, sessao_minima(volume=99, prefix_info=SEGREDO[:20]))
        assert (pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes() == antigo
        assert [p.name for p in pasta_json(tmp_path).iterdir() if p.name.endswith(".tmp")] == []
        assert all(SEGREDO[:20] not in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_dados_que_o_esquema_recusa_nao_substituem_o_arquivo(self, tmp_path):
        cog = cog_de_sessoes()
        await cog.save_session_local(SERVIDOR, sessao_minima(volume=11))
        antigo = (pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes()
        with contextlib.suppress(schema.SchemaError):
            await cog.save_session_local(SERVIDOR, sessao_minima(volume=5000))
        assert (pasta_json(tmp_path) / f"{SERVIDOR}.json").read_bytes() == antigo

    @pytest.mark.asyncio
    async def test_varias_sessoes_no_mesmo_bot_e_so_dele(self, tmp_path):
        cog = cog_de_sessoes()
        for guild in (SERVIDOR, OUTRO):
            await cog.save_session_local(guild, sessao_minima(_id=guild))
        assert sorted(p.name for p in pasta_json(tmp_path).glob("*.json")) == sorted(
            [f"{SERVIDOR}.json", f"{OUTRO}.json"]
        )
        assert pasta_json(tmp_path).name == str(BOT_ID)


# ============================================================================ a leitura


class TestLeitura:
    @pytest.mark.asyncio
    async def test_devolve_as_sessoes_validas_decodificadas(self, tmp_path):
        escrever_json(tmp_path, SERVIDOR, volume=11)
        escrever_json(tmp_path, OUTRO, volume=22)
        lidas = await cog_de_sessoes().get_player_sessions_local()
        assert sorted((s["_id"], s["volume"]) for s in lidas) == [(SERVIDOR, 11), (OUTRO, 22)]
        assert all(type(s["dj"]) is list and s["time"] == INSTANTE for s in lidas)

    @pytest.mark.asyncio
    async def test_sem_pasta_nao_ha_sessoes(self):
        assert await cog_de_sessoes().get_player_sessions_local() == []

    @pytest.mark.asyncio
    async def test_nao_le_nada_que_nao_seja_json_de_sessao(self, tmp_path):
        bom = escrever_json(tmp_path, SERVIDOR)
        for nome in (
            f"{OUTRO}.json.bak",
            f"{OUTRO}.pkl",
            f"{OUTRO}.bak",
            f"{OUTRO}.json.tmp",
            f"{OUTRO}.txt",
            f"{OUTRO}",
        ):
            (bom.parent / nome).write_bytes(bom.read_bytes())
        assert [s["_id"] for s in await cog_de_sessoes().get_player_sessions_local()] == [SERVIDOR]

    @pytest.mark.asyncio
    async def test_nao_le_a_pasta_do_legado(self, tmp_path):
        escrever_pkl(tmp_path, SERVIDOR)
        assert await cog_de_sessoes().get_player_sessions_local() == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome",
        [
            "abc.json",
            "12 3.json",
            ".json",
            "1" * 21 + ".json",
            "١٢٣.json",
            "-5.json",
            "nome qualquer.json",
            "1.5.json",
            "0x10.json",
        ],
        ids=[
            "letras",
            "espaco",
            "sem-nome",
            "21-digitos",
            "digitos-arabes",
            "negativo",
            "nome-qualquer",
            "ponto",
            "hexa",
        ],
    )
    async def test_nome_fora_do_padrao_e_ignorado_e_nao_e_tocado(self, tmp_path, nome):
        bom = escrever_json(tmp_path, SERVIDOR)
        estranho = bom.parent / nome
        estranho.write_bytes(bom.read_bytes())
        assert [s["_id"] for s in await cog_de_sessoes().get_player_sessions_local()] == [SERVIDOR]
        assert estranho.is_file()

    @pytest.mark.asyncio
    async def test_link_simbolico_nao_e_seguido(self, tmp_path):
        bom = escrever_json(tmp_path, SERVIDOR)
        fora = tmp_path / "fora" / "real.json"
        fora.parent.mkdir()
        fora.write_bytes(session.encode_session(sessao_minima(_id=OUTRO)))
        link = bom.parent / f"{OUTRO}.json"
        os.symlink(fora, link)
        assert [s["_id"] for s in await cog_de_sessoes().get_player_sessions_local()] == [SERVIDOR]
        assert link.is_symlink() and fora.is_file()

    @pytest.mark.asyncio
    async def test_pasta_com_nome_de_sessao_e_ignorada(self, tmp_path):
        escrever_json(tmp_path, SERVIDOR)
        (pasta_json(tmp_path) / f"{OUTRO}.json").mkdir()
        assert [s["_id"] for s in await cog_de_sessoes().get_player_sessions_local()] == [SERVIDOR]

    @pytest.mark.asyncio
    async def test_id_do_conteudo_diferente_do_nome_e_recusado_e_o_arquivo_fica(self, tmp_path, caplog, capsys):
        escrever_json(tmp_path, SERVIDOR)
        forjado = pasta_json(tmp_path) / f"{OUTRO}.json"
        forjado.write_bytes(session.encode_session(sessao_minima(_id=SERVIDOR + 1, prefix_info=SEGREDO[:20])))
        with caplog.at_level(logging.DEBUG):
            lidas = await cog_de_sessoes().get_player_sessions_local()
        assert [s["_id"] for s in lidas] == [SERVIDOR] and forjado.is_file()
        assert registrou(caplog, OUTRO, "id_mismatch") and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "conteudo",
        [b"", b"lixo", b"{", b'{"v": 1}', b"[]", b"\x00\xff\xfe", "ação".encode("latin-1"), b'{"v": 2, "_id": 1}'],
        ids=["vazio", "lixo", "truncado", "so-versao", "lista", "binario", "latin1", "versao-futura"],
    )
    async def test_arquivo_ilegivel_e_pulado_e_fica_sem_derrubar_as_outras(self, tmp_path, caplog, conteudo):
        escrever_json(tmp_path, SERVIDOR)
        ruim = pasta_json(tmp_path) / f"{OUTRO}.json"
        ruim.write_bytes(conteudo)
        with caplog.at_level(logging.DEBUG):
            lidas = await cog_de_sessoes().get_player_sessions_local()
        assert [s["_id"] for s in lidas] == [SERVIDOR] and ruim.read_bytes() == conteudo
        assert [r for r in caplog.records if r.levelno >= logging.WARNING and str(OUTRO) in r.getMessage()]

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "quando", ["9999-12-31T23:59:59+00:00", "2100-01-01T00:00:00+00:00", "1999-01-01T00:00:00+00:00"]
    )
    async def test_documento_gravado_direto_com_time_fora_do_intervalo_nao_retoma(self, tmp_path, caplog, quando):
        """Condição de aceite do AppSec (R2): a checagem vale na LEITURA, não só na gravação."""
        import json

        bom = escrever_json(tmp_path, SERVIDOR)
        forjado = pasta_json(tmp_path) / f"{OUTRO}.json"
        documento = json.loads(session.encode_session(sessao_minima(_id=OUTRO)))
        documento["time"] = quando
        forjado.write_text(json.dumps(documento))
        with caplog.at_level(logging.DEBUG):
            lidas = await cog_de_sessoes().get_player_sessions_local()
        assert [s["_id"] for s in lidas] == [SERVIDOR] and forjado.is_file() and bom.is_file()
        assert registrou(caplog, OUTRO, "range")

    @pytest.mark.asyncio
    async def test_arquivo_gigante_e_pulado_sem_ser_lido_e_fica(self, tmp_path):
        escrever_json(tmp_path, SERVIDOR)
        gigante = pasta_json(tmp_path) / f"{OUTRO}.json"
        with open(gigante, "wb") as arquivo:
            arquivo.truncate(80 * MIB)
        tracemalloc.start()
        inicio = time.perf_counter()
        try:
            lidas = await cog_de_sessoes().get_player_sessions_local()
            pico = tracemalloc.get_traced_memory()[1]
        finally:
            tracemalloc.stop()
        assert [s["_id"] for s in lidas] == [SERVIDOR] and gigante.is_file()
        assert time.perf_counter() - inicio < 2.0 and pico < 16 * MIB

    @pytest.mark.asyncio
    async def test_mais_de_cem_sessoes_voltam_todas(self, tmp_path):
        for n in range(150):
            escrever_json(tmp_path, SERVIDOR + n, volume=n % 100)
        assert len(await cog_de_sessoes().get_player_sessions_local()) == 150

    @pytest.mark.asyncio
    async def test_so_le_a_pasta_do_proprio_bot(self, tmp_path):
        escrever_json(tmp_path, SERVIDOR)
        outra = tmp_path / "local_database" / "player_sessions_json" / str(BOT_ID + 1)
        outra.mkdir(parents=True)
        (outra / f"{OUTRO}.json").write_bytes(session.encode_session(sessao_minima(_id=OUTRO)))
        assert [s["_id"] for s in await cog_de_sessoes().get_player_sessions_local()] == [SERVIDOR]

    @pytest.mark.asyncio
    async def test_a_leitura_nao_apaga_nem_reescreve_nada(self, tmp_path):
        bom = escrever_json(tmp_path, SERVIDOR)
        (pasta_json(tmp_path) / f"{OUTRO}.json").write_bytes(b"lixo")
        antes = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in pasta_json(tmp_path).iterdir()}
        await cog_de_sessoes().get_player_sessions_local()
        depois = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in pasta_json(tmp_path).iterdir()}
        assert antes == depois and bom.is_file()


# ============================================================================ a remoção


class TestRemocao:
    def test_remove_o_json_a_copia_e_os_restos_do_legado_so_do_servidor_pedido(self, tmp_path):
        for guild in (SERVIDOR, OUTRO):
            escrever_json(tmp_path, guild)
            (pasta_json(tmp_path) / f"{guild}.json.bak").write_bytes(b"copia")
            escrever_pkl(tmp_path, guild)
            escrever_pkl(tmp_path, guild, ext=".bak")
        cog_de_sessoes().delete_data_local(SERVIDOR)
        restantes = sorted(p.name for pasta in (pasta_json(tmp_path), pasta_legado(tmp_path)) for p in pasta.iterdir())
        assert restantes == sorted([f"{OUTRO}.json", f"{OUTRO}.json.bak", f"{OUTRO}.pkl", f"{OUTRO}.bak"])

    def test_remover_o_que_nao_existe_nao_falha(self):
        cog_de_sessoes().delete_data_local(SERVIDOR)

    @pytest.mark.asyncio
    async def test_delete_data_vai_para_o_disco_quando_o_destino_e_o_disco(self, tmp_path):
        escrever_json(tmp_path, SERVIDOR)
        await cog_de_sessoes().delete_data(SERVIDOR)
        assert not (pasta_json(tmp_path) / f"{SERVIDOR}.json").exists()

    @pytest.mark.asyncio
    async def test_delete_data_aceita_o_player(self, tmp_path):
        escrever_json(tmp_path, SERVIDOR)
        await cog_de_sessoes().delete_data(jogador_falso())
        assert not (pasta_json(tmp_path) / f"{SERVIDOR}.json").exists()
