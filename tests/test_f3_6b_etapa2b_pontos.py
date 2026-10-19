"""F3-6b, etapa 2b (RED) — a chave de corte: os 7 pontos de sessão, fila e skin leem SÓ por ``load_legacy``.

Os pontos (inventário da etapa 0): sessão em ``PlayerSession.get_player_sessions_mongo`` e ``..._local`` (kind ``session``);
fila em ``Music.play`` (``queue``); skin em ``Music.create_player``, ``MusicSettings.change_skin``,
``SkinEditorMenu.load_skin`` e ``SkinEditorMenu.modal_handler`` (``skin``: 4 pontos, 7 linhas hoje).

* por ``ast``: cada ponto chama ``load_legacy`` com o kind certo (direto ou por um auxiliar, de qualquer módulo, que o chama com o kind);
* por espião (``load_legacy`` trocado em todo módulo que o importou): os kinds e os tipos de ``raw`` de verdade, com os
  GRAVADORES REAIS (``save_info``, ``save_queue``, o editor de skin), e o resultado igual ao ``pickle.loads`` de hoje;
* recusa TRATADA em cada ponto com um pickle hostil: sem execução, sem exceção crua, sem perder o que ficou guardado,
  com aviso no log só com ``guild_id`` e tipo da falha (decisões em ``tests/helpers_f3_6b_corte.py``);
* skin ``""`` vale como sem skin.
"""

import ast
import base64
import copy
import logging
import pickle
import zlib
from pathlib import Path

import pytest
import pytest_asyncio

from empiremuse.utils.music.errors import GenericError
from empiremuse.utils.music.interactions import base_skin
from tests.helpers_f3_6b import BOT_ID, SERVIDOR, MongoEmMemoria, cog_de_sessoes
from tests.helpers_f3_6b_corte import (
    avisos,
    cargas_hostis,
    como_fila,
    como_sessao_no_disco,
    como_sessao_no_mongo,
    como_skin,
    criar_armadilhas,
    espionar_load_legacy,
    log_sem_o_conteudo,
    registrou,
)
from tests.helpers_f3_6b_legado import SEGREDO, comprimido, em_base64
from tests.test_f3_6b_formato_fila_salva import caminho_da_fila, montar_leitura, salvar, tres_faixas
from tests.test_f3_6b_formato_sessao import gravar, jogador_completo, pasta_das_sessoes
from tests.test_f3_6b_formato_skin import (
    BotaoDeModo,
    InteracaoDoEditor,
    Jogador,
    chamar_change_skin,
    chamar_create_player,
    dados_globais,
    skin_realista,
    texto_legado,
)
from tests.test_f3_6b_formato_skin import editor_sem_tela as _editor_sem_tela

editor_sem_tela = _editor_sem_tela  # a fixture do editor de skin, reaproveitada de tests/test_f3_6b_formato_skin.py
PACOTE = Path(__file__).resolve().parents[1] / "empiremuse"

# (arquivo relativo a empiremuse/, função qualificada, kind)
PONTOS = [
    ("cogs/player_resume.py", "PlayerSession.get_player_sessions_mongo", "session"),
    ("cogs/player_resume.py", "PlayerSession.get_player_sessions_local", "session"),
    ("cogs/music.py", "Music.play", "queue"),
    ("cogs/music.py", "Music.create_player", "skin"),
    ("cogs/music_settings.py", "MusicSettings.change_skin", "skin"),
    ("utils/music/interactions.py", "SkinEditorMenu.load_skin", "skin"),
    ("utils/music/interactions.py", "SkinEditorMenu.modal_handler", "skin"),
]


@pytest.fixture(autouse=True)
def _ambiente(tmp_path, monkeypatch):
    monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))


@pytest.fixture
def armadilhas(tmp_path, monkeypatch):
    return criar_armadilhas(tmp_path, monkeypatch)


# ============================================================================ por ast


def funcao_do_ponto(arquivo: str, qualificada: str) -> ast.AST:
    classe, metodo = qualificada.split(".")
    arvore = ast.parse((PACOTE / arquivo).read_text(encoding="utf-8"))
    for no in ast.walk(arvore):
        if isinstance(no, ast.ClassDef) and no.name == classe:
            for filho in no.body:
                if isinstance(filho, (ast.FunctionDef, ast.AsyncFunctionDef)) and filho.name == metodo:
                    return filho
    raise AssertionError(f"{qualificada} não existe em {arquivo}")


def nome_chamado(chamada: ast.Call) -> str:
    funcao = chamada.func
    return funcao.attr if isinstance(funcao, ast.Attribute) else getattr(funcao, "id", "")


def kind_da_chamada(chamada: ast.Call):
    """O kind literal de uma chamada a ``load_legacy`` (posicional ou ``kind=``), ou ``None``."""
    argumento = chamada.args[1] if len(chamada.args) > 1 else None
    for palavra in chamada.keywords:
        if palavra.arg == "kind":
            argumento = palavra.value
    return argumento.value if isinstance(argumento, ast.Constant) else None


def kinds_chamados(no: ast.AST, auxiliares: dict[str, set[str]]) -> set[str]:
    achados = set()
    for chamada in ast.walk(no):
        if not isinstance(chamada, ast.Call):
            continue
        nome = nome_chamado(chamada)
        if nome == "load_legacy":
            achados.add(kind_da_chamada(chamada))
        elif nome in auxiliares:
            achados |= auxiliares[nome]
    return achados


def auxiliares_do_projeto() -> dict[str, set[str]]:
    """Funções de QUALQUER módulo do projeto (fora dos pontos) que chamam ``load_legacy`` direto, com os kinds que usam."""
    achados: dict[str, set[str]] = {}
    for arquivo in sorted(PACOTE.rglob("*.py")):
        if "__pycache__" in arquivo.parts or arquivo.name == "legacy_pickle.py":
            continue
        for no in ast.walk(ast.parse(arquivo.read_text(encoding="utf-8"))):
            if isinstance(no, (ast.FunctionDef, ast.AsyncFunctionDef)):
                diretos = {
                    kind_da_chamada(c)
                    for c in ast.walk(no)
                    if isinstance(c, ast.Call) and nome_chamado(c) == "load_legacy"
                }
                if diretos:
                    achados.setdefault(no.name, set()).update(diretos)
    return achados


class TestPorAst:
    @pytest.mark.parametrize(("arquivo", "funcao", "kind"), PONTOS, ids=lambda v: str(v).split("/")[-1])
    def test_cada_ponto_chama_load_legacy_com_o_kind_certo(self, arquivo, funcao, kind):
        no = funcao_do_ponto(arquivo, funcao)
        assert kinds_chamados(no, auxiliares_do_projeto()) == {kind}

    def test_sao_7_pontos_2_de_sessao_1_de_fila_e_4_de_skin(self):
        kinds = [kind for *_, kind in PONTOS]
        assert (kinds.count("session"), kinds.count("queue"), kinds.count("skin")) == (2, 1, 4)

    @pytest.mark.parametrize(("arquivo", "funcao", "kind"), PONTOS, ids=lambda v: str(v).split("/")[-1])
    def test_nenhum_ponto_usa_pickle_para_ler(self, arquivo, funcao, kind):
        no = funcao_do_ponto(arquivo, funcao)
        usados = {
            chamada.func.attr
            for chamada in ast.walk(no)
            if isinstance(chamada, ast.Call)
            and isinstance(chamada.func, ast.Attribute)
            and isinstance(chamada.func.value, ast.Name)
            and chamada.func.value.id in {"pickle", "_pickle"}
        }
        assert not usados & {"load", "loads", "Unpickler"}, sorted(usados)


# ============================================================================ por espião, com os gravadores reais


class TestIdaEVoltaPelosPontosReais:
    @pytest.mark.asyncio
    async def test_sessao_no_disco(self, tmp_path, monkeypatch):
        await cog_de_sessoes().save_info(jogador_completo())
        arquivo = pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.pkl"
        esperado = pickle.loads(zlib.decompress(arquivo.read_bytes()))  # a fixture é do próprio teste
        chamadas = espionar_load_legacy(monkeypatch)
        lidas = await cog_de_sessoes().get_player_sessions_local()
        assert chamadas == [("session", "bytes")]
        assert lidas == [esperado] and type(lidas[0]["dj"]) is set and lidas[0]["command_log_list"].maxlen == 10

    @pytest.mark.asyncio
    async def test_sessao_no_mongo(self, monkeypatch):
        mongo = MongoEmMemoria()
        await cog_de_sessoes(mongo=mongo).save_info(jogador_completo())
        documento = mongo.colecao(BOT_ID, "player_sessions")[str(SERVIDOR)]
        chamadas = espionar_load_legacy(monkeypatch)
        lidas = await cog_de_sessoes(mongo=mongo).get_player_sessions_mongo()
        assert [kind for kind, _ in chamadas] == ["session"] and chamadas[0][1] in {"str", "bytes"}
        esperado = pickle.loads(zlib.decompress(base64.b64decode(documento["data"])))
        assert lidas == [esperado]

    @pytest.mark.asyncio
    async def test_fila_salva(self, tmp_path, monkeypatch):
        """Desde a etapa 4 o gravador escreve JSON; o ponto de leitura legado é o ``.pkl`` antigo (migrado ao ser lido)."""
        from tests.helpers_f3_6b import INSTANTE
        from tests.test_f3_6b_formato_fila_salva import infos

        faixas = tres_faixas()
        for faixa in faixas:
            faixa.info["id"] = faixa.id
        antigo = caminho_da_fila(tmp_path)
        antigo.parent.mkdir(parents=True)
        conteudo = {"tracks": infos(faixas), "created_at": INSTANTE, "guild_id": SERVIDOR}
        antigo.write_bytes(zlib.compress(pickle.dumps(conteudo, protocol=4)))
        chamadas = espionar_load_legacy(monkeypatch)
        lidas = await montar_leitura(monkeypatch, None)()
        assert chamadas == [("queue", "bytes")]
        assert [f.info["title"] for f in lidas] == [f.info["title"] for f in faixas]
        assert not antigo.exists()

    @pytest.mark.asyncio
    async def test_skin_gravada_pelo_editor_nos_quatro_pontos(self, editor_sem_tela, monkeypatch):
        menu, bot, _ = editor_sem_tela(dados_globais())
        menu.message_data = skin_realista()
        BotaoDeModo.modo = "custom_skins"
        await menu.modal_handler(InteracaoDoEditor(skin_name="Minha"))
        texto = bot.salvos[0]["custom_skins"]["Minha"]
        assert isinstance(texto, str)
        chamadas = espionar_load_legacy(monkeypatch)

        novo, _, _ = editor_sem_tela(dados_globais(normais={"Minha": texto}))
        await novo.load_skin(type("I", (), {"values": ["> cs: Minha"]})())
        assert novo.message_data == skin_realista() and chamadas == [("skin", "str")]

        chamadas.clear()
        recebidos = await chamar_create_player(
            {
                **dados_globais(normais={"Minha": texto}),
                "global_skin": False,
                "listen_along_invites": {},
                "prefix": "",
                "voice_channel_status": "",
            }
        )
        assert recebidos["custom_skin_data"] == {"Minha": skin_realista()} and chamadas == [("skin", "str")]

        chamadas.clear()
        jogador = await chamar_change_skin(
            monkeypatch,
            {
                **dados_globais(normais={"Minha": texto}),
                "global_skin": False,
                "player_skin": "",
                "player_skin_static": "",
            },
            nova_skin="> custom_skin: Minha",
        )
        assert jogador.custom_skin_data == {"Minha": skin_realista()} and chamadas == [("skin", "str")]

    @pytest.mark.asyncio
    async def test_o_editor_converte_cada_skin_em_texto_uma_so_vez_ao_salvar(self, editor_sem_tela, monkeypatch):
        dados = dados_globais(
            normais={"A": texto_legado(skin_realista(), 4), "B": texto_legado(skin_realista(), 5)},
            estaticas={"F": texto_legado(skin_realista())},
        )
        jogador = Jogador()
        menu, _, _ = editor_sem_tela(dados, [jogador])
        menu.message_data = skin_realista(content="nova")
        BotaoDeModo.modo = "custom_skins"
        chamadas = espionar_load_legacy(monkeypatch)
        await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert chamadas and {kind for kind, _ in chamadas} == {"skin"} and {tipo for _, tipo in chamadas} == {"str"}
        assert len(chamadas) == 4  # A, B, F e a recém-gravada
        assert set(jogador.custom_skin_data) == {"A", "B", "Nova"} and set(jogador.custom_skin_static_data) == {"F"}


# ============================================================================ recusa tratada: sessão


class TestSessaoRecusada:
    @pytest_asyncio.fixture
    async def sessao(self):
        return await gravar(cog_de_sessoes(), jogador_completo())

    def escrever(self, tmp_path, nome, dados):
        pasta = pasta_das_sessoes(tmp_path)
        pasta.mkdir(parents=True, exist_ok=True)
        (pasta / nome).write_bytes(dados)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome", sorted(["execucao", "segredo-no-global", "protocolo-3", "truncada", "raiz-nao-dicionario"])
    )
    async def test_disco_pula_a_sessao_hostil_le_as_outras_e_deixa_o_arquivo(
        self, tmp_path, armadilhas, sessao, caplog, capsys, nome
    ):
        carga, codigo = cargas_hostis(armadilhas)[nome]
        self.escrever(tmp_path, f"{SERVIDOR}.pkl", como_sessao_no_disco(carga))
        self.escrever(
            tmp_path, f"{SERVIDOR + 1}.pkl", comprimido(pickle.dumps(dict(sessao, _id=SERVIDOR + 1), protocol=4))
        )
        with caplog.at_level(logging.DEBUG):
            lidas = await cog_de_sessoes().get_player_sessions_local()
        assert [d["_id"] for d in lidas] == [SERVIDOR + 1]
        assert (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.pkl").is_file()
        assert armadilhas.intacto()
        assert registrou(caplog, SERVIDOR, codigo), avisos(caplog)
        assert log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lixo", [b"", b"lixo qualquer", b"\x00" * 64], ids=["vazio", "texto", "zeros"])
    async def test_disco_pula_arquivo_que_nem_e_zlib(self, tmp_path, caplog, lixo):
        self.escrever(tmp_path, f"{SERVIDOR}.pkl", lixo)
        with caplog.at_level(logging.DEBUG):
            assert await cog_de_sessoes().get_player_sessions_local() == []
        assert (pasta_das_sessoes(tmp_path) / f"{SERVIDOR}.pkl").is_file()

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome", sorted(["execucao", "segredo-no-global", "protocolo-3", "truncada", "raiz-nao-dicionario"])
    )
    async def test_mongo_pula_o_documento_hostil_le_os_outros_e_nao_apaga(
        self, armadilhas, sessao, caplog, capsys, nome
    ):
        mongo = MongoEmMemoria()
        carga, codigo = cargas_hostis(armadilhas)[nome]
        await mongo.update_data(
            SERVIDOR, {"data": como_sessao_no_mongo(carga)}, db_name=BOT_ID, collection="player_sessions"
        )
        bom = como_sessao_no_mongo(pickle.dumps(dict(sessao, _id=SERVIDOR + 1), protocol=4))
        await mongo.update_data(SERVIDOR + 1, {"data": bom}, db_name=BOT_ID, collection="player_sessions")
        with caplog.at_level(logging.DEBUG):
            lidas = await cog_de_sessoes(mongo=mongo).get_player_sessions_mongo()
        assert [d["_id"] for d in lidas] == [SERVIDOR + 1]
        assert (
            set(mongo.colecao(BOT_ID, "player_sessions")) == {str(SERVIDOR), str(SERVIDOR + 1)} and mongo.apagados == []
        )
        assert armadilhas.intacto()
        assert registrou(caplog, SERVIDOR, codigo), avisos(caplog)
        assert log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_mongo_pula_texto_que_nao_e_base64(self, caplog, capsys):
        mongo = MongoEmMemoria()
        await mongo.update_data(SERVIDOR, {"data": SEGREDO + "!!!"}, db_name=BOT_ID, collection="player_sessions")
        with caplog.at_level(logging.DEBUG):
            assert await cog_de_sessoes(mongo=mongo).get_player_sessions_mongo() == []
        assert registrou(caplog, SERVIDOR, "envelope") and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_o_aviso_traz_so_o_guild_id_e_o_tipo_da_falha(self, tmp_path, armadilhas, caplog):
        carga, _ = cargas_hostis(armadilhas)["segredo-no-global"]
        self.escrever(tmp_path, f"{SERVIDOR}.pkl", como_sessao_no_disco(carga))
        with caplog.at_level(logging.DEBUG):
            await cog_de_sessoes().get_player_sessions_local()
        mensagens = avisos(caplog)
        assert mensagens and all(str(SERVIDOR) in m and "global" in m for m in mensagens)
        assert all(SEGREDO not in m and "posix" not in m and "system" not in m for m in mensagens)


# ============================================================================ recusa tratada: fila salva


class TestFilaRecusada:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome", sorted(["execucao", "segredo-no-global", "protocolo-3", "truncada", "raiz-nao-dicionario"])
    )
    async def test_fila_hostil_vira_generic_error_claro_sem_executar_e_o_arquivo_fica(
        self, tmp_path, armadilhas, monkeypatch, caplog, capsys, nome
    ):
        carga, codigo = cargas_hostis(armadilhas)[nome]
        caminho = caminho_da_fila(tmp_path)
        caminho.parent.mkdir(parents=True)
        caminho.write_bytes(como_fila(carga))
        executar = montar_leitura(monkeypatch, None)
        with caplog.at_level(logging.DEBUG), pytest.raises(GenericError) as erro:
            await executar.rodar()
        assert "incompatível" in erro.value.text and "fila" in erro.value.text.lower()
        assert SEGREDO not in erro.value.text and SEGREDO not in str(erro.value.error)
        assert caminho.is_file() and armadilhas.intacto()
        assert registrou(caplog, SERVIDOR, codigo), avisos(caplog)
        assert log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("lixo", [b"", b"nao e zlib", b"\x00" * 50], ids=["vazio", "texto", "zeros"])
    async def test_fila_que_nem_e_zlib_vira_generic_error(self, tmp_path, monkeypatch, lixo):
        caminho = caminho_da_fila(tmp_path)
        caminho.parent.mkdir(parents=True)
        caminho.write_bytes(lixo)
        with pytest.raises(GenericError, match="incompatível"):
            await montar_leitura(monkeypatch, None).rodar()
        assert caminho.is_file()

    @pytest.mark.asyncio
    async def test_fila_ausente_continua_com_a_mensagem_de_excluida(self, tmp_path, monkeypatch):
        with pytest.raises(GenericError, match="já foi excluída"):
            await montar_leitura(monkeypatch, None).rodar()


# ============================================================================ recusa tratada: skin (4 pontos)

HOSTIS_DE_SKIN = sorted(["execucao", "segredo-no-global", "protocolo-3", "truncada", "raiz-nao-dicionario"]) + [
    "nao-base64"
]


def texto_hostil(armadilhas, nome) -> tuple[str, str]:
    if nome == "nao-base64":
        return SEGREDO + "!!!", "envelope"
    carga, codigo = cargas_hostis(armadilhas)[nome]
    # na skin a allowlist é vazia: o ``STACK_GLOBAL`` nem entra na lista de opcodes (``opcode``) ou cai no ``global``
    return como_skin(carga), (("global", "opcode") if codigo == "global" else codigo)


def dados_com_skin_ruim(texto_ruim: str) -> dict:
    bom = skin_realista(content="boa")
    return {
        "custom_skins": {"Boa": texto_legado(bom), "Ruim": texto_ruim},
        "custom_skins_static": {"FixaBoa": texto_legado(bom), "FixaRuim": texto_ruim},
        "global_skin": False,
        "listen_along_invites": {},
        "prefix": "",
        "voice_channel_status": "",
        "player_skin": "",
        "player_skin_static": "",
    }


@pytest.mark.parametrize("nome", HOSTIS_DE_SKIN)
class TestSkinRecusada:
    @pytest.mark.asyncio
    async def test_create_player_omite_a_skin_ruim_e_deixa_o_texto(self, armadilhas, caplog, capsys, nome):
        texto, codigo = texto_hostil(armadilhas, nome)
        dados = dados_com_skin_ruim(texto)
        with caplog.at_level(logging.DEBUG):
            recebidos = await chamar_create_player(dados)
        assert recebidos["custom_skin_data"] == {"Boa": skin_realista(content="boa")}
        assert recebidos["custom_skin_static_data"] == {"FixaBoa": skin_realista(content="boa")}
        assert dados["custom_skins"]["Ruim"] == texto and dados["custom_skins_static"]["FixaRuim"] == texto
        assert armadilhas.intacto() and registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_change_skin_omite_a_skin_ruim_avisa_o_dono_e_deixa_o_texto(
        self, armadilhas, monkeypatch, caplog, capsys, nome
    ):
        texto, codigo = texto_hostil(armadilhas, nome)
        dados = dados_com_skin_ruim(texto)
        with caplog.at_level(logging.DEBUG):
            jogador = await chamar_change_skin(monkeypatch, dados, nova_skin="> custom_skin: Boa")
        assert jogador.custom_skin_data == {"Boa": skin_realista(content="boa")}
        assert jogador.custom_skin_static_data == {"FixaBoa": skin_realista(content="boa")}
        assert "incompatível" in " ".join(jogador.mensagens)
        assert dados["custom_skins"]["Ruim"] == texto and dados["custom_skins_static"]["FixaRuim"] == texto
        assert armadilhas.intacto() and registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_o_editor_ao_salvar_omite_a_skin_ruim_do_player_e_deixa_o_texto(
        self, armadilhas, editor_sem_tela, caplog, capsys, nome
    ):
        texto, codigo = texto_hostil(armadilhas, nome)
        dados = dados_com_skin_ruim(texto)
        jogador = Jogador()
        menu, bot, _ = editor_sem_tela(dados, [jogador])
        menu.message_data = skin_realista(content="nova")
        BotaoDeModo.modo = "custom_skins"
        with caplog.at_level(logging.DEBUG):
            await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert set(jogador.custom_skin_data) == {"Boa", "Nova"} and set(jogador.custom_skin_static_data) == {"FixaBoa"}
        assert (
            bot.salvos[0]["custom_skins"]["Ruim"] == texto and bot.salvos[0]["custom_skins_static"]["FixaRuim"] == texto
        )
        assert armadilhas.intacto() and registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_load_skin_nao_abre_a_skin_ruim_e_diz_que_e_incompativel(
        self, armadilhas, editor_sem_tela, caplog, capsys, nome
    ):
        texto, codigo = texto_hostil(armadilhas, nome)
        dados = dados_com_skin_ruim(texto)
        menu, _, _ = editor_sem_tela(dados)
        antes = copy.deepcopy(menu.message_data)
        enviados = []

        async def enviar(conteudo=None, **kwargs):
            enviados.append(str(conteudo))

        interacao = type("I", (), {"values": ["> cs: Ruim"], "send": staticmethod(enviar)})()
        with caplog.at_level(logging.DEBUG):
            await menu.load_skin(interacao)
        assert menu.mode == "select" and menu.message_data == antes
        assert "incompatível" in " ".join(enviados)
        assert dados["custom_skins"]["Ruim"] == texto
        assert armadilhas.intacto() and registrou(caplog, SERVIDOR, codigo) and log_sem_o_conteudo(caplog, capsys)

    @pytest.mark.asyncio
    async def test_load_skin_da_skin_ruim_do_song_request_tambem(self, armadilhas, editor_sem_tela, nome):
        texto, _ = texto_hostil(armadilhas, nome)
        menu, _, _ = editor_sem_tela(dados_com_skin_ruim(texto))
        enviados = []

        async def enviar(conteudo=None, **kwargs):
            enviados.append(str(conteudo))

        await menu.load_skin(type("I", (), {"values": ["> css: FixaRuim"], "send": staticmethod(enviar)})())
        assert menu.mode == "select" and "incompatível" in " ".join(enviados)


class TestSkinGiganteEOutrosFormatos:
    @pytest.mark.asyncio
    async def test_skin_enorme_e_recusada_sem_decodificar_e_o_texto_fica(self, caplog):
        texto = "A" * (5 * 1024 * 1024)
        dados = dados_com_skin_ruim(texto)
        with caplog.at_level(logging.DEBUG):
            recebidos = await chamar_create_player(dados)
        assert set(recebidos["custom_skin_data"]) == {"Boa"} and dados["custom_skins"]["Ruim"] is texto
        assert registrou(caplog, SERVIDOR, "too_big")

    @pytest.mark.asyncio
    async def test_skin_com_zlib_no_meio_nao_e_o_formato_do_editor(self, caplog):
        texto = em_base64(comprimido(pickle.dumps(skin_realista(), protocol=4)))
        recebidos = await chamar_create_player(dados_com_skin_ruim(texto))
        assert set(recebidos["custom_skin_data"]) == {"Boa"}


# ============================================================================ skin "" vale como sem skin


class TestSkinVazia:
    def dados(self, vazia):
        return {
            **dados_com_skin_ruim("x"),
            "custom_skins": {"Boa": texto_legado(skin_realista()), "Vazia": vazia},
            "custom_skins_static": {},
        }

    @pytest.mark.asyncio
    async def test_load_skin_de_texto_vazio_abre_a_skin_padrao_sem_erro_e_sem_aviso(self, editor_sem_tela, caplog):
        menu, _, _ = editor_sem_tela(self.dados(""))
        with caplog.at_level(logging.DEBUG):
            await menu.load_skin(type("I", (), {"values": ["> cs: Vazia"]})())
        assert menu.mode == "editor" and menu.message_data == base_skin
        assert avisos(caplog) == []

    @pytest.mark.asyncio
    async def test_create_player_com_texto_vazio_nao_falha_nem_avisa(self, caplog):
        with caplog.at_level(logging.DEBUG):
            recebidos = await chamar_create_player(self.dados(""))
        assert not recebidos["custom_skin_data"].get("Vazia") and "Boa" in recebidos["custom_skin_data"]
        assert avisos(caplog) == []

    @pytest.mark.asyncio
    async def test_change_skin_com_texto_vazio_nao_falha_nem_avisa(self, monkeypatch, caplog):
        dados = {**self.dados(""), "global_skin": False}
        with caplog.at_level(logging.DEBUG):
            jogador = await chamar_change_skin(monkeypatch, dados, nova_skin="> custom_skin: Boa")
        assert not jogador.custom_skin_data.get("Vazia") and "Boa" in jogador.custom_skin_data
        assert avisos(caplog) == [] and "incompatível" not in " ".join(jogador.mensagens)

    @pytest.mark.asyncio
    async def test_o_editor_ao_salvar_com_texto_vazio_nao_falha_nem_avisa(self, editor_sem_tela, caplog):
        jogador = Jogador()
        menu, _, _ = editor_sem_tela(self.dados(""), [jogador])
        menu.message_data = skin_realista(content="nova")
        BotaoDeModo.modo = "custom_skins"
        with caplog.at_level(logging.DEBUG):
            await menu.modal_handler(InteracaoDoEditor(skin_name="Nova"))
        assert not jogador.custom_skin_data.get("Vazia") and avisos(caplog) == []
