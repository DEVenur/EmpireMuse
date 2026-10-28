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

ASSETS = RAIZ / "assets"
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

    def test_the_call_sites_do_not_change_the_url_is_base_plus_subpath(self, arvore):
        _, escrever = arvore
        escrever("ui/ui_warning_icon.png")

        assert branding.asset_url("ui_warning_icon.png") == branding.ASSETS_BASE_URL + "/ui/ui_warning_icon.png"

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

    def test_sha256sums_is_not_an_asset(self, arvore):
        _, escrever = arvore
        escrever("SHA256SUMS", b"abc  providers/x.png\n")
        escrever("providers/x.png")

        with pytest.raises(ValueError):
            branding.asset_url("SHA256SUMS")

    def test_directories_are_not_assets(self, arvore):
        raiz, escrever = arvore
        escrever("providers/x.png")

        with pytest.raises(ValueError):
            branding.asset_url("providers")

    def test_the_index_is_built_once_a_file_added_later_is_not_seen_until_the_cache_is_cleared(self, arvore):
        _, escrever = arvore
        escrever("providers/a.png")
        branding.asset_url("a.png")
        escrever("providers/b.png")

        with pytest.raises(ValueError):
            branding.asset_url("b.png")
        limpar_caches()
        assert branding.asset_url("b.png").endswith("/providers/b.png")


class TestBasenameRepetido:
    def test_a_duplicate_basename_across_subfolders_is_an_error(self, arvore):
        _, escrever = arvore
        escrever("providers/igual.png")
        escrever("ui/igual.png")

        with pytest.raises(ValueError):
            branding.asset_url("igual.png")

    def test_the_duplicate_breaks_the_whole_index_not_only_its_own_name(self, arvore):
        _, escrever = arvore
        escrever("providers/igual.png")
        escrever("ui/igual.png")
        escrever("ui/outra.png")

        with pytest.raises(ValueError):
            branding.asset_url("outra.png")

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
        assert branding.ASSETS_BASE_URL == f"https://raw.githubusercontent.com/{REPO}/main/assets"

    def test_the_repo_comes_from_github_repo(self):
        assert f"/{branding.GITHUB_REPO}/" in branding.assets_base_url(parse_current_version("2.1.1"))

    def test_two_versions_never_share_a_base(self):
        assert branding.assets_base_url(parse_current_version("2.1.1")) != branding.assets_base_url(
            parse_current_version("2.1.0")
        )

    def test_the_module_constant_still_exists_with_the_process_value(self):
        assert branding.ASSETS_BASE_URL == branding.assets_base_url(image_version())

    def test_the_urls_of_assets_use_the_same_base(self, arvore):
        _, escrever = arvore
        escrever("ui/ui_x.png")

        assert branding.asset_url("ui_x.png").startswith(branding.ASSETS_BASE_URL + "/ui/")


# ============================================================================ o assets/ real (vermelho até o Ledger mover os arquivos)


def nomes_de_asset_url_no_pacote() -> dict[str, list[str]]:
    """``{nome literal: [arquivo:linha]}`` de cada ``asset_url("nome")`` do pacote."""
    achados: dict[str, list[str]] = {}
    for caminho in sorted(PACOTE.rglob("*.py")):
        for no in ast.walk(ast.parse(caminho.read_text(encoding="utf-8"))):
            if (
                isinstance(no, ast.Call)
                and getattr(no.func, "id", getattr(no.func, "attr", "")) == "asset_url"
                and no.args
                and isinstance(no.args[0], ast.Constant)
                and isinstance(no.args[0].value, str)
            ):
                achados.setdefault(no.args[0].value, []).append(f"{caminho.relative_to(RAIZ).as_posix()}:{no.lineno}")
    return achados


def arquivos_das_subpastas() -> list[Path]:
    return sorted(p for pasta in ASSETS.iterdir() if pasta.is_dir() for p in pasta.rglob("*") if p.is_file())


class TestAssetsReais:
    def test_the_scan_finds_the_literal_asset_url_calls(self):
        assert len(nomes_de_asset_url_no_pacote()) >= 30

    def test_every_name_used_in_asset_url_resolves_to_a_file_in_a_subfolder(self):
        limpar_caches()
        sem_arquivo = {}
        for nome, locais in nomes_de_asset_url_no_pacote().items():
            try:
                url = branding.asset_url(nome)
            except ValueError as erro:
                sem_arquivo[nome] = (locais[0], str(erro)[:60])
                continue
            subcaminho = url.removeprefix(branding.assets_base_url(image_version()) + "/")
            if "/" not in subcaminho or not (ASSETS / subcaminho).is_file():
                sem_arquivo[nome] = (locais[0], subcaminho)

        assert sem_arquivo == {}, sem_arquivo

    def test_basenames_are_unique_across_the_subfolders(self):
        nomes = [p.name for p in arquivos_das_subpastas()]
        repetidos = sorted({n for n in nomes if nomes.count(n) > 1})

        assert repetidos == []

    def test_no_loose_file_in_the_root_except_sha256sums_and_the_frozen_compatibility_copies(self):
        soltos = {p.name for p in ASSETS.iterdir() if p.is_file()} - {"SHA256SUMS"}

        assert soltos <= COPIAS_DA_RAIZ, sorted(soltos - COPIAS_DA_RAIZ)

    def test_the_assets_are_organized_in_subfolders_not_only_in_the_root(self):
        assert len(arquivos_das_subpastas()) >= 50

    def test_every_root_copy_has_its_twin_in_a_subfolder_with_the_same_bytes(self):
        por_nome = {p.name: p for p in arquivos_das_subpastas()}
        sem_gemeo = sorted(n for n in COPIAS_DA_RAIZ if (ASSETS / n).is_file() and n not in por_nome)
        diferentes = sorted(
            n for n, p in por_nome.items() if (ASSETS / n).is_file() and (ASSETS / n).read_bytes() != p.read_bytes()
        )

        assert sem_gemeo == [] and diferentes == []


def somas() -> dict[str, str]:
    arquivo = ASSETS / "SHA256SUMS"
    pares = (linha.split(None, 1) for linha in arquivo.read_text(encoding="utf-8").splitlines() if linha.strip())
    return {nome.strip(): resumo for resumo, nome in pares}


class TestSemLinksSimbolicos:
    def test_there_is_no_symlink_anywhere_under_assets(self):
        elos = sorted(p.relative_to(ASSETS).as_posix() for p in ASSETS.rglob("*") if p.is_symlink())

        assert elos == []

    def test_every_avatar_in_brand_avatares_resolves_through_asset_url(self):
        limpar_caches()
        pasta = ASSETS / "brand" / "avatares"
        avatares = sorted(p for p in pasta.iterdir() if p.is_file())

        assert len(avatares) >= 5
        for avatar in avatares:
            assert branding.asset_url(avatar.name).endswith(f"/brand/avatares/{avatar.name}")

    def test_the_brand_files_resolve_to_their_subfolder(self):
        limpar_caches()

        for nome in ("avatar.png", "banner.png", "logo.svg", "favicon.ico"):
            assert branding.asset_url(nome).endswith(f"/brand/{nome}")


class TestSomasDeIntegridade:
    def test_every_file_under_assets_is_listed_with_its_relative_path_and_matches(self):
        listadas = somas()
        arquivos = {
            p.relative_to(ASSETS).as_posix(): p for p in ASSETS.rglob("*") if p.is_file() and p.name != "SHA256SUMS"
        }

        faltando = sorted(set(arquivos) - set(listadas))
        errados = sorted(
            n
            for n, p in arquivos.items()
            if n in listadas and listadas[n] != hashlib.sha256(p.read_bytes()).hexdigest()
        )
        assert faltando == [] and errados == []

    def test_no_entry_points_to_a_file_that_does_not_exist(self):
        assert sorted(n for n in somas() if not (ASSETS / n).is_file()) == []

    def test_the_subfolder_entries_use_the_relative_path(self):
        assert any("/" in nome for nome in somas())

    def test_the_emojis_folder_has_only_128_by_128_pngs_and_the_one_animated_gif(self):
        pasta = ASSETS / "emojis"
        if not pasta.is_dir():
            pytest.skip("assets/emojis/ ainda não existe (vem da feature de emojis)")

        gifs = []
        for arquivo in pasta.iterdir():
            dados = arquivo.read_bytes()
            if arquivo.suffix == ".gif":
                gifs.append(arquivo.name)
                assert dados.startswith(b"GIF89a") and struct.unpack("<HH", dados[6:10]) == (128, 128), arquivo.name
                assert len(dados) <= 256 * 1024, arquivo.name
                continue
            assert arquivo.suffix == ".png" and dados.startswith(b"\x89PNG\r\n\x1a\n"), arquivo.name
            assert struct.unpack(">II", dados[16:24]) == (128, 128), arquivo.name

        assert gifs in ([], ["headset.gif"]), gifs
