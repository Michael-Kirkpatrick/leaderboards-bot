"""Variables for different environments to configure the bot."""

from os import getcwd, getenv
from os.path import join
from discord import Intents

_intents = Intents.default()
_intents.guilds = True
_intents.members = True
_intents.emojis_and_stickers = True
_intents.guild_reactions = True
_intents.guild_messages = True
_intents.message_content = True

_intents.moderation = False
_intents.integrations = False
_intents.webhooks = False
_intents.invites = False
_intents.voice_states = False
_intents.presences = False
_intents.dm_messages = False
_intents.dm_reactions = False
_intents.guild_typing = False
_intents.dm_typing = False
_intents.guild_scheduled_events = False
_intents.auto_moderation_configuration = False
_intents.auto_moderation_execution = False


prod_vars = {
    'DB_PATH': join(getcwd(), "db", "leaderboards.db"),
    'BOT_COLOR': 0xF04747,
    'MAX_STATS_PER_GUILD': 3,
    'BOT_TOKEN': getenv('PROD_LEADERBOARDS_BOT_TOKEN'),
    'INTENTS': _intents
}

dev_vars = {
    'DB_PATH': join(getcwd(), "db", "dev_leaderboards.db"),
    'BOT_COLOR': 0x2EB684,
    'MAX_STATS_PER_GUILD': 3,
    'BOT_TOKEN': getenv('DEV_LEADERBOARDS_BOT_TOKEN'),
    'INTENTS': _intents
}
