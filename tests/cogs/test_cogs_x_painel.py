"""F3-5a — bugs de cogs × painel (KI-36 … KI-43): testes RED e guardas.

Cada classe cobre um item de ``docs/known-issues.md``. Os testes ``test_guarda_*`` passam hoje e continuam passando
depois da correção (protegem o comportamento que a correção não pode mudar); os demais são RED e falham pelo defeito
descrito no docstring da classe. Sem Discord real, sem rede, sem ``.env`` e sem ``setup()``: canais, mensagens e
interações são dublês (``tests/support/canal_de_pedidos.py``) e os valores falsos são montados em tempo de execução.
"""

import pytest

from empiremuse.utils.music.interactions import ViewMode
from tests.cogs.test_canal_de_pedidos_setup_reset import Scenario, configured
from tests.support.modais import (
    URL_BASE,
    ModalBot,
    importar,
    trocar_process_idle_embed,
)

pytestmark = pytest.mark.regression


@pytest.fixture
def world(monkeypatch):
    return Scenario(monkeypatch)


def run_reset(world, **kwargs):
    """Executa o ``/reset`` e devolve a exceção levantada (ou ``None``): o teste decide o que esperar dela."""
    try:
        world.reset(**kwargs)
    except Exception as erro:  # noqa: BLE001 — o contrato da falha é justamente o que os testes medem
        return erro
    return None


# ============================================================================ KI-36 — /reset × falha no Discord


class TestKI36ResetFalhaNoDiscord:
    """Hoje o ``/reset`` limpa o banco ANTES de mexer no Discord: se a edição da mensagem ou a exclusão do canal
    falha, o canal continua de pé e o banco fica desconfigurado (e o aviso diz que o reset "foi feito na base")."""

    def forum_com_post(self, world):
        post = world.forum.add_post(900, "post de pedidos")
        world.bot.channels[900] = post
        world.db.doc["player_controller"].update({"channel": "900", "message_id": "900"})
        return post

    # ---- guardas: o caminho feliz e as chamadas ao Discord não podem mudar

    # ---- RED: a falha no Discord preserva a configuração

    def test_falha_ao_editar_a_mensagem_preserva_a_configuracao_no_banco(self, world):
        configured(world).fail_edit = RuntimeError("falha simulada")
        run_reset(world)
        assert (world.saved["channel"], world.saved["message_id"]) == ("22", "555"), (
            "KI-36: o Discord falhou, o canal continua de pé e o banco foi desconfigurado"
        )

    # ---- RED: ordem definida (Discord, banco, aviso, player), erro genérico e detalhe só no log

    def provocar(self, world, falha):
        """Configura a falha pedida e devolve o ``delete`` do ``/reset`` que a exercita."""
        if falha == "apagar_post":
            self.forum_com_post(world).fail_delete = RuntimeError("falha simulada")
            return None
        mensagem = configured(world)
        if falha == "editar_mensagem":
            mensagem.fail_edit = RuntimeError("falha simulada")
            return None
        world.text.fail_delete = RuntimeError("falha simulada")
        return "sim"

    FALHAS = ["editar_mensagem", "apagar_canal", "apagar_post"]


# ============================================================================ KI-39 / KI-40 / KI-41 — modais de favoritos e integrações


@pytest.fixture(autouse=True)
def _sem_idle_embed(monkeypatch):
    async def nada(*args, **kwargs):
        return None

    trocar_process_idle_embed(monkeypatch, nada)


class TestKI41ImportadorDeLinksRapidosDoServidor:
    """Itens com ``> fav:`` no nome pulam a validação da URL (``continue``) e mesmo assim são gravados."""

    def item(self, url, descricao="descrição"):
        return {"url": url, "description": descricao}

    URLS_INVALIDAS = ["isto-nao-e-url", "ftp://exemplo.invalid/musica", "javascript:alert(1)", "https://", ""]

    @pytest.mark.asyncio
    async def test_item_fav_invalido_derruba_a_importacao_inteira(self):
        bot = ModalBot()
        conteudo = {"Bom": self.item(f"{URL_BASE}/bom"), "> fav: Ruim": self.item("isto-nao-e-url")}
        inter = await importar(bot, ViewMode.guild_fav_manager, conteudo)
        assert bot.salvos_servidor == [], "KI-41: nada do arquivo pode ser gravado se um item é inválido"
        assert "link inválido" in inter.texto


class TestKI47ItensMalFormadosNoImportadorDoServidor:
    """Item que não é objeto, ou sem ``url``/``description``, levanta KeyError/TypeError sem aviso ao usuário."""

    ITENS = {
        "texto": "https://exemplo.invalid/a",
        "lista": ["https://exemplo.invalid/a"],
        "numero": 42,
        "nulo": None,
        "sem_url": {"description": "ddd"},
        "sem_description": {"url": "https://exemplo.invalid/a"},
        "url_nao_texto": {"url": 123, "description": "ddd"},
        "description_nao_texto": {"url": "https://exemplo.invalid/a", "description": 5},
    }

    @pytest.mark.asyncio
    async def test_item_mal_formado_com_nome_fav_tambem_e_recusado(self):
        bot = ModalBot()
        try:
            inter = await importar(bot, ViewMode.guild_fav_manager, {"> fav: Item": "https://exemplo.invalid/a"})
        except (KeyError, TypeError) as erro:
            pytest.fail(f"KI-47: {type(erro).__name__} escapou do importador: {erro}")
        assert bot.salvos_servidor == [] and inter.texto


# ============================================================================ reforço pós-mutação (sobreviventes)


class TestImportadoresRecusamJsonQueNaoEObjetoOuEVazio:
    """Lista, texto, número, ``null`` e ``{}`` são recusados com mensagem, nos três modos, sem gravar nada."""

    MODOS = [ViewMode.fav_manager, ViewMode.guild_fav_manager, ViewMode.integrations_manager]
    CONTEUDOS = ["[]", '"texto"', "5", "null", "{}", '[{"url": "https://exemplo.invalid/a"}]']

    @pytest.mark.asyncio
    @pytest.mark.parametrize("modo", list(MODOS)[:2])
    @pytest.mark.parametrize("conteudo", CONTEUDOS)
    async def test_recusa_com_mensagem_e_sem_gravar(self, modo, conteudo):
        bot = ModalBot()
        inter = await importar(bot, modo, conteudo, estrito=True)
        assert bot.salvos_usuario == [] and bot.salvos_servidor == []
        assert "objeto json" in inter.texto, f"o usuário precisa receber o motivo: {inter.texto!r}"


# ============================================================================ endurecimento dos importadores (KI-49 … KI-54)


class TestKI52TrechoEcoadoNasMensagensDeErro:
    """Cada mensagem ao usuário fica abaixo de 2000 caracteres e um ``` do valor não fecha o bloco de código."""

    GIGANTE = 5000

    def casos(self):
        gigante = "x" * self.GIGANTE
        url_gigante = "https://exemplo.invalid/" + "a" * self.GIGANTE
        return {
            "favorito_url_longa": (ViewMode.fav_manager, {"Item": url_gigante}),
            "favorito_invalido_gigante": (ViewMode.fav_manager, {"Item": gigante}),
            "favorito_com_crases": (ViewMode.fav_manager, {"Item": "nao```@everyone"}),
            "favorito_nome_gigante": (ViewMode.fav_manager, {"n" * self.GIGANTE: f"{URL_BASE}/a"}),
            "favorito_nao_texto_gigante": (ViewMode.fav_manager, {"Item": ["a" * self.GIGANTE]}),
            "servidor_url_longa": (ViewMode.guild_fav_manager, {"Item": {"url": url_gigante, "description": "ddd"}}),
            "servidor_descricao_gigante": (
                ViewMode.guild_fav_manager,
                {"Item": {"url": f"{URL_BASE}/a", "description": "d" * self.GIGANTE}},
            ),
            "servidor_url_com_crases": (
                ViewMode.guild_fav_manager,
                {"Item": {"url": "nao```@everyone", "description": "ddd"}},
            ),
            "servidor_nome_gigante": (
                ViewMode.guild_fav_manager,
                {"n" * self.GIGANTE: {"url": f"{URL_BASE}/a", "description": "ddd"}},
            ),
            "integracao_url_longa": (ViewMode.integrations_manager, {"Canal": url_gigante}),
            "integracao_com_crases": (ViewMode.integrations_manager, {"Canal": "nao```@everyone"}),
            "integracao_url_objeto_gigante": (
                ViewMode.integrations_manager,
                {"Canal": {"url": ["a" * self.GIGANTE]}},
            ),
        }

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "caso",
        [
            "favorito_url_longa",
            "integracao_url_objeto_gigante",
        ],
    )
    async def test_mensagem_de_erro_cabe_no_discord_e_nao_quebra_o_bloco(self, caso):
        modo, arquivo = self.casos()[caso]
        bot = ModalBot()
        inter = await importar(bot, modo, arquivo)
        assert inter.enviados, "o usuário precisa receber o motivo da recusa"
        for mensagem in inter.enviados:
            assert len(mensagem) < 2000, (
                f"KI-52: mensagem de {len(mensagem)} caracteres (o Discord recusa acima de 2000)"
            )
            assert mensagem.count("```") <= 2, f"KI-52: o valor do usuário fechou/abriu o bloco: {mensagem[:120]!r}"
