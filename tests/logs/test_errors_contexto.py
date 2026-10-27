"""Item 7, P4 — ``command_context`` (B16, V-L4): o contexto de um comando que falha leva IDs e um resumo por tipo, nunca nomes nem conteúdo.

``logs/errors.py`` (novo, Turbine): ``command_context(ctx_or_inter, *, level) -> dict`` com ``command``, ``user_id``, ``guild_id``, ``channel_id`` e
``params`` (nome → resumo em texto). O texto livre só aparece com ``level == DEBUG`` ou com o servidor em ``LOG_DEBUG_GUILDS``.
"""

import logging

import pytest

from empiremuse.logs.errors import command_context
from empiremuse.logs.redact import register_secret
from empiremuse.logs.setup import configure_logging
from tests.logs.apoio_erros import (
    CANAL,
    SERVIDOR,
    URL_DO_ANEXO,
    USUARIO,
    Cor,
    anexo,
    cargo,
    canal_de_texto,
    configuracao,
    contexto_de_prefixo,
    interacao,
    membro,
    mensagem,
    novo_fluxo,
    sem_nomes,
    servidor,
)

pytestmark = pytest.mark.critical

ERROR, DEBUG = logging.ERROR, logging.DEBUG


def resumo(opcoes: dict[str, object], nivel: int = ERROR) -> dict[str, str]:
    return {nome: str(valor) for nome, valor in command_context(interacao(opcoes), level=nivel)["params"].items()}


class TestCampos:
    def test_it_carries_the_ids_and_the_qualified_command_name(self):
        contexto = command_context(interacao({}, comando="queue clear"), level=ERROR)

        assert contexto["command"] == "queue clear"
        assert (contexto["user_id"], contexto["guild_id"], contexto["channel_id"]) == (USUARIO, SERVIDOR, CANAL)

    def test_a_prefix_context_has_the_same_fields(self):
        contexto = command_context(contexto_de_prefixo("skip"), level=ERROR)

        assert contexto["command"] == "skip"
        assert (contexto["user_id"], contexto["guild_id"], contexto["channel_id"]) == (USUARIO, SERVIDOR, CANAL)

    def test_nothing_in_it_carries_a_name_even_through_repr(self):
        contexto = command_context(
            interacao({"membro": membro(), "mensagem": mensagem(), "servidor": servidor(), "anexo": anexo()}),
            level=ERROR,
        )

        assert sem_nomes(repr(contexto)) == []

    def test_a_dm_without_a_guild_has_no_guild_id(self):
        inter = interacao({})
        inter.guild, inter.guild_id = None, None

        assert command_context(inter, level=ERROR)["guild_id"] is None


class TestResumoPorTipo:
    def test_a_member_becomes_type_and_id_without_any_of_the_three_names(self):
        assert resumo({"alvo": membro(31)})["alvo"] == "Member(id=31)"

    def test_a_message_becomes_type_and_id_without_content(self):
        assert resumo({"msg": mensagem(32)})["msg"] == "Message(id=32)"

    @pytest.mark.parametrize(
        ("valor", "esperado"),
        [(servidor(33), "Guild(id=33)"), (cargo(34), "Role(id=34)"), (canal_de_texto(35), "TextChannel(id=35)")],
        ids=["servidor", "cargo", "canal"],
    )
    def test_the_other_disnake_models_become_type_and_id(self, valor, esperado):
        assert resumo({"x": valor})["x"] == esperado

    def test_an_attachment_becomes_type_and_size_never_the_signed_url(self):
        saida = resumo({"arquivo": anexo("audio/mpeg", 9876)})["arquivo"]

        assert saida == "Attachment(tipo=audio/mpeg, tamanho=9876)"
        assert "cdn" not in saida and URL_DO_ANEXO not in saida

    def test_numbers_booleans_and_enums_keep_their_value(self):
        saida = resumo({"volume": 70, "ativo": True, "cor": Cor.VERMELHO})

        assert saida["volume"] == "70" and saida["ativo"] == "True" and "vermelho" in saida["cor"].lower()

    @pytest.mark.parametrize("nome", ["token", "password", "api_key", "webhook_url"])
    def test_a_parameter_whose_name_matches_the_secret_regex_is_masked_at_any_level(self, nome):
        for nivel in (ERROR, DEBUG):
            assert resumo({nome: "valor-qualquer"}, nivel)[nome] == "***"

    def test_an_unknown_object_never_falls_back_to_repr(self):
        class Estranho:
            def __repr__(self) -> str:
                return "REPR-COM-DADO-PRIVADO"

        assert "REPR-COM-DADO-PRIVADO" not in resumo({"x": Estranho()})["x"]


class TestTextoLivre:
    def test_at_error_only_the_length_appears(self):
        assert resumo({"busca": "musica secreta"})["busca"] == "str(len=14)"

    def test_at_debug_the_value_appears_cut_at_100(self):
        saida = resumo({"busca": "x" * 250}, DEBUG)["busca"]

        assert "x" * 100 in saida and "x" * 101 not in saida

    def test_at_debug_the_total_is_capped_at_500(self):
        saida = resumo({f"p{i}": "y" * 100 for i in range(10)}, DEBUG)

        assert sum(len(valor) for valor in saida.values()) <= 500

    def test_at_debug_a_registered_secret_inside_the_text_is_redacted(self):
        segredo = "".join(["segredo-no-texto-", "livre-Z9"])
        register_secret(segredo)

        assert segredo not in resumo({"busca": f"toque {segredo} agora"}, DEBUG)["busca"]

    def test_a_guild_in_log_debug_guilds_reveals_the_value_even_at_error(self):
        configure_logging(configuracao(debug_guilds=frozenset({SERVIDOR})), [], stream=novo_fluxo())

        assert "musica secreta" in resumo({"busca": "musica secreta"}, ERROR)["busca"]

    def test_another_guild_in_log_debug_guilds_reveals_nothing(self):
        configure_logging(configuracao(debug_guilds=frozenset({SERVIDOR + 1})), [], stream=novo_fluxo())

        assert resumo({"busca": "musica secreta"}, ERROR)["busca"] == "str(len=14)"


class TestRobustez:
    def test_a_broken_option_never_raises_out_of_the_error_path(self):
        class Quebrado:
            def __str__(self) -> str:
                raise RuntimeError("falha ao converter")

        contexto = command_context(interacao({"x": Quebrado(), "ok": 1}), level=ERROR)

        assert contexto["params"]["ok"] in (1, "1")
