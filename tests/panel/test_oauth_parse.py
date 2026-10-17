"""Ressalva do AppSec (E3): parse_managed_guilds descarta itens com `id` inválido sem quebrar a lista."""

from tests.panel.helpers import require


def item(guild_id, **extra):
    return {"id": guild_id, "name": "Srv", "icon": None, "owner": True, "permissions": "8", **extra}


class TestParseManagedGuilds:
    def test_non_numeric_or_missing_ids_are_dropped_and_valid_ones_kept(self):
        parse = require("panel.oauth").parse_managed_guilds
        raw = [
            item("100"),
            item("12a"),
            item(""),
            item(None),
            item(" 12"),
            item("-5"),
            item("1.5"),
            item("٥٠٠"),
            item(123),
            {"name": "sem id", "permissions": "8", "owner": True},
            item("200"),
        ]
        assert [g.id for g in parse(raw)] == ["100", "200"], "só ids numéricos (str de dígitos ASCII) sobrevivem"

    def test_garbage_items_do_not_break_the_list(self):
        parse = require("panel.oauth").parse_managed_guilds
        raw = [item("100"), None, "texto", 5, [], item("300")]
        assert [g.id for g in parse(raw)] == ["100", "300"]
