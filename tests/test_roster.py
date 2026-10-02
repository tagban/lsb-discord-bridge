"""The roll call and login lines (bot/roster.py): python3 -m pytest tests"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "bot"))
import roster  # noqa: E402


def test_zone_names_get_their_apostrophes_back():
    assert roster.zone_name("Southern_San_dOria") == "Southern San d'Oria"
    assert roster.zone_name("RuLude_Gardens") == "Ru'Lude Gardens"
    assert roster.zone_name("Ifrits_Cauldron") == "Ifrit's Cauldron"
    assert roster.zone_name("Crawlers_Nest_[S]") == "Crawlers' Nest [S]"
    assert roster.zone_name("Dynamis-San_dOria_[D]") == "Dynamis-San d'Oria [D]"
    assert roster.zone_name("Grand_Palace_of_HuXzoi") == "Grand Palace of Hu'Xzoi"
    assert roster.zone_name("Windurst_Waters") == "Windurst Waters"
    assert roster.zone_name(None) == "somewhere"


def test_roll_call():
    assert roster.roll_call([]) is None
    players = [
        {"name": "Tagban", "nation": 2, "zone": "Windurst_Waters", "settings": 0, "mjob": 5, "mlvl": 75, "sjob": 3, "slvl": 37},
        {"name": "aria", "nation": 0, "zone": "Southern_San_dOria", "settings": 0, "mjob": 1, "mlvl": 10, "sjob": 0, "slvl": 0},
        {"name": "Ghost", "nation": 1, "zone": "Port_Bastok", "settings": roster.ANON, "mjob": 6, "mlvl": 50, "sjob": 13, "slvl": 25},
    ]
    assert roster.roll_call(players) == (
        "**Online now (3):**\n"
        "🏰 **aria** (WAR10) · Southern San d'Oria\n"
        "⚙️ **Ghost**\n"                                   # /anon: name and nation only
        "⭐ **Tagban** (RDM75/WHM37) · Windurst Waters"
    )
    one = roster.roll_call(players[:1], ["<:sandy:1>", "<:bastok:2>", "<:windy:3>"])
    assert one == "**Online now:**\n<:windy:3> **Tagban** (RDM75/WHM37) · Windurst Waters"


def test_login_line():
    assert roster.login_line("{name} has logged in.", "Tagban", 2) == "Tagban has logged in."
    assert roster.login_line("{name} of {nation} has arrived!", "Tagban", 2) == "Tagban of Windurst has arrived!"
