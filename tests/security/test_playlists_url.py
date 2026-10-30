"""Importar playlists por link (item 17, P5, A10): o bot busca de DENTRO da rede dele, então cada porta do SSRF precisa estar fechada.

Só https e só quatro hosts exatos; todo IP resolvido precisa ser público; o ``yarl.URL`` conferido é o enviado; nada de redirect,
compressão, corpo sem teto ou espera sem fim; a URL (que pode ter ``?token=``) nunca aparece no log nem no erro. Sem rede real.
"""

import asyncio
import logging
import socket
import ssl

import aiohttp
import pytest
import yarl

from empiremuse.rules.errors import FILE_TOO_LARGE, IMPORT_FETCH_FAILED, IMPORT_URL_REFUSED, RuleError
from empiremuse.rules.limits import PLAYLIST_FILE_MAX_BYTES
from empiremuse.rules.playlists import IMPORT_URL_HOSTS, IMPORT_URL_MAX, check_import_url, is_public_address
from empiremuse.utils import server_playlists_fetch as fetch
from empiremuse.utils.server_playlists_fetch import PinnedResolver, default_session, fetch_import

pytestmark = pytest.mark.critical

GOOD = "https://raw.githubusercontent.com/dono/repo/main/playlists.json"
SECRET = "segredo-do-token-9f3a"
PUBLIC = ["8.8.8.8"]


# ---------------------------------------------------------------------- a regra do link


@pytest.mark.parametrize(
    ("raw", "normalized"),
    [
        (GOOD, GOOD),
        ("  " + GOOD + "  ", GOOD),
        ("HTTPS://RAW.GITHUBUSERCONTENT.COM/dono/p.json", "https://raw.githubusercontent.com/dono/p.json"),
        ("<" + GOOD + ">", GOOD),  # o Discord esconde a prévia assim
        ("https://gist.githubusercontent.com/u/abc/raw/p.json", "https://gist.githubusercontent.com/u/abc/raw/p.json"),
        ("https://raw.githubusercontent.com:443/u/p.json", "https://raw.githubusercontent.com/u/p.json"),  # sem porta
        (
            "https://cdn.discordapp.com/attachments/1/2/p.json?ex=a&hm=b",
            "https://cdn.discordapp.com/attachments/1/2/p.json?ex=a&hm=b",
        ),
        ("https://media.discordapp.net/a/b.json#trecho", "https://media.discordapp.net/a/b.json"),  # sem fragmento
    ],
)
def test_only_https_links_to_the_four_exact_hosts_are_accepted_and_come_back_normalized(raw, normalized):
    assert check_import_url(raw) == normalized


@pytest.mark.parametrize(
    "raw",
    [
        "http://raw.githubusercontent.com/u/p.json",
        "ftp://raw.githubusercontent.com/u/p.json",
        "javascript:alert(1)",
        "https://evil.com/p.json",
        "https://raw.githubusercontent.com.evil.com/p.json",  # host por prefixo
        "https://evilraw.githubusercontent.com/p.json",  # host por sufixo (endswith)
        "https://sub.raw.githubusercontent.com/p.json",
        "https://github.com/u/r/raw/main/p.json",
        "https://user:pw@raw.githubusercontent.com/p.json",  # credencial
        "https://raw.githubusercontent.com@evil.com/p.json",  # o host de verdade é evil.com
        "https://evil.com@raw.githubusercontent.com/p.json",
        "https://raw.githubusercontent.com:8443/p.json",
        "https://raw.githubusercontent.com:/p.json",  # porta vazia
        "https://raw.githubusercontent.com:443:80/p.json",
        "https://8.8.8.8/p.json",  # IP literal
        "https://[::1]/p.json",
        "https://[2606:4700::1111]/p.json",
        "https://raw.githubusercontent.com./p.json",  # ponto final
        "https://raw%2egithubusercontent.com/p.json",  # %2e no host
        "https://raw.githubusercontent.com\\@evil.com/p.json",  # barra invertida
        "https://raw.githubusercontent.com/a\\..\\b.json",  # barra invertida no caminho
        "https://raw.githubusercontent.com/p .json",  # espaço
        "https://raw.githubusercontent.com/p\x00.json",  # controle
        "https://raw.githubusercontent.com/p\n.json",
        "https://raw.githubusercontent.com/ç.json",  # fora do ASCII
        "https://raw.githubusercontent.com",  # sem caminho
        "//raw.githubusercontent.com/p.json",
        "raw.githubusercontent.com/p.json",
        "",
        "   ",
        "<>",
        None,
        42,
        ["https://raw.githubusercontent.com/p.json"],
        "https://raw.githubusercontent.com/" + "a" * IMPORT_URL_MAX,
    ],
)
def test_every_other_link_is_refused_without_repeating_it_in_the_error(raw):
    refused = check_import_url(raw)
    assert isinstance(refused, RuleError) and refused.code == IMPORT_URL_REFUSED
    assert not isinstance(raw, str) or not raw.strip() or raw[:40] not in repr(refused)  # o erro não carrega o link


def test_the_allowlist_has_exactly_the_four_hosts():
    assert IMPORT_URL_HOSTS == {
        "raw.githubusercontent.com",
        "gist.githubusercontent.com",
        "cdn.discordapp.com",
        "media.discordapp.net",
    }


@pytest.mark.parametrize(
    "address", ["8.8.8.8", "1.1.1.1", "2606:4700::1111", "::ffff:8.8.8.8", "64:ff9b::808:808", "::ffff:0:8.8.8.8"]
)
def test_public_addresses_are_public(address):
    assert is_public_address(address) is True


@pytest.mark.parametrize(
    "address",
    [
        "10.0.0.5",
        "172.16.0.1",
        "192.168.1.1",
        "127.0.0.1",
        "169.254.169.254",  # metadados de nuvem
        "100.64.0.1",  # CGNAT
        "0.0.0.0",
        "224.0.0.1",  # multicast
        "255.255.255.255",
        "::1",
        "::",
        "fe80::1",
        "fc00::1",
        "ff02::1",
        "::ffff:127.0.0.1",  # IPv4 mapeado
        "::ffff:10.0.0.5",
        "2002:7f00:1::",  # 6to4 com 127.0.0.1
        "64:ff9b::7f00:1",  # NAT64 com 127.0.0.1
        "::7f00:1",  # IPv4 compatível
        "::ffff:0:127.0.0.1",  # SIIT (RFC 2765) com loopback
        "::ffff:0:7f00:1",
        "::ffff:0:0:1",
        "fec0::1",  # site-local
        "5f00::1",  # SRv6
        "64:ff9b:1::1",  # NAT64 local
        "2001:db8::1",  # documentação
        "100::1",  # descarte
        "3fff::1",
        "2001::1",  # Teredo
        "192.0.0.1",  # protocolo IETF
        "2606:4700::1111%eth0",  # público, mas com escopo
        "fe80::1%eth0",  # com escopo
        "abc",
        "",
        "8.8.8.8/32",
        None,
        8888,
    ],
)
def test_private_reserved_embedded_and_malformed_addresses_are_not_public(address):
    assert is_public_address(address) is False


# ---------------------------------------------------------------------- dublês de rede (nada abre socket)


class Content:
    def __init__(self, chunks, hang=None):
        self.chunks, self.consumed, self.hang = list(chunks), 0, hang

    async def iter_chunked(self, size):
        for chunk in self.chunks:
            if self.hang is not None:
                await self.hang.wait()
            self.consumed += 1
            yield chunk


class Response:
    def __init__(self, *, status=200, headers=None, chunks=(b"{}",), hang=None, fail=None):
        self.status, self.headers, self.content, self.fail = status, headers or {}, Content(chunks, hang), fail

    async def __aenter__(self):
        if self.fail:
            raise self.fail
        return self

    async def __aexit__(self, *exc):
        return False


class Session:
    def __init__(self, response):
        self.response, self.calls = response, []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


class World:
    def __init__(self, response=None, addresses=PUBLIC, resolve_error=None, hang_resolve=None):
        self.response = response or Response()
        self.session = Session(self.response)
        self.addresses, self.resolve_error, self.hang_resolve = addresses, resolve_error, hang_resolve
        self.resolved, self.factories = [], []

    async def resolve(self, host, port):
        self.resolved.append((host, port))
        if self.hang_resolve is not None:
            await self.hang_resolve.wait()
        if self.resolve_error:
            raise self.resolve_error
        return self.addresses

    def factory(self, addresses, host):
        self.factories.append((list(addresses), host))
        return self.session

    async def fetch(self, url=GOOD, **kwargs):
        return await fetch_import(url, resolve=self.resolve, session_factory=self.factory, **kwargs)


@pytest.fixture(autouse=True)
def fresh_gate(monkeypatch):
    """O semáforo do módulo se prende ao laço do primeiro teste que disputa: cada teste usa o seu."""
    monkeypatch.setattr(fetch, "_gate", asyncio.Semaphore(fetch.MAX_CONCURRENT))


def is_error(result, code):
    return isinstance(result, RuleError) and result.code == code


# ---------------------------------------------------------------------- o caminho feliz e o que é enviado


@pytest.mark.asyncio
async def test_the_checked_url_is_the_one_sent_with_redirects_off_to_the_pinned_addresses():
    world = World(Response(chunks=[b'{"playlists": []}']))

    result = await world.fetch("<" + GOOD + "#trecho>")

    assert result == b'{"playlists": []}'
    assert world.resolved == [("raw.githubusercontent.com", 443)]
    assert world.factories == [(PUBLIC, "raw.githubusercontent.com")]  # conecta nos IPs conferidos, SNI no host
    ((url, kwargs),) = world.session.calls
    assert isinstance(url, yarl.URL) and url == yarl.URL(GOOD)
    assert (url.scheme, url.raw_host, url.explicit_port, url.user, url.raw_fragment) == (
        "https",
        "raw.githubusercontent.com",
        None,
        None,
        "",
    )
    assert kwargs == {"allow_redirects": False}  # um 302 para 169.254.169.254 nunca é seguido


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "url", ["http://raw.githubusercontent.com/p.json", "https://evil.com/p.json", None, "https://8.8.8.8/p.json"]
)
async def test_a_bad_link_is_refused_before_any_dns_or_session(url):
    world = World()
    assert is_error(await world.fetch(url), IMPORT_URL_REFUSED)
    assert world.resolved == [] and world.factories == []


# ---------------------------------------------------------------------- DNS: todo endereço público, ou nada


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "addresses",
    [
        ["10.0.0.5"],
        ["127.0.0.1"],
        ["169.254.169.254"],
        ["8.8.8.8", "10.0.0.5"],
        ["10.0.0.5", "8.8.8.8"],
        ["::ffff:127.0.0.1"],
        [],
        ["não é ip"],
    ],
    ids=["private", "loopback", "metadata", "mixed", "mixed_reversed", "mapped_loopback", "empty", "garbage"],
)
async def test_one_non_public_address_among_the_resolved_ones_refuses_the_link_without_opening_a_session(addresses):
    world = World(addresses=addresses)
    assert is_error(await world.fetch(), IMPORT_URL_REFUSED)
    assert world.factories == []  # nunca chega a conectar


@pytest.mark.asyncio
async def test_a_public_ipv6_answer_is_fine():
    assert await World(addresses=["2606:4700::1111", "8.8.8.8"]).fetch() == b"{}"


# ---------------------------------------------------------------------- a resposta


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [301, 302, 307, 308, 204, 400, 403, 404, 429, 500, 503])
async def test_anything_but_200_fails_and_redirects_are_not_followed(status):
    world = World(Response(status=status, headers={"Location": "http://169.254.169.254/latest/meta-data"}))
    assert is_error(await world.fetch(), IMPORT_FETCH_FAILED)
    assert world.session.calls[0][1]["allow_redirects"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("encoding", ["gzip", "GZIP", "br", "deflate", "gzip, br", " gzip "])
async def test_a_compressed_body_is_refused(encoding):
    assert is_error(await World(Response(headers={"Content-Encoding": encoding})).fetch(), IMPORT_FETCH_FAILED)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "headers", [{}, {"Content-Encoding": "identity"}, {"Content-Encoding": "Identity"}, {"Content-Encoding": ""}]
)
async def test_an_identity_or_absent_encoding_is_accepted(headers):
    assert await World(Response(headers=headers)).fetch() == b"{}"


@pytest.mark.asyncio
async def test_a_declared_length_over_the_limit_is_refused_before_reading_anything():
    response = Response(headers={"Content-Length": str(PLAYLIST_FILE_MAX_BYTES + 1)}, chunks=[b"x"])
    assert is_error(await World(response).fetch(), FILE_TOO_LARGE)
    assert response.content.consumed == 0


@pytest.mark.asyncio
async def test_a_header_that_lies_does_not_save_a_body_over_the_limit_and_the_rest_is_not_read():
    chunks = [b"x" * 30_000, b"x" * 30_000, b"x" * 30_000, b"x" * 30_000]  # 120 000 bytes sem Content-Length
    response = Response(chunks=chunks)
    assert is_error(await World(response).fetch(), FILE_TOO_LARGE)
    assert response.content.consumed == 3  # aborta no pedaço que estoura (o 3º passa de 65 536), sem ler o 4º

    lying = Response(headers={"Content-Length": "10"}, chunks=chunks)
    assert is_error(await World(lying).fetch(), FILE_TOO_LARGE)


@pytest.mark.asyncio
@pytest.mark.parametrize(("size", "ok"), [(PLAYLIST_FILE_MAX_BYTES, True), (PLAYLIST_FILE_MAX_BYTES + 1, False)])
async def test_the_limit_is_exactly_64_kib(size, ok):
    half = b"x" * (size // 2)
    result = await World(Response(chunks=[half, b"x" * (size - len(half))])).fetch()
    assert (result == b"x" * size) if ok else is_error(result, FILE_TOO_LARGE)


# ---------------------------------------------------------------------- falhas de rede: genéricas, sem vazar nada


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "boom",
    [
        OSError(f"connect to https://x/?token={SECRET} refused"),
        ssl.SSLError(f"certificate {SECRET}"),
        aiohttp.ClientConnectionError(SECRET),
        socket.gaierror(SECRET),
        RuntimeError(SECRET),
    ],
    ids=["os", "tls", "aiohttp", "dns", "other"],
)
async def test_a_network_error_anywhere_is_a_generic_failure_that_leaks_neither_text_nor_link(boom, caplog):
    for world in (World(resolve_error=boom), World(Response(fail=boom))):
        with caplog.at_level(logging.DEBUG):
            result = await world.fetch(GOOD + f"?token={SECRET}")
        assert is_error(result, IMPORT_FETCH_FAILED) and SECRET not in repr(result)
    assert SECRET not in caplog.text and "raw.githubusercontent.com" in caplog.text  # só o host e o tipo do erro
    assert type(boom).__name__ in caplog.text


@pytest.mark.asyncio
async def test_the_url_with_a_token_never_reaches_the_log_even_when_everything_works_or_is_refused(caplog):
    with caplog.at_level(logging.DEBUG):
        await World().fetch(GOOD + f"?token={SECRET}")
        await World(addresses=["10.0.0.5"]).fetch(GOOD + f"?token={SECRET}")
        await World().fetch(f"http://raw.githubusercontent.com/p.json?token={SECRET}")
    assert SECRET not in caplog.text


# ---------------------------------------------------------------------- tempo: relógio curto, nada pendurado


@pytest.mark.asyncio
async def test_a_dns_that_never_answers_times_out_as_a_generic_failure():
    world = World(hang_resolve=asyncio.Event())
    assert is_error(
        await asyncio.wait_for(world.fetch(timeout=0.05), 5), IMPORT_FETCH_FAILED
    )  # 5 s: só se o limite sumir
    assert world.factories == []


@pytest.mark.asyncio
async def test_a_body_that_never_arrives_times_out_as_a_generic_failure():
    world = World(Response(chunks=[b"{", b"}"], hang=asyncio.Event()))
    assert is_error(await asyncio.wait_for(world.fetch(timeout=0.05), 5), IMPORT_FETCH_FAILED)


# ---------------------------------------------------------------------- no máximo duas buscas ao mesmo tempo


@pytest.mark.asyncio
async def test_a_third_simultaneous_fetch_waits_for_one_of_the_first_two_to_finish():
    release = asyncio.Event()
    worlds = [World(Response(chunks=[b"{", b"}"], hang=release)) for _ in range(3)]

    tasks = [asyncio.create_task(world.fetch()) for world in worlds]
    for _ in range(10):
        await asyncio.sleep(0)

    assert [len(world.session.calls) for world in worlds] == [1, 1, 0]  # a 3ª espera (MAX_CONCURRENT = 2)
    release.set()
    results = await asyncio.gather(*tasks)
    assert results == [b"{}"] * 3 and len(worlds[2].session.calls) == 1


# ---------------------------------------------------------------------- o resolvedor fixo e a sessão de verdade (sem abrir rede)


@pytest.mark.asyncio
async def test_the_pinned_resolver_only_answers_with_the_checked_addresses_for_the_checked_host():
    resolver = PinnedResolver("raw.githubusercontent.com", ["8.8.8.8", "2606:4700::1111"])

    answers = await resolver.resolve("raw.githubusercontent.com", 443)

    assert [(a["host"], a["hostname"], a["port"], a["family"]) for a in answers] == [
        ("8.8.8.8", "raw.githubusercontent.com", 443, socket.AF_INET),
        ("2606:4700::1111", "raw.githubusercontent.com", 443, socket.AF_INET6),
    ]
    for other in ("evil.com", "169.254.169.254", "raw.githubusercontent.com.evil.com"):
        with pytest.raises(OSError):
            await resolver.resolve(other, 443)


@pytest.mark.asyncio
async def test_the_default_session_ignores_the_environment_cookies_compression_and_dns_cache():
    session = default_session(PUBLIC, "raw.githubusercontent.com")
    try:
        assert session.trust_env is False  # nada de HTTP(S)_PROXY do ambiente
        assert isinstance(session.cookie_jar, aiohttp.DummyCookieJar)
        assert session.headers["Accept-Encoding"] == "identity"
        assert session._auto_decompress is False
        assert (session.timeout.total, session.timeout.connect) == (10, 5)
        connector = session.connector
        assert connector.use_dns_cache is False and connector.limit == 1
        assert isinstance(connector._resolver, PinnedResolver)
    finally:
        await session.close()
