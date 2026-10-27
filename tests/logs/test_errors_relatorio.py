"""Item 7, P4 (Vigil V-P4-1 e V-P4-2) — o embed do relatório do webhook de erro (``ErrorHandler.build_report_embed``) não vaza dado nem se deixa quebrar.

V-P4-1: as opções do slash saem do resumo por tipo de ``command_context`` (nada de URL assinada da CDN, nome nem texto livre); o ``content`` de
prefixo/mensagem passa por ``scrub`` (segredo registrado, ESC/RLO, teto, e crases que não fecham o bloco). V-P4-2: nome de servidor, canal de texto
e canais de voz entram em bloco de código com exatamente DUAS ocorrências de três crases (abertura e fechamento).
"""

import re
from types import SimpleNamespace

import disnake
import pytest

from empiremuse.cogs.error_handler import ErrorHandler
from empiremuse.logs.redact import MAX_MESSAGE_CHARS, register_secret
from tests.logs.apoio_erros import anexo, membro, sem_nomes, servidor


def links_alheios(texto: str) -> list[str]:
    """Links mascarados para o domínio dos dados de teste (não pode haver nenhum além do texto do nome)."""
    return re.findall(r"\]\(<?https://x\.invalido", texto)


pytestmark = pytest.mark.critical

TRES_CRASES = "`" * 3
TEXTO_LIVRE = "".join(["busca ", "livre privada"])
NOME_HOSTIL = "".join(["A", TRES_CRASES, "[clique](https://x.invalido)", "B"])
SEGREDO_NO_TEXTO = "".join(["segredo-no-texto-", "do-relatorio-Q7"])
ESC, RLO = "\x1b", "‮"


def tratador(*, message_content: bool = True) -> ErrorHandler:
    h = ErrorHandler.__new__(ErrorHandler)
    h.bot = SimpleNamespace(get_color=lambda *a: 0, intents=SimpleNamespace(message_content=message_content))
    return h


def canal_de_voz(nome: str, id_: int) -> SimpleNamespace:
    return SimpleNamespace(name=nome, id=id_, user_limit=0, voice_states={})


def avatar() -> SimpleNamespace:
    return SimpleNamespace(with_static_format=lambda formato: SimpleNamespace(url="https://cdn.exemplo/a.png"))


def autor(*, bot: bool = False, voz=None):
    a = membro()
    a.bot, a.voice, a.display_avatar = bot, voz, avatar()
    return a


def servidor_do_relatorio(nome: str = "Servidor", voz_do_bot=None):
    g = servidor()
    g.name, g.icon = nome, None
    g.me = SimpleNamespace(voice=voz_do_bot)
    return g


def slash(opcoes: dict[str, object], **mais) -> SimpleNamespace:
    return SimpleNamespace(
        bot=SimpleNamespace(get_color=lambda *a: 0),
        guild=servidor_do_relatorio(**mais.pop("servidor", {})),
        channel=SimpleNamespace(name=mais.pop("canal", "geral"), id=60),
        author=mais.pop("autor", autor()),
        data=SimpleNamespace(name="play"),
        filled_options=opcoes,
    )


def prefixo(content: str, *, autor_bot: bool = False) -> SimpleNamespace:
    return SimpleNamespace(
        bot=SimpleNamespace(get_color=lambda *a: 0),
        guild=servidor_do_relatorio(),
        channel=SimpleNamespace(name="geral", id=60),
        author=autor(bot=autor_bot),
        message=SimpleNamespace(content=content),
    )


class TestOpcoesDoSlash:
    def descricao(self, opcoes: dict[str, object]) -> str:
        return tratador().build_report_embed(slash(opcoes)).description

    def test_the_command_name_and_the_label_stay(self):
        descricao = self.descricao({"busca": TEXTO_LIVRE})

        assert "Slash Command:" in descricao and "play" in descricao

    def test_each_option_is_summarized_by_type(self):
        descricao = self.descricao(
            {"busca": TEXTO_LIVRE, "alvo": membro(31), "arquivo": anexo("image/png", 4321), "volume": 70}
        )

        assert f"str(len={len(TEXTO_LIVRE)})" in descricao
        assert "Member(id=31)" in descricao and "Attachment(tipo=image/png, tamanho=4321)" in descricao

    def test_a_secret_named_option_is_masked(self):
        descricao = self.descricao({"token": "valor-privado-R8"})

        assert "valor-privado-R8" not in descricao and "***" in descricao

    def test_nothing_signed_nor_named_nor_free_text_reaches_the_webhook(self):
        descricao = self.descricao({"busca": TEXTO_LIVRE, "alvo": membro(31), "arquivo": anexo()})

        assert sem_nomes(descricao) == [] and TEXTO_LIVRE not in descricao
        assert "ex=" not in descricao and "hm=" not in descricao


class TestConteudoDoPrefixo:
    def descricao(self, content: str, **kwargs) -> str:
        return tratador(**kwargs).build_report_embed(prefixo(content)).description

    def test_the_label_stays(self):
        assert "Comando:" in self.descricao("!play algo")

    def test_a_registered_secret_pasted_in_the_text_is_masked(self):
        register_secret(SEGREDO_NO_TEXTO)

        descricao = self.descricao(f"!play {SEGREDO_NO_TEXTO}")

        assert SEGREDO_NO_TEXTO not in descricao and "***" in descricao

    def test_escape_and_right_to_left_override_are_sanitized(self):
        descricao = self.descricao(f"!play a{ESC}[31mb{RLO}c")

        assert ESC not in descricao and RLO not in descricao

    def test_the_text_never_goes_past_the_cap(self):
        descricao = self.descricao("!play " + "x" * (MAX_MESSAGE_CHARS * 3))

        assert (
            len(descricao) <= MAX_MESSAGE_CHARS + 100
        )  # o teto vale para o texto; sobra só o rótulo e as cercas do bloco

    def test_three_backticks_inside_the_text_cannot_close_the_code_block(self):
        descricao = self.descricao(f"!play a{TRES_CRASES}[clique](https://x.invalido)b")

        assert (
            descricao.count(TRES_CRASES) == 2
        )  # dentro do bloco o texto é literal; o que importa é não haver como fechá-lo

    def test_a_bot_author_or_missing_message_content_intent_adds_no_text(self):
        assert tratador().build_report_embed(prefixo("!play x", autor_bot=True)).description is None
        assert tratador(message_content=False).build_report_embed(prefixo("!play x")).description is None


@pytest.mark.parametrize(
    ("campo", "fabrica"),
    [
        ("Servidor:", lambda: {"servidor": {"nome": NOME_HOSTIL}}),
        ("Canal de texto:", lambda: {"canal": NOME_HOSTIL}),
        ("Canal de voz (user):", lambda: {"autor": autor(voz=SimpleNamespace(channel=canal_de_voz(NOME_HOSTIL, 71)))}),
        (
            "Canal de voz (bot):",
            lambda: {
                "autor": autor(voz=SimpleNamespace(channel=canal_de_voz("Outro", 72))),
                "servidor": {"voz_do_bot": SimpleNamespace(channel=canal_de_voz(NOME_HOSTIL, 73))},
            },
        ),
    ],
    ids=["servidor", "canal-de-texto", "voz-do-usuario", "voz-do-bot"],
)
class TestNomesNosBlocos:
    def valor(self, campo: str, fabrica) -> str:
        embed = tratador().build_report_embed(slash({}, **fabrica()))
        return next(f.value for f in embed.fields if f.name == campo)

    def test_the_block_has_exactly_the_opening_and_the_closing_triple_backticks(self, campo, fabrica):
        valor = self.valor(campo, fabrica)

        assert valor.count(TRES_CRASES) == 2 and links_alheios(valor) == []

    def test_the_name_stays_readable_and_the_id_stays_in_the_block(self, campo, fabrica):
        valor = self.valor(campo, fabrica)

        assert "clique" in valor and "A" in valor and "B" in valor and "ID:" in valor
