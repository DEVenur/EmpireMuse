"""F3-6b, etapa 4 (RED do Backend) — a fila salva do usuário em JSON: esquema, gravação atômica, leitura e migração do ``.pkl``.

* ``empiremuse/serialization/queue.py``: ``encode_saved_queue``, ``decode_saved_queue`` e ``normalize_legacy_queue``
  (documento ``{"v": 1, "tracks": [...], "created_at": ISO com offset, "guild_id": int}`` de até 4 MiB e 5 000 faixas);
* ``Music.save_queue`` grava ``local_database/saved_queues_json/users/<id>.json`` (0600, escrita atômica) e remove o ``.pkl``
  antigo do mesmo usuário; ``Music.play`` lê o JSON e, se só houver o ``.pkl`` legado, lê por ``load_legacy``, grava o JSON e
  só então apaga o ``.pkl``; a migração também roda na inicialização (``BotPool.setup``);
* fila ilegível (JSON ou ``.pkl``) vira ``GenericError`` com "incompatível" e o arquivo FICA.
"""

import ast
import copy
import importlib
import json
import logging
import os
import pickle
import stat
import time
import zlib
from datetime import datetime, timedelta, timezone
from pathlib import Path

import disnake
import pytest

from empiremuse.utils.music.errors import GenericError
from tests.helpers_f3_6b import DONO, INSTANTE, SERVIDOR, faixa_youtube
from tests.helpers_f3_6b_corte import espionar_load_legacy
from tests.helpers_f3_6b_legado import SEGREDO
from tests.helpers_f3_6b_serializacao import (
    DEPTH,
    LENGTH,
    MISSING,
    NOT_FINITE,
    PATTERN,
    RANGE,
    SURROGATE,
    TOO_BIG,
    TYPE,
    VERSION,
    falha,
    vazamentos,
)
from tests.test_f3_6b_formato_fila_salva import (
    caminho_da_fila,
    infos,
    montar_leitura,
    salvar,
    tres_faixas,
)

UTC = timezone.utc
MIB = 1024 * 1024
RAIZ = Path(__file__).resolve().parents[1]


class _Modulo:
    """Importa sob demanda: sem o módulo cada teste falha no corpo, nunca na coleta."""

    def __init__(self, nome):
        self._nome = nome

    def __getattr__(self, atributo):
        return getattr(importlib.import_module(self._nome), atributo)


queue = _Modulo("empiremuse.serialization.queue")
files = _Modulo("empiremuse.serialization.files")
saved_queue = _Modulo("empiremuse.utils.music.saved_queue")


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def caminho_json(tmp_path, usuario=DONO) -> Path:
    return tmp_path / "local_database" / "saved_queues_json" / "users" / f"{usuario}.json"


def faixas_validas(quantas=3) -> list[dict]:
    resultado = []
    for n in range(quantas):
        faixa = faixa_youtube(n)
        faixa.info["id"] = faixa.id
        resultado.append(copy.deepcopy(faixa.info))
    return resultado


def codificar(faixas=None, criada=INSTANTE, servidor=SERVIDOR) -> bytes:
    return queue.encode_saved_queue(faixas_validas() if faixas is None else faixas, criada, servidor)


def documento(**mudancas) -> bytes:
    """JSON de uma fila com ``mudancas`` aplicadas por cima de um documento válido (para os casos ruins)."""
    base = json.loads(codificar())
    base.update(mudancas)
    return json.dumps(base, ensure_ascii=False).encode()


def lendo(raw: bytes):
    return queue.decode_saved_queue(raw)


# ============================================================================ o esquema


class TestCodificar:
    def test_o_documento_tem_versao_faixas_data_em_iso_com_offset_e_servidor(self):
        bruto = json.loads(codificar())
        assert set(bruto) == {"v", "tracks", "created_at", "guild_id"}
        assert bruto["v"] == 1 and bruto["guild_id"] == SERVIDOR and len(bruto["tracks"]) == 3
        assert bruto["created_at"] == INSTANTE.astimezone(UTC).isoformat() and bruto["created_at"].endswith("+00:00")

    def test_e_json_compacto_em_utf8_e_nao_pickle(self):
        bruto = codificar()
        assert bruto[:1] == b"{" and b"\\u" not in bruto and b": " not in bruto

    def test_data_com_outro_fuso_vira_utc(self):
        outro = datetime(2026, 1, 2, 3, 4, 5, tzinfo=timezone(timedelta(hours=-3)))
        assert json.loads(codificar(criada=outro))["created_at"] == "2026-01-02T06:04:05+00:00"

    def test_data_sem_fuso_e_recusada(self):
        assert falha(codificar, criada=datetime(2026, 1, 1)).path == "created_at"

    def test_nao_altera_as_faixas_recebidas(self):
        faixas = faixas_validas()
        antes = copy.deepcopy(faixas)
        codificar(faixas)
        assert faixas == antes

    def test_faixa_com_playlist_e_id_vazio_e_campos_desconhecidos_passam(self):
        faixas = faixas_validas()
        faixas[0]["playlist"] = {"name": "Minha Playlist", "url": "https://exemplo.invalid/playlist/1"}
        faixas[1]["id"] = ""
        faixas[2]["campo_novo"] = {"a": [1, 2]}
        assert lendo(codificar(faixas))["tracks"] == faixas

    def test_metadado_externo_pode_ter_emoji_zwj_e_marca_bidi(self):
        """Título de faixa vem de fora: ZWJ de emoji (``Cf``) e marcas bidi não derrubam a fila; surrogate sim."""
        faixas = faixas_validas()
        faixas[0]["title"] = "Família 👨\u200d👩\u200d👧 \u202eRLO"
        assert lendo(codificar(faixas))["tracks"][0]["title"] == faixas[0]["title"]
        faixas[0]["title"] = "ruim\ud800"
        assert falha(codificar, faixas).code == SURROGATE

    def test_letra_grande_demais_e_descartada_e_a_fila_ainda_e_salva(self):
        faixas = faixas_validas()
        faixas[0]["extra"]["lyrics"] = {"lines": [{"text": "x"}] * 6000}
        lidas = lendo(codificar(faixas))["tracks"]
        assert "lyrics" not in lidas[0]["extra"] and lidas[0]["title"] == faixas[0]["title"]

    def test_o_erro_leva_o_caminho_e_nao_o_valor(self):
        faixas = faixas_validas()
        faixas[1]["title"] = SEGREDO.encode()
        erro = falha(codificar, faixas)
        assert erro.path == "tracks[1].title" and erro.code == TYPE and not vazamentos(erro)


class TestDecodificar:
    def test_ida_e_volta(self):
        faixas = faixas_validas()
        lido = lendo(codificar(faixas))
        assert lido["tracks"] == faixas and lido["guild_id"] == SERVIDOR
        assert lido["created_at"] == INSTANTE.astimezone(UTC) and lido["created_at"].tzinfo is not None

    def test_letra_sincronizada_de_500_linhas_passa(self):
        faixas = faixas_validas()
        linhas = [{"range": {"start": i, "end": i + 1}, "text": "la"} for i in range(500)]
        faixas[0]["extra"]["lyrics"] = {"lines": linhas}
        assert lendo(codificar(faixas))["tracks"][0]["extra"]["lyrics"] == {"lines": linhas}

    def test_o_limite_de_5000_faixas(self):
        base = faixas_validas(1)[0]
        assert len(lendo(codificar([copy.deepcopy(base) for _ in range(5000)]))["tracks"]) == 5000
        assert falha(codificar, [copy.deepcopy(base) for _ in range(5001)]).code == LENGTH

    def test_o_limite_de_4_mib_vale_antes_de_decodificar(self):
        assert falha(lendo, b" " * (4 * MIB + 1)).code == TOO_BIG

    @pytest.mark.parametrize("v", [0, 2, 99, "1", True, None])
    def test_versao_invalida_ou_futura_e_recusada(self, v):
        assert falha(lendo, documento(v=v)).code == VERSION

    def test_sem_versao_e_recusado(self):
        bruto = json.loads(codificar())
        del bruto["v"]
        assert falha(lendo, json.dumps(bruto).encode()).code == VERSION

    @pytest.mark.parametrize(
        ("campo", "valor", "codigo"),
        [
            ("guild_id", -1, RANGE),
            ("guild_id", True, TYPE),
            ("guild_id", "1", TYPE),
            ("created_at", "ontem", PATTERN),
            ("created_at", "2026-01-01T00:00:00", PATTERN),
            ("created_at", 5, TYPE),
            ("tracks", {}, TYPE),
            ("tracks", [], LENGTH),
        ],
    )
    def test_campos_ruins_da_raiz(self, campo, valor, codigo):
        erro = falha(lendo, documento(**{campo: valor}))
        assert erro.path == campo and erro.code == codigo

    def test_campo_desconhecido_na_raiz_e_descartado(self):
        assert "novo" not in lendo(documento(novo=1))

    @pytest.mark.parametrize(
        ("campo", "valor", "codigo"),
        [
            ("title", 5, TYPE),
            ("title", "t" * 5000, LENGTH),
            ("sourceName", None, TYPE),
            ("length", -1, RANGE),
            ("length", float("inf"), NOT_FINITE),
            ("isStream", 1, TYPE),
            ("id", "não é base64!", PATTERN),
            ("id", 5, TYPE),
            ("extra", [], TYPE),
            ("pluginInfo", {"a": [[[[[[[[[1]]]]]]]]]}, DEPTH),
            ("playlist", {"name": "x"}, MISSING),
        ],
    )
    def test_campos_ruins_da_faixa(self, campo, valor, codigo):
        bruto = json.loads(codificar())
        bruto["tracks"][1][campo] = valor
        # ``allow_nan`` só serve para gerar o caso de teste; o leitor recusa o literal
        texto = json.dumps(bruto, allow_nan=True).encode()
        erro = falha(lendo, texto)
        assert erro.code in {codigo, NOT_FINITE} and not vazamentos(erro)
        if erro.code == codigo and codigo != NOT_FINITE:
            assert erro.path.startswith("tracks[1]")

    def test_faixa_sem_titulo_ou_sem_fonte_e_recusada(self):
        for campo in ("title", "sourceName"):
            bruto = json.loads(codificar())
            del bruto["tracks"][0][campo]
            erro = falha(lendo, json.dumps(bruto).encode())
            assert erro.code == MISSING and erro.path == f"tracks[0].{campo}"

    def test_requester_pode_ser_inteiro_ou_texto_mas_nao_bool(self):
        for bom in (DONO, "usuário"):
            bruto = json.loads(codificar())
            bruto["tracks"][0]["extra"]["requester"] = bom
            assert lendo(json.dumps(bruto).encode())["tracks"][0]["extra"]["requester"] == bom
        for ruim in (True, 1.5, None, [1], -4):
            bruto = json.loads(codificar())
            bruto["tracks"][0]["extra"]["requester"] = ruim
            assert falha(lendo, json.dumps(bruto).encode()).path.startswith("tracks[0].extra")

    def test_json_mal_formado_chave_repetida_e_raiz_que_nao_e_objeto(self):
        assert falha(lendo, b"{").code == "syntax"
        assert falha(lendo, b'{"v":1,"v":1}').code == "duplicate_key"
        assert falha(lendo, b"[]").code == TYPE

    def test_nada_do_conteudo_vaza_no_erro(self):
        bruto = json.loads(codificar())
        bruto["tracks"][0]["title"] = SEGREDO + "\ud800"
        assert not vazamentos(falha(lendo, json.dumps(bruto).encode()))


class TestLegado:
    def legado(self, **mudancas):
        base = {"tracks": faixas_validas(), "created_at": INSTANTE, "guild_id": SERVIDOR}
        base.update(mudancas)
        return base

    def test_documento_legado_vira_o_mesmo_formato_decodificado(self):
        assert queue.normalize_legacy_queue(self.legado()) == lendo(codificar())

    def test_tuplas_viram_listas(self):
        faixas = faixas_validas()
        faixas[0]["extra"]["autores"] = ("a", ("b", "c"))
        convertido = queue.normalize_legacy_queue(self.legado(tracks=faixas))
        assert convertido["tracks"][0]["extra"]["autores"] == ["a", ["b", "c"]]

    def test_conjunto_e_recusado(self):
        faixas = faixas_validas()
        faixas[0]["extra"]["s"] = {1, 2}
        assert falha(queue.normalize_legacy_queue, self.legado(tracks=faixas)).code == TYPE

    def test_data_sem_fuso_do_legado_conta_como_utc(self):
        convertido = queue.normalize_legacy_queue(self.legado(created_at=datetime(2026, 1, 1)))
        assert convertido["created_at"] == datetime(2026, 1, 1, tzinfo=UTC)

    def test_legado_sem_faixas_ou_com_campo_ruim_e_recusado(self):
        assert falha(queue.normalize_legacy_queue, {"created_at": INSTANTE, "guild_id": 1}).code == MISSING
        assert falha(queue.normalize_legacy_queue, self.legado(guild_id="x")).code == TYPE


# ============================================================================ gravação atômica e privada


class TestArquivosPrivados:
    def test_grava_com_0600_e_sem_sobras_do_temporario(self, tmp_path):
        alvo = tmp_path / "a" / "b" / "x.json"
        files.write_private_atomic(alvo, b'{"v":1}')
        assert alvo.read_bytes() == b'{"v":1}' and stat.S_IMODE(alvo.stat().st_mode) == 0o600
        assert [p.name for p in alvo.parent.iterdir()] == ["x.json"]

    def test_substitui_o_arquivo_existente_de_uma_vez(self, tmp_path):
        alvo = tmp_path / "x.json"
        alvo.write_bytes(b"antigo")
        files.write_private_atomic(alvo, b"novo")
        assert alvo.read_bytes() == b"novo"

    def test_falha_na_troca_deixa_o_antigo_e_apaga_o_temporario(self, tmp_path, monkeypatch):
        alvo = tmp_path / "x.json"
        alvo.write_bytes(b"antigo")
        monkeypatch.setattr(files.os, "replace", negar)
        with pytest.raises(OSError):
            files.write_private_atomic(alvo, b"novo")
        assert alvo.read_bytes() == b"antigo" and [p.name for p in tmp_path.iterdir()] == ["x.json"]


def negar(*args, **kwargs):
    raise OSError("negado")


# ============================================================================ Music.save_queue


class TestSalvar:
    @pytest.mark.asyncio
    async def test_grava_json_privado_por_usuario_e_nao_pickle(self, tmp_path):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        arquivo = caminho_json(tmp_path)
        assert arquivo.is_file() and stat.S_IMODE(arquivo.stat().st_mode) == 0o600
        assert not caminho_da_fila(tmp_path).exists() and not caminho_json(tmp_path, DONO + 1).exists()
        bruto = json.loads(arquivo.read_bytes())
        assert bruto["v"] == 1 and bruto["guild_id"] == SERVIDOR and len(bruto["tracks"]) == 3
        assert bruto["created_at"] == INSTANTE.astimezone(UTC).isoformat()
        assert [p.name for p in arquivo.parent.iterdir()] == [arquivo.name]

    @pytest.mark.asyncio
    async def test_a_gravacao_nova_apaga_o_pkl_antigo_do_mesmo_usuario(self, tmp_path):
        antigo = caminho_da_fila(tmp_path)
        antigo.parent.mkdir(parents=True)
        antigo.write_bytes(b"qualquer coisa")
        outro = caminho_da_fila(tmp_path, DONO + 1)
        outro.write_bytes(b"de outro usuario")
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        assert not antigo.exists() and outro.is_file() and caminho_json(tmp_path).is_file()

    @pytest.mark.asyncio
    async def test_menos_de_3_faixas_continua_sem_gravar(self, tmp_path):
        with pytest.raises(GenericError, match="mínimo 3"):
            await salvar(tres_faixas()[1:2], atual=tres_faixas()[0])
        assert not caminho_json(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_fila_que_o_esquema_recusa_vira_erro_claro_e_nao_grava(self, tmp_path, caplog):
        faixas = tres_faixas()
        faixas[1].info["title"] = SEGREDO.encode()
        with caplog.at_level(logging.DEBUG), pytest.raises(GenericError, match="(?i)não foi possível") as erro:
            await salvar(faixas[1:], atual=faixas[0])
        assert SEGREDO not in erro.value.text and not caminho_json(tmp_path).exists()
        assert all(SEGREDO not in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    async def test_falha_ao_gravar_deixa_o_json_anterior_e_diz_o_erro(self, tmp_path, monkeypatch):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        antes = caminho_json(tmp_path).read_bytes()
        monkeypatch.setattr(files.os, "replace", negar)
        with pytest.raises(GenericError, match="(?i)não foi possível"):
            await salvar(faixas[1:], atual=faixas[0])
        assert caminho_json(tmp_path).read_bytes() == antes


# ============================================================================ Music.play


def escrever_pkl(tmp_path, conteudo=None, protocolo=4, usuario=DONO):
    if conteudo is None:
        faixas = tres_faixas()
        for faixa in faixas:
            faixa.info["id"] = faixa.id
        conteudo = {"tracks": infos(faixas), "created_at": INSTANTE, "guild_id": SERVIDOR}
    alvo = caminho_da_fila(tmp_path, usuario)
    alvo.parent.mkdir(parents=True, exist_ok=True)
    alvo.write_bytes(zlib.compress(pickle.dumps(conteudo, protocol=protocolo)))
    return alvo


class TestLer:
    @pytest.mark.asyncio
    async def test_le_o_json_sem_passar_pelo_leitor_legado(self, tmp_path, monkeypatch):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        chamadas = espionar_load_legacy(monkeypatch)
        lidas = await montar_leitura(monkeypatch, None)()
        assert chamadas == [] and [f.info["title"] for f in lidas] == [f.info["title"] for f in faixas]

    @pytest.mark.asyncio
    async def test_json_ilegivel_vira_erro_claro_e_o_arquivo_fica(self, tmp_path, monkeypatch, caplog):
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(documento(v=7))
        with caplog.at_level(logging.DEBUG), pytest.raises(GenericError, match="incompatível") as erro:
            await montar_leitura(monkeypatch, None).rodar()
        assert "fila" in erro.value.text.lower() and alvo.is_file()
        assert any(str(SERVIDOR) in r.getMessage() and VERSION in r.getMessage() for r in caplog.records)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lixo", [b"", b"{", b"\xff\xfe", b"[]"], ids=["vazio", "cortado", "nao-utf8", "lista"])
    async def test_json_corrompido_vira_erro_claro(self, tmp_path, monkeypatch, lixo):
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(lixo)
        with pytest.raises(GenericError, match="incompatível"):
            await montar_leitura(monkeypatch, None).rodar()
        assert alvo.is_file()

    @pytest.mark.asyncio
    async def test_arquivo_enorme_e_recusado_sem_ser_lido_inteiro(self, tmp_path, monkeypatch):
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        with open(alvo, "wb") as f:
            f.truncate(300 * MIB)
        inicio = time.perf_counter()
        with pytest.raises(GenericError, match="incompatível"):
            await montar_leitura(monkeypatch, None).rodar()
        assert time.perf_counter() - inicio < 2.0 and alvo.is_file()

    @pytest.mark.asyncio
    async def test_o_json_vale_mais_que_o_pkl_antigo_quando_os_dois_existem(self, tmp_path, monkeypatch):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        escrever_pkl(tmp_path)
        chamadas = espionar_load_legacy(monkeypatch)
        assert len(await montar_leitura(monkeypatch, None)()) == 3 and chamadas == []

    @pytest.mark.asyncio
    async def test_sem_json_nem_pkl_diz_que_a_fila_foi_excluida(self, monkeypatch):
        with pytest.raises(GenericError, match="já foi excluída"):
            await montar_leitura(monkeypatch, None).rodar()


class TestMigracaoNoPrimeiroAcesso:
    @pytest.mark.asyncio
    async def test_pkl_legado_e_lido_por_load_legacy_migrado_e_apagado(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)
        chamadas = espionar_load_legacy(monkeypatch)
        lidas = await montar_leitura(monkeypatch, None)()
        assert chamadas == [("queue", "bytes")]
        assert [f.info["title"] for f in lidas] == ["Música 1", "Faixa Deezer 2", "Faixa parcial 3"]
        assert caminho_json(tmp_path).is_file() and not pkl.exists()
        assert stat.S_IMODE(caminho_json(tmp_path).stat().st_mode) == 0o600
        assert lendo(caminho_json(tmp_path).read_bytes())["guild_id"] == SERVIDOR

    @pytest.mark.asyncio
    async def test_o_segundo_acesso_ja_le_so_o_json(self, tmp_path, monkeypatch):
        escrever_pkl(tmp_path)
        await montar_leitura(monkeypatch, None)()
        chamadas = espionar_load_legacy(monkeypatch)
        await montar_leitura(monkeypatch, None)()
        assert chamadas == []

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [0, 1, 2, 3])
    async def test_pkl_de_protocolo_antigo_continua_recusado_e_o_arquivo_fica(self, tmp_path, monkeypatch, protocolo):
        pkl = escrever_pkl(tmp_path, protocolo=protocolo)
        with pytest.raises(GenericError, match="incompatível"):
            await montar_leitura(monkeypatch, None).rodar()
        assert pkl.is_file() and not caminho_json(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_pkl_que_o_esquema_recusa_fica_e_nao_cria_json(self, tmp_path, monkeypatch):
        conteudo = {"tracks": [{"title": 1}] * 3, "created_at": INSTANTE, "guild_id": SERVIDOR}
        pkl = escrever_pkl(tmp_path, conteudo)
        with pytest.raises(GenericError, match="incompatível"):
            await montar_leitura(monkeypatch, None).rodar()
        assert pkl.is_file() and not caminho_json(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_falha_ao_gravar_o_json_ainda_entrega_a_fila_e_mantem_o_pkl(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)
        monkeypatch.setattr(files.os, "replace", negar)
        lidas = await montar_leitura(monkeypatch, None)()
        assert len(lidas) == 3 and pkl.is_file() and not caminho_json(tmp_path).exists()


# ============================================================================ migração na inicialização


class TestMigracaoNaInicializacao:
    def test_converte_os_pkl_validos_e_apaga_depois_de_reler_o_json(self, tmp_path):
        a = escrever_pkl(tmp_path, usuario=DONO)
        b = escrever_pkl(tmp_path, usuario=DONO + 1)
        assert saved_queue.migrate_saved_queues() == 2
        assert not a.exists() and not b.exists()
        for usuario in (DONO, DONO + 1):
            assert len(lendo(caminho_json(tmp_path, usuario).read_bytes())["tracks"]) == 3

    def test_sem_pasta_nao_faz_nada_e_nao_cria_nada(self, tmp_path):
        assert saved_queue.migrate_saved_queues() == 0 and list(tmp_path.iterdir()) == []

    def test_o_que_nao_converte_fica_onde_esta(self, tmp_path):
        ruim = escrever_pkl(tmp_path, protocolo=2, usuario=DONO)
        vazio = {"tracks": [], "created_at": INSTANTE, "guild_id": 1}
        esquema = escrever_pkl(tmp_path, vazio, usuario=DONO + 1)
        assert saved_queue.migrate_saved_queues() == 0
        assert ruim.is_file() and esquema.is_file() and not caminho_json(tmp_path, DONO).exists()

    def test_nome_de_arquivo_fora_do_padrao_e_ignorado(self, tmp_path):
        pasta = caminho_da_fila(tmp_path).parent
        pasta.mkdir(parents=True)
        conteudo = zlib.compress(
            pickle.dumps({"tracks": faixas_validas(), "created_at": INSTANTE, "guild_id": 1}, protocol=4)
        )
        nomes = ("abc.pkl", "12 3.pkl", ".pkl", "1" * 25 + ".pkl", "12.pkl.bak", "12.txt", "١٢٣.pkl")
        for nome in nomes:
            (pasta / nome).write_bytes(conteudo)
        assert saved_queue.migrate_saved_queues() == 0
        assert len(list(pasta.iterdir())) == len(nomes)
        assert not (tmp_path / "local_database" / "saved_queues_json").exists()

    def test_carga_hostil_nao_executa_e_fica(self, tmp_path, monkeypatch):
        from tests.helpers_f3_6b_corte import cargas_hostis, criar_armadilhas

        armadilhas = criar_armadilhas(tmp_path, monkeypatch)
        carga, _ = cargas_hostis(armadilhas)["execucao"]
        alvo = caminho_da_fila(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(zlib.compress(carga))
        assert saved_queue.migrate_saved_queues() == 0
        assert alvo.is_file() and armadilhas.intacto()

    def test_json_mais_novo_vence_e_o_pkl_velho_e_apagado(self, tmp_path):
        pkl = escrever_pkl(tmp_path)
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(codificar(faixas_validas(4)))
        agora = time.time()
        os.utime(pkl, (agora - 100, agora - 100))
        os.utime(alvo, (agora, agora))
        saved_queue.migrate_saved_queues()
        assert not pkl.exists() and len(lendo(alvo.read_bytes())["tracks"]) == 4

    def test_pkl_mais_novo_que_o_json_substitui_o_json(self, tmp_path):
        """Uma instância antiga gravou depois: o pkl reentra na fila de migração e vence."""
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(codificar(faixas_validas(4)))
        pkl = escrever_pkl(tmp_path)
        agora = time.time()
        os.utime(alvo, (agora - 100, agora - 100))
        os.utime(pkl, (agora, agora))
        saved_queue.migrate_saved_queues()
        assert not pkl.exists() and len(lendo(alvo.read_bytes())["tracks"]) == 3

    def test_falha_ao_gravar_mantem_o_pkl_e_nao_derruba(self, tmp_path, monkeypatch):
        pkl = escrever_pkl(tmp_path)
        monkeypatch.setattr(files.os, "replace", negar)
        assert saved_queue.migrate_saved_queues() == 0 and pkl.is_file()

    def test_o_setup_do_pool_chama_a_migracao(self):
        arvore = ast.parse((RAIZ / "empiremuse" / "utils" / "client.py").read_text(encoding="utf-8"))
        chamadas = {
            no.func.attr if isinstance(no.func, ast.Attribute) else getattr(no.func, "id", "")
            for classe in ast.walk(arvore)
            if isinstance(classe, ast.ClassDef) and classe.name == "BotPool"
            for funcao in classe.body
            if isinstance(funcao, ast.FunctionDef) and funcao.name == "setup"
            for no in ast.walk(funcao)
            if isinstance(no, ast.Call)
        }
        assert "migrate_saved_queues" in chamadas


# ============================================================================ onde a existência da fila é testada


class TestExistenciaDaFila:
    def test_json_ou_pkl_contam_e_nada_nao(self, tmp_path):
        assert saved_queue.has_saved_queue(DONO) is False
        escrever_pkl(tmp_path)
        assert saved_queue.has_saved_queue(DONO) is True
        caminho_da_fila(tmp_path).unlink()
        assert saved_queue.has_saved_queue(DONO) is False
        alvo = caminho_json(tmp_path)
        alvo.parent.mkdir(parents=True)
        alvo.write_bytes(codificar())
        assert saved_queue.has_saved_queue(DONO) is True

    def test_music_usa_o_auxiliar_e_nao_conhece_mais_o_caminho_nem_o_pickle(self):
        codigo = (RAIZ / "empiremuse" / "cogs" / "music.py").read_text(encoding="utf-8")
        assert "saved_queues_v1" not in codigo and "has_saved_queue" in codigo
        arvore = ast.parse(codigo)
        importados = {
            alias.name.split(".")[0] for no in ast.walk(arvore) if isinstance(no, ast.Import) for alias in no.names
        }
        assert "pickle" not in importados
