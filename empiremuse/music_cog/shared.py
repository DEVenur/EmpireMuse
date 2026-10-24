# -*- coding: utf-8 -*-
"""Constantes de corpo de classe usadas por mais de um mixin de ``Music`` (ver ``empiremuse/cogs/music.py``)."""

from disnake.ext import commands

from empiremuse.utils.others import CommandArgparse

EMOJI = "🎶"
NAME = "Música"
DESC_PREFIX = f"[{EMOJI} {NAME}] | "

remove_mc = commands.MaxConcurrency(1, per=commands.BucketType.guild, wait=False)
queue_manipulation_cd = commands.CooldownMapping.from_cooldown(2, 15, commands.BucketType.guild)
case_sensitive_args = CommandArgparse()
case_sensitive_args.add_argument(
    "-casesensitive",
    "-cs",
    action="store_true",
    help="Buscar por músicas com a frase exata no nome da música ao invés de buscar palavra por palavra.",
)
