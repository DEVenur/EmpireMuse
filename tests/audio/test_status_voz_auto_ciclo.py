"""2.1.2 — o status automático nos pontos de ligação do ciclo do player (contrato I4): criação (VP1/VP13/VP4), mover de canal (VP6) e retomada (VP8).

Os três usam a função REAL de produção (``create_player``, ``player_vc_disconnect``, ``PlayerSession.resume_player``) com dublês de Discord e de banco;
o player criado é o ``JogadorDeVoz`` (métodos de voz reais, ``tests/support/voz_auto.py``) e cada envio vira um ``Put`` do bot.
"""

import asyncio
import copy
import importlib
from types import ModuleType, SimpleNamespace
from typing import Any

import pytest

from empiremuse.cogs import player_resume
from empiremuse.cogs.music import Music
from empiremuse.music_cog.player_lifecycle import PlayerLifecycleMixin
from tests.persistence.test_formato_skin import dados_globais
from tests.persistence.test_sessao_retomada_sem_voice_state import montar, sessao_gravada
from tests.support.voz_auto import (
    ID_DO_BOT,
    BotDeVoz,
    JogadorDeVoz,
    RelogioFalso,
    assentar,
    canal_de_voz,
    executar,
    faixa,
    instalar_relogio,
    palco,
    servidor,
)

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

SERVIDOR = 4242
AVISO_DE_PADRAO = "ligado por padrão"
MODELO_SALVO = "Ouvindo {track.title}"


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> RelogioFalso:
    return instalar_relogio(monkeypatch)


def regras() -> ModuleType:
    return importlib.import_module("empiremuse.rules.voice_status")


def documento(**extra: Any) -> dict[str, Any]:
    """O documento global do servidor com o que o ``create_player`` lê; as chaves novas só entram quando o teste as dá."""
    return {
        **dados_globais(),
        "prefix": "!",
        "global_skin": False,
        "listen_along_invites": {},
        "voice_channel_status": "",
        "player_skin": "",
        "player_skin_static": "",
    } | extra


# ============================================================================ criação do player


async def criar(
    global_data: dict[str, Any], *, canal: Any = None, no_canal: bool = True, bot: BotDeVoz | None = None
) -> SimpleNamespace:
    """Roda o ``Music.create_player`` REAL; o ``get_player`` devolve um ``JogadorDeVoz`` (voz real) e guarda o que recebeu."""
    bot = bot or BotDeVoz()
    guilda = servidor(canal or canal_de_voz())
    if not no_canal:
        guilda.me.voice = None
    recebido: dict[str, Any] = {}

    def get_player(**kwargs: Any) -> JogadorDeVoz:
        recebido.update(kwargs)
        return JogadorDeVoz(guilda, bot, atual=faixa(), template=kwargs["stage_title_template"])

    async def get_global_data(*_a: Any, **_k: Any) -> dict[str, Any]:
        return global_data

    async def update_global_data(*_a: Any, **_k: Any) -> None:
        return None

    bot.music = SimpleNamespace(players={}, get_player=get_player)
    bot.pool.check_skin = lambda skin: skin
    bot.pool.check_static_skin = lambda skin: skin
    bot.get_global_data, bot.update_global_data = get_global_data, update_global_data
    bot.default_prefix = "!!"
    guild_data = {
        "player_controller": {"skin": "default", "static_skin": "default", "channel": None, "message_id": None},
        "enable_restrict_mode": False,
        "autoplay": False,
        "default_player_volume": 100,
    }
    cog = Music.__new__(Music)
    cog.bot, cog.extra_hints = bot, []
    inter = SimpleNamespace(
        guild_id=SERVIDOR, author=SimpleNamespace(id=900, voice=None), guild=SimpleNamespace(id=SERVIDOR)
    )
    player = await cog.create_player(
        inter, bot, guilda, None, guild_data=guild_data, node=SimpleNamespace(identifier="n")
    )
    return SimpleNamespace(player=player, bot=bot, kwargs=recebido)


class TestCriacao:
    async def test_a_new_player_from_an_empty_document_starts_on_with_the_d4_default(
        self, relogio: RelogioFalso
    ) -> None:
        r = await executar(relogio, criar(documento()))

        assert r.kwargs["stage_title_template"] == regras().DEFAULT_VOICE_TEMPLATE
        assert r.player.stage_title_event is True and r.player.voice_status_permanent is True
        assert len(r.bot.textos) == 1 and r.bot.textos[0].endswith(" Tocando: Musica - Artista")

    async def test_the_first_put_uses_the_app_emoji_of_the_bot_that_creates_the_player(
        self, relogio: RelogioFalso
    ) -> None:
        emoji = "<:spotify:123456789012345678>"
        bot = BotDeVoz()
        bot.app_emojis = {"spotify": emoji}

        r = await executar(relogio, criar(documento(), bot=bot))

        assert r.bot.textos[0].startswith(emoji + " Tocando:")

    async def test_a_saved_valid_template_is_kept(self, relogio: RelogioFalso) -> None:
        r = await executar(relogio, criar(documento(voice_channel_status=MODELO_SALVO)))

        assert r.kwargs["stage_title_template"] == MODELO_SALVO and r.bot.textos == ["Ouvindo Musica"]

    async def test_a_saved_invalid_template_falls_back_to_the_default(self, relogio: RelogioFalso) -> None:
        r = await executar(relogio, criar(documento(voice_channel_status="sem placeholder nenhum")))

        assert r.kwargs["stage_title_template"] == regras().DEFAULT_VOICE_TEMPLATE

    async def test_a_permanent_saved_as_off_creates_the_player_off_and_sends_nothing(
        self, relogio: RelogioFalso
    ) -> None:
        r = await executar(relogio, criar(documento(voice_status_permanent=False, voice_channel_status=MODELO_SALVO)))

        assert r.player.stage_title_event is False and r.bot.puts == []
        assert r.kwargs["stage_title_template"] == MODELO_SALVO  # o modelo continua valendo para a sessão manual

    async def test_a_garbage_flag_in_the_document_means_on(self, relogio: RelogioFalso) -> None:
        r = await executar(relogio, criar(documento(voice_status_permanent="false")))

        assert r.player.stage_title_event is True

    async def test_a_bot_not_yet_in_a_channel_applies_nothing_at_creation(self, relogio: RelogioFalso) -> None:
        r = await executar(relogio, criar(documento(), no_canal=False))

        assert r.bot.puts == [] and r.player.stage_title_event is False

    async def test_a_stage_channel_gets_no_permanent_status(self, relogio: RelogioFalso) -> None:
        canal = palco()

        r = await executar(relogio, criar(documento(), canal=canal))

        canal.create_instance.assert_not_awaited()
        assert r.bot.puts == [] and r.player.stage_title_event is False

    async def test_a_channel_without_the_permission_gets_one_notice_and_no_put(self, relogio: RelogioFalso) -> None:
        r = await executar(relogio, criar(documento(voice_status_permanent=True), canal=canal_de_voz(permitido=False)))

        assert r.bot.puts == [] and len([a for a in r.player.avisos if "Definir status do canal de voz" in a]) == 1


# ============================================================================ VP13 — aviso de padrão (I-S3)


class TestAvisoDePadrao:
    async def test_a_permanent_never_chosen_puts_one_default_line_in_the_command_log(
        self, relogio: RelogioFalso
    ) -> None:
        r = await executar(relogio, criar(documento()))

        avisos = [a for a in r.player.avisos if AVISO_DE_PADRAO in a]
        assert len(avisos) == 1 and "/setvoicestatus" in avisos[0] and "painel" in avisos[0]

    async def test_a_permanent_saved_as_none_is_the_same_as_never_chosen(self, relogio: RelogioFalso) -> None:
        r = await executar(relogio, criar(documento(voice_status_permanent=None)))

        assert len([a for a in r.player.avisos if AVISO_DE_PADRAO in a]) == 1

    @pytest.mark.parametrize("salvo", [True, False])
    async def test_a_saved_choice_shows_no_default_line(self, relogio: RelogioFalso, salvo: bool) -> None:
        r = await executar(relogio, criar(documento(voice_status_permanent=salvo)))

        assert [a for a in r.player.avisos if AVISO_DE_PADRAO in a] == []

    async def test_the_line_is_not_repeated_by_later_applications_in_the_session(self, relogio: RelogioFalso) -> None:
        r = await executar(relogio, criar(documento()))
        cfg = regras().resolve_voice_status(documento())

        await executar(relogio, r.player.apply_permanent_voice_status(cfg))
        await executar(relogio, r.player.apply_permanent_voice_status(cfg))

        assert len([a for a in r.player.avisos if AVISO_DE_PADRAO in a]) == 1


# ============================================================================ VP6 — sair / mover de canal


class _Lifecycle(PlayerLifecycleMixin):
    pass


async def mover(
    relogio: RelogioFalso, *, sessao_ligada: bool, doc: dict[str, Any], com_status_no_antigo: bool = False
) -> SimpleNamespace:
    """O bot do player vai do canal A para o B (``on_voice_state_update`` REAL); o servidor já mostra o B, como o Discord faz."""
    bot = BotDeVoz()
    antigo, novo = canal_de_voz(1001), canal_de_voz(1002)
    guilda = servidor(novo)
    guilda.voice_client = SimpleNamespace(channel=antigo)
    player = JogadorDeVoz(guilda, bot, atual=faixa(), template="{track.title}")
    player.last_channel = antigo
    player.start_members_timeout = lambda **_k: None
    if sessao_ligada:
        guilda.me.voice.channel = antigo
        await executar(relogio, player.apply_permanent_voice_status(regras().VoiceStatusConfig(True, "{track.title}")))
        await relogio.avancar(regras().VOICE_STATUS_MIN_INTERVAL + 1)
        guilda.me.voice.channel = novo
        bot.puts.clear()
    elif com_status_no_antigo:
        player.last_stage_title = "restos"
    bot.documentos[SERVIDOR] = copy.deepcopy(doc)
    bot.music = SimpleNamespace(players={SERVIDOR: player})
    cog = _Lifecycle()
    cog.bot = bot
    membro = SimpleNamespace(id=ID_DO_BOT, bot=True, guild=guilda)
    await cog.player_vc_disconnect(membro, SimpleNamespace(channel=antigo), SimpleNamespace(channel=novo))
    return SimpleNamespace(player=player, bot=bot, antigo=antigo, novo=novo)


class TestMoverDeCanal:
    async def test_a_session_turned_off_comes_back_to_the_permanent_in_the_new_channel(
        self, relogio: RelogioFalso
    ) -> None:
        r = await mover(
            relogio, sessao_ligada=False, doc={"voice_status_permanent": True, "voice_channel_status": "{track.title}"}
        )

        assert r.player.stage_title_event is True
        assert [(p.canal, p.status) for p in r.bot.puts] == [(r.novo.id, "Musica")]

    async def test_a_session_on_with_the_permanent_off_turns_off_and_clears_the_old_channel(
        self, relogio: RelogioFalso
    ) -> None:
        r = await mover(
            relogio, sessao_ligada=True, doc={"voice_status_permanent": False, "voice_channel_status": "{track.title}"}
        )

        assert r.player.stage_title_event is False
        assert [(p.canal, p.status) for p in r.bot.puts] == [(r.antigo.id, None)]

    async def test_a_session_on_with_the_permanent_on_clears_the_old_channel_and_writes_the_new_one(
        self, relogio: RelogioFalso
    ) -> None:
        r = await mover(
            relogio, sessao_ligada=True, doc={"voice_status_permanent": True, "voice_channel_status": "{track.title}"}
        )

        assert r.bot.limpezas and r.bot.limpezas[0].canal == r.antigo.id
        assert r.bot.textos == ["Musica"] and r.bot.puts[-1].canal == r.novo.id
        assert r.player.stage_title_event is True

    async def test_the_move_rereads_the_document_so_a_change_made_meanwhile_counts(self, relogio: RelogioFalso) -> None:
        r = await mover(
            relogio,
            sessao_ligada=False,
            doc={"voice_status_permanent": True, "voice_channel_status": "Agora {track.author}"},
        )

        assert r.bot.textos == ["Agora Artista"]

    async def test_the_old_channel_is_cleared_through_the_player_not_by_a_loose_task(
        self, relogio: RelogioFalso
    ) -> None:
        r = await mover(
            relogio, sessao_ligada=True, doc={"voice_status_permanent": False, "voice_channel_status": "{track.title}"}
        )

        assert r.player.last_stage_title == "" and r.bot.puts[0].status is None


# ============================================================================ VP8 — retomada


async def retomar_com(
    monkeypatch: pytest.MonkeyPatch,
    saida: dict[str, Any],
    doc: dict[str, Any] | Exception,
    *,
    portao: asyncio.Event | None = None,
) -> SimpleNamespace:
    """Retoma a sessão com o ``resume_player`` REAL; com ``portao``, o apply de cada player fica preso nele até o teste soltar.

    ``doc`` exceção: a leitura do banco (``get_global_data``) levanta essa exceção.
    """
    from tests.persistence.test_sessao_retomada_sem_voice_state import JogadorRetomado

    chamadas: list[tuple[Any, bool]] = []

    async def apply(self: Any, cfg: Any, *, jitter: bool = False) -> None:
        chamadas.append((cfg, jitter))
        if portao is not None:
            await portao.wait()

    monkeypatch.setattr(JogadorRetomado, "apply_permanent_voice_status", apply, raising=False)
    monkeypatch.setattr(player_resume, "can_send_message", lambda *a, **k: None)
    monkeypatch.setattr(player_resume, "can_connect", lambda *a, **k: None)
    cog, _no, criados = montar(4)

    async def get_global_data(*_a: Any, **_k: Any) -> dict[str, Any]:
        if isinstance(doc, Exception):
            raise doc
        return doc

    cog.bot.get_global_data = get_global_data
    resumo = asyncio.ensure_future(cog.resume_player(saida, hints=[]))
    await assentar()  # o apply é uma tarefa por player: deixa-a rodar (ou ficar presa no portão)
    return SimpleNamespace(
        jogador=criados[0] if criados else None, chamadas=chamadas, terminou=resumo.done(), tarefa=resumo
    )


class TestRetomada:
    async def test_a_saved_off_flag_with_the_permanent_on_turns_it_on_with_jitter(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dados = await sessao_gravada(stage_title_event=False, stage_title_template="{track.title}")

        r = await retomar_com(
            monkeypatch, dados, {"voice_status_permanent": True, "voice_channel_status": MODELO_SALVO}
        )

        ((cfg, jitter),) = r.chamadas
        assert cfg.permanent is True and cfg.template == MODELO_SALVO and jitter is True

    async def test_a_saved_on_flag_with_the_permanent_off_turns_it_off(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dados = await sessao_gravada(stage_title_event=True, stage_title_template="{track.title}")

        r = await retomar_com(monkeypatch, dados, {"voice_status_permanent": False})

        ((cfg, jitter),) = r.chamadas
        assert cfg.permanent is False
        assert getattr(r.jogador, "stage_title_event", False) is not True  # o flag salvo não é restaurado

    async def test_the_template_saved_in_the_session_no_longer_counts(self, monkeypatch: pytest.MonkeyPatch) -> None:
        dados = await sessao_gravada(stage_title_event=True, stage_title_template="modelo velho {track.title}")

        r = await retomar_com(monkeypatch, dados, {"voice_status_permanent": True})

        ((cfg, _),) = r.chamadas
        assert cfg.template == regras().DEFAULT_VOICE_TEMPLATE

    async def test_a_session_without_the_stage_keys_still_resumes_with_the_permanent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        dados = await sessao_gravada()
        dados.pop("stage_title_event", None)
        dados.pop("stage_title_template", None)

        r = await retomar_com(monkeypatch, dados, {})

        ((cfg, jitter),) = r.chamadas
        assert cfg.permanent is True and jitter is True


class TestRetomadaComBancoFora:
    """Leitura do permanente falhou: a retomada segue, mas não finge que o servidor escolheu o padrão (nada é aplicado nem avisado)."""

    async def test_the_resume_goes_on_but_applies_nothing_and_keeps_the_default_flag_off(
        self, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        dados = await sessao_gravada()
        falha = RuntimeError("banco fora")

        with caplog.at_level("ERROR"):
            r = await retomar_com(monkeypatch, dados, falha)

        assert r.terminou and r.jogador is not None, "a retomada não pode parar por causa do banco"
        assert r.jogador.loop == dados["loop"], "a retomada parou antes de restaurar o resto da sessão"
        assert r.chamadas == [], "aplicou o status com o padrão sem ter lido o banco"
        assert getattr(r.jogador, "voice_status_apply", None) is None
        assert getattr(r.jogador, "voice_status_saved_default", False) is False, (
            "o aviso de padrão ligado seria mostrado"
        )
        assert any(rec.exc_info and rec.exc_info[1] is falha for rec in caplog.records), "a falha não foi logada"

    async def test_with_the_read_ok_the_resume_still_applies_the_permanent(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        r = await retomar_com(monkeypatch, await sessao_gravada(), {})

        ((cfg, jitter),) = r.chamadas
        assert cfg.permanent is True and jitter is True
        assert r.jogador.voice_status_saved_default is True


class TestApplyNaoPrendeAQuemChama:
    """Contrato I4 ajustado: a retomada agenda o ``apply_permanent_voice_status`` como tarefa do player; nunca o espera em linha."""

    async def test_the_resume_returns_while_the_apply_is_still_running(self, monkeypatch: pytest.MonkeyPatch) -> None:
        portao = asyncio.Event()
        dados = await sessao_gravada()
        try:
            r = await retomar_com(monkeypatch, dados, {"voice_status_permanent": True}, portao=portao)

            assert r.terminou, "a retomada esperou o apply em linha"
            assert len(r.chamadas) == 1 and r.chamadas[0][1] is True  # começou, com jitter, e continua preso no portão
        finally:
            portao.set()
            await assentar()

    async def test_every_resumed_player_gets_its_own_apply_task(self, monkeypatch: pytest.MonkeyPatch) -> None:
        portao = asyncio.Event()
        dados = await sessao_gravada()
        try:
            primeira = await retomar_com(monkeypatch, copy.deepcopy(dados), {}, portao=portao)
            segunda = await retomar_com(monkeypatch, copy.deepcopy(dados), {}, portao=portao)

            assert primeira.terminou and segunda.terminou
            assert len(primeira.chamadas) == 1 and len(segunda.chamadas) == 1  # a 2ª não espera a 1ª soltar
        finally:
            portao.set()
            await assentar()


# ============================================================================ I4/V-S2 — a entrada do bot não reaplica por cima da aplicação agendada


async def entrar(
    relogio: RelogioFalso, *, agendada: bool, ja_ligado: bool, doc: dict[str, Any] | None = None
) -> SimpleNamespace:
    """O bot (já com o player) entra no canal: ``on_voice_state_update`` REAL com ``before.channel`` ``None``.

    ``agendada``: a retomada deixou ``player.voice_status_apply`` pendente (aplicação com jitter). ``ja_ligado``: a criação já aplicou.
    """
    bot = BotDeVoz()
    canal = canal_de_voz(1001)
    guilda = servidor(canal)
    guilda.voice_client = SimpleNamespace(channel=canal)
    player = JogadorDeVoz(guilda, bot, atual=faixa(), template="{track.title}")
    player.start_members_timeout = lambda **_k: None
    cfg = regras().VoiceStatusConfig(True, "{track.title}")
    bot.documentos[SERVIDOR] = copy.deepcopy(
        doc or {"voice_status_permanent": True, "voice_channel_status": "{track.title}"}
    )
    bot.music = SimpleNamespace(players={SERVIDOR: player})
    if ja_ligado:
        await executar(relogio, player.apply_permanent_voice_status(cfg))
    if agendada:
        player.voice_status_apply = asyncio.ensure_future(player.apply_permanent_voice_status(cfg, jitter=True))
        await assentar()  # preso no jitter
    cog = _Lifecycle()
    cog.bot = bot
    membro = SimpleNamespace(id=ID_DO_BOT, bot=True, guild=guilda)
    antes = len(bot.puts)
    await executar(
        relogio, cog.player_vc_disconnect(membro, SimpleNamespace(channel=None), SimpleNamespace(channel=canal))
    )
    return SimpleNamespace(player=player, bot=bot, antes=antes)


class TestEntradaComAplicacaoAgendada:
    async def test_the_entry_does_not_apply_on_the_spot_over_the_scheduled_apply(self, relogio: RelogioFalso) -> None:
        r = await entrar(relogio, agendada=True, ja_ligado=False)

        assert r.bot.puts == [], "a entrada aplicou na hora, sem o jitter da retomada"
        assert not r.player.voice_status_apply.done()

    async def test_the_scheduled_apply_sends_once_after_the_jitter_and_nothing_doubles(
        self, relogio: RelogioFalso
    ) -> None:
        r = await entrar(relogio, agendada=True, ja_ligado=False)

        await relogio.avancar(regras().VOICE_STATUS_RESUME_JITTER + 1)
        assert r.bot.textos == ["Musica"]
        await relogio.avancar(60)

        assert r.bot.textos == ["Musica"], "a sessão enviou duas vezes (entrada + agendada)"
        assert r.player.stage_title_event is True

    async def test_with_the_status_already_on_from_the_creation_the_entry_adds_nothing(
        self, relogio: RelogioFalso
    ) -> None:
        r = await entrar(relogio, agendada=False, ja_ligado=True)
        await relogio.avancar(60)

        assert len(r.bot.puts) == r.antes == 1

    async def test_a_finished_scheduled_apply_does_not_count_as_pending(self, relogio: RelogioFalso) -> None:
        bot = BotDeVoz()
        canal = canal_de_voz(1001)
        guilda = servidor(canal)
        player = JogadorDeVoz(guilda, bot, atual=faixa(), template="{track.title}")
        player.start_members_timeout = lambda **_k: None
        await executar(relogio, player.apply_permanent_voice_status(regras().VoiceStatusConfig(True, "{track.title}")))
        player.voice_status_apply = asyncio.ensure_future(asyncio.sleep(0))
        await assentar()
        bot.documentos[SERVIDOR] = {"voice_status_permanent": True, "voice_channel_status": "{track.title}"}
        bot.music = SimpleNamespace(players={SERVIDOR: player})
        cog = _Lifecycle()
        cog.bot = bot

        await executar(
            relogio,
            cog.player_vc_disconnect(
                SimpleNamespace(id=ID_DO_BOT, bot=True, guild=guilda),
                SimpleNamespace(channel=None),
                SimpleNamespace(channel=canal),
            ),
        )
        await relogio.avancar(60)

        assert len(bot.puts) == 1  # o ligado pela criação continua valendo; a tarefa terminada não é "pendente"


# ============================================================================ V-145-1 — mover durante o 1º PUT em voo


class TestMoverComPutEmVoo:
    async def test_moving_while_the_first_put_is_in_flight_clears_the_old_channel_and_writes_the_new_one(
        self, relogio: RelogioFalso
    ) -> None:
        bot = BotDeVoz()
        antigo, novo = canal_de_voz(1001), canal_de_voz(1002)
        guilda = servidor(antigo)
        guilda.voice_client = SimpleNamespace(channel=antigo)
        player = JogadorDeVoz(guilda, bot, atual=faixa(), template="{track.title}")
        player.last_channel = antigo
        player.start_members_timeout = lambda **_k: None
        bot.documentos[SERVIDOR] = {"voice_status_permanent": True, "voice_channel_status": "{track.title}"}
        bot.music = SimpleNamespace(players={SERVIDOR: player})
        bot.reter_canal = antigo.id
        envio = asyncio.ensure_future(
            player.apply_permanent_voice_status(regras().VoiceStatusConfig(True, "{track.title}"))
        )
        await assentar()
        assert [p.status for p in bot.puts if p.canal == antigo.id] == ["Musica"] and not envio.done()

        guilda.me.voice.channel = novo  # o Discord já mostra o canal novo quando o evento chega
        cog = _Lifecycle()
        cog.bot = bot
        membro = SimpleNamespace(id=ID_DO_BOT, bot=True, guild=guilda)
        await executar(
            relogio, cog.player_vc_disconnect(membro, SimpleNamespace(channel=antigo), SimpleNamespace(channel=novo))
        )
        bot.porta_texto.set()
        await envio
        await relogio.avancar(10)

        assert [p.status for p in bot.puts if p.canal == antigo.id] == ["Musica", None], (
            "o canal antigo ficou com o status preso"
        )
        assert [p.status for p in bot.puts if p.canal == novo.id] == ["Musica"]
        assert player.last_stage_title == "Musica" and player.stage_title_event is True


# ============================================================================ V-145-2 — voice_state do próprio bot no MESMO canal não mexe na sessão


async def mesmo_canal(
    relogio: RelogioFalso, *, canal: Any, sessao_ligada: bool, doc: dict[str, Any]
) -> SimpleNamespace:
    """Mute/deafen de servidor, self_deaf ou suppress: o ``on_voice_state_update`` do bot com ``before.channel is after.channel``."""
    bot = BotDeVoz()
    guilda = servidor(canal)
    guilda.voice_client = SimpleNamespace(channel=canal)
    player = JogadorDeVoz(guilda, bot, atual=faixa(), template="escolha da sessão {track.title}")
    player.last_channel = canal
    player.start_members_timeout = lambda **_k: None
    player.stage_title_event = sessao_ligada
    bot.documentos[SERVIDOR] = copy.deepcopy(doc)
    bot.music = SimpleNamespace(players={SERVIDOR: player})
    cog = _Lifecycle()
    cog.bot = bot
    membro = SimpleNamespace(id=ID_DO_BOT, bot=True, guild=guilda)
    await executar(
        relogio, cog.player_vc_disconnect(membro, SimpleNamespace(channel=canal), SimpleNamespace(channel=canal))
    )
    await relogio.avancar(10)
    return SimpleNamespace(player=player, bot=bot)


DOC_LIGADO = {"voice_status_permanent": True, "voice_channel_status": "{track.title}"}


class TestMesmoCanal:
    async def test_a_session_turned_off_in_a_voice_channel_stays_off(self, relogio: RelogioFalso) -> None:
        r = await mesmo_canal(relogio, canal=canal_de_voz(1001), sessao_ligada=False, doc=DOC_LIGADO)

        assert r.player.stage_title_event is False and r.bot.puts == []
        assert r.player.stage_title_template == "escolha da sessão {track.title}"
        assert r.bot.leituras == 0, "releu o documento global a cada voice_state do mesmo canal"

    async def test_a_session_on_in_a_voice_channel_keeps_its_own_template(self, relogio: RelogioFalso) -> None:
        r = await mesmo_canal(relogio, canal=canal_de_voz(1001), sessao_ligada=True, doc=DOC_LIGADO)

        assert r.player.stage_title_event is True and r.player.stage_title_template == "escolha da sessão {track.title}"
        assert r.bot.puts == [] and r.bot.leituras == 0

    async def test_a_manual_stage_session_is_not_broken_by_a_suppress_event(self, relogio: RelogioFalso) -> None:
        r = await mesmo_canal(relogio, canal=palco(), sessao_ligada=True, doc=DOC_LIGADO)

        assert r.player.stage_title_event is True and r.player.stage_title_template == "escolha da sessão {track.title}"
        assert r.bot.puts == [] and r.bot.leituras == 0

    async def test_entering_still_applies_the_permanent(self, relogio: RelogioFalso) -> None:
        r = await entrar(relogio, agendada=False, ja_ligado=False)

        assert r.player.stage_title_event is True and r.bot.leituras >= 1
