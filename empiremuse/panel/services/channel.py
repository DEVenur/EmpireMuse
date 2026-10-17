"""Categoria Canal de pedidos (G-06 setup, G-07 reset): validação síncrona, token do reset e jobs das tarefas.

As regras e os efeitos no Discord ficam em ``utils/music/request_channel.py`` (compartilhado com os comandos). Aqui:
- a validação roda ANTES de criar a tarefa (422 sem nenhum efeito no Discord nem no banco);
- o reset tem dois passos (confirmação com token assinado, 2 min, uso único);
- os jobs entregam CÓPIA PROFUNDA dos dados ao módulo e rodam sob o lock do escopo ``(bot, servidor)``.
"""

from __future__ import annotations

import copy
import logging
import re
import time
from dataclasses import dataclass
from typing import Any, Callable, NamedTuple, Optional

import disnake

from empiremuse.panel.services.channel_tokens import ResetTokens
from empiremuse.panel.services.base import DBModel, DIGITS, Args, FormContext, first, flag, version_of
from empiremuse.panel.services.service import SettingsService
from empiremuse.panel.services.tasks import Job, Task, TaskFailure, TaskRunner
from empiremuse.utils import branding
from empiremuse.utils.music.converters import perms_translations
from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.request_channel import (
    MissingManagePermissions,
    apply_request_channel,
    build_channel_kwargs,
    create_request_channel,
    ensure_can_create_channel,
    ensure_can_reset,
    find_current_request_message,
    find_request_channel,
    missing_channel_permissions,
    reset_request_channel,
    validate_request_target,
)

logger = logging.getLogger(__name__)

MODES = ("existente", "criar")
KINDS = {"texto": "text", "voz": "voice", "palco": "stage"}
FORUM_TITLE_MIN, FORUM_TITLE_MAX = 4, 30
_ACCEPTED = (disnake.TextChannel, disnake.VoiceChannel, disnake.StageChannel, disnake.ForumChannel)
_TYPE_NAMES = (
    (disnake.StageChannel, "palco"),
    (disnake.VoiceChannel, "voz"),
    (disnake.ForumChannel, "forum"),
    (disnake.TextChannel, "texto"),
)

MSG_MODE = "Escolha como configurar o canal de pedidos."
MSG_CHANNEL = "Escolha um canal da lista."
MSG_TITLE = f"O título do post deve ter de {FORUM_TITLE_MIN} a {FORUM_TITLE_MAX} caracteres."
MSG_TYPE = "Escolha o tipo de canal: texto, voz ou palco."
MSG_STAGE = "Canais de palco só existem em servidores com o recurso Comunidade ativado."
MSG_CATEGORY = "Escolha uma categoria da lista (ou deixe sem categoria)."
MSG_PURGE = (
    "Para limpar as mensagens, o bot precisa das permissões Gerenciar Mensagens e Mostrar histórico de mensagens."
)
MSG_NO_CHANNEL = "Não há canal de pedidos configurado neste bot."
MSG_NAME = "Digite o nome exato do canal para confirmar a exclusão."
MSG_TOKEN = "A confirmação expirou ou é inválida. Peça a reinicialização de novo."
MSG_BUSY = "Já existe uma operação em andamento neste servidor. Aguarde terminar e tente de novo."
MSG_LIMIT = "Há operações demais em andamento. Aguarde um pouco e tente de novo."
MSG_PARTIAL = (
    "O canal de pedidos foi reiniciado no banco de dados, mas ocorreu um erro ao atualizar o Discord. "
    "Verifique o canal manualmente."
)
MSG_SETUP_OK = "O canal de pedidos foi configurado com sucesso."
MSG_RESET_OK = "O canal de pedidos foi reiniciado com sucesso."


class PanelActor:
    """Quem executa a ação no Discord: o usuário do painel (menção e ``str()`` para motivos/avisos)."""

    def __init__(self, user_id: str) -> None:
        self.id = user_id
        self.mention = f"<@{user_id}>"

    def __str__(self) -> str:
        return f"{self.id} (painel)"


def plain_message(text: str) -> str:
    """Texto de um ``GenericError`` sem markdown, menções nem blocos de código."""
    text = re.sub(r"```.*?```", "", text, flags=re.S)
    text = re.sub(r"<[@#][!&]?\d+>", "", text)
    text = text.replace("**", "").replace("`", "")
    return re.sub(r"[ \t]+", " ", text).strip()


MSG_MANAGE_PERMISSIONS = (
    f"O {branding.BOT_NAME} precisa da permissão Gerenciar permissões neste canal (ou de "
    "Administrador). Conceda a permissão ao cargo do bot ou escolha Criar um canal novo."
)


def refusal_message(exc: GenericError) -> str:
    """Mensagem da recusa em termos do painel (a do módulo compartilhado fala do comando ``/setup``)."""
    if isinstance(exc, MissingManagePermissions):
        return MSG_MANAGE_PERMISSIONS
    return plain_message(exc.text)


# ============================================================================ estruturas dos templates


class ChannelItem(NamedTuple):
    id: str
    nome: str
    tipo: str


class ChannelGroup(NamedTuple):
    categoria: Optional[str]
    canais: tuple[ChannelItem, ...]


class TypeOption(NamedTuple):
    value: str
    label: str


class CategoryOption(NamedTuple):
    id: str
    nome: str


class CurrentChannel(NamedTuple):
    configurado: bool
    nome: Optional[str]
    removido: bool


class Confirmation(NamedTuple):
    token: str
    deletar: bool
    nome_canal: str


class TaskView(NamedTuple):
    url: str
    estado: str
    final: bool
    titulo: str
    mensagem: str


@dataclass(frozen=True)
class SetupPlan:
    mode: str
    channel_id: int = 0
    purge: bool = False
    title: str = ""
    kind: str = "text"
    category_id: int = 0


@dataclass
class Check:
    """Resultado de uma validação: ``errors`` vazio = pode executar. ``echo`` devolve o que o usuário enviou."""

    errors: dict[str, str]
    echo: dict[str, Any]
    missing: tuple[str, ...] = ()
    plan: Optional[SetupPlan] = None


# ============================================================================ serviço


class ChannelService:
    def __init__(
        self, runner: TaskRunner, settings: SettingsService, secret: str, clock: Callable[[], float] = time.monotonic
    ) -> None:
        self.runner, self._settings = runner, settings
        self.tokens = ResetTokens(secret, clock)

    # ------------------------------------------------------------------ leitura

    @staticmethod
    def version(doc: dict) -> str:
        controller = doc["player_controller"]
        return version_of({"channel": controller.get("channel"), "message_id": controller.get("message_id")})

    @staticmethod
    def resolve(ctx: FormContext, raw: Optional[str], kinds: tuple) -> Optional[Any]:
        """Canal do cache do bot neste servidor, de um dos tipos aceitos; ``None`` se id inválido/alheio/de outro tipo."""
        if raw is None or not DIGITS.fullmatch(raw):
            return None
        channel = ctx.bot.get_channel(int(raw))
        if channel is None or getattr(getattr(channel, "guild", None), "id", None) != ctx.guild.id:
            return None
        return channel if isinstance(channel, kinds) else None

    @staticmethod
    def _guild_channels(guild: Any) -> list:
        channels = guild.channels
        return list(channels.values()) if isinstance(channels, dict) else list(channels)

    def current(self, ctx: FormContext, doc: dict) -> CurrentChannel:
        raw = doc["player_controller"].get("channel")
        if not raw:
            return CurrentChannel(False, None, False)
        channel = ctx.bot.get_channel(int(raw)) if str(raw).isdigit() else None
        name = str(channel.name) if channel is not None else None
        return CurrentChannel(True, name, name is None)

    def choices(
        self, ctx: FormContext
    ) -> tuple[tuple[ChannelGroup, ...], tuple[TypeOption, ...], tuple[CategoryOption, ...]]:
        channels = self._guild_channels(ctx.guild)
        grouped: dict[Optional[str], list[ChannelItem]] = {}
        for channel in channels:
            kind = next((name for cls, name in _TYPE_NAMES if isinstance(channel, cls)), None)
            if kind is None:
                continue
            category = getattr(channel, "category", None)
            grouped.setdefault(str(category.name) if category is not None else None, []).append(
                ChannelItem(str(channel.id), str(channel.name), kind)
            )
        groups = tuple(
            ChannelGroup(name, tuple(sorted(items, key=lambda i: i.nome.casefold())))
            for name, items in sorted(grouped.items(), key=lambda kv: (kv[0] is not None, (kv[0] or "").casefold()))
        )
        types = [TypeOption("texto", "Canal de texto"), TypeOption("voz", "Canal de voz")]
        if "COMMUNITY" in ctx.guild.features:
            types.append(TypeOption("palco", "Canal de palco"))
        categories = tuple(
            CategoryOption(str(c.id), str(c.name)) for c in channels if isinstance(c, disnake.CategoryChannel)
        )
        return groups, tuple(types), categories

    # ------------------------------------------------------------------ validação (síncrona, sem efeitos)

    def validate_setup(self, ctx: FormContext, args: Args) -> Check:
        mode = first(args, "modo") or ""
        echo = {
            "modo": mode,
            "canal": first(args, "canal") or "",
            "limpar_mensagens": flag(args, "limpar_mensagens"),
            "titulo_forum": (first(args, "titulo_forum") or "").strip(),
            "tipo": first(args, "tipo") or "",
            "categoria": first(args, "categoria") or "",
        }
        if mode not in MODES:
            return Check({"modo": MSG_MODE}, echo)
        if mode == "existente":
            return self._validate_existing(ctx, echo)
        return self._validate_create(ctx, echo)

    def _validate_existing(self, ctx: FormContext, echo: dict) -> Check:
        target = self.resolve(ctx, echo["canal"], _ACCEPTED)
        if target is None:
            return Check({"canal": MSG_CHANNEL}, echo)
        try:
            validate_request_target(ctx.bot, ctx.guild, target, existing_channel=True)
        except GenericError as exc:
            missing = tuple(perms_translations.get(p, p) for p in missing_channel_permissions(target))
            return Check({"canal": refusal_message(exc)}, echo, missing)
        errors: dict[str, str] = {}
        is_forum = isinstance(target, disnake.ForumChannel)
        if is_forum and not FORUM_TITLE_MIN <= len(echo["titulo_forum"]) <= FORUM_TITLE_MAX:
            errors["titulo_forum"] = MSG_TITLE
        purge = echo["limpar_mensagens"] and not is_forum
        if purge and not self._can_purge(ctx, target):
            errors["canal"] = MSG_PURGE
        if errors:
            return Check(errors, echo)
        plan = SetupPlan("existente", target.id, purge, echo["titulo_forum"] if is_forum else "")
        return Check({}, echo, plan=plan)

    @staticmethod
    def _can_purge(ctx: FormContext, target: Any) -> bool:
        permissions = target.permissions_for(ctx.guild.me)
        return bool(permissions.manage_messages and permissions.read_message_history)

    def _validate_create(self, ctx: FormContext, echo: dict) -> Check:
        errors: dict[str, str] = {}
        kind = KINDS.get(echo["tipo"])
        if kind is None:
            errors["tipo"] = MSG_TYPE
        elif kind == "stage" and "COMMUNITY" not in ctx.guild.features:
            errors["tipo"] = MSG_STAGE
        else:
            try:
                ensure_can_create_channel(ctx.bot, ctx.guild)
            except GenericError as exc:
                errors["tipo"] = refusal_message(exc)
        category_id = 0
        if echo["categoria"] != "":
            category = self.resolve(ctx, echo["categoria"], (disnake.CategoryChannel,))
            if category is None:
                errors["categoria"] = MSG_CATEGORY
            else:
                category_id = category.id
        if errors:
            return Check(errors, echo)
        return Check({}, echo, plan=SetupPlan("criar", kind=kind or "text", category_id=category_id))

    def check_reset(self, ctx: FormContext, doc: dict) -> Optional[str]:
        """Mensagem de erro (pt-BR) se o reset não pode começar; ``None`` se pode."""
        raw = doc["player_controller"].get("channel")
        if not raw:
            return MSG_NO_CHANNEL
        try:
            ensure_can_reset(ctx.guild)
        except GenericError as exc:
            return refusal_message(exc)
        if self.current(ctx, doc).removido:
            return MSG_NO_CHANNEL
        return None

    def confirmation(self, ctx: FormContext, doc: dict, delete: bool) -> Confirmation:
        raw = str(doc["player_controller"]["channel"])
        token = self.tokens.issue(ctx.user_id, ctx.guild_id, ctx.bot_id, raw)
        return Confirmation(token, delete, self.current(ctx, doc).nome or "")

    def check_confirmation(self, ctx: FormContext, doc: dict, args: Args) -> tuple[str, Optional[str], dict[str, str]]:
        """(``"ok"`` | ``"invalido"`` | ``"outro"`` | ``"nome"``, token, erros)."""
        token = first(args, "token") or ""
        raw = str(doc["player_controller"].get("channel") or "")
        status = self.tokens.check(token, ctx.user_id, ctx.guild_id, ctx.bot_id, raw)
        if status:
            return status, None, {}
        if flag(args, "deletar") and (first(args, "confirmar_nome") or "") != (self.current(ctx, doc).nome or "\0"):
            return "nome", token, {"confirmar_nome": MSG_NAME}
        return "ok", token, {}

    # ------------------------------------------------------------------ tarefas

    def start_setup(self, ctx: FormContext, plan: SetupPlan) -> Task:
        return self.runner.submit(ctx.user_id, ctx.guild_id, ctx.bot_id, "setup", self._setup_job(ctx, plan))

    def start_reset(self, ctx: FormContext, delete: bool) -> Task:
        return self.runner.submit(ctx.user_id, ctx.guild_id, ctx.bot_id, "reset", self._reset_job(ctx, delete))

    def _setup_job(self, ctx: FormContext, plan: SetupPlan) -> Job:
        async def job() -> str:
            async with self._settings.lock(ctx.bot_id, ctx.guild_id):
                await self._setup(ctx, plan)
            return MSG_SETUP_OK

        return job

    async def _setup(self, ctx: FormContext, plan: SetupPlan) -> None:
        guild_data = copy.deepcopy(await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds))
        player, original_message = await find_current_request_message(ctx.bot, ctx.guild, guild_data)
        channel_kwargs = build_channel_kwargs(ctx.guild)
        try:
            target = await self._target(ctx, plan, channel_kwargs)
            await apply_request_channel(
                ctx.bot,
                ctx.guild,
                PanelActor(ctx.user_id),
                target,
                existing_channel=plan.mode == "existente",
                purge=plan.purge,
                channel_kwargs=channel_kwargs,
                channel_name=plan.title,
                original_message=original_message,
                player=player,
                guild_data=guild_data,
            )
        except GenericError as exc:
            raise TaskFailure(refusal_message(exc))
        self._audit(ctx, "setup")

    async def _target(self, ctx: FormContext, plan: SetupPlan, channel_kwargs: dict) -> Any:
        if plan.mode == "criar":
            ensure_can_create_channel(ctx.bot, ctx.guild)
            parent = ctx.bot.get_channel(plan.category_id) if plan.category_id else ctx.guild
            if parent is None:
                raise TaskFailure(MSG_CATEGORY)
            return await create_request_channel(ctx.bot, parent, plan.kind, channel_kwargs)
        target = ctx.bot.get_channel(plan.channel_id)
        if target is None:
            raise TaskFailure(MSG_CHANNEL)
        return target

    def _reset_job(self, ctx: FormContext, delete: bool) -> Job:
        async def job() -> str:
            async with self._settings.lock(ctx.bot_id, ctx.guild_id):
                await self._reset(ctx, delete)
            return MSG_RESET_OK

        return job

    async def _reset(self, ctx: FormContext, delete: bool) -> None:
        guild_data = copy.deepcopy(await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds))

        async def notify(event: str) -> None:
            return None

        try:
            channel = await find_request_channel(ctx.bot, ctx.guild_id, guild_data)
            await reset_request_channel(
                ctx.bot,
                ctx.guild,
                PanelActor(ctx.user_id),
                channel,
                delete_channel="sim" if delete else None,
                channel_inter=self._detached_channel(ctx),
                guild_data=guild_data,
                notify=notify,
            )
        except GenericError as exc:
            if "```" not in exc.text:
                raise TaskFailure(refusal_message(exc))
            self._audit(ctx, "reset")  # o banco já foi limpo; só o Discord falhou
            raise TaskFailure(MSG_PARTIAL)
        self._audit(ctx, "reset")

    @staticmethod
    def _detached_channel(ctx: FormContext) -> Any:
        """Onde o player volta a "falar" depois do reset: o canal de voz atual dele, se houver."""
        voice = getattr(ctx.guild.me, "voice", None)
        return getattr(voice, "channel", None)

    @staticmethod
    def _audit(ctx: FormContext, kind: str) -> None:
        # Só ids e o tipo da operação: título, nome de canal e token nunca vão para o log.
        logger.info(
            "Configuração alterada: usuario=%s servidor=%s escopo=%s categoria=canal campos=%s",
            ctx.user_id,
            ctx.guild_id,
            ctx.bot_id,
            kind,
        )

    # ------------------------------------------------------------------ exibição da tarefa

    @staticmethod
    def task_view(task: Task, guild_id: int) -> TaskView:
        title = "Configurando o canal de pedidos" if task.kind == "setup" else "Reiniciando o canal de pedidos"
        if task.state == "erro":
            title = "Não foi possível concluir"
        elif task.state == "ok":
            title = "Concluído"
        message = task.message or (
            "Aguardando a vez…" if task.state == "pendente" else "Isso pode levar alguns segundos."
        )
        return TaskView(
            f"/painel/servidores/{guild_id}/canal/tarefas/{task.id}", task.state, task.final, title, message
        )
