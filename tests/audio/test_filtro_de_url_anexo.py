"""Testes do helper is_discord_attachment_url (modules/music.py)."""

import pytest

from empiremuse.cogs.music import is_discord_attachment_url


@pytest.mark.smoke
@pytest.mark.parametrize(
    "url",
    [
        "https://cdn.discordapp.com/attachments/1/2/a.mp3",
        "https://user:pass@cdn.discordapp.com/attachments/1/2/a.mp3",
        "https://media.discordapp.net/ephemeral-attachments/1/2/a.mp3",
    ],
)
def test_returns_true_for_discord_attachment_hosts(url):
    assert is_discord_attachment_url(url) is True


@pytest.mark.parametrize(
    "url",
    [
        "https://media.discordapp.net/external/abc/https/example.com/a.mp3",
        "https://[::1",
    ],
)
def test_returns_false_for_non_attachment_urls_without_raising(url):
    assert is_discord_attachment_url(url) is False
