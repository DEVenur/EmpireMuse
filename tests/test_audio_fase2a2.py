"""Fase 2, Trilha A2 — YouTube com cliente TV + OAuth (refresh token entregue ao Lavalink local pelo ambiente do processo).

Contrato: BRIEFING-FASE2.md ("Trilha A2" e notas seguintes). Interpretações: .qa-fase2a2-interp.txt (staging).
Sem rede, sem Java, sem Discord e sem produção: `subprocess.Popen` é um dublê e tudo roda em tmp_path.

API exigida do Backend (nomes fixados pelos testes):
  utils/branding.py        LAVALINK_BINARIES_URL -> release 0.0.3; LAVALINK_APPLICATION_YML_SHA256 = hash do yml 0.0.3;
                           LAVALINK_APPLICATION_YML_KNOWN_SHA256 inclui os yml 0.0.1 e 0.0.2 (substituídos na atualização).
  config_loader.py         DEFAULT_CONFIG["YOUTUBE_OAUTH_REFRESH_TOKEN"] = "" (segredo, texto).
  .example.env             YOUTUBE_OAUTH_REFRESH_TOKEN= (vazio).
  local_lavalink.py        run_lavalink(..., *, lavalink_file_sha256=None, youtube_oauth_refresh_token=None): com token, o
                           Popen recebe env= (cópia de os.environ + as 3 variáveis PLUGINS_YOUTUBE_OAUTH_*); sem token, nada.
  utils/client.py          start_lavalink passa youtube_oauth_refresh_token=self.config['YOUTUBE_OAUTH_REFRESH_TOKEN'].
  modules/legacy_cmds.py   exportsource nunca grava o token no .env exportado.
"""

import ast
import asyncio
import hashlib
import os
import re
import shutil
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import pytest

from utils import branding
from utils.music import local_lavalink as ll

ROOT = Path(__file__).resolve().parent.parent
STAGING_ENV = os.environ.get("EMPIREMUSE_STAGING")
RELEASE_003 = Path(STAGING_ENV) / "ll-binaries-0.0.3" if STAGING_ENV else None

BASE_003 = "https://github.com/DiscordEmpireHub/EmpireMuse-LL-binaries/releases/download/0.0.3"
YML_003_SHA256 = "a342d5575fac9c394faaaecaae17df1c8fc759dc8a8937ff839aeabb07cb6b95"
YML_002_SHA256 = "0d17d65f3b7d7a889f2b23f2719bd8a1e1aac77b90e0b77e9dacdbd35ce94801"
YML_001_SHA256 = "f93ce9789fb637dc20bd886857a4ed813ad80870b43d268bc0ce80c11f90bfc3"
JAR_SHA256 = "8cb801e591072c3689fafd71ccf571a95a4ead3cc35dfc045e157d763d89119a"
PLUGINS_SHA256 = {
    "youtube-plugin-2be8e542d3f6f178e048dca565892684c2e40177.jar": "b062effdda6abeaa46913dfd1b5d5600120b65f239ce88f30948c7213a3ca1c0",
    "lavasrc-plugin-4.8.3.jar": "4ec389bdae64fd381ee62fcdb902e15d9402823b1ad0b982bd5633619a07c1b3",
    "lavalink-2.6.1.jar": "1fc300ec80d4b1705eff0a3b2b4dae21177467c95a7f1e393ecf018c10f2aaf3",
}

OAUTH_ENV_VARS = (
    "PLUGINS_YOUTUBE_OAUTH_ENABLED",
    "PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN",
    "PLUGINS_YOUTUBE_OAUTH_SKIP_INITIALIZATION",
)
CONFIG_KEY = "YOUTUBE_OAUTH_REFRESH_TOKEN"
# Valor sintético com formato de refresh token do Google; nunca é um segredo real.
FAKE_TOKEN = "1//0gFAKE-refresh_TOKEN-qa-fase2a2-zZ9"


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def assert_no_token(where: str, *texts) -> None:
    """Falha sem imprimir o texto inspecionado (ele pode conter segredos reais do ambiente de desenvolvimento)."""
    if any(FAKE_TOKEN in text for text in texts):
        pytest.fail(f"o refresh token vazou em: {where}", pytrace=False)


# ============================================================================ (1) branding -> release 0.0.3


class TestBrandingRelease003:
    def test_binaries_base_url_points_to_003(self):
        assert branding.LAVALINK_BINARIES_URL == BASE_003

    def test_jar_and_yml_urls_derive_from_the_003_base(self):
        assert branding.LAVALINK_JAR_URL == BASE_003 + "/Lavalink.jar"
        assert branding.LAVALINK_APPLICATION_YML_URL == BASE_003 + "/application.yml"

    def test_application_yml_hash_is_the_003_one(self):
        assert branding.LAVALINK_APPLICATION_YML_SHA256 == YML_003_SHA256

    def test_002_yml_is_a_known_official_version_to_be_replaced(self):
        assert YML_002_SHA256 in branding.LAVALINK_APPLICATION_YML_KNOWN_SHA256

    def test_001_yml_is_still_a_known_official_version(self):
        assert YML_001_SHA256 in branding.LAVALINK_APPLICATION_YML_KNOWN_SHA256

    def test_the_current_yml_is_not_the_002_one(self):
        assert branding.LAVALINK_APPLICATION_YML_SHA256 != YML_002_SHA256

    def test_jar_and_plugin_hashes_are_unchanged_from_002(self):
        assert branding.LAVALINK_JAR_SHA256 == JAR_SHA256
        assert dict(branding.LAVALINK_PLUGIN_SHA256) == PLUGINS_SHA256

    def test_plugin_urls_are_built_from_the_003_base(self):
        for name in branding.LAVALINK_PLUGIN_SHA256:
            assert f"{branding.LAVALINK_BINARIES_URL}/{name}".startswith(BASE_003 + "/")

    def test_no_runtime_python_file_still_hardcodes_the_002_release(self):
        offenders = []
        # branding.py e local_lavalink.py podem listar URLs antigas de propósito (URLs oficiais de versões anteriores são
        # reconhecidas e atualizadas sozinhas — tests/test_audio_fase2a3.py); aqui só o que escolhe a versão atual.
        for rel in ("config_loader.py", "utils/client.py"):
            for lineno, line in enumerate((ROOT / rel).read_text("utf-8").splitlines(), start=1):
                if "EmpireMuse-LL-binaries/releases/download/0.0.2" in line:
                    offenders.append(f"{rel}:{lineno}")
        assert not offenders, f"URL da release 0.0.2 ainda fixa no código: {offenders}"


class TestReplacingThe002Yml:
    """O yml 0.0.2 (conhecido) deve ser substituído pelo 0.0.3; um yml personalizado, mantido (com as constantes reais)."""

    @pytest.fixture
    def net(self, monkeypatch):
        calls = []
        yml_003 = b"yml 0.0.3 simulado\n"

        class Resp:
            headers = {"content-length": str(len(yml_003))}
            status_code = 200

            def iter_content(self, chunk_size=1):
                yield yml_003

            def raise_for_status(self):
                return None

            def close(self):
                return None

            def __enter__(self):
                return self

            def __exit__(self, *exc):
                return False

        def fake_get(url, *args, **kwargs):
            calls.append(url)
            return Resp()

        monkeypatch.setattr(ll.requests, "get", fake_get)
        monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(yml_003))
        # a 0.0.2 é representada por um conteúdo local cujo hash é inserido nos "conhecidos" junto com a 0.0.1 real
        return SimpleNamespace(calls=calls, new=yml_003)

    def test_known_002_is_replaced_and_custom_is_kept(self, net, monkeypatch, tmp_path):
        old = b"yml oficial 0.0.2 simulado\n"
        monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_KNOWN_SHA256", frozenset({YML_001_SHA256, sha(old)}))
        target = tmp_path / "application.yml"
        target.write_bytes(old)
        ll._prepare_yml(str(tmp_path))
        assert target.read_bytes() == net.new, "o yml oficial anterior deve ser atualizado"
        assert net.calls == [branding.LAVALINK_APPLICATION_YML_URL]
        target.write_bytes(b"yml do dono\n")
        net.calls.clear()
        ll._prepare_yml(str(tmp_path))
        assert target.read_bytes() == b"yml do dono\n" and net.calls == []


# ============================================================================ (2) configuração do segredo


def _example_env_lines() -> list:
    return [l for l in (ROOT / ".example.env").read_text("utf-8").splitlines() if l.startswith(f"{CONFIG_KEY}=")]


class TestConfigKey:
    def test_default_config_declares_it_empty_and_as_text(self):
        import config_loader

        assert config_loader.DEFAULT_CONFIG.get(CONFIG_KEY, "<ausente>") == ""
        assert type(config_loader.DEFAULT_CONFIG[CONFIG_KEY]) is str

    def test_example_env_declares_it_exactly_once_and_empty(self):
        lines = _example_env_lines()
        assert len(lines) == 1, f".example.env deve ter uma linha {CONFIG_KEY}= (achou {len(lines)})"
        assert lines[0].split("=", 1)[1].strip().strip("'\"") == ""

    def test_example_env_documents_it_in_portuguese_with_a_secret_warning(self):
        lines = (ROOT / ".example.env").read_text("utf-8").splitlines()
        index = next(i for i, l in enumerate(lines) if l.startswith(f"{CONFIG_KEY}="))
        comment = "\n".join(l for l in lines[max(0, index - 12) : index] if l.lstrip().startswith("#")).lower()
        assert comment, "a variável precisa de comentário explicativo acima"
        assert "segredo" in comment or "secreto" in comment or "não compartilhe" in comment, (
            "o comentário deve avisar que o valor é um segredo"
        )
        assert "descartável" in comment, "o comentário deve recomendar uma conta Google descartável"

    @staticmethod
    def _isolated_loader(monkeypatch, tmp_path, dot_env_text=None):
        """`dotenv_values()` procura o .env a partir do módulo (não do cwd): sem isto o .env REAL do dono entraria no teste."""
        import config_loader
        import dotenv

        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv(CONFIG_KEY, raising=False)
        if dot_env_text is not None:
            (tmp_path / ".env").write_text(dot_env_text, encoding="utf-8")
        monkeypatch.setattr(config_loader, "dotenv_values", lambda *a, **k: dotenv.dotenv_values(tmp_path / ".env"))
        return config_loader

    def test_load_config_reads_it_from_the_environment_as_text(self, monkeypatch, tmp_path):
        loader = self._isolated_loader(monkeypatch, tmp_path)
        monkeypatch.setenv(CONFIG_KEY, FAKE_TOKEN)
        assert loader.load_config()[CONFIG_KEY] == FAKE_TOKEN

    def test_load_config_reads_it_from_dot_env(self, monkeypatch, tmp_path):
        loader = self._isolated_loader(monkeypatch, tmp_path, f"{CONFIG_KEY}='{FAKE_TOKEN}'\n")
        assert loader.load_config()[CONFIG_KEY] == FAKE_TOKEN

    def test_load_config_defaults_to_empty_without_environment(self, monkeypatch, tmp_path):
        loader = self._isolated_loader(monkeypatch, tmp_path, "")
        assert loader.load_config()[CONFIG_KEY] == ""

    def test_the_token_is_never_hardcoded_in_the_repo_example_or_default(self):
        import config_loader

        assert FAKE_TOKEN not in (ROOT / ".example.env").read_text("utf-8")
        assert not re.search(r"1//0[0-9A-Za-z_-]{20,}", (ROOT / ".example.env").read_text("utf-8"))
        assert not re.search(r"1//0[0-9A-Za-z_-]{20,}", repr(config_loader.DEFAULT_CONFIG))


# ============================================================================ (3) env do Popen


@pytest.fixture
def started(monkeypatch, tmp_path):
    """Executa run_lavalink sem rede/Java; registra (args, kwargs) de cada Popen. Os binários verificados já existem em tmp_path."""
    monkeypatch.chdir(tmp_path)
    jar, yml = b"JAR-A2", b"YML-A2\n"
    plugins = {name: f"plugin {name}".encode() for name in branding.LAVALINK_PLUGIN_SHA256}
    monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(jar))
    monkeypatch.setattr(branding, "LAVALINK_APPLICATION_YML_SHA256", sha(yml))
    monkeypatch.setattr(branding, "LAVALINK_PLUGIN_SHA256", {n: sha(d) for n, d in plugins.items()})
    (tmp_path / "Lavalink.jar").write_bytes(jar)
    (tmp_path / "application.yml").write_bytes(yml)
    (tmp_path / "plugins").mkdir()
    for name, data in plugins.items():
        (tmp_path / "plugins" / name).write_bytes(data)

    def no_network(*args, **kwargs):
        raise AssertionError("rede inesperada: tudo já está presente e verificado")

    monkeypatch.setattr(ll.requests, "get", no_network)
    monkeypatch.setattr(ll, "validate_java", lambda cmd, debug=False: cmd)
    monkeypatch.setattr(ll.platform, "architecture", lambda *a, **k: ("64bit", "ELF"))
    for var in OAUTH_ENV_VARS:
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("PATH", "/usr/bin:/bin:/caminho/do/java")
    records = []

    class FakePopen:
        def __init__(self, args, **kwargs):
            records.append((list(args), kwargs))

    monkeypatch.setattr(ll.subprocess, "Popen", FakePopen)
    return records


def start(token=None, **kwargs):
    if token is _OMIT:
        return ll.run_lavalink(lavalink_file_url=branding.LAVALINK_JAR_URL, **kwargs)
    return ll.run_lavalink(lavalink_file_url=branding.LAVALINK_JAR_URL, youtube_oauth_refresh_token=token, **kwargs)


_OMIT = object()


def env_of(record) -> dict:
    kwargs = record[1]
    env = kwargs.get("env")
    return dict(env) if env is not None else {}


class TestRunLavalinkOauthEnv:
    def test_with_token_the_java_process_gets_the_three_variables(self, started):
        start(FAKE_TOKEN)
        assert len(started) == 1
        env = env_of(started[0])
        assert env.get("PLUGINS_YOUTUBE_OAUTH_ENABLED") == "true"
        assert env.get("PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN") == FAKE_TOKEN
        assert env.get("PLUGINS_YOUTUBE_OAUTH_SKIP_INITIALIZATION") == "true"

    def test_with_token_the_environment_is_a_dict_of_strings(self, started):
        start(FAKE_TOKEN)
        env = started[0][1].get("env")
        assert isinstance(env, dict) and env
        assert all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())

    def test_with_token_only_the_allowlisted_environment_is_inherited(self, started, monkeypatch):
        # Fase 2.1 (item 2): o filho Java não herda mais o os.environ inteiro; a allowlist completa está em
        # tests/test_audio_fase2_1.py. Aqui: PATH segue (o java precisa ser achado) e uma variável qualquer NÃO segue.
        monkeypatch.setenv("QA_MARKER_VAR", "valor-herdado")
        start(FAKE_TOKEN)
        env = env_of(started[0])
        assert env.get("PATH") == "/usr/bin:/bin:/caminho/do/java", "sem PATH o processo não encontra o java"
        assert "QA_MARKER_VAR" not in env, "variável fora da allowlist vazou para o processo do Lavalink"

    def test_the_token_is_stripped_of_surrounding_whitespace(self, started):
        start(f"  {FAKE_TOKEN}\n")
        assert env_of(started[0]).get("PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN") == FAKE_TOKEN

    @pytest.mark.parametrize("token", [None, "", "   ", "\n\t "])
    def test_without_token_none_of_the_variables_is_set(self, started, token):
        start(token)
        assert len(started) == 1
        env = env_of(started[0])
        assert [v for v in OAUTH_ENV_VARS if v in env] == []

    def test_omitting_the_parameter_behaves_as_without_token(self, started):
        start(_OMIT)
        assert [v for v in OAUTH_ENV_VARS if v in env_of(started[0])] == []

    def test_the_process_is_still_started_once_with_the_jar(self, started):
        start(FAKE_TOKEN)
        assert len(started) == 1 and started[0][0][-2:] == ["-jar", "Lavalink.jar"]

    def test_the_token_never_appears_in_the_command_line(self, started):
        start(FAKE_TOKEN)
        args = started[0][0]
        assert_no_token("linha de comando do Java", *args)
        assert not any("refresh" in arg.lower() or "oauth" in arg.lower() for arg in args)

    def test_the_token_is_not_passed_through_any_other_popen_argument(self, started):
        start(FAKE_TOKEN)
        others = {k: v for k, v in started[0][1].items() if k != "env"}
        assert_no_token("argumentos do Popen além do env", repr(others))

    def test_the_bot_own_process_environment_is_not_mutated(self, started):
        start(FAKE_TOKEN)
        assert [v for v in OAUTH_ENV_VARS if v in os.environ] == [], (
            "o ambiente do processo do bot (herdado por git/shell) não pode receber o token; só o env do Popen"
        )

    def test_each_start_computes_its_own_environment(self, started):
        start(FAKE_TOKEN)
        start(None)
        assert "PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN" in env_of(started[0])
        assert "PLUGINS_YOUTUBE_OAUTH_REFRESH_TOKEN" not in env_of(started[1]), "sem vazamento entre inicializações"

    def test_the_token_is_never_written_to_disk(self, started, tmp_path):
        start(FAKE_TOKEN)
        offenders = [
            str(p.relative_to(tmp_path))
            for p in tmp_path.rglob("*")
            if p.is_file() and FAKE_TOKEN.encode() in p.read_bytes()
        ]
        assert offenders == [], f"token gravado em arquivo: {offenders}"

    def test_the_application_yml_stays_untouched(self, started, tmp_path):
        before = (tmp_path / "application.yml").read_bytes()
        start(FAKE_TOKEN)
        assert (tmp_path / "application.yml").read_bytes() == before

    def test_nothing_printed_contains_the_token(self, started, capsys):
        start(FAKE_TOKEN)
        captured = capsys.readouterr()
        assert_no_token("stdout/stderr", captured.out, captured.err)

    def test_no_log_record_contains_the_token(self, started, caplog):
        caplog.set_level(0)
        start(FAKE_TOKEN)
        text = "\n".join(f"{r.getMessage()} {r.args!r} {r.exc_text}" for r in caplog.records)
        assert_no_token("registros de log", text)

    def test_integrity_failure_never_starts_the_process_even_with_token(self, started, monkeypatch):
        monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(b"outro jar"))
        monkeypatch.setattr(ll.requests, "get", mock.Mock(side_effect=ll.requests.ConnectionError("sem rede")))
        with pytest.raises(ll.LavalinkDownloadError):
            start(FAKE_TOKEN)
        assert started == []

    def test_error_text_does_not_carry_the_token(self, started, monkeypatch):
        monkeypatch.setattr(branding, "LAVALINK_JAR_SHA256", sha(b"outro jar"))
        monkeypatch.setattr(ll.requests, "get", mock.Mock(side_effect=ll.requests.ConnectionError("sem rede")))
        with pytest.raises(ll.LavalinkDownloadError) as info:
            start(FAKE_TOKEN)
        assert_no_token("mensagem da exceção", str(info.value), repr(info.value))


class TestRunLavalinkSignatureA2:
    def test_token_parameter_is_keyword_only_and_defaults_to_empty(self):
        import inspect

        param = inspect.signature(ll.run_lavalink).parameters.get("youtube_oauth_refresh_token")
        assert param is not None, "run_lavalink precisa do parâmetro youtube_oauth_refresh_token"
        assert param.kind is inspect.Parameter.KEYWORD_ONLY
        assert param.default in (None, "")

    def test_positional_order_and_sha256_parameter_are_preserved(self):
        import inspect

        params = inspect.signature(ll.run_lavalink).parameters
        names = list(params)
        assert names[:6] == [
            "lavalink_file_url",
            "lavalink_initial_ram",
            "lavalink_ram_limit",
            "lavalink_additional_sleep",
            "lavalink_cpu_cores",
            "use_jabba",
        ]
        assert params["lavalink_file_sha256"].kind is inspect.Parameter.KEYWORD_ONLY

    def test_client_passes_the_configured_token_by_keyword(self):
        source = (ROOT / "utils" / "client.py").read_text("utf-8").replace('"', "'")
        assert "youtube_oauth_refresh_token=self.config['YOUTUBE_OAUTH_REFRESH_TOKEN']" in source

    def test_client_keeps_passing_the_sha256(self):
        source = (ROOT / "utils" / "client.py").read_text("utf-8").replace('"', "'")
        assert "lavalink_file_sha256=self.config['LAVALINK_FILE_SHA256']" in source


# ============================================================================ (4) o token nunca vaza


@pytest.fixture
def export_env(monkeypatch, tmp_path):
    """Roda `Owner.exportsource` sem Discord/git: captura o conteúdo do .env que iria dentro do source.zip."""
    from modules import legacy_cmds

    monkeypatch.chdir(tmp_path)
    shutil.copyfile(ROOT / ".example.env", tmp_path / ".example.env")
    (tmp_path / "git_dir").mkdir()
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "git_dir"))
    monkeypatch.delenv(CONFIG_KEY, raising=False)
    snapshots, sent = [], []

    async def fake_run_command(cmd):
        return ""

    monkeypatch.setattr(legacy_cmds, "run_command", fake_run_command)

    def fake_zip_dir(self, filelist):
        snapshots.append((tmp_path / ".env-temp").read_text(encoding="utf-8"))
        (tmp_path / "source.zip").write_bytes(b"PK")

    monkeypatch.setattr(legacy_cmds.Owner, "zip_dir", fake_zip_dir)

    async def author_send(*args, **kwargs):
        sent.append((args, kwargs))
        return SimpleNamespace(jump_url="https://discord.test/msg")

    async def run_in_executor(executor, func, *args):
        return func(*args)

    bot = SimpleNamespace(
        config={"SOURCE_REPO": "https://example.test/repo.git", "EXTRA_HINTS": ""},
        loop=SimpleNamespace(run_in_executor=run_in_executor),
        get_color=lambda me: 0,
        user="bot#0000",
    )
    cog = legacy_cmds.Owner(bot)
    ctx = SimpleNamespace(
        author=SimpleNamespace(send=author_send), guild=SimpleNamespace(me=None), send=mock.AsyncMock()
    )

    def run_export(flags=""):
        return asyncio.run(legacy_cmds.Owner.exportsource.callback(cog, ctx, flags=flags))

    return SimpleNamespace(
        run=run_export, snapshots=snapshots, sent=sent, tmp=tmp_path, ctx=ctx, monkeypatch=monkeypatch
    )


def exported_value(env_text: str):
    from dotenv import dotenv_values
    import io

    return dotenv_values(stream=io.StringIO(env_text)).get(CONFIG_KEY)


class TestExportNeverCarriesTheToken:
    def test_token_from_the_process_environment_is_not_exported(self, export_env):
        export_env.monkeypatch.setenv(CONFIG_KEY, FAKE_TOKEN)
        export_env.run()
        assert len(export_env.snapshots) == 1
        assert_no_token(".env exportado", export_env.snapshots[0])

    def test_token_from_dot_env_is_not_exported(self, export_env):
        (export_env.tmp / ".env").write_text(f"{CONFIG_KEY}='{FAKE_TOKEN}'\nTOKEN=''\n", encoding="utf-8")
        export_env.run()
        assert_no_token(".env exportado", export_env.snapshots[0])

    def test_token_from_config_json_is_not_exported(self, export_env):
        (export_env.tmp / "config.json").write_text(f'{{"{CONFIG_KEY}": "{FAKE_TOKEN}"}}', encoding="utf-8")
        export_env.run()
        assert_no_token(".env exportado", export_env.snapshots[0])

    def test_exported_entry_is_empty_or_absent(self, export_env):
        export_env.monkeypatch.setenv(CONFIG_KEY, FAKE_TOKEN)
        export_env.run()
        if exported_value(export_env.snapshots[0]) not in (None, ""):
            pytest.fail("a chave do refresh token deve sair vazia (ou ausente) no .env exportado", pytrace=False)

    def test_export_keeps_working_for_other_values(self, export_env):
        """Guarda: mascarar o segredo não pode quebrar a exportação das demais chaves."""
        export_env.monkeypatch.setenv("SPOTIFY_CLIENT_ID", "id-do-spotify-qa")
        export_env.monkeypatch.setenv(CONFIG_KEY, FAKE_TOKEN)
        export_env.run()
        if "id-do-spotify-qa" not in export_env.snapshots[0]:
            pytest.fail("a exportação das demais chaves foi quebrada", pytrace=False)

    def test_message_sent_to_the_owner_does_not_contain_the_token(self, export_env):
        export_env.monkeypatch.setenv(CONFIG_KEY, FAKE_TOKEN)
        export_env.run()
        assert_no_token("mensagem enviada ao dono", repr(export_env.sent), repr(export_env.ctx.send.call_args_list))

    def test_no_leftover_env_temp_file_contains_the_token(self, export_env):
        export_env.monkeypatch.setenv(CONFIG_KEY, FAKE_TOKEN)
        export_env.run()
        leftovers = [p.name for p in export_env.tmp.iterdir() if p.is_file() and FAKE_TOKEN.encode() in p.read_bytes()]
        assert leftovers == []


SINK_NAMES = frozenset(
    {
        "print",
        "debug",
        "info",
        "warning",
        "warn",
        "error",
        "exception",
        "critical",
        "log",
        "send",
        "send_message",
        "respond",
        "followup",
        "reply",
        "edit",
        "edit_message",
        "set_footer",
        "write",
    }
)
SENSITIVE_IDENTIFIERS = frozenset({CONFIG_KEY, "youtube_oauth_refresh_token", "oauth_refresh_token", "refresh_token"})
PRODUCTION_DIRS = ("empiremuse",)
PRODUCTION_FILES = ("main.py", "app.py")


def _production_python_files():
    assert (ROOT / "empiremuse").is_dir(), "empiremuse/ deve ser o pacote raiz de produção"
    files = [ROOT / name for name in PRODUCTION_FILES if (ROOT / name).is_file()]
    for directory in PRODUCTION_DIRS:
        files.extend(p for p in (ROOT / directory).rglob("*.py") if "__pycache__" not in p.parts)
    return sorted(files)


def _call_name(node: ast.Call) -> str:
    func = node.func
    return func.id if isinstance(func, ast.Name) else func.attr if isinstance(func, ast.Attribute) else ""


def _mentions_sensitive(node: ast.AST) -> bool:
    for sub in ast.walk(node):
        if isinstance(sub, ast.Constant) and isinstance(sub.value, str) and sub.value in SENSITIVE_IDENTIFIERS:
            return True
        if isinstance(sub, ast.Name) and sub.id in SENSITIVE_IDENTIFIERS:
            return True
        if isinstance(sub, ast.Attribute) and sub.attr in SENSITIVE_IDENTIFIERS:
            return True
    return False


def _is_direct_secret_reference(node: ast.AST) -> bool:
    """O valor atribuído É o segredo (`config['CHAVE']`, `config.get('CHAVE')`, `token`), não uma chamada que o recebe."""
    if isinstance(node, ast.Subscript):
        key = node.slice
        return isinstance(key, ast.Constant) and key.value in SENSITIVE_IDENTIFIERS
    if isinstance(node, ast.Name):
        return node.id in SENSITIVE_IDENTIFIERS
    if isinstance(node, ast.Attribute):
        return node.attr in SENSITIVE_IDENTIFIERS
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "get" and node.args:
        first = node.args[0]
        return isinstance(first, ast.Constant) and first.value in SENSITIVE_IDENTIFIERS
    return False


def _is_whole_config(node: ast.AST) -> bool:
    """`config`, `CONFIG`, `self.config`, `bot.config`, `dict(os.environ)` passados inteiros a um destino de saída."""
    if isinstance(node, ast.Name):
        return node.id in {"config", "CONFIG", "DEFAULT_CONFIG", "SECRETS"}
    if isinstance(node, ast.Attribute):
        return node.attr == "config"
    return False


class TestNoOutputSinkReceivesTheToken:
    """Guarda estática: nenhuma chamada de print/log/envio ao Discord referencia o token nem despeja a config inteira."""

    def test_no_sink_call_mentions_the_token(self):
        offenders = []
        for path in _production_python_files():
            tree = ast.parse(path.read_text("utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Call) and _call_name(node) in SINK_NAMES and _mentions_sensitive(node):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        assert offenders == [], f"chamada de saída (print/log/send) referencia o refresh token: {offenders}"

    def test_no_sink_call_dumps_the_whole_config(self):
        offenders = []
        for path in _production_python_files():
            tree = ast.parse(path.read_text("utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if not (isinstance(node, ast.Call) and _call_name(node) in SINK_NAMES):
                    continue
                values = list(node.args) + [kw.value for kw in node.keywords]
                if any(
                    _is_whole_config(v) or (isinstance(v, ast.FormattedValue) and _is_whole_config(v.value))
                    for v in values
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
                for sub in ast.walk(node):
                    if isinstance(sub, ast.FormattedValue) and _is_whole_config(sub.value):
                        offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        assert sorted(set(offenders)) == [], (
            f"saída com a configuração inteira (vazaria segredos): {sorted(set(offenders))}"
        )

    def test_only_the_expected_modules_reference_the_token(self):
        allowed = {"config_loader.py", "utils/client.py", "utils/music/local_lavalink.py", "modules/legacy_cmds.py"}
        found = set()
        for path in _production_python_files():
            if CONFIG_KEY in path.read_text("utf-8"):
                found.add(str(path.relative_to(ROOT)))
        assert found <= allowed, f"módulos inesperados leem o refresh token: {sorted(found - allowed)}"
        assert "config_loader.py" in found, "config_loader.py deve declarar a chave"
        assert "utils/client.py" in found, "client.py deve entregar o token ao Lavalink local"

    def test_the_token_is_not_stored_in_a_bot_or_pool_attribute(self):
        """Guarda: o valor só atravessa a chamada de run_lavalink; nada o copia para um atributo de longa vida."""
        offenders = []
        for path in _production_python_files():
            tree = ast.parse(path.read_text("utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if (
                    isinstance(node, ast.Assign)
                    and any(isinstance(t, ast.Attribute) for t in node.targets)
                    and _is_direct_secret_reference(node.value)
                ):
                    offenders.append(f"{path.relative_to(ROOT)}:{node.lineno}")
        assert offenders == [], f"refresh token copiado para atributo: {offenders}"


# ============================================================================ (5) application.yml 0.0.3


@pytest.fixture(scope="module")
def release_003():
    if not RELEASE_003 or not RELEASE_003.is_dir():
        pytest.skip("artefatos da release 0.0.3 ausentes; defina a variável EMPIREMUSE_STAGING para habilitar")
    return RELEASE_003


@pytest.fixture(scope="module")
def yml_003(release_003):
    from ruamel.yaml import YAML

    return YAML(typ="safe").load((release_003 / "application.yml").read_text("utf-8"))


class TestApplicationYml003:
    def test_its_sha256_matches_the_branding_constant(self, release_003):
        digest = sha((release_003 / "application.yml").read_bytes())
        assert digest == YML_003_SHA256, "o yml em staging mudou: atualize o contrato com o DevOps"
        assert branding.LAVALINK_APPLICATION_YML_SHA256 == digest

    def test_sha256sums_file_agrees_with_branding(self, release_003):
        sums = {}
        for line in (release_003 / "SHA256SUMS").read_text("utf-8").splitlines():
            digest, _, name = line.partition("  ")
            sums[name.strip()] = digest
        assert sums.get("application.yml") == branding.LAVALINK_APPLICATION_YML_SHA256
        assert sums.get("Lavalink.jar") == branding.LAVALINK_JAR_SHA256
        for name, digest in branding.LAVALINK_PLUGIN_SHA256.items():
            assert sums.get(name) == digest, name

    def test_youtube_oauth_handler_logger_is_at_warn(self, yml_003):
        level = yml_003["logging"]["level"]
        assert level.get("dev.lavalink.youtube.http.YoutubeOauth2Handler") == "WARN"

    def test_root_logger_is_not_lowered_to_debug_or_trace(self, yml_003):
        for logger, value in yml_003["logging"]["level"].items():
            assert str(value).upper() not in {"DEBUG", "TRACE"}, f"{logger} em {value} imprimiria o token"

    def test_youtube_clients_are_in_the_contract_order(self, yml_003):
        assert list(yml_003["plugins"]["youtube"]["clients"]) == [
            "MUSIC",
            "TV",
            "ANDROID_VR",
            "WEB",
            "WEBEMBEDDED",
            "TVHTML5_SIMPLY",
        ]

    def test_oauth_is_disabled_by_default(self, yml_003):
        assert yml_003["plugins"]["youtube"]["oauth"]["enabled"] is False

    def test_the_yml_never_carries_a_refresh_token(self, release_003, yml_003):
        oauth = yml_003["plugins"]["youtube"]["oauth"]
        assert not any("refresh" in str(key).lower() for key in oauth), "o token só vai pelo ambiente do processo"
        assert not re.search(r"1//0[0-9A-Za-z_-]{20,}", (release_003 / "application.yml").read_text("utf-8"))

    def test_the_yml_has_no_other_secret_than_the_known_local_password(self, release_003):
        text = (release_003 / "application.yml").read_text("utf-8")
        assert "refreshToken" not in text and "refresh_token" not in text.lower()

    def test_search_and_remote_cipher_settings_are_preserved_from_002(self, yml_003):
        youtube = yml_003["plugins"]["youtube"]
        assert youtube["enabled"] is True and youtube["allowSearch"] is True
        assert youtube["remoteCipher"]["url"] == "https://cipher.kikkia.dev"
        assert yml_003["lavalink"]["server"]["sources"]["youtube"] is False, "fonte embutida segue desativada"

    def test_plugin_dependencies_match_the_canonical_jar_names(self, yml_003):
        declared = [entry["dependency"] for entry in yml_003["lavalink"]["plugins"]]
        assert declared == [
            "dev.lavalink.youtube:youtube-plugin:2be8e542d3f6f178e048dca565892684c2e40177",
            "com.github.topi314.lavasrc:lavasrc-plugin:4.8.3",
            "dev.schlaubi.lyrics:lavalink:2.6.1",
        ]
