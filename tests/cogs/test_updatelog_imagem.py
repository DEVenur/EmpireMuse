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
from collections.abc import AsyncIterator, Iterator
from pathlib import Path
from types import SimpleNamespace

import pytest

from empiremuse.cogs import legacy_cmds
from empiremuse.updater.git_flow import UpdateError
from empiremuse.utils import branding
from empiremuse.utils.others import CustomContext
from tests.support.drivers_de_regras import BotDeComandos

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

CANAL = 31
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
        self.iniciou = asyncio.Event()

    async def fetch(self, session: object, tag: str) -> str:
        self.consultas.append(tag)
        self.iniciou.set()
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


class RespostaHttp:
    """Só o que ``fetch_changelog`` REAL lê da resposta: status, cabeçalhos e o corpo em pedaços."""

    status = 200
    headers: dict[str, str] = {}

    def __init__(self, corpo: bytes) -> None:
        self.content = self
        self._corpo = corpo

    async def __aenter__(self) -> RespostaHttp:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False

    async def iter_chunked(self, tamanho: int) -> AsyncIterator[bytes]:
        yield self._corpo


class RedeHttp:
    """A camada HTTP dublada (``ClientSession``), com o ``fetch_changelog`` de verdade por cima."""

    def __init__(self) -> None:
        self.urls: list[str] = []
        self.texto = CHANGELOG

    def get(self, url: str, **kwargs: object) -> RespostaHttp:
        self.urls.append(url)
        return RespostaHttp(self.texto.encode())

    async def __aenter__(self) -> RedeHttp:
        return self

    async def __aexit__(self, *args: object) -> bool:
        return False


@pytest.fixture
def rede_http(monkeypatch: pytest.MonkeyPatch) -> RedeHttp:
    r = RedeHttp()
    monkeypatch.setattr(legacy_cmds, "ClientSession", lambda *a, **k: r)
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


class TestImagemRcComOFetchReal:
    """Sem trocar ``fetch_changelog``: a tag rc tem de passar pela validação dele e chegar ao pedido HTTP."""

    async def test_an_rc_image_requests_the_full_rc_tag_and_shows_the_stable_section(
        self, rede_http: RedeHttp, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.0-rc.1")
        rede_http.texto = CHANGELOG_DA_RC

        _, texto = await usar()

        assert rede_http.urls == [f"https://raw.githubusercontent.com/{branding.GITHUB_REPO}/v2.1.0-rc.1/CHANGELOG.md"]
        assert "Novidades da versão 2.1.0-rc.1" in texto and "Item C da 2.1.0" in texto
        assert "Item D da 2.0.2" not in texto


class TestFalhaDaConsulta:
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


# ============================================================================ VE5 — cache e single-flight (V-T1)


async def disparar(
    rede: Rede, monkeypatch: pytest.MonkeyPatch, quantidade: int, cogs: list[legacy_cmds.Owner] | None = None
) -> list[asyncio.Future]:
    """Dispara ``quantidade`` chamadas simultâneas e só devolve quando TODAS já passaram por ``image_version`` e a consulta já está parada no portão.

    Sem giros do laço: cada chamada roda até o seu primeiro ``await`` (o da consulta compartilhada) sem ser interrompida, então
    ter passado por ``image_version`` e o evento da consulta é a sincronização, e não um palpite de quantas voltas bastam.
    """
    rede.portao = asyncio.Event()
    chegaram: set[asyncio.Task] = set()
    todas = asyncio.Event()
    real = legacy_cmds.image_version

    def espiao(*args: object, **kwargs: object) -> object:
        chegaram.add(asyncio.current_task())
        if len(chegaram) >= quantidade:
            todas.set()
        return real(*args, **kwargs)

    monkeypatch.setattr(legacy_cmds, "image_version", espiao)
    chamadas = [asyncio.ensure_future(usar(cogs[i % len(cogs)] if cogs else None)) for i in range(quantidade)]
    await todas.wait()
    await rede.iniciou.wait()
    return chamadas


class TestCacheEUmaConsultaSo:
    async def test_two_cogs_and_many_simultaneous_calls_make_one_fetch(
        self, rede: Rede, sem_git: None, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")

        chamadas = await disparar(rede, monkeypatch, 8, [novo_cog(), novo_cog()])
        rede.portao.set()
        resultados = await asyncio.gather(*chamadas)

        assert rede.consultas == ["v2.1.1"] and rede.sessoes == 1
        assert all("Item A da 2.1.1" in texto for _, texto in resultados)


# ============================================================================ VE6 — o aviso do caminho (V-T2)


class TestAvisoDoCaminho:
    async def test_the_path_never_reaches_the_user(
        self, rede: Rede, sem_git: None, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        com_versao(monkeypatch, "2.1.1")

        _, texto = await usar()

        assert str(tmp_path) not in texto
