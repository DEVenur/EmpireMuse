"""Testes de caracterização e rejeição de deploy legado (Fase D1).

Garante que:
1. O reinício não utiliza 'kill 1' (sai com código de retorno ou finalização limpa);
2. O comando auto-update via 'git reset --hard' / 'git pull' está desativado com mensagem clara;
3. exportsource não empacota arquivos de squarecloud;
4. Desvios e verificações de ambiente da Replit ('REPL_SLUG') foram totalmente expurgados, mantendo MONGO_SSL_FIX;
5. Arquivos legados de deploy de terceiros estão ausentes da raiz do repositório, preservando lavalink.ini.example.
"""

from pathlib import Path
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
        # lavalink.ini.example deve ser mantido
        assert (PROJECT_DIR / "lavalink.ini.example").is_file(), "lavalink.ini.example deve ser preservado"

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
