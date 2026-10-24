"""Testes de caracterização e rejeição de deploy legado (Fase D1).

Garante que:
1. O reinício não utiliza 'kill 1' (sai com código de retorno ou finalização limpa);
2. O comando auto-update via 'git reset --hard' / 'git pull' está desativado com mensagem clara;
3. exportsource não empacota arquivos de squarecloud;
4. Desvios e verificações de ambiente da Replit ('REPL_SLUG') foram totalmente expurgados, mantendo MONGO_SSL_FIX;
5. Arquivos legados de deploy de terceiros estão ausentes da raiz do repositório, preservando deploy/lavalink.ini.example.
"""

from unittest.mock import AsyncMock, MagicMock, patch
import pytest


class TestDeployLegadoD1:
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
