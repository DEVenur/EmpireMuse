"""Teste do dono em produção 2.1.1, parte E — ``!updatelog`` sem ``.git`` (imagem Docker), com o Threat model do Vigil.

VE2 com versão: seção da versão em execução + link da tag (antes da seção, V-T7); VE3 consulta com ``UpdateError`` → só título e link; VE4 sem versão → releases;
VE5 (V-T1) cache e single-flight no módulo: 2 cogs + N chamadas → 1 consulta, todo 200 fica em cache, ``UpdateError`` só volta a consultar depois de ~60 s;
VE6 (V-T2) o aviso do caminho sai 1 vez por processo; VE7 (V-T3) a seção sai em embed, nunca no ``content``. E4: com ``.git`` nada muda e o painel recebe o texto.

Sem rede e sem relógio real: ``fetch_changelog``/``ClientSession`` são dublês no módulo do comando e o relógio é o ``time`` do módulo (o teste o avança).
O estado de módulo que o fix criar (cache, tarefas, aviso único) é fotografado e restaurado a cada teste.
"""

import asyncio
import copy
import logging
import time as tempo_real
from collections.abc import Iterator
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from empiremuse.cogs import legacy_cmds
from empiremuse.updater.git_flow import UpdateError
from empiremuse.utils import branding
from empiremuse.utils.others import CustomContext
from tests.support.drivers_de_regras import BotDeComandos

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

CANAL = 31
CACHE_NEGATIVO = 60
CHANGELOG = """# Changelog

## [2.1.1] - 2026-10-28
### Corrigido
- Item A da 2.1.1

## [2.1.0] - 2026-10-20
- Item B da 2.1.0
"""
CHANGELOG_DA_RC = """# Changelog

## [Unreleased]
- ainda não lançado

## [2.1.0] - em preparação
### Adicionado
- Item C da 2.1.0

## [2.0.2] - 2026-10-26
- Item D da 2.0.2
"""
CHANGELOG_RC_SEM_SECAO = (
    "# Changelog\n\n## [Unreleased]\n- ainda não lançado\n\n## [2.0.2] - 2026-10-26\n- Item D da 2.0.2\n"
)
CHANGELOG_SEM_A_VERSAO = "# Changelog\n\n## [2.0.0] - 2026-01-01\n- Item Z da 2.0.0\n"
TIPOS_DE_ESTADO = (dict, list, set, bool, int, float, str, type(None))


# ============================================================================ estado de módulo, relógio e rede


@pytest.fixture(autouse=True)
def estado_do_modulo_intacto() -> Iterator[None]:
    """Fotografa os dados simples do módulo e os restaura: cache, tarefas em voo e o aviso único não vazam entre testes."""
    espaco = vars(legacy_cmds)
    nomes = set(espaco)
    foto = {
        nome: copy.copy(valor)
        for nome, valor in espaco.items()
        if isinstance(valor, TIPOS_DE_ESTADO) and not nome.startswith("__")
    }
    yield
    for nome in set(espaco) - nomes:
        del espaco[nome]  # nomes novos do módulo (nunca dunders)
    for nome, valor in foto.items():
        atual = espaco.get(nome)
        if isinstance(valor, (dict, list, set)) and type(atual) is type(valor):
            atual.clear()
            atual.update(valor) if not isinstance(valor, list) else atual.extend(valor)
        else:
            espaco[nome] = valor


class Relogio:
    """O ``time`` do módulo do comando, com o relógio nas mãos do teste."""

    def __init__(self) -> None:
        self.agora = 1_000_000.0

    def monotonic(self) -> float:
        return self.agora

    time = perf_counter = monotonic

    def __getattr__(self, nome: str) -> object:
        return getattr(tempo_real, nome)


@pytest.fixture
def relogio(monkeypatch: pytest.MonkeyPatch) -> Relogio:
    r = Relogio()
    monkeypatch.setattr(legacy_cmds, "time", r)
    return r


class Rede:
    """``fetch_changelog`` e ``ClientSession`` dublados: contam as consultas e podem esperar um portão."""

    def __init__(self) -> None:
        self.consultas: list[str] = []
        self.sessoes = 0
        self.texto = CHANGELOG
        self.erro: Exception | None = None
        self.portao: asyncio.Event | None = None

    async def fetch(self, session: object, tag: str) -> str:
        self.consultas.append(tag)
        if self.portao is not None:
            await self.portao.wait()
        if self.erro is not None:
            raise self.erro
        return self.texto


@pytest.fixture
def rede(monkeypatch: pytest.MonkeyPatch) -> Rede:
    r = Rede()

    class Sessao:
        async def __aenter__(self) -> Sessao:
            r.sessoes += 1
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

    monkeypatch.setattr(legacy_cmds, "fetch_changelog", r.fetch)
    monkeypatch.setattr(legacy_cmds, "ClientSession", lambda *a, **k: Sessao())
    return r


@pytest.fixture
def sem_git(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GIT_DIR", str(tmp_path / "nao-existe" / ".git"))


def com_versao(monkeypatch: pytest.MonkeyPatch, versao: str | None) -> None:
    if versao is None:
        monkeypatch.delenv("EMPIREMUSE_VERSION", raising=False)
    else:
        monkeypatch.setenv("EMPIREMUSE_VERSION", versao)


# ============================================================================ contexto e chamada


class ContextoDePrefixo(CustomContext):
    """``isinstance(ctx, CustomContext)`` verdadeiro; guarda o que foi enviado."""

    def __init__(self) -> None:
        self.message = SimpleNamespace(guild=SimpleNamespace(id=CANAL, me=SimpleNamespace()))
        self.enviados: list[dict] = []

    async def send(self, content: str | None = None, **kwargs: object) -> None:
        self.enviados.append({"content": content, **kwargs})


def novo_cog() -> legacy_cmds.Owner:
    bot = BotDeComandos()
    bot.pool.remote_git_url = "https://exemplo.invalid/repo"
    return legacy_cmds.Owner(bot)


async def usar(cog: legacy_cmds.Owner | None = None) -> tuple[str | None, str]:
    """Roda o ``updatelog`` pelo prefixo; devolve ``(content, descrição do embed)``."""
    ctx = ContextoDePrefixo()
    await legacy_cmds.Owner.updatelog.callback(cog or novo_cog(), ctx)
    (envio,) = ctx.enviados
    return envio["content"], envio["embed"].description


async def usar_pelo_painel() -> str:
    return await legacy_cmds.Owner.updatelog.callback(novo_cog(), SimpleNamespace(guild=None))


# ============================================================================ VE2, VE3, VE4


class TestComVersao:
    async def test_it_shows_the_title_the_release_link_and_only_the_running_version(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")

        _, texto = await usar()

        assert "📈 **Novidades da versão 2.1.1 (em execução)**" in texto
        assert "Item A da 2.1.1" in texto and "Item B da 2.1.0" not in texto
        assert "Notas da versão" in texto and f"{branding.REPO_URL}/releases/tag/v2.1.1" in texto
        assert rede.consultas == ["v2.1.1"]

    async def test_the_release_link_comes_before_the_section(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")

        _, texto = await usar()

        assert texto.index("Novidades da versão") < texto.index("Notas da versão") < texto.index("Item A da 2.1.1")

    async def test_it_never_mentions_the_development_environment(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")

        _, texto = await usar()

        assert "desenvolvimento" not in texto.lower() and "repositório git" not in texto.lower()

    async def test_the_panel_gets_the_same_text_instead_of_an_error(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")

        texto = await usar_pelo_painel()

        assert isinstance(texto, str) and "Novidades da versão 2.1.1" in texto and "Item A da 2.1.1" in texto

    async def test_an_empty_section_gives_only_the_title_and_the_link(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.texto = CHANGELOG_SEM_A_VERSAO

        _, texto = await usar()

        assert "Novidades da versão 2.1.1" in texto and "releases/tag/v2.1.1" in texto and "Item Z" not in texto


class TestImagemRc:
    """O ``release.yml`` tira as notas de uma tag ``vX.Y.Z-rc.N`` da seção ESTÁVEL ``## [X.Y.Z]``: a imagem rc mostra essa seção."""

    async def test_the_stable_section_is_shown_while_the_fetch_asks_for_the_full_tag(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.0-rc.1")
        rede.texto = CHANGELOG_DA_RC

        _, texto = await usar()

        assert "Item C da 2.1.0" in texto and "Item D da 2.0.2" not in texto
        assert rede.consultas == ["v2.1.0-rc.1"]

    async def test_the_title_and_the_link_keep_the_rc(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.0-rc.1")
        rede.texto = CHANGELOG_DA_RC

        _, texto = await usar()

        assert "📈 **Novidades da versão 2.1.0-rc.1 (em execução)**" in texto
        assert f"{branding.REPO_URL}/releases/tag/v2.1.0-rc.1" in texto

    async def test_an_rc_without_the_stable_section_gives_only_the_title_and_the_link(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.0-rc.1")
        rede.texto = CHANGELOG_RC_SEM_SECAO

        _, texto = await usar()

        assert "Novidades da versão 2.1.0-rc.1" in texto and "releases/tag/v2.1.0-rc.1" in texto
        assert "Item D" not in texto and "ainda não lançado" not in texto

    async def test_two_rcs_of_the_same_version_are_fetched_separately(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rede.texto = CHANGELOG_DA_RC
        com_versao(monkeypatch, "2.1.0-rc.1")
        await usar()
        com_versao(monkeypatch, "2.1.0-rc.2")
        _, texto = await usar()

        assert rede.consultas == ["v2.1.0-rc.1", "v2.1.0-rc.2"] and "Item C da 2.1.0" in texto


class TestFalhaDaConsulta:
    async def test_an_update_error_gives_only_the_title_and_the_link_without_raising(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.erro = UpdateError("Não consegui obter o histórico de mudanças desta versão.")

        _, texto = await usar()

        assert "Novidades da versão 2.1.1" in texto and f"{branding.REPO_URL}/releases/tag/v2.1.1" in texto
        assert "Item A" not in texto and "Não consegui" not in texto

    async def test_the_failure_leaves_at_most_one_line_without_traceback(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.erro = UpdateError("falha-segura")

        with caplog.at_level(logging.DEBUG):
            await usar()

        proprios = [r for r in caplog.records if r.name == legacy_cmds.__name__ and r.levelno >= logging.WARNING]
        assert len(proprios) <= 2  # o aviso único do caminho sem ``.git`` e, no máximo, 1 linha da falha
        assert [r for r in caplog.records if r.exc_info] == []


class TestSemVersao:
    @pytest.mark.parametrize("versao", [None, "dev"], ids=["sem-variavel", "dev"])
    async def test_it_points_to_the_releases_and_never_fetches(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch, versao: str | None
    ) -> None:
        com_versao(monkeypatch, versao)

        _, texto = await usar()

        assert "**Não há histórico de atualizações neste bot.**" in texto
        assert "Versões publicadas" in texto and f"{branding.REPO_URL}/releases" in texto
        assert "desenvolvimento" not in texto.lower()
        assert rede.consultas == [] and rede.sessoes == 0

    async def test_the_panel_gets_the_message_instead_of_an_error(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, None)

        texto = await usar_pelo_painel()

        assert isinstance(texto, str) and "Não há histórico de atualizações neste bot." in texto


class TestComGit:
    async def test_with_git_nothing_changes_and_nothing_is_fetched(
        self, rede: Rede, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        (tmp_path / ".git").mkdir()
        monkeypatch.setenv("GIT_DIR", str(tmp_path / ".git"))
        com_versao(monkeypatch, "2.1.1")
        monkeypatch.setattr(
            legacy_cmds,
            "run_git",
            AsyncMock(return_value="a" * 40 + "*****abc1234*****mensagem do commit*****1700000000"),
        )

        _, texto = await usar()

        assert "Atualizações recentes" in texto and "abc1234" in texto and "Novidades da versão" not in texto
        assert rede.consultas == []


# ============================================================================ VE5 — cache e single-flight (V-T1)


async def ceder(vezes: int = 25) -> None:
    for _ in range(vezes):
        await asyncio.sleep(0)


class TestCacheEUmaConsultaSo:
    async def test_two_cogs_and_many_simultaneous_calls_make_one_fetch(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.portao = asyncio.Event()
        cogs = [novo_cog(), novo_cog()]

        chamadas = [asyncio.ensure_future(usar(cogs[i % 2])) for i in range(8)]
        await ceder()
        rede.portao.set()
        resultados = await asyncio.gather(*chamadas)

        assert rede.consultas == ["v2.1.1"] and rede.sessoes == 1
        assert all("Item A da 2.1.1" in texto for _, texto in resultados)

    async def test_a_200_stays_in_the_cache(self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch) -> None:
        com_versao(monkeypatch, "2.1.1")

        await usar()
        await usar(novo_cog())

        assert len(rede.consultas) == 1

    async def test_a_200_with_an_empty_section_is_cached_too(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.texto = CHANGELOG_SEM_A_VERSAO

        await usar()
        await usar()

        assert len(rede.consultas) == 1

    async def test_each_version_has_its_own_entry(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        await usar()
        com_versao(monkeypatch, "2.1.2")
        await usar()

        assert rede.consultas == ["v2.1.1", "v2.1.2"]

    async def test_simultaneous_failures_make_one_fetch_too(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.portao = asyncio.Event()
        rede.erro = UpdateError("falha")

        chamadas = [asyncio.ensure_future(usar()) for _ in range(6)]
        await ceder()
        rede.portao.set()
        resultados = await asyncio.gather(*chamadas)

        assert len(rede.consultas) == 1 and all("Novidades da versão" in texto for _, texto in resultados)

    async def test_a_caller_that_gives_up_does_not_cancel_the_others(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.portao = asyncio.Event()

        chamadas = [asyncio.ensure_future(usar()) for _ in range(3)]
        await ceder()
        chamadas[0].cancel()
        await ceder()
        rede.portao.set()
        resultados = await asyncio.gather(*chamadas, return_exceptions=True)

        assert isinstance(resultados[0], asyncio.CancelledError)
        assert all("Item A da 2.1.1" in texto for _, texto in resultados[1:])
        assert len(rede.consultas) == 1


class TestCacheNegativo:
    async def test_an_update_error_is_not_retried_inside_the_window(
        self, rede: Rede, relogio: Relogio, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.erro = UpdateError("falha")

        await usar()
        relogio.agora += CACHE_NEGATIVO - 1
        await usar()

        assert len(rede.consultas) == 1

    async def test_after_the_window_it_fetches_again(
        self, rede: Rede, relogio: Relogio, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.erro = UpdateError("falha")
        await usar()

        relogio.agora += CACHE_NEGATIVO + 1
        rede.erro = None
        _, texto = await usar()

        assert len(rede.consultas) == 2 and "Item A da 2.1.1" in texto

    async def test_the_recovered_fetch_is_cached_like_any_200(
        self, rede: Rede, relogio: Relogio, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.erro = UpdateError("falha")
        await usar()
        relogio.agora += CACHE_NEGATIVO + 1
        rede.erro = None
        await usar()

        relogio.agora += 10 * CACHE_NEGATIVO
        await usar()

        assert len(rede.consultas) == 2


# ============================================================================ VE6 — o aviso do caminho (V-T2)


class TestAvisoDoCaminho:
    @pytest.mark.parametrize("versao", ["2.1.1", None], ids=["com-versao", "sem-versao"])
    async def test_three_calls_leave_one_warning_and_the_rest_at_debug(
        self,
        rede: Rede,
        sem_git: None,
        monkeypatch: pytest.MonkeyPatch,
        caplog: pytest.LogCaptureFixture,
        versao: str | None,
    ) -> None:
        com_versao(monkeypatch, versao)

        with caplog.at_level(logging.DEBUG):
            for _ in range(3):
                await usar()

        proprios = [r for r in caplog.records if r.name == legacy_cmds.__name__]
        assert len([r for r in proprios if r.levelno >= logging.WARNING]) == 1
        assert len([r for r in proprios if r.levelno == logging.DEBUG]) >= 2

    async def test_the_warning_is_the_one_that_names_the_path(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
    ) -> None:
        com_versao(monkeypatch, None)

        with caplog.at_level(logging.DEBUG):
            await usar()

        (aviso,) = [r for r in caplog.records if r.name == legacy_cmds.__name__ and r.levelno == logging.WARNING]
        assert "updatelog" in aviso.getMessage() and aviso.exc_info is None

    async def test_the_path_never_reaches_the_user(
        self, rede: Rede, sem_git: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")

        _, texto = await usar()

        assert str(tmp_path) not in texto


# ============================================================================ VE7 — menção (V-T3)


class TestSemMencao:
    async def test_a_mention_inside_the_section_reaches_the_embed_but_never_the_content(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")
        rede.texto = "## [2.1.1] - 2026-10-28\n- avisa <@123> e @everyone\n"

        conteudo, texto = await usar()

        assert "<@123>" in texto
        assert not conteudo

    async def test_the_unreleased_path_without_version_also_sends_an_embed_without_content(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, None)

        conteudo, texto = await usar()

        assert not conteudo and texto
