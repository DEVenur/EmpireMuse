"""F3-6b, etapa 0 — caracterização da fila salva do usuário no formato ATUAL (sem produção alterada).

Roda o ``Music.save_queue`` REAL (o callback do comando, com faixas das classes reais) e o ramo da fila salva do
``Music.play`` REAL, que lê o arquivo e entrega ``data["tracks"]`` ao ``process_track_cls``. O ``play`` tem muita coisa
antes e depois; aqui as dependências de Discord são dublês e o ``check_player_queue`` com as faixas lidas é o ponto de
parada (guarda o que recebeu e interrompe).

* o que continua valendo depois da migração para JSON: o mínimo de 3 faixas, o caminho por usuário, o conteúdo
  (``tracks``, ``created_at`` em UTC, ``guild_id``) e as faixas que voltam como as classes reais;
* o que muda de propósito na etapa 4 (``TestFormatoGravadoHoje``, ``TestLegadoEmVariosProtocolos``): extensão ``.pkl``,
  envelope ``zlib``, protocolo, opcodes e o leitor que aceita qualquer protocolo e dispensa o ``zlib``.
"""

import copy
import pickle
import zlib
from types import SimpleNamespace

import disnake
import pytest
import pytest_asyncio

from empiremuse.cogs import music
from empiremuse.cogs.music import Music
from empiremuse.utils.client import BotPool
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.models import LavalinkTrack, PartialTrack
from tests.helpers_f3_6b import (
    DONO,
    INSTANTE,
    SERVIDOR,
    faixa_com_playlist,
    faixa_deezer,
    faixa_parcial,
    faixa_youtube,
    globais_do_pickle,
    letras_sincronizadas,
    opcodes_do_pickle,
    protocolo_do_pickle,
)

CONSULTA = ">> [💾 Fila Salva 💾] <<"
OPCODES_DA_FILA = frozenset(
    "PROTO FRAME STOP MARK NONE NEWTRUE NEWFALSE BININT BININT1 BININT2 LONG1 BINFLOAT SHORT_BINUNICODE BINUNICODE "
    "SHORT_BINBYTES BINBYTES EMPTY_LIST EMPTY_DICT EMPTY_TUPLE APPEND APPENDS SETITEM SETITEMS TUPLE1 TUPLE2 TUPLE3 "
    "MEMOIZE BINGET LONG_BINGET STACK_GLOBAL REDUCE".split()
)
PADROES_DO_PLAY = dict(
    position=0, force_play="no", mix=False, manual_selection=False, options=False, server=None, manual_bot_choice="no"
)
GLOBAIS_DA_FILA = {("datetime", "datetime"), ("datetime", "timezone"), ("datetime", "timedelta")}


class Parou(Exception):
    """Interrompe o ``Music.play`` logo depois de ler a fila salva e entregá-la ao ``check_player_queue``."""

    def __init__(self, faixas):
        self.faixas = faixas


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)


def caminho_da_fila(tmp_path, usuario=DONO):
    return tmp_path / "local_database" / "saved_queues_v1" / "users" / f"{usuario}.pkl"


class Resposta:
    def __init__(self):
        self.enviados = []

    async def defer(self, **kwargs):
        self.enviados.append(("defer", kwargs))

    def is_done(self):
        return True


class Interacao:
    def __init__(self, bot, guild, usuario=DONO):
        self.bot, self.guild, self.guild_id = bot, guild, SERVIDOR
        self.author = SimpleNamespace(id=usuario, mention=f"<@{usuario}>", voice=None)
        self.channel = SimpleNamespace(id=777)
        self.response = Resposta()
        self.embeds = []

    async def edit_original_response(self, **kwargs):
        self.embeds.append(kwargs["embed"])


def montar_cenario(faixas_atual, faixas_fila):
    """Cog ``Music`` real (sem ``__init__``) com um bot e um player mínimos; devolve ``(cog, interação)``."""
    guild = SimpleNamespace(id=SERVIDOR, me=SimpleNamespace(voice=SimpleNamespace(channel=None)))
    player = SimpleNamespace(current=faixas_atual, queue=list(faixas_fila), node=SimpleNamespace())
    bot = SimpleNamespace(
        music=SimpleNamespace(players={SERVIDOR: player}),
        user=SimpleNamespace(id=1),
        get_guild=lambda guild_id: guild,
        get_color=lambda *args: 0,
        get_global_command_named=lambda *args, **kwargs: None,
        default_prefix="!!",
        config={"ENABLE_DISCORD_URLS_PLAYBACK": False},
        pool=SimpleNamespace(
            process_track_cls=lambda *args, **kwargs: BotPool.process_track_cls(None, *args, **kwargs)
        ),
    )

    async def dados_globais(*args, **kwargs):
        return {"prefix": ""}

    bot.get_global_data = dados_globais
    cog = Music.__new__(Music)
    cog.bot = bot
    return cog, Interacao(bot, guild)


async def salvar(faixas, *, atual=None):
    cog, inter = montar_cenario(atual, faixas)
    await Music.save_queue.callback(cog, inter)
    return cog, inter


def tres_faixas():
    return [faixa_youtube(1, letras=letras_sincronizadas(5)), faixa_deezer(2), faixa_parcial(3)]


def infos(faixas):
    return [copy.deepcopy(faixa.info) for faixa in faixas]


def montar_leitura(monkeypatch, faixas_lidas):
    """Prepara o ``Music.play`` para ler a fila salva; devolve ``executar()`` que roda e devolve as faixas recebidas."""
    cog, inter = montar_cenario(None, [])
    guild_data = {"player_controller": {"channel": "0", "message_id": "0", "fav_links": {}}}

    async def sem_canal(*args, **kwargs):
        return False

    async def nada(*args, **kwargs):
        return None

    async def dados(*args, **kwargs):
        return {"fav_links": {}, "integration_links": {}, "last_tracks": []}

    async def parar(autor, bot, guild_id, faixas=None):
        if faixas is not None:
            raise Parou(faixas)

    inter.channel.id = 777
    inter.author.voice = SimpleNamespace(channel=SimpleNamespace(id=555, voice_states={1: object()}, mention="<#555>"))
    inter.guild.me.voice = SimpleNamespace(channel=inter.author.voice.channel)
    inter.guild.voice_client = object()
    inter.guild.get_member = lambda user_id: inter.author
    inter.message = None
    inter.music_bot = inter.bot
    inter.music_guild = inter.guild
    cog.is_request_channel = sem_canal
    cog.check_player_queue = parar
    cog.bot.get_data = lambda *args, **kwargs: _devolver(guild_data)
    cog.bot.get_global_data = dados
    cog.bot.get_channel = lambda channel_id: SimpleNamespace(id=channel_id)
    monkeypatch.setattr(music, "can_send_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(music, "check_player_perm", nada)
    monkeypatch.setattr(music, "check_channel_limit", lambda *args, **kwargs: True)

    async def executar():
        with pytest.raises(Parou) as parada:
            await Music.play.callback(cog, inter, CONSULTA, **PADROES_DO_PLAY)
        return parada.value.faixas

    return executar


async def _devolver(valor):
    return valor


async def ler(monkeypatch):
    return await montar_leitura(monkeypatch, None)()


# ============================================================================ o que vale antes e depois da migração


class TestSalvarAFila:
    @pytest.mark.asyncio
    async def test_grava_a_faixa_atual_e_a_fila_por_usuario(self, tmp_path):
        atual, fila = faixa_youtube(0), [faixa_deezer(1), faixa_parcial(2), faixa_com_playlist(3)]
        await salvar(fila, atual=atual)
        assert caminho_da_fila(tmp_path).is_file()
        assert not caminho_da_fila(tmp_path, DONO + 1).exists()

    @pytest.mark.asyncio
    async def test_responde_com_o_numero_de_musicas_salvas(self, tmp_path):
        _, inter = await salvar([faixa_deezer(1), faixa_parcial(2)], atual=faixa_youtube(0))
        assert "`3`" in inter.embeds[0].description and inter.response.enviados == [("defer", {"ephemeral": True})]

    @pytest.mark.asyncio
    async def test_menos_de_3_faixas_recusa_e_nao_grava(self, tmp_path):
        with pytest.raises(GenericError, match="mínimo 3"):
            await salvar([faixa_deezer(1)], atual=faixa_youtube(0))
        assert not caminho_da_fila(tmp_path).exists()

    @pytest.mark.asyncio
    async def test_exatamente_3_faixas_vale_e_sem_faixa_atual_conta_so_a_fila(self, tmp_path):
        await salvar([faixa_youtube(1), faixa_youtube(2), faixa_youtube(3)])
        assert caminho_da_fila(tmp_path).is_file()
        with pytest.raises(GenericError):
            await salvar([faixa_youtube(1), faixa_youtube(2)])


class TestLerAFilaSalva:
    @pytest.mark.asyncio
    async def test_a_fila_gravada_volta_como_as_classes_reais(self, tmp_path, monkeypatch):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        lidas = await ler(monkeypatch)
        assert [type(f) for f in lidas] == [LavalinkTrack, LavalinkTrack, PartialTrack]
        assert [f.info["title"] for f in lidas] == [f.info["title"] for f in faixas]
        assert lidas[0].info["extra"]["lyrics"]["lines"][0]["range"] == {"start": 0, "end": 2900}
        assert lidas[1].info["pluginInfo"]["albumName"] == "Álbum de Teste"
        assert lidas[2].info["is_partial"] is True and lidas[2].info["extra"]["requester"] == DONO

    @pytest.mark.asyncio
    async def test_a_playlist_da_faixa_volta_como_objeto(self, tmp_path, monkeypatch):
        await salvar([faixa_com_playlist(2), faixa_youtube(3)], atual=faixa_youtube(1))
        lidas = await ler(monkeypatch)
        assert lidas[1].playlist_name == "Minha Playlist" and lidas[1].playlist_url.endswith("/playlist/1")
        assert lidas[0].playlist is None

    @pytest.mark.asyncio
    async def test_sem_arquivo_diz_que_a_fila_ja_foi_excluida(self, tmp_path, monkeypatch):
        executar = montar_leitura(monkeypatch, None)
        with pytest.raises(GenericError, match="já foi excluída"):
            await executar()


# ============================================================================ o que o formato de hoje tem e a etapa 4 muda


class TestFormatoGravadoHoje:
    """Deixa de valer na etapa 4 (JSON), quando estes testes são reescritos."""

    @pytest_asyncio.fixture
    async def bytes_do_disco(self, tmp_path):
        faixas = tres_faixas()
        await salvar(faixas[1:], atual=faixas[0])
        return caminho_da_fila(tmp_path).read_bytes()

    @pytest.mark.asyncio
    async def test_o_arquivo_e_pickle_comprimido_com_zlib(self, bytes_do_disco):
        assert bytes_do_disco[:1] == b"x"
        assert protocolo_do_pickle(zlib.decompress(bytes_do_disco)) in {4, 5}

    @pytest.mark.asyncio
    async def test_os_opcodes_cabem_na_lista_fechada_e_as_classes_sao_so_de_data(self, bytes_do_disco):
        dados = zlib.decompress(bytes_do_disco)
        assert set(opcodes_do_pickle(dados)) <= OPCODES_DA_FILA
        assert globais_do_pickle(dados) == GLOBAIS_DA_FILA

    @pytest.mark.asyncio
    async def test_o_conteudo_tem_tracks_created_at_em_utc_e_guild_id(self, bytes_do_disco):
        """O JSON novo terá ``v``, ``tracks``, ``created_at`` em ISO e ``guild_id``."""
        gravado = pickle.loads(zlib.decompress(bytes_do_disco))  # lê o que o próprio código gravou
        assert set(gravado) == {"tracks", "created_at", "guild_id"}
        assert gravado["created_at"] == INSTANTE and gravado["guild_id"] == SERVIDOR and len(gravado["tracks"]) == 3


class TestLegadoEmVariosProtocolos:
    """O leitor de hoje aceita a fila em qualquer protocolo (e até sem ``zlib``). O leitor restrito aceita só 4 e 5."""

    @staticmethod
    def escrever(tmp_path, dados: bytes):
        alvo = caminho_da_fila(tmp_path)
        alvo.parent.mkdir(parents=True, exist_ok=True)
        alvo.write_bytes(dados)

    @staticmethod
    def conteudo():
        faixas = tres_faixas()
        for faixa in faixas:
            faixa.info["id"] = faixa.id
        return {"tracks": infos(faixas), "created_at": INSTANTE, "guild_id": SERVIDOR}

    @pytest.mark.asyncio
    @pytest.mark.parametrize("protocolo", [3, 4, 5])
    async def test_le_a_fila_nos_protocolos_3_4_e_5(self, tmp_path, monkeypatch, protocolo):
        self.escrever(tmp_path, zlib.compress(pickle.dumps(self.conteudo(), protocol=protocolo)))
        lidas = await ler(monkeypatch)
        assert [f.info["title"] for f in lidas] == ["Música 1", "Faixa Deezer 2", "Faixa parcial 3"]

    @pytest.mark.asyncio
    async def test_o_leitor_de_hoje_aceita_pickle_sem_zlib(self, tmp_path, monkeypatch):
        """A rota "sem zlib" sai no JSON novo: o codec novo exige o envelope."""
        self.escrever(tmp_path, pickle.dumps(self.conteudo(), protocol=4))
        assert len(await ler(monkeypatch)) == 3
