"""F3-1 — testes RED dos bugs altos KI-01, KI-09 e KI-15 (docs/known-issues.md). Sem rede, sem Discord, sem .env real.

KI-01  ``requirements.txt`` precisa declarar ``tinymongo[serialization]``: ``empiremuse/utils/db.py`` importa
       ``tinydb_serialization``, que só vem com esse extra. CI, Dockerfile e docs instalam o extra à parte, mas a Discloud
       instala SÓ o requirements.txt.

KI-09  ``update_values`` descarta as LISTAS do usuário ao migrar o ``ver`` do modelo. Comportamento esperado da migração
       (nunca perder dados):
         * valor do usuário vence o padrão: escalar, mapeamento e LISTA (inclusive lista vazia e lista de dicts), em
           qualquer profundidade e também dentro de mapeamentos de chaves dinâmicas (``fav_links``, ``custom_skins``...);
         * chave NOVA do modelo (escalar, mapeamento, lista ou subchave aninhada) recebe o padrão do modelo;
         * chave REMOVIDA do modelo é PRESERVADA com o valor salvo, de qualquer tipo (a migração só acrescenta e atualiza,
           não apaga: quem limpa chaves obsoletas é uma tarefa explícita, nunca o efeito colateral de subir o ``ver``);
         * ``ver`` passa a ser o do modelo, ``_id`` é mantido; o documento antigo não é alterado nem compartilha listas
           com o resultado; migrar de novo não muda nada; documento já na versão atual não é reescrito.

KI-15  ``SpotifyClient.get_access_token`` com credenciais inválidas zera as credenciais e chama a si mesma com
       ``token_refresh`` ainda True: a chamada recursiva espera para sempre por ela mesma. Comportamento esperado: a
       chamada TERMINA (aqui, em até 2 s) com ``GenericError`` (ou subclasse) — escolhida porque é o erro de usuário do
       projeto, formatado pelo error_handler e já usado no resto do módulo —, com mensagem clara em pt-BR, sem vazar as
       credenciais, e ``token_refresh`` volta a False; uma chamada seguinte (ou concorrente) também não fica presa.
"""

import ast
import asyncio
import base64
import copy
import re
import sys
import tempfile
from importlib import metadata
from pathlib import Path

import pytest
from aiohttp import ClientError
from packaging.markers import default_environment
from packaging.requirements import Requirement

from empiremuse.utils.db import DBModel, LocalDatabase, db_models, global_db_models, update_values
from empiremuse.utils.music.audio_sources import spotify
from empiremuse.utils.music.errors import GenericError
from tests.support.raiz import RAIZ

pytestmark = [pytest.mark.critical, pytest.mark.regression]

ROOT = RAIZ
REQUIREMENTS = ROOT / "requirements.txt"
DB_PY = ROOT / "empiremuse" / "utils" / "db.py"


def _normalizar(nome: str) -> str:
    return re.sub(r"[-_.]+", "-", nome).lower()


# ============================================================================ KI-01 — extra serialization


def _linhas_do_requirements() -> list[str]:
    linhas = []
    for linha in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        linha = linha.split(" #", 1)[0].strip()
        if linha and not linha.startswith(("#", "-")):
            linhas.append(linha)
    return linhas


def _nome_e_extras(linha: str) -> tuple[str, set[str]]:
    """Nome normalizado e extras de uma linha; ``git+https://.../disnake.git@sha`` vira ``disnake``."""
    if linha.startswith("git+"):
        repo = linha.split("@", 1)[0].rstrip("/").rsplit("/", 1)[-1].removesuffix(".git")
        return _normalizar(repo), set()
    requisito = Requirement(linha)
    return _normalizar(requisito.name), {_normalizar(extra) for extra in requisito.extras}


def _fecho_de_dependencias(raizes: list[tuple[str, set[str]]]) -> set[str]:
    """Tudo o que uma instalação limpa SÓ do requirements.txt traria (dependências e extras, pelos metadados instalados)."""
    ambiente = default_environment()
    visto, pilha, nomes = set(), list(raizes), set()
    while pilha:
        nome, extras = pilha.pop()
        chave = (nome, frozenset(extras))
        if chave in visto:
            continue
        visto.add(chave)
        nomes.add(nome)
        try:
            exigencias = metadata.requires(nome) or []
        except metadata.PackageNotFoundError:
            continue
        for texto in exigencias:
            exigido = Requirement(texto)
            if exigido.marker is not None and not any(
                exigido.marker.evaluate({**ambiente, "extra": extra}) for extra in extras | {""}
            ):
                continue
            pilha.append((_normalizar(exigido.name), {_normalizar(extra) for extra in exigido.extras}))
    return nomes


def _imports_de_terceiros(arquivo: Path) -> set[str]:
    modulos = set()
    for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
        if isinstance(no, ast.Import):
            modulos.update(alias.name.split(".")[0] for alias in no.names)
        elif isinstance(no, ast.ImportFrom) and no.level == 0 and no.module:
            modulos.add(no.module.split(".")[0])
    return {m for m in modulos if m not in sys.stdlib_module_names and m not in ("empiremuse", "__future__")}


class TestKI01TinymongoComExtraSerialization:
    def test_requirements_declara_tinymongo_com_o_extra_serialization(self):
        declaradas = [_nome_e_extras(linha) for linha in _linhas_do_requirements()]
        extras = [extras for nome, extras in declaradas if nome == "tinymongo"]
        assert extras, "tinymongo não está no requirements.txt"
        assert "serialization" in extras[0], (
            "requirements.txt precisa de 'tinymongo[serialization]': sem o extra, 'import tinydb_serialization' "
            "(empiremuse/utils/db.py) falha numa instalação limpa só do requirements.txt (ex.: Discloud)"
        )

    def test_uma_instalacao_so_do_requirements_traz_tudo_o_que_o_db_py_importa(self):
        fecho = _fecho_de_dependencias([_nome_e_extras(linha) for linha in _linhas_do_requirements()])
        distribuicoes = metadata.packages_distributions()
        faltando = []
        for modulo in sorted(_imports_de_terceiros(DB_PY)):
            candidatas = {_normalizar(dist) for dist in distribuicoes.get(modulo, [modulo])}
            if not candidatas & fecho:
                faltando.append(f"{modulo} (distribuição {sorted(candidatas)})")
        assert not faltando, f"imports de empiremuse/utils/db.py que o requirements.txt NÃO instala: {faltando}"


# ============================================================================ KI-09 — update_values / migração de ver


def modelo(**campos) -> dict:
    return {"ver": 2.0, **campos}


def antigo(**campos) -> dict:
    return {"_id": "1", "ver": 1.0, **campos}


class TestKI09UpdateValues:
    def test_lista_de_dicts_do_usuario_e_mantida(self):
        faixas = [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}]
        assert update_values(modelo(last_tracks=[]), antigo(last_tracks=faixas))["last_tracks"] == faixas

    def test_lista_vazia_do_usuario_vence_um_padrao_nao_vazio(self):
        assert update_values(modelo(tags=["padrao"]), antigo(tags=[]))["tags"] == []

    def test_lista_dentro_de_mapeamento_de_chaves_dinamicas_e_mantida(self):
        """custom_skins/fav_links são mapeamentos cujas chaves vêm do usuário: as listas dentro delas não podem sumir."""
        salvo = {"minha_skin": {"cores": ["#fff", "#000"], "nome": "x"}}
        resultado = update_values(modelo(custom_skins={}), antigo(custom_skins=salvo))
        assert resultado["custom_skins"] == salvo

    def test_chaves_novas_do_modelo_recebem_o_padrao(self):
        resultado = update_values(
            modelo(velha=1, nova_escalar=10, nova_lista=["x"], novo_mapa={"a": 1}, cfg={"antiga": 1, "nova_sub": "s"}),
            antigo(velha=5, cfg={"antiga": 2}),
        )
        assert resultado["velha"] == 5
        assert resultado["nova_escalar"] == 10
        assert resultado["nova_lista"] == ["x"]
        assert resultado["novo_mapa"] == {"a": 1}
        assert resultado["cfg"] == {"antiga": 2, "nova_sub": "s"}

    def test_chave_removida_do_modelo_e_preservada_qualquer_que_seja_o_tipo(self):
        resultado = update_values(
            modelo(atual=1), antigo(atual=2, obsoleta_escalar="a", obsoleta_mapa={"k": 1}, obsoleta_lista=[1, 2])
        )
        assert resultado["obsoleta_escalar"] == "a"
        assert resultado["obsoleta_mapa"] == {"k": 1}
        assert resultado["obsoleta_lista"] == [1, 2], "lista de chave removida do modelo também não pode ser apagada"

    def test_migrar_duas_vezes_da_o_mesmo_resultado(self):
        primeiro = update_values(modelo(djroles=[], x=1), antigo(djroles=[1]))
        segundo = update_values(modelo(djroles=[], x=1), copy.deepcopy(primeiro))
        assert segundo == primeiro


def _documento_antigo_do_servidor() -> dict:
    return {
        "_id": "900",
        "ver": 1.0,
        "autoplay": True,
        "default_player_volume": 55,
        "djroles": [111, 222],
        "player_controller": {
            "channel": 123,
            "message_id": 456,
            "skin": "minha",
            "static_skin": None,
            "fav_links": {"musica": {"url": "https://exemplo/x", "tags": ["a", "b"]}},
        },
        "campo_removido_do_modelo": ["fica"],
    }


def _documento_antigo_do_usuario() -> dict:
    return {
        "_id": "42",
        "ver": 1.0,
        "fav_links": {},
        "token": "t",
        "custom_prefix": "?",
        "last_tracks": [{"url": "https://a", "title": "A"}, {"url": "https://b", "title": "B"}],
        "lastfm": {"username": "u", "sessionkey": "", "scrobble": True},
    }


@pytest.fixture
def pasta_do_banco(tmp_path) -> str:
    return str(tmp_path / "banco")


def semear(pasta: str, collection: str, db_name: str, documento: dict) -> None:
    LocalDatabase(dir_=pasta)._connect[collection][db_name].insert_one(copy.deepcopy(documento))


class TestKI09MigracaoNoLocalDatabase:
    @pytest.mark.asyncio
    async def test_usuario_global_mantem_last_tracks_ao_subir_o_ver(self, pasta_do_banco):
        semear(pasta_do_banco, "global", DBModel.users, _documento_antigo_do_usuario())
        banco = LocalDatabase(dir_=pasta_do_banco)

        dados = await banco.get_data("42", db_name=DBModel.users, collection="global", default_model=global_db_models)

        assert dados["last_tracks"] == _documento_antigo_do_usuario()["last_tracks"], "KI-09: last_tracks perdido"
        assert dados["lastfm"]["scrobble"] is True and dados["custom_prefix"] == "?"
        assert dados["ver"] == global_db_models[DBModel.users]["ver"]

    @pytest.mark.asyncio
    async def test_chave_removida_do_modelo_e_preservada_na_migracao_real(self, pasta_do_banco):
        semear(pasta_do_banco, "bot1", DBModel.guilds, _documento_antigo_do_servidor())

        dados = await LocalDatabase(dir_=pasta_do_banco).get_data("900", db_name=DBModel.guilds, collection="bot1")

        assert dados["campo_removido_do_modelo"] == ["fica"]

    @pytest.mark.asyncio
    async def test_as_listas_sobrevivem_no_disco_e_a_migracao_nao_se_repete(self, pasta_do_banco):
        semear(pasta_do_banco, "bot1", DBModel.guilds, _documento_antigo_do_servidor())
        await LocalDatabase(dir_=pasta_do_banco).get_data("900", db_name=DBModel.guilds, collection="bot1")

        reaberto = LocalDatabase(dir_=pasta_do_banco)  # cache vazio: lê do arquivo
        bruto = reaberto._connect["bot1"][DBModel.guilds].find_one({"_id": "900"})
        assert bruto["djroles"] == [111, 222], "a lista não foi gravada na migração"
        assert bruto["ver"] == db_models[DBModel.guilds]["ver"]
        de_novo = await reaberto.get_data("900", db_name=DBModel.guilds, collection="bot1")
        assert de_novo["djroles"] == [111, 222] and de_novo["ver"] == bruto["ver"]

    @pytest.mark.asyncio
    async def test_documento_ja_na_versao_atual_volta_intacto(self, pasta_do_banco):
        """Caracterização (passa hoje): sem diferença de ver não há migração."""
        atual = {**copy.deepcopy(db_models[DBModel.guilds]), "_id": "7", "djroles": [5, 6]}
        semear(pasta_do_banco, "bot1", DBModel.guilds, atual)

        dados = await LocalDatabase(dir_=pasta_do_banco).get_data("7", db_name=DBModel.guilds, collection="bot1")

        assert dados["djroles"] == [5, 6]


# ============================================================================ KI-15 — Spotify get_access_token


ID_FAKE = "id-spotify-fake"
SEGREDO_FAKE = "segredo-spotify-fake-123"
LIMITE = 2.0


class _RespostaFake:
    def __init__(self, status, corpo, falha_de_rede=False):
        self.status, self._corpo, self._falha = status, corpo, falha_de_rede
        self.url = "https://accounts.spotify.com/api/token"

    async def __aenter__(self):
        if self._falha:
            raise ClientError("sem rede (simulado)")
        return self

    async def __aexit__(self, *exc):
        return False

    async def json(self, *args, **kwargs):
        # cede o controle ao event loop, como uma resposta de rede de verdade: sem isso a 1ª chamada termina antes de a
        # 2ª começar e o caminho "esperar a renovação em andamento" nunca seria exercitado
        await asyncio.sleep(0.05)
        return copy.deepcopy(self._corpo)


class _SessaoFake:
    def __init__(self, resposta, chamadas):
        self._resposta, self._chamadas = resposta, chamadas

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    def post(self, url, headers=None, data=None, **kwargs):
        self._chamadas.append({"url": url, "headers": headers, "data": data})
        return self._resposta

    get = post


def _arquivos_gravados(raiz) -> list:
    return [p for p in raiz.rglob("*") if p.is_file()]


@pytest.fixture
def spotify_fake(monkeypatch, tmp_path):
    """SpotifyClient com o aiohttp substituído e o cache do token isolado em tmp_path (nunca o do sistema nem o RUNTIME_DIR real).

    O local do arquivo de cache não é fixado aqui: RUNTIME_DIR (EMPIREMUSE_HOME), cwd e o tmp do sistema apontam para
    pastas de tmp_path, e os testes só olham se ALGUM arquivo foi gravado em tmp_path.
    """
    for pasta in ("runtime", "cwd", "sistema"):
        (tmp_path / pasta).mkdir()
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path / "runtime"))
    monkeypatch.chdir(tmp_path / "cwd")
    monkeypatch.setattr(tempfile, "tempdir", str(tmp_path / "sistema"))
    monkeypatch.setattr(spotify, "spotify_cache_file", str(tmp_path / "sistema" / ".spotify_cache.json"), raising=False)

    def preparar(status=401, corpo=None, falha_de_rede=False):
        chamadas: list[dict] = []
        resposta = _RespostaFake(status, corpo, falha_de_rede)
        monkeypatch.setattr(spotify, "ClientSession", lambda *a, **k: _SessaoFake(resposta, chamadas))
        return spotify.SpotifyClient(client_id=ID_FAKE, client_secret=SEGREDO_FAKE), chamadas

    return preparar


INVALIDO = {"error": "invalid_client", "error_description": "Invalid client"}


async def _terminar(corotina, o_que="get_access_token"):
    try:
        return await asyncio.wait_for(corotina, LIMITE)
    except asyncio.TimeoutError:
        pytest.fail(f"KI-15: {o_que} ficou preso por mais de {LIMITE} s (espera infinita com credenciais inválidas)")


class TestKI15SpotifyCredenciaisInvalidas:
    @pytest.mark.asyncio
    @pytest.mark.parametrize("status", [400, 401])
    async def test_termina_com_generic_error_claro_e_libera_o_token_refresh(self, spotify_fake, status):
        cliente, _ = spotify_fake(status=status, corpo=INVALIDO)

        with pytest.raises(GenericError) as erro:
            await _terminar(cliente.get_access_token())

        assert "spotify" in str(erro.value).lower(), f"mensagem sem contexto: {erro.value}"
        assert cliente.token_refresh is False, "token_refresh ficou True: toda chamada seguinte esperaria para sempre"

    @pytest.mark.asyncio
    async def test_a_mensagem_de_erro_nao_vaza_as_credenciais(self, spotify_fake):
        cliente, _ = spotify_fake(status=401, corpo=INVALIDO)

        with pytest.raises(GenericError) as erro:
            await _terminar(cliente.get_access_token())

        texto = f"{erro.value} {erro.value!r} {getattr(erro.value, 'error', '')}"
        assert SEGREDO_FAKE not in texto and ID_FAKE not in texto

    @pytest.mark.asyncio
    async def test_uma_chamada_seguinte_tambem_nao_fica_presa(self, spotify_fake):
        cliente, _ = spotify_fake(status=401, corpo=INVALIDO)
        with pytest.raises(GenericError):
            await _terminar(cliente.get_access_token())

        try:
            await _terminar(cliente.get_access_token(), "a 2ª chamada de get_access_token")
        except GenericError:
            pass  # falhar de novo, rápido, é aceitável; ficar presa não

        assert cliente.token_refresh is False

    @pytest.mark.asyncio
    async def test_chamadas_concorrentes_terminam_todas(self, spotify_fake):
        cliente, _ = spotify_fake(status=401, corpo=INVALIDO)

        async def duas():
            return await asyncio.gather(cliente.get_access_token(), cliente.get_access_token(), return_exceptions=True)

        # a 2ª espera a 1ª num laço de sleep(1): damos folga de 3 s; presa de verdade não termina nunca
        try:
            resultados = await asyncio.wait_for(duas(), 4.0)
        except asyncio.TimeoutError:
            pytest.fail("KI-15: chamadas concorrentes de get_access_token ficaram presas")

        assert any(isinstance(r, GenericError) for r in resultados), resultados
        assert cliente.token_refresh is False

    @pytest.mark.asyncio
    async def test_erro_sem_error_description_vira_generic_error_e_nao_keyerror(self, spotify_fake):
        cliente, _ = spotify_fake(status=400, corpo={"error": "invalid_client"})

        with pytest.raises(GenericError):
            await _terminar(cliente.get_access_token())

        assert cliente.token_refresh is False

    @pytest.mark.asyncio
    async def test_uma_requisicao_da_api_com_token_vencido_e_credenciais_invalidas_nao_trava(self, spotify_fake):
        cliente, _ = spotify_fake(status=401, corpo=INVALIDO)
        cliente.spotify_cache = {"access_token": "velho", "expires_at": 0}

        try:
            await _terminar(cliente.get_track_info("faixa"), "get_track_info")
        except GenericError:
            pass  # erro claro para o usuário; ou retorno vazio se o cliente se desativar

        assert cliente.token_refresh is False

    @pytest.mark.asyncio
    async def test_credenciais_nao_vazam_para_logs_nem_para_a_saida(self, spotify_fake, caplog, capsys):
        cliente, _ = spotify_fake(status=401, corpo=INVALIDO)
        basic = base64.b64encode(f"{ID_FAKE}:{SEGREDO_FAKE}".encode()).decode()

        with caplog.at_level(0), pytest.raises(GenericError):
            await _terminar(cliente.get_access_token())

        saida = capsys.readouterr()
        tudo = f"{caplog.text} {saida.out} {saida.err}"
        assert SEGREDO_FAKE not in tudo and ID_FAKE not in tudo and basic not in tudo

    @pytest.mark.asyncio
    async def test_token_valido_continua_funcionando(self, spotify_fake, tmp_path):
        """Caracterização (passa hoje): o caminho feliz grava o cache e libera o token_refresh."""
        cliente, chamadas = spotify_fake(
            status=200, corpo={"access_token": "tok", "token_type": "Bearer", "expires_in": 3600}
        )

        await _terminar(cliente.get_access_token())

        assert cliente.spotify_cache["access_token"] == "tok" and cliente.spotify_cache["expires_at"] > 0
        assert cliente.token_refresh is False
        assert len(chamadas) == 1 and chamadas[0]["data"] == {"grant_type": "client_credentials"}
        assert _arquivos_gravados(tmp_path), "o caminho feliz não gravou o arquivo de cache"
