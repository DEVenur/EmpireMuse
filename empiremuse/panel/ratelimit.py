"""Limite de requisições por chave (IP) em janela deslizante, em memória."""

from __future__ import annotations

import time
from collections import deque
from typing import Callable

DEFAULT_LIMIT = 10
DEFAULT_WINDOW_SECONDS = 60
MAX_TRACKED_KEYS = 10_000


class RateLimiter:
    def __init__(
        self,
        limit: int = DEFAULT_LIMIT,
        window: float = DEFAULT_WINDOW_SECONDS,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._limit = limit
        self._window = window
        self._clock = clock
        self._hits: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        """Registra a tentativa e diz se está dentro do limite (tentativas negadas não são contadas)."""
        now = self._clock()
        if len(self._hits) >= MAX_TRACKED_KEYS:
            self._drop_stale(now)
        hits = self._hits.setdefault(key, deque())
        while hits and now - hits[0] >= self._window:
            hits.popleft()
        if len(hits) >= self._limit:
            return False
        hits.append(now)
        return True

    def _drop_stale(self, now: float) -> None:
        for key in [k for k, h in self._hits.items() if not h or now - h[-1] >= self._window]:
            del self._hits[key]
