"""E5 — caracterização (VERDE desde já) das regras da conta, medidas no COMPORTAMENTO dos comandos e modais.

Cada teste chama o callback real (comando, modal, view ou botão) com dublês de disnake; nenhum lê o texto do
código-fonte, então a extração das regras (F3-5b) não os quebra. Se um comando mudar, estes testes avisam que o painel
(panel/services/account*.py) precisa acompanhar, e o contrário.
"""

import json
import re
import string
from types import SimpleNamespace

import pytest

import empiremuse.cogs.legacy_cmds as legacy_cmds
import empiremuse.cogs.music_settings as music_settings
from empiremuse.utils.db import DBModel, get_prefix
from empiremuse.utils.music.interactions import FavMenuView, ViewMode
from tests.support.drivers_de_regras import (
    AUTOR,
    BotDeComandos,
    BotDoPlayer,
    BotDoRpc,
    InteracaoFalsa,
    campos_do_modal,
    executar,
    favoritar_pelo_embed,
    favoritar_pelo_seletor,
    jogador_no_canal_de_voz,
    montar_rpc,
)
from tests.support.modais import (
    SERVIDOR_DO_COMANDO,
    URL_BASE,
    ModalBot,
    ModalInteraction,
    adicionar_favorito,
    adicionar_integracao,
    exportar,
    gravados,
    importar,
    modal_view,
)
from tests.panel.helpers import ROOT

LASTFM = (ROOT / "empiremuse/cogs/lastfm.py").read_text(encoding="utf-8")

URL = f"{URL_BASE}/a"
FAVORITOS, INTEGRACOES = ViewMode.fav_manager, ViewMode.integrations_manager


def flat(text):
    return " ".join(text.split())


def url_com_tamanho(tamanho):
    base = f"{URL_BASE}/"
    return base + "x" * (tamanho - len(base))


class TestUserPrefixRules:
    @pytest.mark.asyncio
    async def test_set_user_prefix_limit_strip_and_cache_key(self):
        bot = BotDeComandos()
        aceito = await executar(bot, legacy_cmds.Owner.setuserprefix, "  ab  ")
        assert not aceito.recusado and bot.ultimo_global["custom_prefix"] == "ab"
        assert bot.pool.user_prefix_cache == {AUTOR: "ab"}, "chave = id INT do usuário"
        assert all(isinstance(chave, int) for chave in bot.pool.user_prefix_cache)
        for prefixo in ("", "   ", "a" * 6):
            recusado = await executar(BotDeComandos(), legacy_cmds.Owner.setuserprefix, prefixo)
            assert recusado.recusado and recusado.bot.gravacoes == [], prefixo
        no_limite = await executar(BotDeComandos(), legacy_cmds.Owner.setuserprefix, "a" * 5)
        assert not no_limite.recusado

    @pytest.mark.asyncio
    async def test_reset_user_prefix_writes_empty_string_in_field_and_cache(self):
        bot = BotDeComandos()
        bot.documento("global", DBModel.users, AUTOR)["custom_prefix"] = ">>"
        bot.pool.user_prefix_cache[AUTOR] = ">>"
        resultado = await executar(bot, legacy_cmds.Owner.resetuserprefix)
        assert not resultado.recusado
        assert bot.ultimo_global["custom_prefix"] == "" and bot.pool.user_prefix_cache == {AUTOR: ""}

    @pytest.mark.asyncio
    async def test_reset_user_prefix_without_a_prefix_is_refused_and_writes_nothing(self):
        bot = BotDeComandos()
        resultado = await executar(bot, legacy_cmds.Owner.resetuserprefix)
        assert resultado.recusado and bot.gravacoes == [] and bot.pool.user_prefix_cache == {}

    @pytest.mark.asyncio
    async def test_cache_is_read_with_the_same_int_key(self):
        bot = BotDeComandos(config={"DEFAULT_PREFIX": "!!"})
        bot.user.id = 77
        mensagem = SimpleNamespace(content=">>play x", author=SimpleNamespace(id=AUTOR), guild=None)
        bot.pool.user_prefix_cache[AUTOR] = ">>"
        assert await get_prefix(bot, mensagem) == ">>", "o cache pela chave int vale sem ir ao banco"
        assert bot.gravacoes == []
        vazio = BotDeComandos(config={"DEFAULT_PREFIX": "!!"})
        vazio.user.id = 77
        vazio.documento("global", DBModel.users, AUTOR)["custom_prefix"] = "%%"
        mensagem.content = "%%play x"
        assert await get_prefix(vazio, mensagem) == "%%"
        assert vazio.pool.user_prefix_cache == {AUTOR: "%%"}, "e é preenchido com a chave int"


class TestFavoritesRules:
    def test_config_defaults(self):
        import empiremuse.config_loader as config_loader

        cfg = config_loader.DEFAULT_CONFIG
        assert (
            cfg["MAX_USER_FAVS"],
            cfg["USER_FAV_MAX_NAME_LENGTH"],
            cfg["USER_FAV_MAX_URL_LENGTH"],
            cfg["MAX_USER_INTEGRATIONS"],
        ) == (10, 35, 90, 10)

    @pytest.mark.asyncio
    async def test_add_modal_limits_and_extraction(self):
        campos = campos_do_modal(FAVORITOS)
        assert (campos["user_fav_name"].min_length, campos["user_fav_name"].max_length) == (2, 25)
        assert (campos["user_fav_url"].min_length, campos["user_fav_url"].max_length) == (10, 200)
        bot = ModalBot()
        await adicionar_favorito(bot, url=f"  <{URL}>  ")
        assert bot.salvos_usuario[-1]["fav_links"]["novo"] == URL, (
            "valor = URL em texto (Etapa 4: URL pura, desembrulhada)"
        )

    @pytest.mark.asyncio
    async def test_add_modal_and_both_player_buttons_have_the_zero_and_owner_exemption(self):
        """KI-39: o comportamento do modal é medido em tests/cogs/test_cogs_x_painel.py; aqui os três caminhos de escrita."""
        cheios = {f"f{i}": URL for i in range(8)}
        for favs, dono in ((0, False), (3, True)):
            modal = ModalBot(favs=favs, dono=dono, fav_links=cheios)
            await adicionar_favorito(modal)
            assert "novo" in modal.salvos_usuario[-1]["fav_links"], (favs, dono)
            embed = BotDoPlayer(favs=favs, dono=dono, favoritos=cheios)
            await favoritar_pelo_embed(embed, "Pelo embed")
            assert "Pelo embed" in embed.ultimo_global["fav_links"], (favs, dono)
            seletor = BotDoPlayer(favs=favs, dono=dono, favoritos=cheios)
            await favoritar_pelo_seletor(seletor, "Pelo seletor")
            assert "Pelo seletor" in seletor.ultimo_global["fav_links"], (favs, dono)

    @pytest.mark.asyncio
    async def test_import_rules(self):
        # URL: texto cabe em USER_FAV_MAX_URL_LENGTH e tem de ser URL inteira
        for tamanho, aceito in ((90, True), (91, False)):
            bot = ModalBot(url_max=90)
            await importar(bot, FAVORITOS, {"Musica": url_com_tamanho(tamanho)})
            assert bool(bot.salvos_usuario) is aceito, tamanho
        recusado = ModalBot()
        await importar(recusado, FAVORITOS, {"Musica": "isto não é um link"})
        assert recusado.salvos_usuario == []
        # nome: respeita USER_FAV_MAX_NAME_LENGTH quando menor que 25
        curto = ModalBot(nome_max=10)
        await importar(curto, FAVORITOS, {"n" * 15: URL})
        assert curto.salvos_usuario == []
        # itens do arquivo entram por cima do que já existe (update) e o resto é preservado
        bot = ModalBot(fav_links={"a1": f"{URL_BASE}/1", "a2": f"{URL_BASE}/2"})
        await importar(bot, FAVORITOS, {"a1": URL, "novo": URL})
        assert gravados(bot, FAVORITOS) == {"a1": URL, "a2": f"{URL_BASE}/2", "novo": URL}
        # cota: o arquivo não pode passar de MAX_USER_FAVS, nem o total depois de somar o que já existe
        grande = ModalBot(favs=2)
        await importar(grande, FAVORITOS, {"a1": URL, "a2": URL, "a3": URL})
        assert grande.salvos_usuario == []
        cheio = ModalBot(favs=2, fav_links={"x1": URL, "x2": URL})
        await importar(cheio, FAVORITOS, {"novo": URL})
        assert cheio.salvos_usuario == []

    @pytest.mark.asyncio
    async def test_export_is_the_stored_dict_dumped_as_json(self):
        bot = ModalBot(fav_links={"Rock": URL, "Pop": f"{URL_BASE}/b"})
        nome, texto = await exportar(bot, FAVORITOS)
        assert nome == "favoritos.json"
        assert texto == json.dumps(bot.user_data["fav_links"], indent=4)


class TestIntegrationsRules:
    @pytest.mark.asyncio
    async def test_import_rules(self):
        # URL: no máximo 200 caracteres (Etapa 5, D4) e URL inteira, independentemente da configuração dos favoritos
        for tamanho, aceito in ((200, True), (201, False)):
            bot = ModalBot(url_max=90)
            await importar(bot, INTEGRACOES, {"Canal": url_com_tamanho(tamanho)})
            assert bool(bot.salvos_usuario) is aceito, tamanho
        recusado = ModalBot()
        await importar(recusado, INTEGRACOES, {"Canal": "isto não é um link"})
        assert recusado.salvos_usuario == []
        # a chave antiga (minúscula e truncada em 90) de um título é substituída pela nova
        antiga = ModalBot(integration_links={"canal": {"url": f"{URL_BASE}/antiga"}})
        await importar(antiga, INTEGRACOES, {"Canal": URL})
        assert list(gravados(antiga, INTEGRACOES)) == ["Canal"]
        # cota: MAX_USER_INTEGRATIONS, com 0 = ilimitado e o dono do bot isento
        for integracoes, dono, cabe in ((1, False, False), (0, False, True), (1, True, True)):
            bot = ModalBot(integracoes=integracoes, dono=dono, integration_links={"antigo": {"url": URL}})
            await importar(bot, INTEGRACOES, {"novo": URL})
            assert bool(bot.salvos_usuario) is cabe, (integracoes, dono)
        # os itens do arquivo entram por cima do que já existe
        bot = ModalBot(integration_links={"a": {"url": f"{URL_BASE}/1"}, "b": {"url": f"{URL_BASE}/2"}})
        await importar(bot, INTEGRACOES, {"a": {"url": URL}, "novo": {"url": URL}})
        assert gravados(bot, INTEGRACOES) == {"a": {"url": URL}, "b": {"url": f"{URL_BASE}/2"}, "novo": {"url": URL}}

    @pytest.mark.asyncio
    async def test_stored_shape_of_added_integrations_is_an_object_with_url_and_optional_avatar(self):
        deezer = ModalBot()
        await adicionar_integracao(deezer, url="https://www.deezer.com/br/profile/123456")
        assert deezer.salvos_usuario[-1]["integration_links"]["【DZ】: Ana"] == {
            "url": "https://www.deezer.com/br/profile/123456",
            "avatar": f"{URL_BASE}/ana.png",
        }
        spotify = ModalBot()

        async def usuario_do_spotify(user_id):
            return {
                "display_name": "Bia",
                "external_urls": {"spotify": f"https://open.spotify.com/user/{user_id}"},
                "images": [{"url": f"{URL_BASE}/grande.png"}, {"url": f"{URL_BASE}/bia.png"}],
            }

        spotify.spotify = SimpleNamespace(get_user_info=usuario_do_spotify)
        await adicionar_integracao(spotify, url="https://open.spotify.com/user/abc123")
        assert spotify.salvos_usuario[-1]["integration_links"]["【SP】: Bia"] == {
            "url": "https://open.spotify.com/user/abc123",
            "avatar": f"{URL_BASE}/bia.png",
        }

    @pytest.mark.asyncio
    async def test_remove_deletes_by_exact_title(self):
        bot = ModalBot(integration_links={"Canal": {"url": URL}, "canal": {"url": f"{URL_BASE}/b"}})
        view = modal_view(bot, INTEGRACOES)
        view.current = "Canal"
        await FavMenuView.remove_callback(view, ModalInteraction())
        assert list(bot.salvos_usuario[-1]["integration_links"]) == ["canal"]


class TestLastFmRules:
    def test_toggle_exists_only_with_a_session_key_and_writes_only_the_scrobble_flag(self):
        assert re.search(r"def build_components\(self\):\s+if self\.session_key:", LASTFM)
        assert 'user_data["lastfm"]["scrobble"] = self.scrobble_enabled' in LASTFM
        assert "CooldownMapping.from_cooldown(1, 7, commands.BucketType.user)" in flat(LASTFM)

    def test_scrobbling_needs_the_flag_and_a_session_key(self):
        assert 'if fminfo["scrobble"] is False or not fminfo["sessionkey"]:' in flat(LASTFM)


def rpc_inter(custom_id="", *, author_id=AUTOR):
    inter = InteracaoFalsa(autor=author_id, custom_id=custom_id)
    inter.message.flags.ephemeral = True
    return inter


class TestRpcTokenRules:
    @pytest.mark.asyncio
    async def test_command_availability_condition(self):
        # sem ENABLE_RPC_COMMAND, só o dono do bot usa o comando
        fechado = BotDoRpc(config={"ENABLE_RPC_COMMAND": False})
        rpc, _ = montar_rpc(fechado)
        with pytest.raises(music_settings.GenericError):
            await music_settings.RPCCog.rich_presence.callback(self=rpc, inter=rpc_inter())
        dono = BotDoRpc(config={"ENABLE_RPC_COMMAND": False}, dono=True)
        rpc, _ = montar_rpc(dono)
        inter = rpc_inter()
        await music_settings.RPCCog.rich_presence.callback(self=rpc, inter=inter)
        assert inter.enviados
        # sem URL do servidor de RPC configurada, o comando também é recusado
        sem_url = BotDoRpc(config={"RPC_PUBLIC_URL": "", "RPC_SERVER": ""})
        rpc, _ = montar_rpc(sem_url)
        with pytest.raises(music_settings.GenericError):
            await music_settings.RPCCog.rich_presence.callback(self=rpc, inter=rpc_inter())

    @pytest.mark.asyncio
    @pytest.mark.parametrize(("auth", "botoes"), [(True, 3), (False, 0)], ids=["com_auth", "sem_auth"])
    async def test_token_buttons_exist_only_with_enable_rpc_auth(self, auth, botoes):
        bot = BotDoRpc(config={"ENABLE_RPC_AUTH": auth})
        rpc, _ = montar_rpc(bot)
        inter = rpc_inter()
        await music_settings.RPCCog.rich_presence.callback(self=rpc, inter=inter)
        ids = [componente.custom_id for componente in inter.componentes]
        assert len(ids) == botoes
        if auth:
            assert ids == [f"rpc_gen.{AUTOR}", f"rpc_create.{AUTOR}", f"rpc_remove.{AUTOR}"]

    @pytest.mark.asyncio
    async def test_generated_token_format_is_50_letters_and_digits(self):
        bot = BotDoRpc()
        rpc, _ = montar_rpc(bot)
        await rpc.rpc_button_event(rpc_inter(f"rpc_gen.{AUTOR}"))
        token = bot.ultimo_global["token"]
        assert re.fullmatch(r"[A-Za-z0-9]{50}", token) and set(token) <= set(string.ascii_letters + string.digits)
        modal = rpc_inter(f"rpc_create.{AUTOR}")
        await rpc.rpc_button_event(modal)
        campo = modal.response.modais[0]["components"][0]
        assert (campo.custom_id, campo.min_length, campo.max_length) == ("token_input", 50, 50)
        assert campo.value == token, "o modal mostra o token atual quando ele tem 50 caracteres"

    @pytest.mark.asyncio
    async def test_replacing_or_removing_a_token_closes_the_active_presence_first(self):
        bot = BotDoRpc()
        bot.documento("global", DBModel.users, AUTOR)["token"] = "a" * 50
        rpc, configuracoes = montar_rpc(bot)
        await rpc.rpc_button_event(rpc_inter(f"rpc_gen.{AUTOR}"))
        assert [evento[0] for evento in bot.eventos] == ["fechar", "gravar"]
        novo = BotDoRpc()
        novo.documento("global", DBModel.users, AUTOR)["token"] = "a" * 50
        _, configuracoes = montar_rpc(novo)
        modal = rpc_inter("rpc_token_create")
        modal.text_values = {"token_input": "b" * 50}
        await configuracoes.rpc_create_modal(modal)
        assert [evento[0] for evento in novo.eventos] == ["fechar", "gravar"] and novo.ultimo_global[
            "token"
        ] == "b" * 50
        remover = BotDoRpc()
        remover.documento("global", DBModel.users, AUTOR)["token"] = "a" * 50
        rpc_remover, _ = montar_rpc(remover)
        await rpc_remover.rpc_button_event(rpc_inter(f"rpc_remove.{AUTOR}"))
        assert [evento[0] for evento in remover.eventos] == ["fechar", "gravar"] and remover.ultimo_global[
            "token"
        ] == ""

    @pytest.mark.asyncio
    async def test_gen_without_a_previous_token_does_not_close_anything(self):
        bot = BotDoRpc()
        rpc, _ = montar_rpc(bot)
        await rpc.rpc_button_event(rpc_inter(f"rpc_gen.{AUTOR}"))
        assert [evento[0] for evento in bot.eventos] == ["gravar"]

    @pytest.mark.asyncio
    async def test_importing_the_same_token_changes_nothing(self):
        bot = BotDoRpc()
        bot.documento("global", DBModel.users, AUTOR)["token"] = "a" * 50
        _, configuracoes = montar_rpc(bot)
        modal = rpc_inter("rpc_token_create")
        modal.text_values = {"token_input": "a" * 50}
        await configuracoes.rpc_create_modal(modal)
        assert bot.eventos == [] and "igual ao token atual" in modal.texto

    @pytest.mark.asyncio
    async def test_close_presence_sends_op_close_to_players_where_the_user_is_in_voice(self):
        bot = BotDoRpc()
        rpc, _ = montar_rpc(bot)
        enviados = jogador_no_canal_de_voz(bot, [AUTOR])
        inter = rpc_inter(f"rpc_remove.{AUTOR}")
        inter.guild_id = SERVIDOR_DO_COMANDO
        await music_settings.RPCCog.close_presence(rpc, inter)
        assert len(enviados) == 1 and enviados[0][0] == [AUTOR]
        assert enviados[0][1]["op"] == "close" and enviados[0][1]["bot_id"] == bot.user.id
        fora = BotDoRpc()
        rpc_fora, _ = montar_rpc(fora)
        enviados_fora = jogador_no_canal_de_voz(fora, [123])
        await music_settings.RPCCog.close_presence(rpc_fora, inter)
        assert enviados_fora == []
