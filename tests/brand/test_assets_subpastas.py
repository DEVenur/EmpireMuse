"""``assets/`` em subpastas (contrato ``assets-subpastas.md``), parte do código: ``asset_url`` e ``assets_base_url`` em ``utils/branding.py``.

Os testes do índice usam ÁRVORES TEMPORÁRIAS (``_ASSETS_DIR`` trocado e os caches limpos); só os critérios A1, A2, A5 e A6 olham o ``assets/`` real e
ficam vermelhos até o Ledger mover os arquivos. A lista ``COPIAS_DA_RAIZ`` congela os arquivos soltos na raiz de hoje (cópias de compatibilidade da
2.1.0): ela só pode diminuir.
"""

import ast
import hashlib
import os
import struct
from pathlib import Path

import pytest

from empiremuse.rules.release import parse_current_version
from empiremuse.utils import branding
from empiremuse.version import image_version
from tests.support.raiz import RAIZ

pytestmark = pytest.mark.critical

PACOTE = RAIZ / "empiremuse"
COPIAS_DA_RAIZ = frozenset(
    {
        "discord_support_guild_widget_banner.png",
        "lastfm_album_icon.jpg",
        "lastfm_artist_icon.jpg",
        "lastfm_default_twitter_avatar.png",
        "lastfm_disc_icon.jpg",
        "legacy_avatar_muse.png",
        "player_equalizer_1.gif",
        "player_equalizer_2.gif",
        "player_loading_neon_circle.gif",
        "player_pause_icon.png",
        "player_requester_avatar_unknown.png",
        "provider_applemusic_icon.png",
        "provider_deezer_icon.png",
        "provider_jiosaavn_icon.png",
        "provider_lastfm_emoji.png",
        "provider_soundcloud_icon.png",
        "provider_spotify_icon.png",
        "provider_tidal_icon.png",
        "provider_twitch_icon.png",
        "provider_youtube_icon.png",
        "provider_youtubemusic_icon.png",
        "readme_preview_controller_forum.png",
        "readme_preview_lastfm.png",
        "readme_preview_player_default.png",
        "readme_preview_player_setup.png",
        "readme_preview_slashcommands.png",
        "skin_normal_classic_preview.png",
        "skin_normal_default_preview.png",
        "skin_normal_default_progressbar_preview.png",
        "skin_normal_embed_link_preview.png",
        "skin_normal_lite_preview.png",
        "skin_normal_micro_controller_preview.png",
        "skin_normal_micro_nc_preview.png",
        "skin_normal_mini_preview.png",
        "skin_normal_minimalist_preview.png",
        "skin_normal_miniplayer_preview.png",
        "skin_preview_placeholder_yt.jpg",
        "skin_static_classic_preview.png",
        "skin_static_default_preview.png",
        "skin_static_default_progressbar_preview.png",
        "skin_static_embed_link_preview.png",
        "skin_static_mini_preview.png",
        "tutorial_guest_invite_guide.png",
        "tutorial_intents_guide.png",
        "tutorial_server_deafen_guide.png",
        "tutorial_token_guide.png",
        "ui_confirm_icon.png",
        "ui_floppy_save_icon.png",
        "ui_rainbow_bar_2.gif",
        "ui_rainbow_bar_3.gif",
        "ui_warning_icon.png",
    }
)
REPO = "EmpireCommunity/EmpireMuse"


def limpar_caches() -> None:
    """Esvazia todo ``lru_cache`` do módulo (o índice e o que mais ele guardar)."""
    for objeto in vars(branding).values():
        if hasattr(objeto, "cache_clear"):
            objeto.cache_clear()


@pytest.fixture
def arvore(tmp_path, monkeypatch):
    """Cria ``assets/`` temporário e devolve ``(raiz, escrever)``; ``escrever('providers/x.png')`` cria o arquivo."""
    raiz = tmp_path / "assets"
    raiz.mkdir()
    monkeypatch.setattr(branding, "_ASSETS_DIR", raiz)
    limpar_caches()

    def escrever(subcaminho: str, conteudo: bytes = b"x") -> Path:
        caminho = raiz / subcaminho
        caminho.parent.mkdir(parents=True, exist_ok=True)
        caminho.write_bytes(conteudo)
        return caminho

    yield raiz, escrever
    limpar_caches()


class TestIndiceNomeParaSubcaminho:
    def test_a_basename_in_a_subfolder_resolves_to_its_subpath(self, arvore):
        _, escrever = arvore
        escrever("providers/provider_spotify_icon.png")

        assert (
            branding.asset_url("provider_spotify_icon.png")
            == f"{branding.ASSETS_BASE_URL}/providers/provider_spotify_icon.png"
        )

    def test_each_basename_resolves_to_its_own_subfolder(self, arvore):
        _, escrever = arvore
        for subcaminho in (
            "brand/logo.svg",
            "player/player_pause_icon.png",
            "skins/skin_x_preview.png",
            "ui/ui_confirm_icon.png",
        ):
            escrever(subcaminho)

        for subcaminho in (
            "brand/logo.svg",
            "player/player_pause_icon.png",
            "skins/skin_x_preview.png",
            "ui/ui_confirm_icon.png",
        ):
            assert branding.asset_url(Path(subcaminho).name).endswith(f"/{subcaminho}")

    def test_a_root_copy_is_ignored_by_the_index(self, arvore):
        _, escrever = arvore
        escrever("ui_warning_icon.png")
        escrever("ui/ui_warning_icon.png")

        assert branding.asset_url("ui_warning_icon.png").endswith("/ui/ui_warning_icon.png")

    def test_a_file_that_exists_only_in_the_root_is_not_found(self, arvore):
        _, escrever = arvore
        escrever("so_na_raiz.png")

        with pytest.raises(ValueError):
            branding.asset_url("so_na_raiz.png")


class TestBasenameRepetido:
    def test_a_duplicate_basename_across_subfolders_is_an_error(self, arvore):
        _, escrever = arvore
        escrever("providers/igual.png")
        escrever("ui/igual.png")

        with pytest.raises(ValueError):
            branding.asset_url("igual.png")

    def test_the_same_basename_in_the_root_and_one_subfolder_is_not_a_duplicate(self, arvore):
        _, escrever = arvore
        escrever("igual.png")
        escrever("ui/igual.png")

        assert branding.asset_url("igual.png").endswith("/ui/igual.png")


class TestNomesRecusados:
    @pytest.mark.parametrize(
        "nome", ["", "a/b", "a\\b", "..", "a..b", "../x.png", "providers/x.png", "/x.png"], ids=repr
    )
    def test_an_invalid_name_is_refused(self, arvore, nome):
        _, escrever = arvore
        escrever("providers/x.png")

        with pytest.raises(ValueError):
            branding.asset_url(nome)

    def test_a_missing_name_is_refused(self, arvore):
        _, escrever = arvore
        escrever("providers/x.png")

        with pytest.raises(ValueError):
            branding.asset_url("nao_existe.png")

    def test_a_symlink_pointing_outside_assets_is_refused(self, arvore, tmp_path):
        raiz, escrever = arvore
        fora = tmp_path / "fora.png"
        fora.write_bytes(b"x")
        (raiz / "ui").mkdir()
        (raiz / "ui" / "elo.png").symlink_to(fora)
        escrever("ui/normal.png")

        with pytest.raises(ValueError):
            branding.asset_url("elo.png")
        assert branding.asset_url("normal.png").endswith("/ui/normal.png")

    def test_a_subfolder_that_is_a_symlink_outside_assets_is_refused(self, arvore, tmp_path):
        raiz, _ = arvore
        externa = tmp_path / "externa"
        externa.mkdir()
        (externa / "dentro.png").write_bytes(b"x")
        (raiz / "providers").symlink_to(externa)

        with pytest.raises(ValueError):
            branding.asset_url("dentro.png")

    def test_a_symlink_to_another_file_inside_assets_is_refused_too(self, arvore):
        raiz, escrever = arvore
        escrever("ui/real.png")
        (raiz / "player").mkdir()
        (raiz / "player" / "atalho.png").symlink_to(raiz / "ui" / "real.png")

        with pytest.raises(ValueError):
            branding.asset_url("atalho.png")
        assert branding.asset_url("real.png").endswith("/ui/real.png")

    def test_a_subfolder_that_is_a_symlink_to_another_folder_inside_assets_is_refused_too(self, arvore):
        raiz, escrever = arvore
        escrever("ui/real.png")
        (raiz / "atalho").symlink_to(raiz / "ui")

        assert branding.asset_url("real.png").endswith("/ui/real.png")
        limpar_caches()
        # o atalho de pasta não cria um segundo caminho para o mesmo arquivo (nem um basename "repetido")
        assert branding.asset_url("real.png").count("/atalho/") == 0

    def test_a_nested_subfolder_resolves_with_its_full_subpath(self, arvore):
        _, escrever = arvore
        escrever("brand/avatares/Avatar_1.png")

        assert branding.asset_url("Avatar_1.png").endswith("/brand/avatares/Avatar_1.png")

    def test_the_same_basename_in_a_nested_and_a_top_level_subfolder_is_a_duplicate(self, arvore):
        _, escrever = arvore
        escrever("brand/avatares/igual.png")
        escrever("ui/igual.png")

        with pytest.raises(ValueError):
            branding.asset_url("igual.png")


class TestBaseDasUrlsPorVersao:
    def test_a_known_version_points_at_its_own_immutable_tag(self):
        url = branding.assets_base_url(parse_current_version("2.1.1"))

        assert url == f"https://raw.githubusercontent.com/{REPO}/v2.1.1/assets"

    def test_a_release_candidate_points_at_its_rc_tag(self):
        url = branding.assets_base_url(parse_current_version("2.1.1-rc.1"))

        assert url == f"https://raw.githubusercontent.com/{REPO}/v2.1.1-rc.1/assets"

    def test_no_version_points_at_main_as_today(self):
        assert branding.assets_base_url(None) == f"https://raw.githubusercontent.com/{REPO}/main/assets"

    def test_the_urls_of_assets_use_the_same_base(self, arvore):
        _, escrever = arvore
        escrever("ui/ui_x.png")

        assert branding.asset_url("ui_x.png").startswith(branding.ASSETS_BASE_URL + "/ui/")


# ============================================================================ o assets/ real (vermelho até o Ledger mover os arquivos)
