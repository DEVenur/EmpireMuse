"""F3-6b, etapa 5 (RED, commit 3) — o endurecimento do ``PlayerSession.resume_player``.

Condição 1 do 5.1: depois de CADA ``get_channel``/``fetch_channel`` (``voice_channel``, ``last_voice_channel_id``,
``text_channel_id`` e o canal do ``player_controller``) o canal tem de ser do MESMO servidor da sessão (``canal.guild.id ==
guild.id``; canal sem ``guild`` é recusado). Falhou: a sessão não conecta nem envia mensagem em outro servidor; o log leva o
``guild_id`` e o tipo da falha, NUNCA o id do canal alheio. A mensagem (``message_id``) só é buscada no canal já validado.

Também: a sessão decodificada (sem ``voice_state`` nem ``extra_info``, ``dj`` e log em lista, defaults nos campos ausentes) retoma
direito; o ``time`` antigo continua apagando (as duas contas de 172 800 s ficam); o ramo ``Thread`` de ``text_channel_id`` saiu.
"""

import ast
import logging
from collections import deque
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace

import disnake
import pytest

from empiremuse.cogs import player_resume
from tests.support.formatos_reais import (
    CANAL_DE_TEXTO,
    CANAL_DE_VOZ,
    DJ_A,
    DJ_B,
    INSTANTE,
    MENSAGEM,
    SERVIDOR,
    cog_de_sessoes,
)
from tests.support.sessoes import codificar, session, sessao_minima
from tests.persistence.test_formato_sessao import gravar, jogador_completo
from tests.persistence.test_sessao_retomada_sem_voice_state import JogadorRetomado, No
from tests.support.raiz import RAIZ

OUTRO_SERVIDOR = 1100000000000000555
CANAL_ALHEIO = 1100000000000000777


@pytest.fixture(autouse=True)
def _ambiente(monkeypatch):
    monkeypatch.setattr(disnake.utils, "utcnow", lambda: INSTANTE)
    monkeypatch.setattr(player_resume, "can_send_message", lambda *args, **kwargs: None)
    monkeypatch.setattr(player_resume, "can_connect", lambda *args, **kwargs: None)


class CanalEspiao:
    """Canal de mentira que anota tudo o que o ``resume_player`` faz com ele (enviar, buscar mensagem, ler o histórico)."""

    def __init__(self, canal_id, guild=..., *, conectar=True):
        self.id, self.name, self.mention = canal_id, f"canal-{canal_id}", f"<#{canal_id}>"
        if guild is not ...:
            self.guild = guild  # ``...`` = canal SEM o atributo ``guild`` (como um DM)
        self.conectar, self.chamadas = conectar, []
        membro = SimpleNamespace(bot=False, voice=SimpleNamespace(deaf=False, self_deaf=False))
        self.members = [membro]

    def permissions_for(self, quem):
        return SimpleNamespace(
            connect=self.conectar,
            read_message_history=True,
            send_messages=True,
            read_messages=True,
            manage_threads=True,
        )

    async def send(self, *args, **kwargs):
        self.chamadas.append("send")

    async def fetch_message(self, message_id):
        self.chamadas.append(("fetch_message", message_id))
        return SimpleNamespace(id=message_id)

    def history(self, **kwargs):
        self.chamadas.append("history")

        async def vazio():
            return
            yield  # pragma: no cover - gerador assíncrono vazio

        return vazio()


def montar(*, canais, controller=None, buscaveis=None, servidor_existe=True):
    """Cog real + bot mínimo; ``canais`` responde ao ``get_channel`` e ``buscaveis`` ao ``fetch_channel``."""
    cog = cog_de_sessoes()
    servidor = SimpleNamespace(id=SERVIDOR, name="servidor", me=SimpleNamespace(voice=object(), id=1))
    no, criados, jogadores = No(4), [], {}

    def get_player(**kwargs):
        jogador = JogadorRetomado(no, **kwargs)
        criados.append(jogador)
        jogadores[kwargs["guild_id"]] = jogador
        return jogador

    async def get_data(*args, **kwargs):
        return {"player_controller": controller or {"channel": None, "message_id": None}}

    async def fetch_channel(canal_id):
        try:
            return (buscaveis or {})[canal_id]
        except KeyError:
            raise disnake.NotFound(SimpleNamespace(status=404, reason="n/a"), "não existe") from None

    cog.bot.user = SimpleNamespace(id=1)
    cog.bot.get_channel = canais.get
    cog.bot.fetch_channel = fetch_channel
    cog.bot.get_guild = lambda guild_id: servidor if servidor_existe else None
    cog.bot.get_data = get_data
    cog.bot.get_color = lambda *args: 0
    cog.bot.music = SimpleNamespace(players=jogadores, get_best_node=lambda: no, get_player=get_player)
    cog.bot.players_resumed = {}
    cog.apagados = []

    async def delete_data(player):
        cog.apagados.append(player)

    cog.delete_data = delete_data
    return cog, servidor, criados


def proprio(canal_id, **kwargs):
    return CanalEspiao(canal_id, SimpleNamespace(id=SERVIDOR), **kwargs)


def alheio(canal_id=CANAL_ALHEIO, **kwargs):
    return CanalEspiao(canal_id, SimpleNamespace(id=OUTRO_SERVIDOR), **kwargs)


async def retomar(cog, dados):
    await cog.resume_player(dados, hints=[])


async def sessao() -> dict:
    return await gravar(cog_de_sessoes(), jogador_completo())


def sem_rastro_do_canal_alheio(canal: CanalEspiao, criados) -> bool:
    return canal.chamadas == [] and not any(CANAL_ALHEIO in j.conexoes for j in criados)


# ============================================================================ condição 1: servidor == canal


class TestCanalDeOutroServidor:
    @pytest.mark.asyncio
    async def test_canal_de_voz_de_outro_servidor_nao_conecta_nem_envia_nada(self):
        estranho = alheio()
        dados = await sessao()
        dados["voice_channel"] = CANAL_ALHEIO
        cog, _, criados = montar(canais={CANAL_ALHEIO: estranho, CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO)})
        await retomar(cog, dados)
        assert criados == [] and sem_rastro_do_canal_alheio(estranho, criados)

    @pytest.mark.asyncio
    async def test_ultimo_canal_de_voz_de_outro_servidor_nao_e_usado_como_reserva(self):
        estranho = alheio()
        dados = await sessao()
        dados["last_voice_channel_id"] = CANAL_ALHEIO
        canais = {
            CANAL_DE_VOZ: proprio(CANAL_DE_VOZ, conectar=False),  # sem permissão: força o ramo do canal reserva
            CANAL_ALHEIO: estranho,
            CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO),
        }
        cog, _, criados = montar(canais=canais)
        await retomar(cog, dados)
        assert sem_rastro_do_canal_alheio(estranho, criados) and criados == []

    @pytest.mark.asyncio
    async def test_canal_de_texto_de_outro_servidor_nao_recebe_nada_e_a_sessao_cai_no_canal_de_voz(self):
        estranho = alheio()
        dados = await sessao()
        dados["text_channel_id"] = CANAL_ALHEIO
        voz = proprio(CANAL_DE_VOZ)
        cog, _, criados = montar(canais={CANAL_DE_VOZ: voz, CANAL_ALHEIO: estranho})
        await retomar(cog, dados)
        assert len(criados) == 1 and criados[0].conexoes == [CANAL_DE_VOZ]
        assert sem_rastro_do_canal_alheio(estranho, criados) and criados[0].kwargs["channel"] is voz

    @pytest.mark.asyncio
    async def test_canal_do_player_controller_de_outro_servidor_e_ignorado(self):
        estranho = alheio()
        dados = await sessao()
        voz, texto = proprio(CANAL_DE_VOZ), proprio(CANAL_DE_TEXTO)
        cog, _, criados = montar(
            canais={CANAL_DE_VOZ: voz, CANAL_DE_TEXTO: texto, CANAL_ALHEIO: estranho},
            controller={"channel": str(CANAL_ALHEIO), "message_id": str(MENSAGEM)},
        )
        await retomar(cog, dados)
        assert len(criados) == 1 and sem_rastro_do_canal_alheio(estranho, criados)
        assert criados[0].kwargs["channel"] is not estranho

    @pytest.mark.asyncio
    async def test_canal_do_controller_buscado_por_fetch_channel_tambem_e_conferido(self):
        estranho = alheio()
        dados = await sessao()
        cog, _, criados = montar(
            canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO)},
            buscaveis={CANAL_ALHEIO: estranho},
            controller={"channel": str(CANAL_ALHEIO), "message_id": str(MENSAGEM)},
        )
        await retomar(cog, dados)
        assert len(criados) == 1 and sem_rastro_do_canal_alheio(estranho, criados)

    @pytest.mark.asyncio
    async def test_texto_buscado_por_fetch_channel_de_outro_servidor_e_recusado_e_do_proprio_vale(self):
        """Sem o ramo ``Thread`` de ``text_channel_id``: o id é inteiro e a busca passa pela mesma conferência de servidor."""
        estranho = alheio()
        dados = await sessao()
        dados["text_channel_id"] = CANAL_ALHEIO
        cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ)}, buscaveis={CANAL_ALHEIO: estranho})
        await retomar(cog, dados)
        assert len(criados) == 1 and sem_rastro_do_canal_alheio(estranho, criados)

        meu = proprio(CANAL_DE_TEXTO)
        dados = await sessao()  # o resume_player altera o dicionário que recebe
        dados["text_channel_id"] = CANAL_DE_TEXTO
        cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ)}, buscaveis={CANAL_DE_TEXTO: meu})
        await retomar(cog, dados)
        assert criados[0].kwargs["channel"] is meu and ("fetch_message", MENSAGEM) in meu.chamadas

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lugar", ["voz", "texto", "controller"])
    async def test_canal_sem_guild_e_recusado(self, lugar):
        sem_guild = CanalEspiao(CANAL_ALHEIO)  # nenhum atributo ``guild``
        dados = await sessao()
        canais = {CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO), CANAL_ALHEIO: sem_guild}
        controller = None
        if lugar == "voz":
            dados["voice_channel"] = CANAL_ALHEIO
        elif lugar == "texto":
            dados["text_channel_id"] = CANAL_ALHEIO
        else:
            controller = {"channel": str(CANAL_ALHEIO), "message_id": str(MENSAGEM)}
        cog, _, criados = montar(canais=canais, controller=controller)
        await retomar(cog, dados)
        assert sem_rastro_do_canal_alheio(sem_guild, criados)

    @pytest.mark.asyncio
    async def test_a_mensagem_so_e_buscada_no_canal_ja_validado(self):
        meu = proprio(CANAL_DE_TEXTO)
        dados = await sessao()
        cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: meu})
        await retomar(cog, dados)
        assert len(criados) == 1 and meu.chamadas.count(("fetch_message", MENSAGEM)) == 1

    @pytest.mark.asyncio
    async def test_o_aviso_leva_o_servidor_e_nao_o_id_do_canal_alheio(self, caplog):
        estranho = alheio()
        dados = await sessao()
        dados["voice_channel"] = CANAL_ALHEIO
        cog, _, _ = montar(canais={CANAL_ALHEIO: estranho, CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO)})
        with caplog.at_level(logging.DEBUG):
            await retomar(cog, dados)
        avisos = [r.getMessage() for r in caplog.records if r.levelno >= logging.WARNING]
        assert any(str(SERVIDOR) in m for m in avisos)
        assert all(str(CANAL_ALHEIO) not in m and str(OUTRO_SERVIDOR) not in m for m in avisos)

    @pytest.mark.asyncio
    async def test_tudo_do_proprio_servidor_continua_funcionando(self):
        dados = await sessao()
        cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO)})
        await retomar(cog, dados)
        assert len(criados) == 1 and criados[0].conexoes == [CANAL_DE_VOZ]


# ============================================================================ a sessão decodificada retoma direito


class TestSessaoDecodificada:
    @pytest.mark.asyncio
    async def test_a_sessao_que_saiu_do_decode_session_retoma_com_dj_set_e_log_em_lista(self):
        dados = session.decode_session(session.encode_session(await sessao()))
        cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO)})
        await retomar(cog, dados)
        (jogador,) = criados
        assert jogador.dj == {DJ_A, DJ_B} and type(jogador.dj) is set
        assert [e["text"] for e in jogador.command_log_list] == ["Comando 0", "Comando 1", "Comando 2"]
        assert jogador._voice_state is None and jogador.extra_info == {}
        assert jogador.listen_along_invite == "https://exemplo.invalid/convite" and jogador.loop == "queue"
        assert [t.info["title"] for t in jogador.queue][:2] == ["Faixa Deezer 1", "Faixa parcial 2"]

    @pytest.mark.asyncio
    async def test_a_sessao_minima_sem_os_campos_opcionais_retoma_sem_erro(self):
        import json

        documento = json.loads(codificar())
        for campo in list(documento):
            if campo not in {"v", "_id", "voice_channel", "time", "queue"}:
                del documento[campo]
        dados = session.decode_session(json.dumps(documento).encode())
        cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ)})
        await retomar(cog, dados)
        assert len(criados) == 1 and criados[0].conexoes == [CANAL_DE_VOZ]

    @pytest.mark.asyncio
    async def test_o_dj_vazio_e_o_log_vazio_viram_conjunto_e_deque_vazios(self):
        dados = session.decode_session(codificar(dj=set(), command_log_list=[]))
        cog, _, criados = montar(canais={CANAL_DE_VOZ: proprio(CANAL_DE_VOZ), CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO)})
        await retomar(cog, dados)
        assert criados[0].dj == set() and isinstance(criados[0].command_log_list, deque)


# ============================================================================ time: as contas de 48 h continuam (caracterização)


class TestIdadeDaSessao:
    @pytest.mark.asyncio
    async def test_servidor_inexistente_e_sessao_com_mais_de_48_horas_e_apagada(self):
        dados = session.decode_session(codificar(time=INSTANTE - timedelta(hours=49)))
        cog, _, criados = montar(canais={}, servidor_existe=False)
        await retomar(cog, dados)
        assert cog.apagados == [SERVIDOR] and criados == []

    @pytest.mark.asyncio
    async def test_servidor_inexistente_e_sessao_recente_fica_sem_retomar(self):
        dados = session.decode_session(codificar(time=INSTANTE - timedelta(hours=47)))
        cog, _, criados = montar(canais={}, servidor_existe=False)
        await retomar(cog, dados)
        assert cog.apagados == [] and criados == []

    @pytest.mark.asyncio
    async def test_canal_de_voz_inexistente_e_sessao_com_mais_de_48_horas_e_apagada(self):
        dados = session.decode_session(codificar(time=INSTANTE - timedelta(hours=49)))
        cog, _, criados = montar(canais={CANAL_DE_TEXTO: proprio(CANAL_DE_TEXTO)})
        await retomar(cog, dados)
        assert cog.apagados == [SERVIDOR] and criados == []

    @pytest.mark.asyncio
    async def test_o_delete_usa_o_id_da_sessao_validada(self):
        dados = session.decode_session(codificar(time=INSTANTE - timedelta(hours=49)), expected_id=SERVIDOR)
        cog, _, _ = montar(canais={}, servidor_existe=False)
        await retomar(cog, dados)
        assert cog.apagados == [dados["_id"]]


# ============================================================================ por ast


def funcao(nome: str, no_arquivo="cogs/player_resume.py") -> ast.AsyncFunctionDef:
    arvore = ast.parse((RAIZ / "empiremuse" / no_arquivo).read_text(encoding="utf-8"))
    for classe in ast.walk(arvore):
        if isinstance(classe, ast.ClassDef) and classe.name == "PlayerSession":
            for no in classe.body:
                if isinstance(no, (ast.AsyncFunctionDef, ast.FunctionDef)) and no.name == nome:
                    return no
    raise AssertionError(nome)


def nomes_usados(no) -> set[str]:
    achados = set()
    for filho in ast.walk(no):
        if isinstance(filho, ast.Name):
            achados.add(filho.id)
        elif isinstance(filho, ast.Attribute):
            achados.add(filho.attr)
    return achados


class TestPorAst:
    def test_o_resume_player_nao_fala_mais_de_voice_state_nem_de_thread_no_texto(self):
        no = funcao("resume_player")
        textos = {c.value for c in ast.walk(no) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        assert "voice_state" not in textos and "extra_info" not in textos
        thread = [
            c
            for c in ast.walk(no)
            if isinstance(c, ast.Call)
            and getattr(c.func, "id", "") == "isinstance"
            and any(isinstance(a, ast.Attribute) and a.attr == "Thread" for a in ast.walk(c.args[1]))
            and "text_channel_id" in ast.dump(c.args[0])
        ]
        assert thread == []

    def test_o_save_info_nao_grava_voice_state_nem_extra_info(self):
        no = funcao("save_info")
        textos = {c.value for c in ast.walk(no) if isinstance(c, ast.Constant) and isinstance(c.value, str)}
        assert "voice_state" not in textos and "extra_info" not in textos

    def test_resume_players_migra_antes_de_ler(self):
        no = funcao("resume_players")
        migrar = [
            c.lineno for c in ast.walk(no) if isinstance(c, ast.Attribute) and c.attr == "migrate_legacy_sessions"
        ]
        ler = [
            c.lineno for c in ast.walk(no) if isinstance(c, ast.Attribute) and c.attr.startswith("get_player_sessions_")
        ]
        assert migrar and ler and min(migrar) < min(ler)

    def test_o_modulo_nao_importa_pickle_nem_le_sem_teto(self):
        arvore = ast.parse((RAIZ / "empiremuse" / "cogs" / "player_resume.py").read_text(encoding="utf-8"))
        importados = {a.name.split(".")[0] for n in ast.walk(arvore) if isinstance(n, ast.Import) for a in n.names}
        assert "pickle" not in importados and "_pickle" not in importados
        sem_limite = [
            (n.func.attr, n.lineno)
            for n in ast.walk(arvore)
            if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute)
            and (
                n.func.attr in {"read_bytes", "read_text"} or (n.func.attr == "read" and not n.args and not n.keywords)
            )
        ]
        assert sem_limite == []
