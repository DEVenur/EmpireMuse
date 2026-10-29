"""A23 (item 18, P4) — ``empiremuse/updater/releases.py``: releases imutáveis do GitHub, digest da imagem e CHANGELOG.

Um servidor aiohttp local (``aiohttp.test_utils``) faz o papel do GitHub: as URLs-base do módulo e os hosts permitidos são trocados por monkeypatch,
então nada sai da máquina e nada depende da implementação (sessão, leitura do corpo). Mensagens de erro são genéricas: sem URL nem detalhe.
"""

import asyncio
import importlib
import json
from collections import Counter
from types import ModuleType

import aiohttp
import pytest
import pytest_asyncio
from aiohttp import web
from aiohttp.test_utils import TestServer

from empiremuse.rules.release import Version
from empiremuse.updater.git_flow import UpdateError

pytestmark = [pytest.mark.critical, pytest.mark.asyncio]

DIGEST = "sha256:" + "ab" * 32
MSG_VERSOES = "Não consegui consultar as versões publicadas agora."
MSG_IMAGEM = "Não consegui conferir a imagem da versão publicada."
UM_MIB = 1024 * 1024


@pytest.fixture
def releases():
    return importlib.import_module("empiremuse.updater.releases")


class GitHubFalso:
    """Rotas configuráveis por teste: ``rotas[caminho] = handler``; ``chamadas`` conta os pedidos por caminho."""

    def __init__(self) -> None:
        self.rotas: dict[str, object] = {}
        self.chamadas: Counter[str] = Counter()
        self.pedidos: list[web.Request] = []
        self.url = ""

    async def tratar(self, request: web.Request) -> web.StreamResponse:
        self.chamadas[request.path] += 1
        self.pedidos.append(request)
        handler = self.rotas.get(request.path)
        if handler is None:
            return web.Response(status=404)
        return await handler(request) if callable(handler) else handler


@pytest_asyncio.fixture
async def github(releases, monkeypatch):
    falso = GitHubFalso()
    app = web.Application()
    app.router.add_route("*", "/{tail:.*}", falso.tratar)
    servidor = TestServer(app)
    await servidor.start_server()
    falso.url = str(servidor.make_url("")).rstrip("/")
    monkeypatch.setattr(releases, "GITHUB_API_URL", falso.url)
    monkeypatch.setattr(releases, "RAW_URL", falso.url)
    monkeypatch.setattr(releases, "ALLOWED_REDIRECT_HOSTS", ("127.0.0.1",))
    monkeypatch.setattr(releases, "ALLOWED_REDIRECT_SCHEMES", ("http",))
    yield falso
    await servidor.close()


@pytest_asyncio.fixture
async def sessao():
    async with aiohttp.ClientSession() as sessao:
        yield sessao


def release_json(
    tag: str, *, draft=False, prerelease=False, immutable=True, asset="image-digest.txt", url=None
) -> dict:
    assets = [{"name": asset, "browser_download_url": url or f"{BASE_ASSET}/{tag}/{asset}"}]
    return {
        "tag_name": tag,
        "draft": draft,
        "prerelease": prerelease,
        "immutable": immutable,
        "assets": assets,
    }


def responder_json(corpo) -> web.Response:
    return web.json_response(corpo)


API = "/repos/EmpireCommunity/EmpireMuse/releases"
BASE_ASSET = "https://github.com/EmpireCommunity/EmpireMuse/releases/download"


# ============================================================================ list_releases


@pytest.fixture
def hosts_do_github(releases, monkeypatch):
    """Para os testes de elegibilidade o asset vive no host de verdade (``github.com``, https); só a API fica no servidor local."""
    monkeypatch.setattr(releases, "ALLOWED_REDIRECT_HOSTS", ("github.com",))
    monkeypatch.setattr(releases, "ALLOWED_REDIRECT_SCHEMES", ("https",))


async def test_only_published_immutable_releases_with_the_digest_asset_are_eligible_newest_first(
    releases, github, sessao, hosts_do_github
):
    github.rotas[API] = responder_json(
        [
            release_json("v2.1.0"),
            release_json("v2.3.0"),
            release_json("v2.9.0", draft=True),
            release_json("v2.8.0", prerelease=True),
            release_json("v2.4.0-rc.1"),  # publicada como estável (prerelease false), mas a tag é rc: nunca é alvo
            release_json("v2.7.0", immutable=False),
            release_json("latest"),
            release_json("v2.6.0", asset="outro.txt"),
            release_json("v2.2.0"),
        ]
    )

    lista = await releases.list_releases(sessao)

    assert [(r.version, r.tag) for r in lista] == [
        (Version(2, 3, 0), "v2.3.0"),
        (Version(2, 2, 0), "v2.2.0"),
        (Version(2, 1, 0), "v2.1.0"),
    ]
    assert lista[0].digest_url == f"{BASE_ASSET}/v2.3.0/image-digest.txt"


@pytest.mark.parametrize(
    "url",
    [
        "https://github.com/outro/repo/releases/download/v2.1.0/image-digest.txt",
        f"{BASE_ASSET}/v9.9.9/image-digest.txt",
        f"{BASE_ASSET}/v2.1.0/outro.txt",
        f"{BASE_ASSET}/v2.1.0/image-digest.txt?x=1",
        f"{BASE_ASSET}/v2.1.0/image-digest.txt#x",
        f"{BASE_ASSET}/v2.1.0/../v2.1.0/image-digest.txt",
        f"{BASE_ASSET}/v2.1.0/image-digest.txt/",
        "https://evil.example/EmpireCommunity/EmpireMuse/releases/download/v2.1.0/image-digest.txt",
        "http://github.com/EmpireCommunity/EmpireMuse/releases/download/v2.1.0/image-digest.txt",
    ],
    ids=[
        "outro-repo",
        "outra-tag",
        "outro-arquivo",
        "query",
        "fragmento",
        "ponto-ponto",
        "barra-final",
        "host-fora-da-lista",
        "http",
    ],
)
async def test_a_release_whose_asset_url_is_not_exactly_the_published_digest_file_is_not_eligible(
    releases, github, sessao, hosts_do_github, url
):
    github.rotas[API] = responder_json([release_json("v2.2.0"), release_json("v2.1.0", url=url)])

    lista = await releases.list_releases(sessao)

    assert [r.tag for r in lista] == ["v2.2.0"]


async def test_the_listing_asks_for_30_releases_without_any_token(releases, github, sessao):
    github.rotas[API] = responder_json([])

    assert await releases.list_releases(sessao) == []

    (pedido,) = github.pedidos
    assert pedido.query == {"per_page": "30"} and "Authorization" not in pedido.headers


@pytest.mark.parametrize(
    "resposta",
    [
        web.Response(status=500),
        web.Response(status=404),
        web.Response(status=200, text="isto não é json", content_type="application/json"),
        web.Response(status=200, text='{"nao": "lista"}', content_type="application/json"),
        web.Response(status=200, body=b"[" + b" " * (UM_MIB + 10) + b"]", content_type="application/json"),
    ],
    ids=["500", "404", "json-invalido", "nao-e-lista", "maior-que-1-mib"],
)
async def test_any_bad_listing_response_is_one_generic_error(releases, github, sessao, resposta):
    github.rotas[API] = resposta

    with pytest.raises(UpdateError) as erro:
        await releases.list_releases(sessao)

    assert str(erro.value) == MSG_VERSOES and github.url not in str(erro.value)


async def test_a_listing_that_times_out_is_the_same_generic_error(releases, github, sessao, monkeypatch):
    monkeypatch.setattr(releases, "TIMEOUT", 0.05)
    nunca = asyncio.Event()

    async def travado(request: web.Request) -> web.Response:
        await nunca.wait()
        return web.Response()

    github.rotas[API] = travado

    with pytest.raises(UpdateError) as erro:
        await releases.list_releases(sessao)

    assert str(erro.value) == MSG_VERSOES


# ============================================================================ fetch_image_digest


def uma_release(releases, github, caminho="/dl/digest.txt"):
    return releases.Release(Version(2, 1, 0), "v2.1.0", f"{github.url}{caminho}")


@pytest.mark.parametrize(
    "corpo",
    [
        "sha256:" + "ab" * 31,
        "sha256:" + "AB" * 32,
        "sha1:" + "ab" * 20,
        DIGEST + " extra",
        "",
        "x" * 129,
        DIGEST + "\n" + "0" * 200,
    ],
    ids=[
        "curto",
        "maiusculas",
        "outro-algoritmo",
        "texto-extra",
        "vazio",
        "maior-que-128-bytes",
        "digest-seguido-de-lixo-grande",
    ],
)
async def test_a_malformed_or_oversized_digest_is_refused(releases, github, sessao, corpo):
    github.rotas["/dl/digest.txt"] = web.Response(text=corpo)

    with pytest.raises(UpdateError) as erro:
        await releases.fetch_image_digest(sessao, uma_release(releases, github))

    assert str(erro.value) == MSG_IMAGEM


@pytest.mark.parametrize("status", [404, 500])
async def test_a_failing_digest_download_is_the_generic_error(releases, github, sessao, status):
    github.rotas["/dl/digest.txt"] = web.Response(status=status)

    with pytest.raises(UpdateError) as erro:
        await releases.fetch_image_digest(sessao, uma_release(releases, github))

    assert str(erro.value) == MSG_IMAGEM


def redirecionar(para: str, status: int = 302):
    async def handler(request: web.Request) -> web.Response:
        return web.Response(status=status, headers={"Location": para})

    return handler


async def test_a_redirect_to_an_allowed_host_is_followed_by_hand(releases, github, sessao):
    github.rotas["/dl/digest.txt"] = redirecionar(f"{github.url}/cdn/digest.txt")
    github.rotas["/cdn/digest.txt"] = web.Response(text=DIGEST)

    assert await releases.fetch_image_digest(sessao, uma_release(releases, github)) == DIGEST


async def test_a_redirect_to_another_host_is_refused_and_never_requested(releases, github, sessao):
    destino = github.url.replace("127.0.0.1", "localhost")  # mesmo servidor, mas o host não está na lista
    github.rotas["/dl/digest.txt"] = redirecionar(f"{destino}/cdn/digest.txt")
    github.rotas["/cdn/digest.txt"] = web.Response(text=DIGEST)

    with pytest.raises(UpdateError) as erro:
        await releases.fetch_image_digest(sessao, uma_release(releases, github))

    assert str(erro.value) == MSG_IMAGEM and github.chamadas["/cdn/digest.txt"] == 0


async def test_a_redirect_to_a_scheme_that_is_not_allowed_is_refused(releases, github, sessao, monkeypatch):
    monkeypatch.setattr(releases, "ALLOWED_REDIRECT_SCHEMES", ("https",))  # o servidor de teste fala http
    github.rotas["/dl/digest.txt"] = redirecionar(f"{github.url}/cdn/digest.txt")
    github.rotas["/cdn/digest.txt"] = web.Response(text=DIGEST)

    with pytest.raises(UpdateError):
        await releases.fetch_image_digest(sessao, uma_release(releases, github))

    assert github.chamadas["/cdn/digest.txt"] == 0


async def encadear(github, saltos: int) -> None:
    """``/dl/digest.txt`` -> ``/salto/1`` -> ... -> ``/salto/<saltos>`` (cada um redireciona) -> ``/fim`` com o digest."""
    caminhos = ["/dl/digest.txt"] + [f"/salto/{n}" for n in range(1, saltos)]
    for atual, proximo in zip(caminhos, caminhos[1:] + ["/fim"]):
        github.rotas[atual] = redirecionar(f"{github.url}{proximo}")
    github.rotas["/fim"] = web.Response(text=DIGEST)


async def test_a_fourth_redirect_hop_is_refused(releases, github, sessao):
    await encadear(github, 4)

    with pytest.raises(UpdateError) as erro:
        await releases.fetch_image_digest(sessao, uma_release(releases, github))

    assert str(erro.value) == MSG_IMAGEM and github.chamadas["/fim"] == 0


# ============================================================================ fetch_changelog

CHANGELOG = "/EmpireCommunity/EmpireMuse/v2.1.0/CHANGELOG.md"


async def test_the_changelog_of_the_tag_is_read_as_utf8_with_replacement(releases, github, sessao):
    github.rotas[CHANGELOG] = web.Response(
        body="## [2.1.0]\n- novidade ação\n".encode() + b"\xff", content_type="text/plain"
    )

    texto = await releases.fetch_changelog(sessao, "v2.1.0")

    assert texto.startswith("## [2.1.0]\n- novidade ação\n") and "�" in texto


@pytest.mark.parametrize(
    "resposta",
    [web.Response(status=404), web.Response(status=500), web.Response(body=b"x" * (UM_MIB + 10))],
    ids=["404", "500", "maior-que-1-mib"],
)
async def test_a_failing_or_oversized_changelog_is_an_update_error(releases, github, sessao, resposta):
    github.rotas[CHANGELOG] = resposta

    with pytest.raises(UpdateError) as erro:
        await releases.fetch_changelog(sessao, "v2.1.0")

    assert github.url not in str(erro.value)


@pytest.mark.parametrize(
    "tag", ["latest", "../x", "v2.1.0/../../x", "v2.1", "", "v2.1.0\n"], ids=lambda t: repr(t)[:20]
)
async def test_an_invalid_tag_is_refused_without_any_request(releases, github, sessao, tag):
    with pytest.raises(UpdateError):
        await releases.fetch_changelog(sessao, tag)

    assert sum(github.chamadas.values()) == 0


# ============================================================================ fetch_changelog com tag rc (imagem rc)

TAGS_ACEITAS = ["v2.1.0", "v2.1.0-rc.1", "v2.1.0-rc.12", "v10.20.30-rc.3"]
TAGS_RECUSADAS = [
    "2.1.0",
    "v2.1",
    "v2.1.0-rc",
    "v2.1.0-rc.",
    "v2.1.0-beta.1",
    "v2.1.0/../x",
    "v2.1.0-rc.1/x",
    "v2.1.0-rc.1\n",
    "v2.1.0-rc.1 ",
    "v2.1.0-RC.1",
    "V2.1.0-rc.1",
    "v2.1.0-rc.-1",
    "v2.1.0-rc.1-rc.2",
    "v2.1.0+build",
    "v2.1.0-rc.1?x=1",
    "v2.1.0-rc.1#x",
    "../v2.1.0-rc.1",
]


@pytest.mark.parametrize("tag", TAGS_ACEITAS)
async def test_a_release_or_rc_tag_reaches_the_request_with_its_own_raw_path(
    releases: ModuleType, github: GitHubFalso, sessao: aiohttp.ClientSession, tag: str
) -> None:
    caminho = f"/EmpireCommunity/EmpireMuse/{tag}/CHANGELOG.md"
    github.rotas[caminho] = web.Response(body=f"## [x]\n- da {tag}\n".encode(), content_type="text/plain")

    texto = await releases.fetch_changelog(sessao, tag)

    assert texto == f"## [x]\n- da {tag}\n" and github.chamadas[caminho] == 1
    assert sum(github.chamadas.values()) == 1


@pytest.mark.parametrize("tag", TAGS_RECUSADAS, ids=lambda t: repr(t)[:24])
async def test_anything_else_is_refused_without_any_request(
    releases: ModuleType, github: GitHubFalso, sessao: aiohttp.ClientSession, tag: str
) -> None:
    with pytest.raises(UpdateError):
        await releases.fetch_changelog(sessao, tag)

    assert sum(github.chamadas.values()) == 0


async def test_an_rc_tag_that_does_not_exist_is_an_update_error_without_the_url(
    releases: ModuleType, github: GitHubFalso, sessao: aiohttp.ClientSession
) -> None:
    caminho = "/EmpireCommunity/EmpireMuse/v2.1.0-rc.1/CHANGELOG.md"
    github.rotas[caminho] = web.Response(status=404)

    with pytest.raises(UpdateError) as erro:
        await releases.fetch_changelog(sessao, "v2.1.0-rc.1")

    assert github.url not in str(erro.value) and github.chamadas[caminho] == 1
