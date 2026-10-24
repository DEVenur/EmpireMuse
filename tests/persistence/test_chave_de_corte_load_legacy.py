"""F3-6b, etapa 2b (RED) — a chave de corte: os 7 pontos de sessão, fila e skin leem SÓ por ``load_legacy``.

Os pontos (inventário da etapa 0): sessão em ``PlayerSession.get_player_sessions_mongo`` e ``..._local`` (kind ``session``);
fila em ``Music.play`` (``queue``); skin em ``Music.create_player``, ``MusicSettings.change_skin``,
``SkinEditorMenu.load_skin`` e ``SkinEditorMenu.modal_handler`` (``skin``: 4 pontos, 7 linhas hoje).

* por ``ast``: cada ponto chama ``load_legacy`` com o kind certo (direto ou por um auxiliar, de qualquer módulo, que o chama com o kind);
* por espião (``load_legacy`` trocado em todo módulo que o importou): os kinds e os tipos de ``raw`` de verdade, com os
  GRAVADORES REAIS (``save_info``, ``save_queue``, o editor de skin), e o resultado igual ao ``pickle.loads`` de hoje;
* recusa TRATADA em cada ponto com um pickle hostil: sem execução, sem exceção crua, sem perder o que ficou guardado,
  com aviso no log só com ``guild_id`` e tipo da falha (decisões em ``tests/support/chave_de_corte.py``);
* skin ``""`` vale como sem skin.
"""

import ast
import logging

import pytest

from empiremuse.utils.music.errors import GenericError
from tests.support.formatos_reais import SERVIDOR
from tests.support.chave_de_corte import (
    avisos,
    cargas_hostis,
    como_fila,
    como_skin,
    criar_armadilhas,
    log_sem_o_conteudo,
    registrou,
)
from tests.support.leitor_legado import SEGREDO
from tests.support.formato_fila_salva import caminho_da_fila, montar_leitura
from tests.persistence.test_formato_skin import chamar_change_skin, chamar_create_player, skin_realista, texto_legado
from tests.persistence.test_formato_skin import editor_sem_tela as _editor_sem_tela
from tests.support.raiz import RAIZ

editor_sem_tela = _editor_sem_tela  # fixture do editor de skin, de persistence/test_formato_skin.py
PACOTE = RAIZ / "empiremuse"

# (arquivo ou pasta relativo a empiremuse/, função qualificada, kind); pasta = a classe pode estar em qualquer .py dela
PONTOS = [
    ("music_cog/play_command.py", "PlayCommandMixin.play", "queue"),
    ("music_cog/player_lifecycle.py", "PlayerLifecycleMixin.create_player", "skin"),
    ("cogs/music_settings.py", "MusicSettings.change_skin", "skin"),
    ("utils/music/interactions", "SkinEditorMenu.load_skin", "skin"),
    ("utils/music/interactions", "SkinEditorMenu.modal_handler", "skin"),
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
    alvo = PACOTE / arquivo
    fontes = sorted(alvo.rglob("*.py")) if alvo.is_dir() else [alvo]
    for fonte in fontes:
        arvore = ast.parse(fonte.read_text(encoding="utf-8"))
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


class TestPorAst:
    @pytest.mark.parametrize(("arquivo", "funcao", "kind"), list(PONTOS)[:2], ids=lambda v: str(v).split("/")[-1])
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


# ============================================================================ recusa tratada: fila salva


class TestFilaRecusada:
    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "nome", list(sorted(["execucao", "segredo-no-global", "protocolo-3", "truncada", "raiz-nao-dicionario"]))[:2]
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


# ============================================================================ skin "" vale como sem skin


class TestSkinVazia:
    def dados(self, vazia):
        return {
            **dados_com_skin_ruim("x"),
            "custom_skins": {"Boa": texto_legado(skin_realista()), "Vazia": vazia},
            "custom_skins_static": {},
        }

    @pytest.mark.asyncio
    async def test_change_skin_com_texto_vazio_nao_falha_nem_avisa(self, monkeypatch, caplog):
        dados = {**self.dados(""), "global_skin": False}
        with caplog.at_level(logging.DEBUG):
            jogador = await chamar_change_skin(monkeypatch, dados, nova_skin="> custom_skin: Boa")
        assert not jogador.custom_skin_data.get("Vazia") and "Boa" in jogador.custom_skin_data
        assert avisos(caplog) == [] and "incompatível" not in " ".join(jogador.mensagens)
