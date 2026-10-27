"""Guarda do teste de integração do Mongo: a URI só vale se for ``mongodb://`` e TODOS os hosts da lista de seeds forem locais."""

import re

HOSTS_LOCAIS = {"localhost", "127.0.0.1", "::1"}
ESQUEMA = "mongodb://"


def hosts_da_uri(uri: str) -> list[str]:
    """Os hosts da lista de seeds, sem credenciais, porta nem colchetes do IPv6."""
    autoridade = uri[len(ESQUEMA) :].split("/", 1)[0].split("?", 1)[0].rsplit("@", 1)[-1]
    return [_sem_porta(seed.strip()) for seed in autoridade.split(",")]


def _sem_porta(seed: str) -> str:
    if seed.startswith("["):  # IPv6: [::1]:27017
        return seed[1:].split("]", 1)[0]
    return re.sub(r":\d+$", "", seed)


def uri_so_local(uri: str) -> bool:
    """``mongodb+srv`` e qualquer seed fora de ``HOSTS_LOCAIS`` (o driver usa todos) reprovam."""
    if not uri.startswith(ESQUEMA):
        return False
    return all(host in HOSTS_LOCAIS for host in hosts_da_uri(uri))
