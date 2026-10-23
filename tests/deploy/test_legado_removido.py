"""Testes de caracterização e rejeição de deploy legado (Fase D1).

Garante que:
1. O reinício não utiliza 'kill 1' (sai com código de retorno ou finalização limpa);
2. O comando auto-update via 'git reset --hard' / 'git pull' está desativado com mensagem clara;
3. exportsource não empacota arquivos de squarecloud;
4. Desvios e verificações de ambiente da Replit ('REPL_SLUG') foram totalmente expurgados, mantendo MONGO_SSL_FIX;
5. Arquivos legados de deploy de terceiros estão ausentes da raiz do repositório, preservando deploy/lavalink.ini.example.
"""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from empiremuse.paths import PROJECT_DIR
from empiremuse.utils.music.errors import GenericError
from empiremuse.cogs.legacy_cmds import Owner


LEGACY_FILES = [
    ".Dockerfile",
    ".gitpod.yml",
    ".replit",
    "replit.nix",
    "deploy_handlers",
    "render.yaml",
    "squarecloud.config.example",
    "discloud.config.example",
    "source_cleanup.sh",
    "source_cleanup_windows.bat",
    "source_quick_setup.sh",
    "source_quick_update.sh",
    "source_setup.sh",
    "source_start.sh",
    "source_start_windows.bat",
    "source_update.sh",
    "app.py",
]


class TestDeployLegadoD1:
    def test_arquivos_legados_ausentes(self):
        """(5) Arquivos legados de deploy e scripts de terceiros devem ser removidos da raiz."""
        present_files = [f for f in LEGACY_FILES if (PROJECT_DIR / f).exists()]
        assert not present_files, f"Arquivos legados ainda presentes no repositório: {present_files}"
        # o exemplo de nós Lavalink foi para deploy/ (F3-7, D6) e não pode voltar para a raiz
        assert (PROJECT_DIR / "deploy" / "lavalink.ini.example").is_file(), (
            "deploy/lavalink.ini.example deve ser preservado"
        )
        assert not (PROJECT_DIR / "lavalink.ini.example").exists(), "lavalink.ini.example voltou para a raiz"

    def test_nenhum_uso_de_kill_1_no_codigo(self):
        """(1) O código do pacote empiremuse não deve conter invocações de 'kill 1'."""
        py_files = list((PROJECT_DIR / "empiremuse").rglob("*.py"))
        offenders = []
        for file in py_files:
            text = file.read_text(encoding="utf-8")
            if "kill 1" in text:
                offenders.append(str(file.relative_to(PROJECT_DIR)))
        assert not offenders, f"Invocação de 'kill 1' encontrada em: {offenders}"

    def test_desvios_de_repl_slug_expurgados(self):
        """(4) REPL_SLUG não deve ser referenciado no código de produção; MONGO_SSL_FIX deve ser mantido."""
        py_files = list((PROJECT_DIR / "empiremuse").rglob("*.py"))
        offenders = []
        for file in py_files:
            text = file.read_text(encoding="utf-8")
            if "REPL_SLUG" in text:
                offenders.append(str(file.relative_to(PROJECT_DIR)))
        assert not offenders, f"Referência a REPL_SLUG encontrada em: {offenders}"

        # Confirma que MONGO_SSL_FIX continua presente em empiremuse/utils/db.py
        db_text = (PROJECT_DIR / "empiremuse" / "utils" / "db.py").read_text(encoding="utf-8")
        assert "MONGO_SSL_FIX" in db_text, "MONGO_SSL_FIX deve ser mantido em empiremuse/utils/db.py"

    def test_exportsource_sem_squarecloud(self):
        """(3) additional_files do Owner não deve referenciar squarecloud."""
        assert not any("squarecloud" in f for f in Owner.additional_files), (
            f"Owner.additional_files ainda contém referências a squarecloud: {Owner.additional_files}"
        )

    @pytest.mark.asyncio
    async def test_auto_update_desativado_com_mensagem_clara(self, monkeypatch):
        """(2) O comando update via git deve estar desativado com mensagem explicativa."""
        owner_cog = Owner.__new__(Owner)
        owner_cog.bot = None

        class DummyCtx:
            author = None
            guild = None
            response = None

        # Ao chamar update, deve levantar GenericError ou informar que foi desativado
        with pytest.raises(GenericError) as exc_info:
            await owner_cog.update.callback(owner_cog, DummyCtx())

        msg = str(exc_info.value).lower()
        assert "desativad" in msg or "release" in msg or "imagem" in msg, (
            f"Mensagem de desativação do update inesperada: {exc_info.value}"
        )

    def test_metodos_e_listeners_auto_update_removidos(self):
        """Métodos destrutivos de git/pip e listener de updatecmd não devem existir no Owner."""
        assert not hasattr(Owner, "cleanup_git"), "Owner.cleanup_git deve ser removido"
        assert not hasattr(Owner, "update_deps"), "Owner.update_deps deve ser removido"
        assert not hasattr(Owner, "update_flags"), "Owner.update_flags deve ser removido"
        assert not hasattr(Owner, "update_buttons"), "Owner.update_buttons deve ser removido"

        # Nenhum listener registrado responde a updatecmd
        for listener in getattr(Owner, "_Cog__listeners", []):
            listener_name = listener[1] if isinstance(listener, tuple) else str(listener)
            assert "updatecmd" not in listener_name and "update_buttons" not in listener_name

        dummy_bot = MagicMock()
        dummy_bot.config = {"SOURCE_REPO": "https://github.com/test/repo.git", "EXTRA_HINTS": ""}
        owner_inst = Owner(dummy_bot)
        assert not hasattr(owner_inst, "git_init_cmds"), "Owner.git_init_cmds deve ser removido"

    @pytest.mark.asyncio
    async def test_botpool_shutdown_fecha_bots_mata_lavalink_e_define_exit_code(self):
        """BotPool.shutdown deve definir exit_code, fechar bots abertos e finalizar Lavalink local."""
        from empiremuse.utils.client import BotPool

        pool = BotPool.__new__(BotPool)
        pool.exit_code = 0
        pool.killing_state = False
        pool.lavalink_instance = MagicMock()

        bot_aberto = AsyncMock()
        bot_aberto.is_closed = MagicMock(return_value=False)
        bot_fechado = AsyncMock()
        bot_fechado.is_closed = MagicMock(return_value=True)

        pool.bots = [bot_aberto, bot_fechado]
        pool.guild_bots = {}

        await pool.shutdown(exit_code=42)

        assert pool.exit_code == 42
        assert pool.killing_state is True
        bot_aberto.close.assert_awaited_once()
        bot_fechado.close.assert_not_awaited()
        pool.lavalink_instance.kill.assert_called_once()

    @pytest.mark.asyncio
    async def test_botpool_shutdown_registra_warning_se_fechamento_falhar(self):
        """BotPool.shutdown deve registrar logger.warning com exc_info=True se fechar bot ou lavalink falhar."""
        from empiremuse.utils.client import BotPool

        pool = BotPool.__new__(BotPool)
        pool.exit_code = 0
        pool.killing_state = False
        pool.lavalink_instance = MagicMock()
        pool.lavalink_instance.kill.side_effect = RuntimeError("falha lavalink")

        bot_falho = AsyncMock()
        bot_falho.identifier = "bot_1"
        bot_falho.is_closed = MagicMock(return_value=False)
        bot_falho.close.side_effect = RuntimeError("falha fechar")

        pool.bots = [bot_falho]
        pool.guild_bots = {}

        with patch("empiremuse.utils.client.logger.warning") as mock_warn:
            await pool.shutdown(exit_code=1)

            assert mock_warn.call_count == 2
            bot_call = mock_warn.call_args_list[0]
            assert "bot" in bot_call[0][0].lower()
            assert bot_call[1].get("exc_info") is True
            ll_call = mock_warn.call_args_list[1]
            assert "lavalink" in ll_call[0][0].lower()
            assert ll_call[1].get("exc_info") is True

    def test_integracao_shutdown_ordena_loop_sem_runtime_error(self):
        """Loop real com 2 bots que chamam shutdown(1) deve concluir run_until_complete sem RuntimeError."""
        import asyncio
        from empiremuse.utils.client import BotPool

        loop = asyncio.new_event_loop()
        try:
            pool = BotPool.__new__(BotPool)
            pool.exit_code = 0
            pool.killing_state = False
            pool.lavalink_instance = None
            pool.loop = loop
            pool.guild_bots = {}

            class FakeBot:
                def __init__(self, identifier: str, should_trigger_shutdown: bool = False):
                    self.identifier = identifier
                    self.should_trigger_shutdown = should_trigger_shutdown
                    self._closed = False
                    self.close_event = asyncio.Event()
                    self.http = MagicMock()
                    self.http.token = f"token-{identifier}"

                def is_closed(self) -> bool:
                    return self._closed

                async def start(self, token: str):
                    if self.should_trigger_shutdown:
                        await asyncio.sleep(0.01)
                        await pool.shutdown(1)
                    await self.close_event.wait()

                async def close(self):
                    self._closed = True
                    self.close_event.set()

            bot1 = FakeBot("bot-1", should_trigger_shutdown=True)
            bot2 = FakeBot("bot-2", should_trigger_shutdown=False)
            pool.bots = [bot1, bot2]

            # run_until_complete deve concluir normalmente sem levantar RuntimeError
            loop.run_until_complete(pool.run_bots(pool.get_all_bots()))

            assert pool.exit_code == 1
            assert bot1.is_closed() is True
            assert bot2.is_closed() is True
        finally:
            loop.close()

    @pytest.mark.asyncio
    async def test_ratelimit_429_aciona_shutdown(self, monkeypatch):
        """Ratelimit 429 no start_bot deve acionar pool.shutdown(1)."""
        import disnake
        from empiremuse.utils.client import BotPool

        pool = BotPool.__new__(BotPool)
        pool.config = {"KILL_ON_429": True}
        pool.killing_state = False
        pool.shutdown = AsyncMock()

        monkeypatch.setattr("asyncio.sleep", AsyncMock())

        mock_bot = AsyncMock()
        mock_bot.http = MagicMock()
        mock_bot.http.token = "fake-token"
        resp = MagicMock()
        resp.status = 429
        resp.reason = "Too Many Requests"
        mock_bot.start.side_effect = disnake.HTTPException(resp, "429 Too Many Requests")

        await pool.start_bot(mock_bot)

        pool.shutdown.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_error_handler_process_interaction_error_aciona_shutdown(self, monkeypatch):
        """process_interaction_error com kill_process=True deve acionar pool.shutdown(1)."""
        from empiremuse.cogs.error_handler import ErrorHandler

        dummy_bot = MagicMock()
        dummy_bot.pool = MagicMock()
        dummy_bot.pool.shutdown = AsyncMock()
        dummy_bot.config = {
            "AUTO_ERROR_REPORT_WEBHOOK": False,
            "ERROR_REPORT_WEBHOOK": "",
            "SUPPORT_SERVER": "",
        }
        handler = ErrorHandler(dummy_bot)

        monkeypatch.setattr(
            "empiremuse.cogs.error_handler.parse_error",
            lambda inter, error, **kwargs: ("erro", "traceback", True, [], False),
        )
        monkeypatch.setattr("empiremuse.cogs.error_handler.send_message", AsyncMock())

        mock_inter = MagicMock()
        await handler.process_interaction_error(mock_inter, Exception("fatal"), resp_msg=False)

        dummy_bot.pool.shutdown.assert_awaited_once_with(1)

    @pytest.mark.asyncio
    async def test_error_handler_legacy_command_error_aciona_shutdown(self, monkeypatch):
        """on_legacy_command_error com kill_process=True deve acionar pool.shutdown(1)."""
        from empiremuse.cogs.error_handler import ErrorHandler

        dummy_bot = MagicMock()
        dummy_bot.pool = MagicMock()
        dummy_bot.pool.shutdown = AsyncMock()
        dummy_bot.config = {
            "AUTO_ERROR_REPORT_WEBHOOK": False,
            "ERROR_REPORT_WEBHOOK": "",
            "SUPPORT_SERVER": "",
        }
        dummy_bot.user = MagicMock()
        dummy_bot.user.mention = "@bot"
        handler = ErrorHandler(dummy_bot)

        monkeypatch.setattr(
            "empiremuse.cogs.error_handler.parse_error",
            lambda ctx, error, **kwargs: ("erro", "traceback", True, [], False),
        )

        mock_ctx = MagicMock()
        mock_ctx.bot = dummy_bot
        mock_ctx.author = MagicMock()
        mock_ctx.author.bot = False
        mock_ctx.prefix = "!"
        mock_ctx.command = MagicMock()
        mock_ctx.command.name = "test"
        mock_ctx.send = AsyncMock()

        await handler.on_legacy_command_error(mock_ctx, Exception("fatal"), resp_msg=False)

        dummy_bot.pool.shutdown.assert_awaited_once_with(1)

    def test_main_sai_com_pool_exit_code(self, monkeypatch):
        """__main__.main() deve sair com o exit_code configurado no pool."""
        import empiremuse.__main__ as main_module

        class MockPool:
            def __init__(self):
                self.exit_code = 42

            def setup(self):
                pass

        monkeypatch.setattr(main_module, "BotPool", MockPool)

        with pytest.raises(SystemExit) as exc_info:
            main_module.main()

        assert exc_info.value.code == 42
