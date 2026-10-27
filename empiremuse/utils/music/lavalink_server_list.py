"""Validação da lista de servidores Lavalink baixada da internet, com fallback para o arquivo do repositório."""

from configparser import ConfigParser, Error as ConfigParserError
from pathlib import Path

from empiremuse.paths import PROJECT_DIR

BUNDLED_SERVER_LIST_PATH = PROJECT_DIR / "data" / "lavalink_servers.ini"

_REQUIRED_KEYS = ("host", "port", "password")


def _is_valid_server_list(content: bytes) -> bool:
    """Indica se `content` é um INI UTF-8 com ao menos 1 seção e `host`/`port`/`password` em todas elas.

    Usa o mesmo parser do consumidor (`ConfigParser()` padrão, com interpolação) e materializa os valores
    de cada seção, para rejeitar aqui o que levantaria erro de interpolação na leitura real.
    """
    try:
        parser = ConfigParser()
        parser.read_string(content.decode("utf-8"))
        sections = {section: dict(parser.items(section)) for section in parser.sections()}
    except UnicodeDecodeError, ConfigParserError:
        return False

    return bool(sections) and all(all(key in values for key in _REQUIRED_KEYS) for values in sections.values())


def validated_server_list(status: int | None, content: bytes | None) -> bytes:
    """Retorna `content` se o download foi válido; caso contrário, os bytes do arquivo bundled.

    Válido: status 200 e conteúdo UTF-8 em formato INI com ao menos 1 seção, todas com `host`, `port` e `password`.
    Entrada ruim (status, bytes ou INI inválidos) nunca levanta exceção, mas pode levantar `OSError` se o
    arquivo do repositório (`data/lavalink_servers.ini`) estiver ausente, o que indica instalação incompleta.
    """
    if status == 200 and content is not None and _is_valid_server_list(content):
        return content
    return BUNDLED_SERVER_LIST_PATH.read_bytes()
