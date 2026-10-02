"""Who's online, for people to read: the roll call the bridge posts in Discord, and the line the
game gets when someone logs in. Plain functions, no Discord or database (tests/test_roster.py)."""

import re

JOBS = ["", "WAR", "MNK", "WHM", "BLM", "RDM", "THF", "PLD", "DRK", "BST", "BRD", "RNG", "SAM", "NIN",
        "DRG", "SMN", "BLU", "COR", "PUP", "DNC", "SCH", "GEO", "RUN"]

# chars.nation: 0 San d'Oria, 1 Bastok, 2 Windurst
NATIONS = ["San d'Oria", "Bastok", "Windurst"]
NATION_EMOJI = ["🏰", "⚙️", "⭐"]

# chars.settings is the client's SAVE_CONF (src/common/mmo.h): bit 2 is /anon.
ANON = 0x04

# Zone script names lose their apostrophes ("RuLude_Gardens", "Ifrits_Cauldron"): put them back.
_POSSESSIVE = {
    "Balgas": "Balga's", "Behemoths": "Behemoth's", "Carpenters": "Carpenters'", "Crawlers": "Crawlers'",
    "Delkfutts": "Delkfutt's", "Dragons": "Dragon's", "Ghoyus": "Ghoyu's", "Ifrits": "Ifrit's",
    "Ordelles": "Ordelle's", "Ranperres": "Ranperre's", "Sealions": "Sealion's",
}


def zone_name(script_name):
    """'Southern_San_dOria' -> "Southern San d'Oria", 'RuLude_Gardens' -> "Ru'Lude Gardens"."""
    if not script_name:
        return "somewhere"
    s = re.sub(r"(?<=[a-z])(?=[A-Z])", "'", script_name.replace("_", " "))
    return " ".join(_POSSESSIVE.get(w, w) for w in s.split(" "))


def jobs(mjob, mlvl, sjob, slvl):
    """'RDM75/WHM37', 'WAR10', or '' when unknown."""
    main = JOBS[mjob] if mjob and 0 < mjob < len(JOBS) else ""
    if not main:
        return ""
    sub = JOBS[sjob] if sjob and 0 < sjob < len(JOBS) else ""
    return f"{main}{mlvl}" + (f"/{sub}{slvl}" if sub and slvl else "")


def roll_call(players, nation_emoji=None, escape=lambda s: s):
    """The Discord post for who's online, or None when no one is. `players` are dicts with name,
    nation, zone (script name), settings, mjob, mlvl, sjob, slvl. /anon players show their name and
    nation only, as the game's own search does."""
    if not players:
        return None
    emoji = list(nation_emoji or NATION_EMOJI)
    lines = []
    for p in sorted(players, key=lambda p: p["name"].lower()):
        n = p.get("nation")
        mark = emoji[n] if isinstance(n, int) and 0 <= n < len(emoji) else "•"
        line = f"{mark} **{escape(p['name'])}**"
        if not (p.get("settings") or 0) & ANON:
            j = jobs(p.get("mjob"), p.get("mlvl"), p.get("sjob"), p.get("slvl"))
            line += (f" ({j})" if j else "") + f" · {zone_name(p.get('zone'))}"
        lines.append(line)
    head = f"**Online now ({len(players)}):**" if len(players) != 1 else "**Online now:**"
    return head + "\n" + "\n".join(lines)


def login_line(template, name, nation=None):
    """The game's line when someone logs in: the template with {name} and {nation}."""
    nation_name = NATIONS[nation] if isinstance(nation, int) and 0 <= nation < len(NATIONS) else ""
    return template.format(name=name, nation=nation_name).strip()
