-----------------------------------
-- Discord bridge: the game's side (modules/discord_bridge)
-- Copy this file into your server's settings/ folder (beside login.lua, map.lua...) and change what
-- you want. After a change, restart the map server.
-----------------------------------

xi = xi or {}
xi.settings = xi.settings or {}

xi.settings.discord_bridge =
{
    -- The module does nothing while this is false.
    ENABLED = true,

    -- Which chat the module records for the bridge's bot (each can go to its own Discord channel;
    -- the bot's config.toml says which). Party and alliance chat are never recorded; tells neither.
    RECORD_SAY       = true,
    RECORD_SHOUT     = true,
    RECORD_YELL      = true,
    RECORD_LINKSHELL = false, -- every linkshell's chat, with its name (the bot picks which to post)
    RECORD_UNITY     = false,
    RECORD_ASSIST    = false, -- the Assist channels (English and Japanese)

    -- Worldwide chat, for small servers: Say, Shout and/or Yell reach everyone in every zone instead
    -- of those nearby (or, for Yell, those in yell zones). Each is independent of the recording above.
    WORLDWIDE_SAY   = false,
    WORLDWIDE_SHOUT = false,
    WORLDWIDE_YELL  = false,

    -- A line starting with / is a mistyped command (the game's own commands never reach the server as
    -- chat): true says it to nobody, false lets it be said as typed. Lines starting with ! (commands)
    -- are always left to the server and never recorded.
    DROP_SLASH_LINES = true,
}
