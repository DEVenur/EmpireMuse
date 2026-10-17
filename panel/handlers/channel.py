"""Categoria Canal de pedidos: página, configurar/reset (em dois passos) e acompanhamento das tarefas.

Só HTTP: validação, token e execução ficam em ``panel.services.channel.py`` e ``panel/services/tasks.py``.
"""

from __future__ import annotations

from typing import Any, Optional

import tornado.web

from panel.authz import GuildAccess, GuildAccessDenied
from panel.handlers.servers import initial_of
from panel.handlers.settings import MAX_BODY_BYTES, SettingsHandler, decode_args
from panel.services.base import (
    CONFLICT_TEXT,
    HEX16,
    INVALID_TEXT,
    KIND_ERROR,
    Args,
    DBModel,
    FormContext,
    Formulario,
    first,
    flag,
)
from panel.services.channel import MSG_BUSY, MSG_LIMIT, MSG_TOKEN, ChannelService, Check, Confirmation, TaskView
from panel.services.tasks import Task, TaskBusy, TaskLimit, valid_task_id

CHANNEL_TEMPLATE = "bloco_canal.html"
TASK_TEMPLATE = "bloco_tarefa_canal.html"
PAGE_TEMPLATE = "config_canal.html"
_MSG_RATE = "Muitas alterações em pouco tempo. Aguarde um minuto e tente novamente."
_MSG_ACTION = "Ação desconhecida."
_MSG_VERSION = "Não foi possível validar o formulário. Recarregue a página e tente novamente."
_DEFAULT_VALUES = {
    "modo": "existente",
    "canal": "",
    "limpar_mensagens": False,
    "titulo_forum": "",
    "tipo": "texto",
    "categoria": "",
}


class ChannelHandler(SettingsHandler):
    """``GET/POST /painel/servidores/<gid>/canal[?bot=<id>]``."""

    @property
    def channels(self) -> ChannelService:
        return self.application.settings["channel_service"]

    def _own_active_task(self, ctx: FormContext) -> Optional[Task]:
        """Tarefa ativa do servidor só se for do próprio usuário (a de outro daria 404 no polling)."""
        active = self.channels.runner.active_for_guild(ctx.guild_id)
        return active if active is not None and active.owner == ctx.user_id else None

    # ------------------------------------------------------------------ GET

    async def get(self, guild_id: str) -> None:  # type: ignore[override]
        try:
            ctx, access, action = await self._resolve(guild_id, "canal", fresh=False)
        except GuildAccessDenied:
            self._not_found()
            return
        doc = await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds)
        self._render(200, access, ctx, self._namespace_for(ctx, doc, action, task=self._own_active_task(ctx)))

    # ------------------------------------------------------------------ POST

    async def post(self, guild_id: str) -> None:  # type: ignore[override]
        if len(self.request.body) > MAX_BODY_BYTES:
            self._reject_plain(413, "Envio grande demais", "Os dados enviados excedem o limite permitido.")
            return
        if not self._write_allowed():
            await self._rate_limited_channel(guild_id)
            return
        try:
            ctx, access, action = await self._resolve(guild_id, "canal", fresh=True)
        except GuildAccessDenied:
            self._not_found()
            return
        args = decode_args(self)
        if self.channels.runner.active_for_guild(ctx.guild_id) is not None:
            # Antes do lock: a tarefa em andamento o segura até terminar e este POST não deve esperar por ela.
            doc = await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds)
            self._render(
                409,
                access,
                ctx,
                self._namespace_for(ctx, doc, action, message=MSG_BUSY, task=self._own_active_task(ctx)),
            )
            return
        async with self.application.settings["settings_service"].lock(ctx.bot_id, ctx.guild_id):
            status, namespace = await self._dispatch(ctx, action, args)
        self._render(status, access, ctx, namespace)

    async def _dispatch(self, ctx: FormContext, action: str, args: Args) -> tuple[int, dict[str, Any]]:
        doc = await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds)
        sent = first(args, "versao")
        if sent is None or not HEX16.fullmatch(sent):
            return 422, self._namespace_for(ctx, doc, action, message=_MSG_VERSION)
        if sent != self.channels.version(doc):
            return 409, self._namespace_for(ctx, doc, action, message=CONFLICT_TEXT)
        handler = {
            "configurar": self._configure,
            "reset": self._reset_step_one,
            "confirmar_reset": self._reset_confirm,
        }.get(first(args, "acao") or "")
        if handler is None:
            return 422, self._namespace_for(ctx, doc, action, message=_MSG_ACTION)
        return await handler(ctx, doc, action, args)

    async def _configure(self, ctx: FormContext, doc: dict, action: str, args: Args) -> tuple[int, dict[str, Any]]:
        check = self.channels.validate_setup(ctx, args)
        if check.errors or check.plan is None:
            return 422, self._invalid(ctx, doc, action, check)
        return self._start(ctx, doc, action, lambda: self.channels.start_setup(ctx, check.plan))

    async def _reset_step_one(self, ctx: FormContext, doc: dict, action: str, args: Args) -> tuple[int, dict[str, Any]]:
        error = self.channels.check_reset(ctx, doc)
        if error:
            return 422, self._namespace_for(ctx, doc, action, message=error, errors={"acao": error})
        confirmation = self.channels.confirmation(ctx, doc, flag(args, "deletar"))
        return 200, self._namespace_for(ctx, doc, action, confirmation=confirmation)

    async def _reset_confirm(self, ctx: FormContext, doc: dict, action: str, args: Args) -> tuple[int, dict[str, Any]]:
        error = self.channels.check_reset(ctx, doc)
        if error:
            return 422, self._namespace_for(ctx, doc, action, message=error, errors={"acao": error})
        status, token, errors = self.channels.check_confirmation(ctx, doc, args)
        if status == "outro":
            return 409, self._namespace_for(ctx, doc, action, message=CONFLICT_TEXT)
        if status == "invalido":
            return 422, self._namespace_for(ctx, doc, action, message=MSG_TOKEN)
        if errors:
            confirmation = Confirmation(token or "", True, self.channels.current(ctx, doc).nome or "")
            return 422, self._namespace_for(ctx, doc, action, errors=errors, confirmation=confirmation)
        delete = flag(args, "deletar")
        result = self._start(ctx, doc, action, lambda: self.channels.start_reset(ctx, delete))
        if result[0] == 202:
            self.channels.tokens.consume(token or "")
        return result

    def _start(self, ctx: FormContext, doc: dict, action: str, submit) -> tuple[int, dict[str, Any]]:
        try:
            task = submit()
        except TaskBusy:
            return 409, self._namespace_for(ctx, doc, action, message=MSG_BUSY, task=self._own_active_task(ctx))
        except TaskLimit:
            return 429, self._namespace_for(ctx, doc, action, message=MSG_LIMIT)
        return 202, self._namespace_for(ctx, doc, action, task=task)

    def _invalid(self, ctx: FormContext, doc: dict, action: str, check: Check) -> dict[str, Any]:
        return self._namespace_for(ctx, doc, action, values=check.echo, errors=check.errors, missing=check.missing)

    async def _rate_limited_channel(self, guild_id: str) -> None:
        self.set_header("Retry-After", "60")
        if not self._is_htmx():
            self.render_error(429, "Muitas requisições", _MSG_RATE)
            return
        try:
            ctx, access, action = await self._resolve(guild_id, "canal", fresh=False)
        except GuildAccessDenied:
            self._not_found()
            return
        doc = await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds)
        self._render(429, access, ctx, self._namespace_for(ctx, doc, action, message=_MSG_RATE))

    # ------------------------------------------------------------------ montagem do que vai ao template

    def _namespace_for(
        self,
        ctx: FormContext,
        doc: dict,
        action: str,
        *,
        values: Optional[dict] = None,
        errors: Optional[dict] = None,
        message: Optional[str] = None,
        task: Optional[Task] = None,
        confirmation: Optional[Confirmation] = None,
        missing: tuple[str, ...] = (),
    ) -> dict[str, Any]:
        groups, types, categories = self.channels.choices(ctx)
        text = message or (INVALID_TEXT if errors else None)
        form = Formulario(
            key="canal",
            form_id="canal-conteudo",
            template=CHANNEL_TEMPLATE,
            acao=action,
            versao=self.channels.version(doc),
            valores={**_DEFAULT_VALUES, **(values or {})},
            erros=errors or {},
            mensagem=text,
            mensagem_tipo=KIND_ERROR if text else None,
        )
        view: Optional[TaskView] = self.channels.task_view(task, ctx.guild_id) if task is not None else None
        return {
            "canal_atual": self.channels.current(ctx, doc),
            "formulario": form,
            "canais": groups,
            "tipos": types,
            "categorias_discord": categories,
            "permissoes_faltando": tuple(missing),
            "tarefa": view,
            "confirmacao": confirmation,
        }

    def _render(self, status: int, access: GuildAccess, ctx: FormContext, namespace: dict[str, Any]) -> None:
        self.set_status(status)
        common = {"acesso": access, "inicial": initial_of(access.name), "bot_atual": self._bot_ref(access, ctx)}
        if self._is_htmx():
            self.render_page(CHANNEL_TEMPLATE, **common, **namespace)
            return
        self.render_page(PAGE_TEMPLATE, mostrar_seletor=len(access.bots) >= 2, **common, **namespace)


class ChannelTaskHandler(ChannelHandler):
    """``GET /painel/servidores/<gid>/canal/tarefas/<id>``: estado da tarefa (só o dono, com acesso ainda válido)."""

    async def get(self, guild_id: str, task_id: str) -> None:  # type: ignore[override]
        task = self.channels.runner.get(task_id) if valid_task_id(task_id) else None
        if task is None or task.owner != self.session.user.id or str(task.guild_id) != guild_id:
            self._not_found()
            return
        try:
            ctx, access, action = await self._resolve(guild_id, "canal", fresh=False, bot_id=task.bot_id)
        except GuildAccessDenied:
            self._not_found()
            return
        view = self.channels.task_view(task, ctx.guild_id)
        if self._is_htmx():
            self.render_page(TASK_TEMPLATE, tarefa=view)
            return
        doc = await ctx.bot.get_data(ctx.guild_id, db_name=DBModel.guilds)
        self._render(200, access, ctx, self._namespace_for(ctx, doc, action, task=task))

    async def post(self, *args: str) -> None:  # type: ignore[override]
        """A URL de acompanhamento só aceita GET (o POST herdado tem outra assinatura e daria 500)."""
        raise tornado.web.HTTPError(405)
