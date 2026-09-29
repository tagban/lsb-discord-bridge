-- The Discord bridge's chat lines: what the module records (the chat kinds settings/discord_bridge.lua
-- chooses), for the bridge's bot to post in Discord. The bot keeps only where it is up to; old lines
-- can be deleted at any time (the bot also clears lines older than its keep_days).
CREATE TABLE IF NOT EXISTS `discord_bridge_chat` (
    `id`           INT UNSIGNED NOT NULL AUTO_INCREMENT,
    `at`           DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    `speaker`      VARCHAR(16) NOT NULL,
    `kind`         VARCHAR(12) NOT NULL,          -- SAY SHOUT YELL LINKSHELL UNITY ASSIST_E ASSIST_J
    `grp`          VARCHAR(20) NOT NULL DEFAULT '', -- the linkshell's name, for LINKSHELL
    `unity_leader` INT UNSIGNED NOT NULL DEFAULT 0,   -- the unity leader, for UNITY
    `zoneid`       SMALLINT UNSIGNED NOT NULL DEFAULT 0,
    `mjob`         TINYINT UNSIGNED NOT NULL DEFAULT 0,
    `mlvl`         TINYINT UNSIGNED NOT NULL DEFAULT 0,
    `sjob`         TINYINT UNSIGNED NOT NULL DEFAULT 0,
    `slvl`         TINYINT UNSIGNED NOT NULL DEFAULT 0,
    `message`      BLOB,
    PRIMARY KEY (`id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_general_ci;
