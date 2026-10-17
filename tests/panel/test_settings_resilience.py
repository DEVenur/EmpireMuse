"""E4a — resiliência: falha de efeito em memória depois de gravar não pode derrubar a resposta nem desfazer o dado."""

from tests.panel.test_settings_http import HttpBase


class EffectFailureTest(HttpBase):
    def test_player_effect_failure_still_saves_and_answers_200(self):
        async def boom():
            raise RuntimeError("falha simulada do player")

        self.world.p100.process_save_queue = boom
        browser = self.logged_in()
        response = self.save(browser, 100, "player", "default_player_volume", default_player_volume="45")
        assert response.code == 200, f"status {response.code}"
        assert self.db.doc("1", 100)["default_player_volume"] == 45
        assert "falha simulada" not in response.body.decode() and "Traceback" not in response.body.decode()
        assert "falha simulada" not in self.all_log_text(), "a mensagem da exceção não deve ir ao log"
