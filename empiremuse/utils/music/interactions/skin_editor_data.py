# -*- coding: utf-8 -*-
from __future__ import annotations

SKIN_NAME_REFUSED = (
    "**O nome da skin precisa ter de 1 a 64 caracteres, sem pontos, cifrão nem caracteres invisíveis ou de controle.**"
)
SKIN_REFUSED = (
    "**Não foi possível salvar a skin: algum campo passa dos limites ou tem conteúdo inválido. "
    "Revise o texto, os embeds e os campos e tente de novo.**"
)
SKIN_LIMIT_REFUSED = (
    "**Não foi possível salvar: cada modo comporta no máximo 25 skins. Exclua uma ou salve por cima de uma existente.**"
)


base_skin = {
    "queue_max_entries": 7,
    "queue_format": "`{track.number}) [{track.duration}]` [`{track.title_42}`]({track.url})",
    "embeds": [
        {"title": "Próximas músicas:", "description": "{queue_format}", "color": "{guild.color}"},
        {
            "description": "**Tocando agora:\n[{track.title}]({track.url})**\n\n**Duração:** `{track.duration}`\n**Pedido por:** {requester.mention}\n**Uploader**: `{track.author}`\n**Playlist de origem:** [`{playlist.name}`]({playlist.url})\n\n{player.log.emoji} **Última ação:** {player.log.text}",
            "image": {"url": "{track.thumb}"},
            "color": "{guild.color}",
            "footer": {"text": "Músicas na lista: {player.queue.size}"},
        },
    ],
}
