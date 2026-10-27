"""``target_commit`` do pendente git (D10): só entra nos fakes onde o campo existe, para as fixtures valerem antes e depois da mudança de esquema."""

import dataclasses

from empiremuse.updater.state import PendingUpdate

ALVO_GIT = "b" * 40


def alvo_git(sha: str = ALVO_GIT) -> dict[str, str]:
    campos = {campo.name for campo in dataclasses.fields(PendingUpdate)}
    return {"target_commit": sha} if "target_commit" in campos else {}
