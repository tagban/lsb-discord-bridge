"""The Discord bridge's bot, for a LandSandBoat server: game chat into Discord channels (as its
speakers, with a badge for their job), Discord into the game's chat, a roll call of who's online
(or each login and logout), logins announced in the game, and the server's state as the bot's nickname. What goes where is config.toml (see config.example.toml).

    python3 bridge.py [config.toml]

It reads the lines the discord_bridge module records (the discord_bridge_chat table), and speaks to
the game through the world server's IPC port, as LandSandBoat's tools/announce.py does; the IPC
message numbers are read from the server's own tools/generate_ipc_stubs.py, so they follow its updates.
"""

import ast
import asyncio
import os
import re
import socket
import struct
import subprocess
import sys
import time
import tomllib
import unicodedata

import discord
import mysql.connector
import zmq
from discord import app_commands

import roster

sys.stdout.reconfigure(line_buffering=True)  # to a service's log as printed

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = sys.argv[1] if len(sys.argv) > 1 else os.path.join(HERE, "config.toml")
with open(CONFIG_PATH, "rb") as f:
    CONFIG = tomllib.load(f)

SERVER = CONFIG.get("server", {})
LSB = SERVER.get("lsb_path", "")


def load_env_file(path):
    """KEY=value lines (a .env file, as Docker Compose reads them) into the environment, where not set."""
    if not path or not os.path.exists(path):
        return
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            value = value.strip().strip('"').strip("'")
            os.environ.setdefault(key.strip(), value)


load_env_file(SERVER.get("env_file", ""))


def secret(section, name, default=""):
    """A setting from config.toml, or from the environment variable its <name>_env names."""
    table = CONFIG.get(section, {})
    if table.get(f"{name}_env"):
        return os.environ.get(table[f"{name}_env"], default)
    return table.get(name, default)


TOKEN = secret("discord", "token")
GUILD_ID = int(CONFIG.get("discord", {}).get("guild_id", 0))
DB = {
    "host": CONFIG.get("database", {}).get("host", "127.0.0.1"),
    "port": int(CONFIG.get("database", {}).get("port", 3306)),
    "user": secret("database", "user", "xiadmin"),
    "password": secret("database", "password"),
    "database": secret("database", "database", "xidb"),
    "connection_timeout": 5,
}
world_host, _, world_port = SERVER.get("world", "127.0.0.1:54003").rpartition(":")
WORLD = (world_host or "127.0.0.1", int(world_port or 54003))
STATUS = CONFIG.get("status", {})
BRIDGES = CONFIG.get("bridge", [])
KEEP_DAYS = int(CONFIG.get("chat", {}).get("keep_days", 7))
GAME = CONFIG.get("game", {})
BADGES = os.path.join(HERE, "badges")

JOBS = roster.JOBS
KIND_LABEL = {"SAY": "Say", "SHOUT": "Shout", "YELL": "Yell", "LINKSHELL": "LS", "UNITY": "Unity",
              "ASSIST_E": "Assist", "ASSIST_J": "Assist (J)"}

# the game's chat kinds (src/map/enums/chat_message_type.h)
MESSAGE = {"say": 0, "shout": 1, "system": 6, "yell": 26, "unity": 33, "assist_j": 34, "assist_e": 35}

NO_PINGS = discord.AllowedMentions.none()


# --- the database ------------------------------------------------------------------------------------

def query(sql, args=()):
    conn = mysql.connector.connect(**DB)
    try:
        cur = conn.cursor()
        cur.execute(sql, args)
        rows = cur.fetchall() if cur.with_rows else []
        conn.commit()
        return rows
    finally:
        conn.close()


def ensure_table():
    with open(os.path.join(HERE, "..", "module", "discord_bridge", "sql", "discord_bridge_chat.sql")) as f:
        sql = "\n".join(line for line in f if not line.lstrip().startswith("--"))
    query(sql)


def online_characters():
    rows = query("SELECT c.charname FROM chars c INNER JOIN accounts_sessions s ON c.charid = s.charid ORDER BY c.charname")
    return [r[0] for r in rows]


def online_players():
    """Everyone online, with what the roll call shows (see roster.roll_call)."""
    rows = query("SELECT c.charname, c.nation, z.name, c.settings, cs.mjob, cs.mlvl, cs.sjob, cs.slvl "
                 "FROM accounts_sessions s INNER JOIN chars c ON c.charid = s.charid "
                 "LEFT JOIN char_stats cs ON cs.charid = c.charid "
                 "LEFT JOIN zone_settings z ON z.zoneid = c.pos_zone ORDER BY c.charname")
    keys = ("name", "nation", "zone", "settings", "mjob", "mlvl", "sjob", "slvl")
    return [dict(zip(keys, r)) for r in rows]


def game_version():
    """CLIENT_VER in the server's login settings (its own over LandSandBoat's defaults)."""
    for path in ("settings/login.lua", "settings/default/login.lua"):
        try:
            with open(os.path.join(LSB, path)) as f:
                m = re.search(r"^\s*CLIENT_VER\s*=\s*['\"]([^'\"]+)['\"]", f.read(), re.M)
                if m:
                    return m.group(1)
        except OSError:
            pass
    return ""


# --- the game's IPC ----------------------------------------------------------------------------------

def ipc_numbers():
    """The world server's message numbers: the order of IPC_STRUCT_NAMES in the server's own
    tools/generate_ipc_stubs.py, from 1 (as its generator numbers them)."""
    path = os.path.join(LSB, "tools", "generate_ipc_stubs.py")
    with open(path) as f:
        tree = ast.parse(f.read())
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(getattr(t, "id", "") == "IPC_STRUCT_NAMES" for t in node.targets):
            return {name: i for i, name in enumerate(ast.literal_eval(node.value), 1)}
    raise RuntimeError(f"no IPC_STRUCT_NAMES in {path}")


IPC = {}


def text(s):
    b = s.encode("utf-8")
    return struct.pack("<I", len(b)) + b


# LandSandBoat's IPC is alpaca's fixed-length encoding (src/common/ipc.h): each message one byte, its
# number, then the struct's fields in order, integers little-endian at their own size, strings as a
# uint32 length and their bytes (src/common/ipc_structs.h).

def server_message(sender, msg, kind):
    return bytes([IPC["ChatMessageServerMessage"]]) + struct.pack("<I", 0) + text(sender) + text(msg) + struct.pack("<HBB?", 0, 0, kind, False)


def linkshell_message(linkshell_id, sender, msg):
    return bytes([IPC["ChatMessageLinkshell"]]) + struct.pack("<II", linkshell_id, 0) + text(sender) + text(msg) + struct.pack("<HB", 0, 0)


def unity_message(leader, sender, msg):
    return bytes([IPC["ChatMessageUnity"]]) + struct.pack("<II", leader, 0) + text(sender) + text(msg) + struct.pack("<HBB", 0, 0, MESSAGE["unity"])


def assist_message(sender, msg, kind):
    return bytes([IPC["ChatMessageAssist"]]) + struct.pack("<I", 0) + text(sender) + text(msg) + struct.pack("<BBBB", 0, 1, 0, kind)


_world = None


def to_world(message):
    global _world
    if _world is None:
        _world = zmq.Context.instance().socket(zmq.DEALER)
        (ip,) = struct.unpack("!I", socket.inet_aton(WORLD[0]))
        _world.setsockopt(zmq.ROUTING_ID, struct.pack("!Q", ip | (WORLD[1] << 32)))
        _world.setsockopt(zmq.LINGER, 0)
        _world.connect(f"tcp://{WORLD[0]}:{WORLD[1]}")
    _world.send(message, zmq.NOBLOCK)


def announce_in_game(msg):
    """A server message to every zone (as tools/announce.py sends)."""
    to_world(server_message("", msg, MESSAGE["system"]))


def say_in_game(target, sender, msg):
    """A Discord line into the game, as the bridge's to_game says: say, shout, yell or system (every
    zone), linkshell:<name>, unity (every unity) or unity:<leader>, assist_e or assist_j."""
    target = target.strip()
    low = target.lower()
    if low in ("say", "shout", "yell", "system"):
        to_world(server_message(sender if low != "system" else "", msg if low != "system" else f"{sender}: {msg}", MESSAGE[low]))
    elif low.startswith("linkshell:"):
        name = target.split(":", 1)[1]
        rows = query("SELECT linkshellid FROM linkshells WHERE name = %s", (name,))
        if not rows:
            raise RuntimeError(f"no linkshell named {name}")
        to_world(linkshell_message(rows[0][0], sender, msg))
    elif low == "unity" or low.startswith("unity:"):
        leaders = [int(low.split(":", 1)[1])] if ":" in low else [r[0] for r in query("SELECT leader FROM unity_system")]
        for leader in leaders:
            to_world(unity_message(leader, sender, msg))
    elif low in ("assist_e", "assist_j"):
        to_world(assist_message(sender, msg, MESSAGE[low]))
    else:
        raise RuntimeError(f"unknown to_game target {target!r}")


# --- text between them -------------------------------------------------------------------------------

def from_game(raw):
    """A line as the game stores it, for Discord: auto-translate phrases (0xFD, 4 bytes, 0xFD) as
    [AT], its color codes dropped, the rest as plain text."""
    if isinstance(raw, str):
        raw = raw.encode("latin-1", "replace")
    out, i = [], 0
    while i < len(raw):
        c = raw[i]
        if c == 0xFD and i + 5 < len(raw) and raw[i + 5] == 0xFD:
            out.append("[AT]")
            i += 6
        elif c in (0x1E, 0x1F, 0x7F):
            i += 2
        elif 0x20 <= c < 0x7F:
            out.append(chr(c))
            i += 1
        else:
            i += 1
    return "".join(out).strip()


def for_game(s, limit):
    """Discord's text for the game's font: plain letters only (no emoji or accents), one line."""
    s = re.sub(r"<a?:(\w+):\d+>", r":\1:", s)
    s = unicodedata.normalize("NFKD", s)  # accented letters to theirs without the accent (é to e)
    s = "".join(ch if 0x20 <= ord(ch) < 0x7F else ("" if unicodedata.combining(ch) else " ") for ch in s.replace("\n", " "))
    return re.sub(r"\s+", " ", s).strip()[:limit]


# --- Discord ------------------------------------------------------------------------------------------

intents = discord.Intents.default()
READS = os.environ.get("LSB_BRIDGE_READS_MESSAGES", "1") == "1" and any(b.get("to_game") for b in BRIDGES)
intents.message_content = READS
client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)
GUILD = discord.Object(id=GUILD_ID) if GUILD_ID else None


def matches(bridge, kind, grp, leader):
    """Whether a game line is for a bridge: its from_game names SAY, SHOUT, YELL, ASSIST_E,
    ASSIST_J, LINKSHELL (every linkshell) or LINKSHELL:<name>, UNITY or UNITY:<leader>."""
    for want in bridge.get("from_game", []):
        w = want.upper()
        if w == kind:
            return True
        if kind == "LINKSHELL" and want.lower().startswith("linkshell:") and want.split(":", 1)[1] == grp:
            return True
        if kind == "UNITY" and w.startswith("UNITY:") and w.split(":", 1)[1] == str(leader):
            return True
    return False


class Poster:
    """A bridge's posts as game characters: through a webhook, its picture the speaker's job badge.
    The webhook is the one whose URL is in the bridge's webhook_env, or ones the bot makes itself in
    the channel (it needs Manage Webhooks there); failing both, the bot posts the lines itself."""

    KEPT = 10  # of the bot's own webhooks per channel (a channel may have 15)

    def __init__(self, bridge):
        self.url = os.environ.get(bridge.get("webhook_env", ""), "") if bridge.get("webhook_env") else ""
        self.badges = bridge.get("badges", True)
        self.given = None
        self.given_job = None
        self.own = {}

    def badge(self, job):
        path = os.path.join(BADGES, f"{job}.png")
        return path if os.path.exists(path) else os.path.join(BADGES, "XI.png")

    async def hook(self, channel, job):
        with open(self.badge(job), "rb") as f:
            picture = f.read()
        if self.url:
            if self.given is None:
                self.given = discord.Webhook.from_url(self.url, client=client)
            if job != self.given_job:
                self.given = await self.given.edit(avatar=picture, prefer_auth=False)
                self.given_job = job
            return self.given
        if not self.own:
            for h in await channel.webhooks():
                if h.user == client.user and h.name.startswith("Bridge "):
                    self.own[h.name[7:]] = h
        h = self.own.pop(job, None)
        if h is None:
            if len(self.own) >= self.KEPT:
                h = await self.own.pop(next(iter(self.own))).edit(name=f"Bridge {job}", avatar=picture)
            else:
                h = await channel.create_webhook(name=f"Bridge {job}", avatar=picture)
        self.own[job] = h
        return h

    async def post(self, channel, speaker, kind, grp, mjob, mlvl, sjob, slvl, line):
        label = KIND_LABEL.get(kind, kind) + (f" {grp}" if grp else "")
        body = f"**[{label}]** {discord.utils.escape_markdown(line)}"
        main = JOBS[mjob] if 0 < mjob < len(JOBS) else ""
        sub = JOBS[sjob] if 0 < sjob < len(JOBS) else ""
        jobs = f" ({main}{mlvl}{f'/{sub}{slvl}' if sub else ''})" if main else ""
        if self.badges:
            try:
                h = await self.hook(channel, main or "XI")
                await h.send(body, username=f"{speaker}{jobs}"[:80], allowed_mentions=NO_PINGS)
                return
            except (discord.Forbidden, discord.HTTPException) as e:
                print(f"Webhook ({channel.id}): {e}; posting as the bot")
        await channel.send(f"**[{label}] {discord.utils.escape_markdown(speaker)}{jobs}:** {discord.utils.escape_markdown(line)}",
                           allowed_mentions=NO_PINGS)


POSTERS = [Poster(b) for b in BRIDGES]


@client.event
async def on_message(msg: discord.Message):
    if msg.author.bot or msg.webhook_id:
        return
    for bridge in BRIDGES:
        if int(bridge.get("channel", 0)) != msg.channel.id or not bridge.get("to_game"):
            continue
        line = for_game(msg.clean_content, int(bridge.get("max_length", 110)))
        if not line or line[0] in "!/":
            return  # commands, to Discord bots or mistyped: not for the game
        name = re.sub(r"[^A-Za-z0-9]", "", msg.author.display_name)[:12] or "Discord"
        try:
            await asyncio.to_thread(say_in_game, bridge["to_game"], name + bridge.get("name_suffix", "[D]"), line)
        except Exception as e:
            print(f"To the game ({bridge['to_game']}): {e}")
            await msg.add_reaction("❌")


async def chat_loop():
    """Every 2 seconds, the lines recorded since the last look; every 10, who logged in or out.
    Starting, it only notes where things are. Through a database hiccup it keeps its place,
    so what was said meanwhile still reaches Discord once the database answers again."""
    last = None
    online = None
    tick = 0
    while True:
        try:
            if last is None:
                await asyncio.to_thread(ensure_table)
                last = (await asyncio.to_thread(query, "SELECT COALESCE(MAX(id), 0) FROM discord_bridge_chat"))[0][0]
            else:
                rows = await asyncio.to_thread(
                    query,
                    "SELECT id, speaker, kind, grp, unity_leader, mjob, mlvl, sjob, slvl, message FROM discord_bridge_chat "
                    "WHERE id > %s ORDER BY id LIMIT 50",
                    (last,),
                )
                if not rows and tick % 30 == 0:
                    # The table was emptied or recreated (a reinstall): start from where it is now.
                    newest = (await asyncio.to_thread(query, "SELECT COALESCE(MAX(id), 0) FROM discord_bridge_chat"))[0][0]
                    if newest < last:
                        last = newest
                for rid, speaker, kind, grp, leader, mjob, mlvl, sjob, slvl, message in rows:
                    last = max(last, rid)
                    line = from_game(message)
                    if not line or line[0] in "!/":
                        continue
                    for bridge, poster in zip(BRIDGES, POSTERS):
                        channel = client.get_channel(int(bridge.get("channel", 0)))
                        if channel and matches(bridge, kind, grp, leader):
                            await poster.post(channel, speaker, kind, grp, mjob, mlvl, sjob, slvl, line)

            if tick % 5 == 0 and (any(b.get("logins") for b in BRIDGES) or GAME.get("announce_logins")):
                players = await asyncio.to_thread(online_players)
                now = {p["name"] for p in players}
                if online is not None:
                    came = sorted(now - online)
                    for bridge in BRIDGES:
                        channel = client.get_channel(int(bridge.get("channel", 0)))
                        if not (channel and bridge.get("logins")):
                            continue
                        for name in came:
                            await channel.send(f"\U0001F7E2 **{discord.utils.escape_markdown(name)}** has logged in.", allowed_mentions=NO_PINGS)
                        for name in sorted(online - now):
                            await channel.send(f"⚪ **{discord.utils.escape_markdown(name)}** has logged out.", allowed_mentions=NO_PINGS)
                    if GAME.get("announce_logins") and came:
                        nations = {p["name"]: p["nation"] for p in players}
                        for name in came:
                            try:
                                await asyncio.to_thread(announce_in_game, roster.login_line(
                                    GAME.get("login_message", "{name} has logged in."), name, nations.get(name)))
                            except Exception as e:
                                print(f"Login announcement: {e}")
                online = now
            await roll_calls()
            if tick % 43200 == 0:  # daily: lines older than keep_days
                await asyncio.to_thread(query, "DELETE FROM discord_bridge_chat WHERE at < NOW() - INTERVAL %s DAY", (KEEP_DAYS,))
        except Exception as e:
            print(f"Chat: {e}")
            online = None  # don't announce everyone as logging in when it's back
        tick += 1
        await asyncio.sleep(2)


def server_emoji(names):
    """The Discord server's own emoji written by name (":sand:") as Discord needs them
    ("<:sand:1234...>"); anything else (plain emoji, or already in that form) as it is."""
    if not names:
        return names
    guild = client.get_guild(GUILD_ID)
    found = {e.name: str(e) for e in guild.emojis} if guild else {}
    return [found.get(n[1:-1], n) if re.fullmatch(r":\w+:", n or "") else n for n in names]


_roll_slots = {}


async def roll_calls():
    """Each bridge with roll_call = N posts who's online every N minutes, on the clock (:00 and
    :30 for 30), and only when someone is. A restart doesn't post one early."""
    due = []
    for i, bridge in enumerate(BRIDGES):
        minutes = int(bridge.get("roll_call", 0) or 0)
        if minutes <= 0:
            continue
        slot = int(time.time() // (minutes * 60))
        if _roll_slots.setdefault(i, slot) != slot:
            _roll_slots[i] = slot
            due.append(bridge)
    if not due:
        return
    players = await asyncio.to_thread(online_players)
    for bridge in due:
        text = roster.roll_call(players, server_emoji(bridge.get("nation_emoji")), discord.utils.escape_markdown)
        channel = client.get_channel(int(bridge.get("channel", 0)))
        if text and channel:
            await channel.send(text[:2000], allowed_mentions=NO_PINGS)


def server_up():
    """Up: every service status.needed names runs (Docker Compose's status.compose_file), or, with
    no compose file, the database answering."""
    compose = STATUS.get("compose_file", "")
    if compose:
        out = subprocess.run(["docker", "compose", "-f", compose, "ps", "--services", "--filter", "status=running"],
                             capture_output=True, text=True, timeout=10).stdout
        running = {s.strip() for s in out.splitlines() if s.strip()}
        return set(STATUS.get("needed", ["database", "connect", "search", "world", "map"])) <= running
    try:
        query("SELECT 1")
        return True
    except Exception:
        return False


async def status_loop():
    last_nick = last_status = None
    while True:
        try:
            up = await asyncio.to_thread(server_up)
            count = 0
            if up:
                try:
                    count = len(await asyncio.to_thread(online_characters))
                except Exception as e:
                    print(f"Player count: {e}")
            nick = (STATUS.get("nickname_up", "Up - {online} Online") if up else STATUS.get("nickname_down", "Down")).format(online=count)
            guild = client.get_guild(GUILD_ID)
            if guild and guild.me and nick != last_nick:
                await guild.me.edit(nick=nick[:32])
                last_nick = nick
            version = game_version() if STATUS.get("show_game_version", True) else ""
            status = STATUS.get("activity", "Game version {version}" if version else "").format(version=version)
            if status != last_status:
                await client.change_presence(activity=discord.CustomActivity(name=status) if status else None)
                last_status = status
        except Exception as e:
            print(f"Status: {e}")
        await asyncio.sleep(30)


@tree.command(name="online", description="Who is online in the game", guild=GUILD)
async def online(interaction: discord.Interaction):
    try:
        players = await asyncio.to_thread(online_players)
        await interaction.response.send_message(
            (roster.roll_call(players, server_emoji(next((b.get("nation_emoji") for b in BRIDGES if b.get("nation_emoji")), None)),
                              discord.utils.escape_markdown) or "No one is online right now.")[:2000],
            allowed_mentions=NO_PINGS)
    except Exception:
        await interaction.response.send_message("The server's database is not answering (it may be down).")


_started = False


@client.event
async def on_ready():
    """Discord calls this after every fresh session, not just the first: the loops and
    the command sync happen once, or each reconnect would add another copy of each loop
    (and every game line would be posted twice, three times, ...)."""
    global _started
    print(f"Bridge bot online as {client.user}; {len(BRIDGES)} channel(s); reading Discord: {READS}")
    if _started:
        return
    _started = True
    if GUILD:
        await tree.sync(guild=GUILD)
    if STATUS.get("enabled", True):
        asyncio.create_task(status_loop())
    asyncio.create_task(chat_loop())


def main():
    IPC.update(ipc_numbers())
    print(f"World server IPC: ChatMessageServerMessage = {IPC.get('ChatMessageServerMessage')}")
    try:
        client.run(TOKEN)
    except discord.errors.PrivilegedIntentsRequired:
        if not READS:
            raise
        print("Message Content is not turned on for this bot (Discord developer portal, Bot, Privileged Gateway Intents): "
              "starting without it; Discord messages will not reach the game until it is.")
        os.execve(sys.executable, [sys.executable] + sys.argv, {**os.environ, "LSB_BRIDGE_READS_MESSAGES": "0"})


if __name__ == "__main__":
    main()
