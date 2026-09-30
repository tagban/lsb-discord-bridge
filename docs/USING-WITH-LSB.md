# Using the module with LandSandBoat

The step-by-step of adding `discord_bridge` to a LandSandBoat server, for both ways of running one:
built from source on the machine, or LandSandBoat's Docker setup. The README has the overview and the
bot's side.

## What LandSandBoat needs from you

A LandSandBoat module is a folder under `modules/` listed in `modules/init.txt`. Lua modules load when
the map server starts; C++ modules (this one) are compiled into the map server, so adding one, or
changing its code, means building the server again. Its settings are a Lua file in `settings/`, which
LandSandBoat loads with its own: changing those needs only a map server restart.

| Piece | Goes to | Changed later |
|---|---|---|
| `module/discord_bridge/` | `modules/discord_bridge/` | rebuild the server |
| `settings/discord_bridge.lua` | `settings/discord_bridge.lua` | restart the map server |
| `module/discord_bridge/sql/discord_bridge_chat.sql` | the database (the bot makes it if missing) | |

`modules/init.txt` gets one line:

```
discord_bridge/
```

## Built from source

```bash
cd /path/to/server
cp -a /path/to/lsb-discord-bridge/module/discord_bridge modules/
echo "discord_bridge/" >> modules/init.txt
cp /path/to/lsb-discord-bridge/settings/discord_bridge.lua settings/
# build as you always do, e.g.:
cmake --build build -j$(nproc)
```

Restart the map server (xi_map). Its log shows, once it has started:

```
discord_bridge: on (worldwide say false, shout false, yell false)
```

## Docker (LandSandBoat's docker-compose.yml)

The image is built from the checkout, so the module has to be in the checkout's `modules/` and listed
in its `modules/init.txt` when you build. An update that resets the checkout (`git reset --hard`,
`git checkout .`) resets `modules/init.txt` too, so keep your copy of it and the module outside the
checkout and copy them back in before each build, or mount them (below).

1. Copy the module and list it, as above, then build: `docker compose build`.
2. The settings file: `settings/` is already mounted into the containers by LandSandBoat's compose
   file (`./settings:/server/settings`), so copying `discord_bridge.lua` there is enough.
3. Publish the world server's IPC port to the machine only, for the bot (and `tools/announce.py`):

   ```yaml
     world:
       ports:
         - "127.0.0.1:54003:54003"
   ```

   and the database's the same way (`"127.0.0.1:3306:3306"`) if the bot runs outside Docker. Don't
   publish either to every address: the IPC port lets anything that reaches it speak to your players,
   and the database's needs no explaining.
4. `docker compose up -d`, then check the map server's log for the `discord_bridge: on` line.

To change the settings without rebuilding, you can also mount the module's list and folder over the
image's, in the map service:

```yaml
  map:
    volumes:
      - ./my-modules/init.txt:/server/modules/init.txt:ro
```

(the C++ still has to be in the image: that part is always a rebuild).

### A LandSandBoat Docker build problem to know about (September 2026)

LandSandBoat generates part of its Lua (`scripts/enum/*.codegen.lua`: `xi.job`, `xi.element`,
`xi.effect`, `xi.mod`, `xi.zone`...) while building, and records that it did so in the build folder.
The Docker build keeps the build folder in a cache between builds but copies the source fresh each time,
so from the second build on it believes the files are there and skips them, and the image has none: the
map server then logs `attempt to index field 'element' (a nil value)` and the like at start, and spells,
abilities and mob skills fail (with a log that grows by gigabytes an hour). Nothing to do with this
module, but it bites the second build, which adding a module is. Before building, generate them into the
checkout with the image you have:

```bash
docker compose run --rm --no-deps -v "$PWD:/src" -w /src --entrypoint python map -m tools.codegen /tmp/codegen
ls scripts/enum | grep -c codegen   # more than 0
```

The build then copies them in with the rest of `scripts/`.

## Checking it works

1. Say something in game. With `RECORD_SAY = true`, the line is in the table:
   `SELECT speaker, kind, message FROM discord_bridge_chat ORDER BY id DESC LIMIT 5;`
2. With `WORLDWIDE_SAY = true`, a character in another zone sees it.
3. With the bot running and a `[[bridge]]` for that kind, it shows in Discord.

## The IPC, and announce.py

The bot speaks to the game the way LandSandBoat's `tools/announce.py` does: one message to the world
server's IPC port, which passes it to every zone. Since August 2026 (LandSandBoat commit 51084c308d) that
IPC uses alpaca's fixed-length encoding; LandSandBoat's own `announce.py` was not updated with it, and the
world server refuses its messages (`Failed to deserialize ChatMessageServerMessage message.`). The fix
was offered to LandSandBoat ([#11663](https://github.com/LandSandBoat/server/pull/11663)); until the
LandSandBoat you run has it, `tools/announce.py` here is the fixed one:

```bash
python3 tools/announce.py "The server restarts in 5 minutes."            # on the server
docker compose exec -T world python - "Restarting soon" < tools/announce.py  # with Docker
```

The bot does not use `announce.py`; it has its own encoders (the same bytes), and reads the IPC message
numbers from your checkout's `tools/generate_ipc_stubs.py`, so a LandSandBoat update that adds messages
does not shift them.

## Removing it

Take `discord_bridge/` out of `modules/init.txt` and rebuild; delete `settings/discord_bridge.lua` and,
if you like, the `discord_bridge_chat` table. Nothing else of LandSandBoat's was changed.
