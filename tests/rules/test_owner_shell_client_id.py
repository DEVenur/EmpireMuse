"""2.1.2 (A, regra fechada com o Vigil) — ``PANEL_OAUTH_CLIENT_ID`` é identificador público, não segredo.

Só o nome exato (case-sensitive) e só com um snowflake ASCII de 17 a 20 dígitos: qualquer outro valor sob esse nome
(alfanumérico, token com pontos, dígitos fullwidth) continua coletado. Nenhum outro nome com CLIENT_ID deixa de ser segredo.
"""

import pytest

from empiremuse.rules.owner_shell import MASK, collect_secret_values, is_secret_name, mask_secrets

pytestmark = pytest.mark.critical

NOME = "PANEL_OAUTH_CLIENT_ID"
SNOWFLAKE = "123456789012345678"
FULLWIDTH = "".join(chr(0xFF11 + (i % 9)) for i in range(18))  # "１２３…" (18 caracteres, isdigit() é True)


def com_digitos(quantidade: int) -> str:
    return "".join(str(1 + i % 9) for i in range(quantidade))


class TestSnowflakeNaoESegredo:
    @pytest.mark.parametrize("digitos", [17, 18, 19, 20])
    def test_a_snowflake_under_the_public_name_is_not_collected(self, digitos: int) -> None:
        valor = com_digitos(digitos)

        assert collect_secret_values({NOME: valor}) == frozenset()

    def test_mask_secrets_leaves_the_snowflake_in_the_clear(self) -> None:
        coletados = collect_secret_values({NOME: SNOWFLAKE})

        assert mask_secrets(f"client_id={SNOWFLAKE}", coletados) == f"client_id={SNOWFLAKE}"
        assert MASK not in mask_secrets(f"client_id={SNOWFLAKE}", coletados)

    def test_the_name_alone_is_no_longer_a_secret_name(self) -> None:
        assert is_secret_name(NOME) is False

    def test_the_exemption_works_in_both_sources_of_the_pool(self) -> None:
        assert collect_secret_values({NOME: SNOWFLAKE}, {NOME: SNOWFLAKE}) == frozenset()


class TestOutroValorContinuaColetado:
    @pytest.mark.parametrize(
        "valor",
        [
            "a1B2c3D4e5F6g7H8i9J0k1L2m3N4o5P6",  # 32 alfanuméricos
            "xxxxxxxxxxxx.yyyyyy.zzzzzzzzzzzzzzzzzzzzzzzzzzz",  # token com pontos
            FULLWIDTH,
            com_digitos(16),
            com_digitos(21),
            SNOWFLAKE + "\n",  # fullmatch: o "\n" final não passa
            " " + SNOWFLAKE,
            SNOWFLAKE + "x",
        ],
        ids=[
            "alfanumerico32",
            "token-com-pontos",
            "fullwidth",
            "16-digitos",
            "21-digitos",
            "quebra-final",
            "espaco",
            "sufixo",
        ],
    )
    def test_a_non_snowflake_value_under_the_public_name_is_still_collected(self, valor: str) -> None:
        assert collect_secret_values({NOME: valor}) == frozenset({valor})

    def test_the_fullwidth_case_is_really_a_str_isdigit_trap(self) -> None:
        assert len(FULLWIDTH) == 18 and FULLWIDTH.isdigit() and not FULLWIDTH.isascii()


class TestOutrosNomesContinuamSegredo:
    @pytest.mark.parametrize(
        "nome",
        [
            "SPOTIFY_CLIENT_ID",
            "PANEL_OAUTH_CLIENT_SECRET",
            "LASTFM_API_KEY",
            "LASTFM_API_SECRET",
            "panel_oauth_client_id",
            "Panel_Oauth_Client_Id",
            "X_OAUTH_CLIENT_ID",
            "PANEL_OAUTH_CLIENT_ID_2",
            " PANEL_OAUTH_CLIENT_ID",
        ],
    )
    def test_the_name_is_secret_and_its_snowflake_value_is_collected(self, nome: str) -> None:
        assert is_secret_name(nome) is True
        assert collect_secret_values({nome: SNOWFLAKE}) == frozenset({SNOWFLAKE})

    def test_the_same_snowflake_under_another_secret_key_is_still_masked(self) -> None:
        fontes = {NOME: SNOWFLAKE, "PANEL_OAUTH_CLIENT_SECRET": SNOWFLAKE}

        coletados = collect_secret_values(fontes)

        assert coletados == frozenset({SNOWFLAKE})
        assert mask_secrets(f"id={SNOWFLAKE}", coletados) == f"id={MASK}"

    def test_the_public_exemption_does_not_leak_to_the_secret_beside_it(self) -> None:
        segredo = "segredo-do-painel-xyz"
        coletados = collect_secret_values({NOME: SNOWFLAKE, "PANEL_OAUTH_CLIENT_SECRET": segredo})

        assert coletados == frozenset({segredo})
