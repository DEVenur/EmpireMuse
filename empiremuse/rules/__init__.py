"""Regras de negócio compartilhadas entre os comandos do Discord e o painel web.

Só biblioteca padrão (e os próprios módulos deste pacote): sem ``disnake``, ``tornado`` nem outro módulo do projeto.
O bot (``cogs/`` e ``utils/``) e o painel (``panel/``) importam daqui; este pacote não importa nenhum dos dois.
"""
