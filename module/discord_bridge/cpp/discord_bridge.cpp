//
// Discord bridge (LandSandBoat C++ module)
//
//   The game's side of the Discord bridge (https://github.com/tagban/lsb-discord-bridge):
//
//   - records the chat kinds a server chooses (Say, Shout, Yell, Linkshell, Unity, Assist) in the
//     discord_bridge_chat table, where the bridge's bot picks them up for Discord;
//   - optionally sends Say, Shout and/or Yell to every zone instead of nearby only (for small
//     servers, where the few players online are rarely in the same place).
//
//   Everything is chosen in settings/discord_bridge.lua (its keys below). Lines starting with ! (a
//   command, typed right or not) are left to the server and never recorded; lines starting with /
//   (a mistyped command) can be dropped (DROP_SLASH_LINES). A GM's # broadcast, a jailed player, and
//   a Yell from a player banned from yelling are left to the server as they are.
//

#include "common/database.h"
#include "common/ipc_structs.h"
#include "common/settings.h"

#include "map/entities/char_entity.h"
#include "map/ipc_client.h"
#include "map/linkshell.h"
#include "map/map_session.h"
#include "map/packets/basic.h"
#include "map/unitychat.h"
#include "map/utils/jailutils.h"
#include "map/utils/moduleutils.h"
#include "packets/c2s/0x0b5_chat_std.h"

class DiscordBridgeModule : public CPPModule
{
    struct Settings
    {
        bool enabled         = false;
        bool recordSay       = false;
        bool recordShout     = false;
        bool recordYell      = false;
        bool recordLinkshell = false;
        bool recordUnity     = false;
        bool recordAssist    = false;
        bool worldwideSay    = false;
        bool worldwideShout  = false;
        bool worldwideYell   = false;
        bool dropSlashLines  = true;
    } set;

    void OnInit() override
    {
        // settings/discord_bridge.lua; a server without it gets the module off (and one error per key
        // in the log, from the settings lookup)
        set.enabled         = settings::get<bool>("discord_bridge.ENABLED");
        set.recordSay       = settings::get<bool>("discord_bridge.RECORD_SAY");
        set.recordShout     = settings::get<bool>("discord_bridge.RECORD_SHOUT");
        set.recordYell      = settings::get<bool>("discord_bridge.RECORD_YELL");
        set.recordLinkshell = settings::get<bool>("discord_bridge.RECORD_LINKSHELL");
        set.recordUnity     = settings::get<bool>("discord_bridge.RECORD_UNITY");
        set.recordAssist    = settings::get<bool>("discord_bridge.RECORD_ASSIST");
        set.worldwideSay    = settings::get<bool>("discord_bridge.WORLDWIDE_SAY");
        set.worldwideShout  = settings::get<bool>("discord_bridge.WORLDWIDE_SHOUT");
        set.worldwideYell   = settings::get<bool>("discord_bridge.WORLDWIDE_YELL");
        set.dropSlashLines  = settings::get<bool>("discord_bridge.DROP_SLASH_LINES");

        ShowInfoFmt("discord_bridge: {} (worldwide say {}, shout {}, yell {})", set.enabled ? "on" : "off", set.worldwideSay,
                    set.worldwideShout, set.worldwideYell);
    }

    // a line for the bot: kind SAY, SHOUT, YELL, LINKSHELL, UNITY, ASSIST_E or ASSIST_J; the linkshell's
    // name, or the unity leader, when it is one of those
    static void record(MapSession* PSession, CCharEntity* PChar, const std::string& kind, const std::string& group, uint32 unityLeader,
                       const std::string& message)
    {
        const auto name   = PChar->getName();
        const auto zoneId = static_cast<uint16>(PChar->getZone());
        const auto job    = static_cast<uint8>(PChar->GetMJob());
        const auto level  = static_cast<uint8>(PChar->GetMLevel());
        const auto sjob   = static_cast<uint8>(PChar->GetSJob());
        const auto slevel = static_cast<uint8>(PChar->GetSLevel());
        PSession->scheduler->postToWorkerThread(
            [name, kind, group, unityLeader, zoneId, job, level, sjob, slevel, message]()
            {
                const auto query = "INSERT INTO discord_bridge_chat (speaker, kind, grp, unity_leader, zoneid, mjob, mlvl, sjob, slvl, message) "
                                   "VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)";
                if (!db::preparedStmt(query, name, kind, group, unityLeader, zoneId, job, level, sjob, slevel, message))
                {
                    ShowErrorFmt("discord_bridge: could not record {}'s {} (is sql/discord_bridge_chat.sql imported?)", name, kind);
                }
            });
    }

    auto OnIncomingPacket(MapSession* PSession, CCharEntity* PChar, CBasicPacket& data) -> bool override
    {
        TracyZoneScoped;

        if (!set.enabled || data.getType() != static_cast<uint16_t>(PacketC2S::GP_CLI_COMMAND_CHAT_STD) || !PChar || !PChar->loc.zone)
        {
            return false;
        }

        const auto* packet = data.as<GP_CLI_COMMAND_CHAT_STD>();

        // the text, as the server's own handler reads it (it may not end in a NUL)
        const auto length  = std::min<std::size_t>((packet->header.size * 4) - 0x6, sizeof(packet->Str));
        const auto message = asStringFromUntrustedSource(packet->Str, length);
        const auto first   = message.find_first_not_of(' ');
        if (first == std::string::npos || jailutils::InPrison(PChar))
        {
            return false;
        }
        if (message[first] == '/' && set.dropSlashLines)
        {
            return true; // a /command mistyped: said to nobody
        }
        if (message[first] == '!' || message[first] == '/' || (message[first] == '#' && PChar->m_GMlevel > 0))
        {
            return false; // a command (or a mistyped one), a GM's broadcast: the server's own handling
        }

        CHAT_MESSAGE_TYPE type{};
        bool              worldwide = false;
        switch (static_cast<GP_CLI_COMMAND_CHAT_STD_KIND>(packet->Kind))
        {
            case GP_CLI_COMMAND_CHAT_STD_KIND::Say:
                if (set.recordSay)
                {
                    record(PSession, PChar, "SAY", "", 0, message);
                }
                type = MESSAGE_SAY, worldwide = set.worldwideSay;
                break;
            case GP_CLI_COMMAND_CHAT_STD_KIND::Shout:
                if (set.recordShout)
                {
                    record(PSession, PChar, "SHOUT", "", 0, message);
                }
                type = MESSAGE_SHOUT, worldwide = set.worldwideShout;
                break;
            case GP_CLI_COMMAND_CHAT_STD_KIND::Yell:
                if (PChar->getCharVar("[YELL]Banned") == 1)
                {
                    return false;
                }
                if (set.recordYell)
                {
                    record(PSession, PChar, "YELL", "", 0, message);
                }
                type = MESSAGE_YELL, worldwide = set.worldwideYell;
                break;
            case GP_CLI_COMMAND_CHAT_STD_KIND::Linkshell1:
            case GP_CLI_COMMAND_CHAT_STD_KIND::Linkshell2:
            {
                const bool first_shell = static_cast<GP_CLI_COMMAND_CHAT_STD_KIND>(packet->Kind) == GP_CLI_COMMAND_CHAT_STD_KIND::Linkshell1;
                CLinkshell* PLinkshell = first_shell ? PChar->PLinkshell1 : PChar->PLinkshell2;
                if (set.recordLinkshell && PLinkshell)
                {
                    record(PSession, PChar, "LINKSHELL", PLinkshell->getName(), 0, message);
                }
                return false;
            }
            case GP_CLI_COMMAND_CHAT_STD_KIND::Unity:
                if (set.recordUnity && PChar->PUnityChat)
                {
                    record(PSession, PChar, "UNITY", "", PChar->PUnityChat->getLeader(), message);
                }
                return false;
            case GP_CLI_COMMAND_CHAT_STD_KIND::AssistE:
            case GP_CLI_COMMAND_CHAT_STD_KIND::AssistJ:
                if (set.recordAssist)
                {
                    const bool english = static_cast<GP_CLI_COMMAND_CHAT_STD_KIND>(packet->Kind) == GP_CLI_COMMAND_CHAT_STD_KIND::AssistE;
                    record(PSession, PChar, english ? "ASSIST_E" : "ASSIST_J", "", 0, message);
                }
                return false;
            default:
                return false;
        }

        if (!worldwide)
        {
            return false; // recorded (or not); the server says it as usual
        }

        // to every zone, as the same kind of line from the same speaker; the nearby-only copy is not
        // sent, so nobody sees it twice
        message::send(ipc::ChatMessageServerMessage{
            .senderId    = PChar->id,
            .senderName  = PChar->getName(),
            .message     = message,
            .zoneId      = PChar->getZone(),
            .gmLevel     = PChar->m_GMlevel,
            .messageType = type,
            .skipSender  = true, // the speaker's own game shows their line already
        });
        return true;
    }
};

REGISTER_CPP_MODULE(DiscordBridgeModule);
