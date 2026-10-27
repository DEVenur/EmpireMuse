"""Cliente do proxy de atualização: o único caminho do bot até o auxiliar Docker, por um socket Unix.

O bot nunca fala com o ``docker.sock``. O proxy só aceita cinco operações sobre um container auxiliar de nome fixo
(``empiremuse-updater``); este cliente é o lado do bot dessas cinco. Mensagens de erro são genéricas e nunca trazem o
caminho do socket nem o corpo da resposta.
"""

from __future__ import annotations

import dataclasses
import json
from typing import Any

import aiohttp

from empiremuse.updater.git_flow import UpdateError

TIMEOUT = 15  # segundos, por chamada
HELPER_NAME = "empiremuse-updater"
MIN_TAIL = 1
MAX_TAIL = 200
MAX_RESPONSE_BYTES = 256 * 1024

MSG_IN_PROGRESS = "Já há uma atualização em andamento."
MSG_UNREACHABLE = "proxy de atualização inacessível"
MSG_UNEXPECTED = "Resposta inesperada do proxy de atualização."


@dataclasses.dataclass(frozen=True)
class HelperState:
    """Subconjunto do ``State`` do container auxiliar que o bot precisa."""

    status: str
    running: bool
    exit_code: int
    started_at: str
    finished_at: str


class ProxyClient:
    """Cliente das cinco operações do proxy sobre o auxiliar. Cada chamada abre e fecha a própria conexão."""

    def __init__(self, socket_path: str) -> None:
        self._socket_path = socket_path

    async def _request(
        self, method: str, path: str, *, query: dict[str, str] | None = None, body: Any = None
    ) -> tuple[int, bytes]:
        timeout = aiohttp.ClientTimeout(total=TIMEOUT)
        connector = aiohttp.UnixConnector(path=self._socket_path)
        try:
            async with aiohttp.ClientSession(connector=connector, timeout=timeout) as session:
                async with session.request(method, f"http://proxy{path}", params=query, json=body) as response:
                    # ``read(n)`` devolve só o que já chegou: lê até o EOF, com o teto valendo durante a leitura.
                    received = bytearray()
                    async for chunk in response.content.iter_chunked(64 * 1024):
                        received += chunk
                        if len(received) > MAX_RESPONSE_BYTES:
                            raise UpdateError(MSG_UNEXPECTED)
                    return response.status, bytes(received)
        except (aiohttp.ClientError, TimeoutError, OSError) as error:
            raise UpdateError(MSG_UNREACHABLE) from error

    @staticmethod
    def _json(data: bytes) -> object:
        try:
            return json.loads(data.decode("utf-8"))
        except (ValueError, RecursionError) as error:
            raise UpdateError(MSG_UNEXPECTED) from error

    async def create_helper(self, target: str) -> None:
        """Cria o auxiliar para ``X.Y.Z@sha256:<64hex>``. Se ele já existe, há uma atualização em andamento."""
        status, _ = await self._request(
            "POST", "/containers/create", query={"name": HELPER_NAME}, body={"Cmd": [target]}
        )
        if status == 409:
            raise UpdateError(MSG_IN_PROGRESS)
        if status != 201:
            raise UpdateError(MSG_UNEXPECTED)

    async def start_helper(self) -> None:
        status, _ = await self._request("POST", f"/containers/{HELPER_NAME}/start")
        if status == 409:
            raise UpdateError(MSG_IN_PROGRESS)
        if status != 204:
            raise UpdateError(MSG_UNEXPECTED)

    async def helper_state(self) -> HelperState | None:
        """Estado do auxiliar, ou ``None`` se ele não existe."""
        status, data = await self._request("GET", f"/containers/{HELPER_NAME}/json")
        if status == 404:
            return None
        if status != 200:
            raise UpdateError(MSG_UNEXPECTED)
        payload = self._json(data)
        state = payload.get("State") if isinstance(payload, dict) else None
        if not isinstance(state, dict):
            raise UpdateError(MSG_UNEXPECTED)
        text = (state.get("Status"), state.get("StartedAt"), state.get("FinishedAt"))
        running, exit_code = state.get("Running"), state.get("ExitCode")
        if not all(isinstance(value, str) for value in text):
            raise UpdateError(MSG_UNEXPECTED)
        if not isinstance(running, bool) or not isinstance(exit_code, int) or isinstance(exit_code, bool):
            raise UpdateError(MSG_UNEXPECTED)
        return HelperState(text[0], running, exit_code, text[1], text[2])

    async def helper_logs(self, tail: int = 20) -> list[str]:
        """Até ``tail`` linhas (1..200) do log do auxiliar, já filtradas pelo proxy."""
        tail = max(MIN_TAIL, min(MAX_TAIL, tail))
        query = {"stdout": "1", "stderr": "1", "tail": str(tail)}
        status, data = await self._request("GET", f"/containers/{HELPER_NAME}/logs", query=query)
        if status != 200:
            raise UpdateError(MSG_UNEXPECTED)
        payload = self._json(data)
        lines = payload.get("lines") if isinstance(payload, dict) else None
        if not isinstance(lines, list) or not all(isinstance(line, str) for line in lines):
            raise UpdateError(MSG_UNEXPECTED)
        return lines[:tail]

    async def remove_helper(self) -> None:
        """Remove o auxiliar parado. Já ausente também vale; em execução (409) ou qualquer outra coisa é erro."""
        status, _ = await self._request("DELETE", f"/containers/{HELPER_NAME}")
        if status == 409:
            raise UpdateError(MSG_IN_PROGRESS)
        if status not in (204, 404):
            raise UpdateError(MSG_UNEXPECTED)
