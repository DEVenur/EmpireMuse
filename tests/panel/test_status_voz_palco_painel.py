"""2.1.2 (I8/VP4b, condição C2) — o formulário REAL do painel › Geral com uma sessão de palco ativa: o permanente é salvo e a sessão fica intacta.

O ``effects`` do #146 agenda ``schedule_permanent_voice_status`` no player; aqui o player é o ``JogadorDeVoz`` de produção (métodos de voz reais) no palco.
"""

from typing import Any

from tests.audio.test_status_voz_palco import MODELO_DA_SESSAO, SessaoDePalco, canal_de_palco
from tests.panel.helpers_settings import assentar
from tests.panel.test_settings_http import HttpBase
from tests.support.voz_auto import BotDeVoz, JogadorDeVoz, faixa, servidor

CAMPO_PERMANENTE = "voice_status_permanent"
CAMPO_MODELO = "voice_channel_status"
MODELO = "permanente {track.author}"


class SessaoDePalcoPeloPainelTest(HttpBase):
    def sessao_no_palco(self) -> SessaoDePalco:
        async def montar() -> SessaoDePalco:
            bot, canal = BotDeVoz(), canal_de_palco()
            jogador = JogadorDeVoz(servidor(canal), bot, atual=faixa(), template="{track.title}")
            sessao = await SessaoDePalco(bot, canal, jogador).ligar_sessao()
            self.world.bot1.music.players[100] = jogador
            return sessao

        return self.io_loop.run_sync(montar)

    def salvar(self, **campos: Any) -> int:
        resposta = self.save(self.logged_in(), 100, "geral", CAMPO_PERMANENTE, **campos)
        self.io_loop.run_sync(assentar)
        return resposta.code

    def test_turning_the_permanent_on_leaves_the_stage_session_alone(self) -> None:
        sessao = self.sessao_no_palco()

        assert self.salvar(**{CAMPO_PERMANENTE: "on", CAMPO_MODELO: MODELO}) == 200

        assert self.db.doc("global", 100)[CAMPO_PERMANENTE] is True
        assert sessao.player.voice_status_permanent is True
        assert sessao.sessao_intacta(), "o save pelo painel mexeu na sessão de palco"
        assert sessao.nada_foi_ao_palco()

    def test_turning_the_permanent_off_leaves_the_stage_session_alone(self) -> None:
        sessao = self.sessao_no_palco()

        assert self.salvar(**{CAMPO_PERMANENTE: None, CAMPO_MODELO: MODELO}) == 200

        assert self.db.doc("global", 100)[CAMPO_PERMANENTE] is False
        assert sessao.player.voice_status_permanent is False
        assert sessao.sessao_intacta() and sessao.nada_foi_ao_palco()
        assert sessao.player.stage_title_template == MODELO_DA_SESSAO

    def test_changing_only_the_model_leaves_the_stage_session_alone(self) -> None:
        sessao = self.sessao_no_palco()

        assert self.salvar(**{CAMPO_PERMANENTE: "on", CAMPO_MODELO: "outro {track.title}"}) == 200

        assert sessao.sessao_intacta() and sessao.nada_foi_ao_palco()
