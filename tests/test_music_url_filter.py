"""Testes do helper is_discord_attachment_url (modules/music.py)."""

import pytest

from empiremuse.cogs.music import is_discord_attachment_url


@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.discordapp.com/attachments/1/2/a.mp3",
        "http://cdn.discordapp.com/attachments/1/2/a.mp3",
        "https://CDN.DISCORDAPP.COM/attachments/1/2/a.mp3",
        "https://cdn.discordapp.com:443/attachments/1/2/a.mp3",
        "https://user:pass@cdn.discordapp.com/attachments/1/2/a.mp3",
        "https://media.discordapp.net/attachments/1/2/a.mp3",
        "https://MEDIA.DISCORDAPP.NET/attachments/1/2/a.mp3",
        "https://cdn.discordapp.com./attachments/1/2/a.mp3",
        "https://cdn.discordapp.com/ephemeral-attachments/1/2/a.mp3",
        "https://media.discordapp.net/ephemeral-attachments/1/2/a.mp3",
    ],
)
def test_returns_true_for_discord_attachment_hosts(url):
    assert is_discord_attachment_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://media.discordapp.net/external/abc/https/example.com/a.mp3",
        "https://cdn.discordapp.com/emojis/123.png",
        "https://evil.example/x?u=cdn.discordapp.com/attachments/1/2/a.mp3",
        "https://evil.example/cdn.discordapp.com/attachments/1/2/a.mp3",
        "",
        "cdn.discordapp.com/attachments/1/2/a.mp3",
        "https://[x",
        "https://[::1",
    ],
)
def test_returns_false_for_non_attachment_urls_without_raising(url):
    assert is_discord_attachment_url(url) is False
