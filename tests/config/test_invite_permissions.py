"""INVITE_PERMISSIONS: o convite carrega toda permissão de que o bot precisa (auditoria do Sonar, 2.1.1).

Antigo ``332892794064`` -> novo ``2533601240804560``: entram LER O HISTÓRICO DE MENSAGENS (bit 16), DEFINIR O STATUS DO CANAL DE VOZ (bit 48) e
FIXAR MENSAGENS (bit 51); saem USAR COMANDOS DE APLICATIVO (bit 31) e PEDIR PARA FALAR (bit 32). Nenhum outro bit muda.

O mesmo número também vive em ``.example.env``, ``deploy/docker-compose.hostinger.yml`` e ``deploy/pterodactyl/egg-empiremuse.json``; por regra do
``testing.md`` nenhum teste lê esses arquivos: a conferência deles é por revisão do diff.
"""

import disnake
import pytest

from empiremuse import config_loader

pytestmark = pytest.mark.critical

ANTIGO = 332892794064
NOVO = 2533601240804560
ENTRAM = {"READ_MESSAGE_HISTORY": 16, "SET_VOICE_CHANNEL_STATUS": 48, "PIN_MESSAGES": 51}
SAEM = {"USE_APPLICATION_COMMANDS": 31, "REQUEST_TO_SPEAK": 32}


def mascara(*bits: int) -> int:
    return sum(1 << bit for bit in bits)


class TestValorPadrao:
    def test_the_default_is_the_new_mask(self):
        assert config_loader.DEFAULT_CONFIG["INVITE_PERMISSIONS"] == NOVO

    def test_the_loaded_config_without_any_override_uses_the_new_mask(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("INVITE_PERMISSIONS", raising=False)

        assert config_loader.load_config()["INVITE_PERMISSIONS"] == NOVO

    def test_an_environment_override_still_wins_and_stays_an_int(self, monkeypatch, tmp_path):
        monkeypatch.setenv("EMPIREMUSE_HOME", str(tmp_path))
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("INVITE_PERMISSIONS", "8")

        assert config_loader.load_config()["INVITE_PERMISSIONS"] == 8

    @pytest.mark.parametrize(("nome", "bit"), ENTRAM.items())
    def test_the_new_permissions_are_in_the_mask(self, nome, bit):
        assert NOVO & (1 << bit), f"{nome} (bit {bit}) falta na máscara"
        assert config_loader.DEFAULT_CONFIG["INVITE_PERMISSIONS"] & (1 << bit)

    @pytest.mark.parametrize(("nome", "bit"), SAEM.items())
    def test_the_removed_permissions_are_out_of_the_mask(self, nome, bit):
        assert not config_loader.DEFAULT_CONFIG["INVITE_PERMISSIONS"] & (1 << bit), (
            f"{nome} (bit {bit}) não deveria estar na máscara"
        )

    def test_the_old_mask_had_exactly_the_removed_ones_and_not_the_new_ones(self):
        assert all(ANTIGO & (1 << bit) for bit in SAEM.values())
        assert not any(ANTIGO & (1 << bit) for bit in ENTRAM.values())

    def test_no_other_bit_changed(self):
        esperado = (ANTIGO | mascara(*ENTRAM.values())) & ~mascara(*SAEM.values())

        assert config_loader.DEFAULT_CONFIG["INVITE_PERMISSIONS"] == esperado

    def test_disnake_reads_the_mask_with_the_expected_flags(self):
        permissoes = disnake.Permissions(config_loader.DEFAULT_CONFIG["INVITE_PERMISSIONS"])

        assert permissoes.read_message_history and permissoes.pin_messages
        assert not permissoes.use_application_commands and not permissoes.request_to_speak

    def test_the_music_essentials_are_kept(self):
        permissoes = disnake.Permissions(config_loader.DEFAULT_CONFIG["INVITE_PERMISSIONS"])

        assert permissoes.view_channel and permissoes.send_messages and permissoes.embed_links
        assert permissoes.connect and permissoes.speak
