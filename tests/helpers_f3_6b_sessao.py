"""Apoio dos testes da etapa 5 da F3-6b: as sessões do player em JSON (``empiremuse/serialization/session.py``).

``session`` e ``files`` são importados SOB DEMANDA (proxy): sem o módulo cada teste falha de verdade no corpo, nunca na coleta.

DECISÕES DA ETAPA 5 (plano do Backend e decisões do MAESTRO R1 a R6; para inverter uma, troque aqui e na implementação):

* ``encode_session(dados) -> bytes`` (JSON UTF-8 compacto) recebe o dicionário que o ``save_info`` monta (``time`` ``datetime`` com
  fuso, ``dj`` ``set``, ``command_log_list`` ``deque``); ``decode_session(bruto, expected_id=) -> dict`` devolve o que o
  ``resume_player`` consome: ``time`` ``datetime`` UTC, ``dj`` LISTA de inteiros ordenada, ``command_log_list`` LISTA, sem ``v``;
  ``validate_session`` é a mesma validação sobre esse dicionário (entrada do migrador do ``.pkl``/Mongo legado);
* o erro é ``SchemaError(path, code)`` sem o valor; ``id_mismatch`` é o código do ``_id`` do conteúdo diferente do esperado;
* ``voice_state``, ``extra_info`` e qualquer chave desconhecida são descartados em SILÊNCIO (nunca gravados, nunca lidos);
* R1: ``uri``, ``artworkUrl``, ``playlist.url``/``thumb`` e ``extra.album.url`` inválidos viram ``""`` (faixa mantida); ``uri``
  ausente ou ``None`` também vira ``""`` (``None`` quebra a construção da faixa no YouTube e no SoundCloud); em ``pluginInfo``,
  chave que termina em ``Url``/``url`` com valor inválido SAI; ``listen_along_invite`` inválido sai (vale como sem convite);
* R2: ``time`` fora de 2000-01-01 .. agora + 5 min recusa a sessão (``range``); data que estoura (``OverflowError``) é erro do esquema;
* R5: ``custom_skin_data``/``custom_skin_static_data`` com mais de uma entrada ou com skin que o ``validate_skin`` recusa vira ``{}``;
* R6: o ``encode_session`` nunca recusa por tamanho antes de reduzir: tira ``played``, depois ``queue_autoplay``, depois ``extra.lyrics``
  de todas as faixas, e só então recusa (``too_big``); para no primeiro passo que cabe em 8 MiB;
* faixa que o esquema recusa é DESCARTADA (a sessão segue); campo obrigatório ruim (``_id``, ``voice_channel``, ``time``, ``queue`` que
  não é lista) recusa a sessão;
* o consumidor lê o armazenamento por ``PlayerSession`` (``save_session_*``, ``get_player_sessions_*``, ``delete_data_*``) e a
  migração do legado roda por ``PlayerSession.migrate_legacy_sessions()`` (disco sempre; Mongo se configurado), chamada no início de
  ``resume_players`` (nomes do QA: o plano não os fixa).
"""

import copy
import json
from types import SimpleNamespace

from tests.helpers_f3_6b import (
    CANAL_DE_TEXTO,
    CANAL_DE_VOZ,
    DONO,
    INSTANTE,
    MENSAGEM,
    SERVIDOR,
    faixa_youtube,
)
from tests.helpers_f3_6b_serializacao import _Modulo

session = _Modulo("empiremuse.serialization.session")
files = _Modulo("empiremuse.serialization.files")

LIMITES = SimpleNamespace(
    max_bytes=8 * 1024 * 1024,
    queue=5000,
    played=1000,
    queue_autoplay=200,
    failed_tracks=500,
    dj=100,
    lastfm_artists=100,
    command_log=10,
    skin=256,
    stage_title_template=500,
    prefix_info=32,
    current_encoded=16 * 1024,
    volume=1000,
    numero_maximo=10**12,
    log_text=500,
    log_emoji=64,
    mongo_empacotado=12 * 1024 * 1024,
    ano_minimo=2000,
)
BOOLEANOS = [
    "nightcore",
    "static",
    "paused",
    "keep_connected",
    "autoplay",
    "stage_title_event",
    "restrict_mode",
    "mini_queue_enabled",
    "live_lyrics_status",
]
IDS_OPCIONAIS = ["text_channel_id", "message_id", "player_creator", "last_voice_channel_id"]
SURROGATE_SOLTO = chr(0xD800)  # um só: alto+baixo seguidos, escritos no JSON, viram um emoji válido


def faixa_info(n: int = 0, **mudancas) -> dict:
    """O ``info`` de uma faixa do YouTube como o ``save_info`` o grava (com ``id`` e ``extra``)."""
    faixa = faixa_youtube(n)
    info = copy.deepcopy(faixa.info)
    info["id"] = faixa.id
    info.update(mudancas)
    return info


def sessao_minima(**mudancas) -> dict:
    """Uma sessão válida no formato do consumidor (o que o ``save_info`` monta, sem ``voice_state`` e ``extra_info``)."""
    dados = {
        "_id": SERVIDOR,
        "version": 1.1,
        "volume": 100,
        "nightcore": False,
        "position": 0.0,
        "voice_channel": CANAL_DE_VOZ,
        "dj": set(),
        "player_creator": DONO,
        "static": False,
        "paused": False,
        "text_channel_id": CANAL_DE_TEXTO,
        "message_id": MENSAGEM,
        "keep_connected": False,
        "loop": False,
        "autoplay": False,
        "stage_title_event": False,
        "stage_title_template": "",
        "skin": "default",
        "skin_static": "default",
        "custom_skin_data": {},
        "custom_skin_static_data": {},
        "uptime": 1760000000,
        "restrict_mode": False,
        "mini_queue_enabled": True,
        "listen_along_invite": "",
        "queue": [faixa_info(0)],
        "played": [],
        "queue_autoplay": [],
        "failed_tracks": [],
        "prefix_info": "!!",
        "time": INSTANTE,
        "lastfm_artists": [],
        "start_timestamp": 1760882602.5,
        "last_voice_channel_id": CANAL_DE_VOZ,
        "live_lyrics_status": False,
        "current_encoded": None,
        "command_log_list": [],
    }
    dados.update(mudancas)
    return dados


def codificar(**mudancas) -> bytes:
    return session.encode_session(sessao_minima(**mudancas))


def bruto(**mudancas) -> dict:
    """O JSON de uma sessão válida como dicionário Python, para estragar à mão (o que um atacante plantaria)."""
    documento = json.loads(codificar())
    documento.update(mudancas)
    return documento


def em_bytes(documento: dict) -> bytes:
    return json.dumps(documento).encode(
        "utf-8"
    )  # ensure_ascii: aceita até o surrogate solto, que o atacante pode plantar


def decodificar(documento: dict, **kwargs):
    return session.decode_session(em_bytes(documento), **kwargs)


def tamanho_do_json(dados: dict) -> int:
    return len(session.encode_session(dados))


# ============================================================================ disco, legado e Mongo de mentira (commit 2)

import base64  # noqa: E402
import copy as _copy  # noqa: E402
import os  # noqa: E402
import pickle  # noqa: E402
import time as _time  # noqa: E402
import zlib  # noqa: E402
from collections import deque  # noqa: E402
from pathlib import Path  # noqa: E402

from tests.helpers_f3_6b import BOT_ID, DJ_A, DJ_B, MongoEmMemoria  # noqa: E402
from tests.helpers_f3_6b_legado import SEGREDO  # noqa: E402

HORAS = 3600
JANELA_DE_48H = 48 * HORAS


def pasta_json(tmp_path) -> Path:
    return tmp_path / "local_database" / "player_sessions_json" / str(BOT_ID)


def pasta_legado(tmp_path) -> Path:
    return tmp_path / "local_database" / "player_sessions" / str(BOT_ID)


def sessao_legada(**mudancas) -> dict:
    """A sessão como a versão ANTIGA a gravava: com ``voice_state`` e ``extra_info`` (tupla), ``dj`` em ``set`` e log em ``deque``."""
    log = deque([{"text": f"Comando {n}", "emoji": "▶️", "timestamp": 1760882600.0 + n} for n in range(3)], maxlen=10)
    dados = sessao_minima(
        dj={DJ_A, DJ_B},
        command_log_list=log,
        queue=[faixa_info(0), faixa_info(1)],
        played=[faixa_info(2)],
        **mudancas,
    )
    dados["voice_state"] = {"sessionId": SEGREDO, "event": {"token": SEGREDO, "endpoint": "voz.exemplo.invalid"}}
    dados["extra_info"] = {"guild-yt-oauth": (SEGREDO, 1, (2, 3))}
    return dados


def pkl_bytes(dados, protocolo: int = 4) -> bytes:
    """O que a versão antiga gravava no disco: ``zlib`` de ``pickle``."""
    return zlib.compress(pickle.dumps(dados, protocol=protocolo))


def envelope_do_mongo(raw: bytes) -> str:
    """``base64`` de ``zlib`` (o envelope do Mongo, igual para o pickle antigo e para o JSON novo)."""
    return base64.b64encode(zlib.compress(raw)).decode("ascii")


def envelope_antigo_do_mongo(dados, protocolo: int = 4) -> str:
    return base64.b64encode(pkl_bytes(dados, protocolo)).decode("ascii")


def com_idade(caminho: Path, horas: float) -> Path:
    """Põe a data de modificação de ``caminho`` ``horas`` horas atrás (relógio real)."""
    quando = _time.time() - horas * HORAS
    os.utime(caminho, (quando, quando))
    return caminho


def escrever_pkl(tmp_path, guild=SERVIDOR, dados=None, *, ext=".pkl", horas=None, bruto_=None, protocolo=4) -> Path:
    pasta = pasta_legado(tmp_path)
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / f"{guild}{ext}"
    alvo.write_bytes(
        bruto_ if bruto_ is not None else pkl_bytes(sessao_legada(_id=guild) if dados is None else dados, protocolo)
    )
    return com_idade(alvo, horas) if horas is not None else alvo


def escrever_json(tmp_path, guild=SERVIDOR, *, horas=None, **mudancas) -> Path:
    pasta = pasta_json(tmp_path)
    pasta.mkdir(parents=True, exist_ok=True)
    alvo = pasta / f"{guild}.json"
    alvo.write_bytes(session.encode_session(sessao_minima(_id=guild, **mudancas)))
    return com_idade(alvo, horas) if horas is not None else alvo


class MongoDeSessoes(MongoEmMemoria):
    """O Mongo de mentira das sessões: ``$set`` no ``update_data``, leitura em CURSOR preguiçoso (``iter_data``) e um diário.

    * ``eventos``: ``(ação, coleção, id)`` na ordem, com ``ação`` em ``update``, ``leitura`` e ``delete``;
    * ``consumidos`` / ``consumidos_por[coleção]``: documentos que o ``iter_data`` realmente entregou (o teto por subida é medido na coleção do legado);
    * ``falhas``: ``{"update:coleção": exceção}`` levantada pela operação (erro transitório de rede, por exemplo);
    * ``adulterar``: ``{coleção: função(documento) -> documento}`` aplicada ao que o banco GUARDA (corrompe a gravação).
    """

    def __init__(self):
        super().__init__()
        self.eventos: list[tuple[str, str, str]] = []
        self.consumidos = 0
        self.consumidos_por: dict[str, int] = {}
        self.falhas: dict[str, Exception] = {}
        self.adulterar: dict = {}

    def _checar(self, acao: str, colecao: str) -> None:
        erro = self.falhas.get(f"{acao}:{colecao}")
        if erro is not None:
            raise erro

    async def update_data(self, id_, data, *, db_name, collection, default_model=None):
        self.eventos.append(("update", collection, str(id_)))
        self._checar("update", collection)
        atual = self.colecao(db_name, collection).get(str(id_), {})
        documento = {**atual, **_copy.deepcopy(data), "_id": str(id_)}
        if collection in self.adulterar:
            documento = self.adulterar[collection](documento)
        self.colecao(db_name, collection)[str(id_)] = documento

    async def query_data(self, db_name, collection, filter=None, limit=100):
        self.eventos.append(("leitura", collection, "*"))
        self._checar("leitura", collection)
        return [_copy.deepcopy(d) for d in self.colecao(db_name, collection).values()]

    async def iter_data(self, db_name, collection, filter=None):
        """Cursor preguiçoso: cada documento só é copiado e contado quando o consumidor o pede (``filter`` = igualdade de campos)."""
        self.eventos.append(("leitura", collection, "*"))
        self._checar("leitura", collection)
        for chave in list(self.colecao(db_name, collection)):
            documento = self.colecao(db_name, collection).get(chave)
            if documento is None or any(documento.get(k) != v for k, v in (filter or {}).items()):
                continue
            self.consumidos += 1
            self.consumidos_por[collection] = self.consumidos_por.get(collection, 0) + 1
            yield _copy.deepcopy(documento)

    async def get_data(self, id_, *, db_name, collection, default_model=None):
        self.eventos.append(("leitura", collection, str(id_)))
        self._checar("leitura", collection)
        documento = self.colecao(db_name, collection).get(str(id_))
        return _copy.deepcopy(documento) if documento is not None else None

    async def delete_data(self, id_, db_name, collection):
        self.eventos.append(("delete", collection, str(id_)))
        self._checar("delete", collection)
        await super().delete_data(id_, db_name, collection)

    def doc(self, collection: str, id_) -> dict | None:
        return self.colecao(BOT_ID, collection).get(str(id_))

    def ids(self, collection: str) -> set[str]:
        return set(self.colecao(BOT_ID, collection))
