"""D13 — a versão ATUAL da imagem pode ser ``X.Y.Z-rc.N``; este apoio importa ``parse_current_version`` só na hora de usar.

Assim os arquivos de teste que já existem continuam coletando (e os testes antigos continuam rodando) mesmo antes de a função existir.
"""

from empiremuse.rules.release import Version

RC2 = "2.1.0-rc.2"


def atual_rc(texto: str = RC2) -> Version:
    from empiremuse.rules.release import parse_current_version

    versao = parse_current_version(texto)
    assert versao is not None, f"parse_current_version({texto!r}) deveria aceitar"
    return versao
