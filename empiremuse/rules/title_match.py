"""Casamento de títulos de faixas: uma regra composta única para busca (Spotify, Deezer, Lavalink) e scrobble (Last.fm).

O medidor de similaridade (``rapidfuzz.fuzz.token_set_ratio``) é injetado por quem chama: este pacote só usa a
biblioteca padrão. Análise e amostra de pares em ``.local/fuzz-check-title.md``.
"""

from __future__ import annotations

from typing import Callable

TITLE_ONLY_MIN_SCORE = 60  # só o título, sem o artista: barra "mesmo artista, outra música"

Scorer = Callable[[str, str], float]


def title_matches(
    scorer: Scorer,
    candidate_full: str,
    wanted_full: str,
    candidate_title: str,
    wanted_title: str,
    threshold: float,
) -> bool:
    """O texto completo (``artista - título``) passa do limiar do ponto E o título sozinho passa de ``TITLE_ONLY_MIN_SCORE``.

    Só o texto completo casa "metallica - one" com "metallica - the unforgiven ii" (o artista pesa quase tudo); só o
    título deixaria passar outro artista com o mesmo título. As duas juntas aceitam clipe do YouTube com sufixo e
    faixa "(feat. ...)" ou "Remastered", e recusam outra música do mesmo artista.
    """
    return (
        scorer(candidate_full, wanted_full) >= threshold
        and scorer(candidate_title, wanted_title) >= TITLE_ONLY_MIN_SCORE
    )
