"""Main entry point to LeaderboardsBot"""

"""
TODO:
- Add a app_commands.check function to check for administrator or configured roles to handle permissions, rather than use defaults.
- Create a proper database migration tool
- Admin command to remove deleted emojis from the emoji leaderboard. Just delete them from database entirely if they aren't found.
"""

import os
from random import randint
from json import loads, dumps
from typing import Optional
import re
import asyncio
import sqlite3
import datetime
import sys
import discord
from discord import app_commands
import menu
import modal
from config.env_vars import prod_vars, dev_vars


synced_guilds = set()
async def sync_commands_to_guild(clientObj, guild_id):
    try:
        if guild_id in synced_guilds:
            return

        guild = discord.Object(id=guild_id)
        clientObj.tree.copy_global_to(guild=guild)
        await clientObj.tree.sync(guild=guild)
        synced_guilds.add(guild_id)
    except Exception as e:
        print(f"Failed to sync commands for guild id {guild_id}. Error: {e}")


def create_connection():
    conn = None
    try:
        conn = sqlite3.connect(client.db_path)
        return conn
    except sqlite3.Error as e:
        print(e)

    return conn


def cleanse_string(string):
    bad_string = False
    i = 0
    while i < len(string) and not bad_string:
        char = string[i]
        if not char.isalnum() or not char == '_':
            bad_string = True
        i += 1

    return "".join(char for char in string if char.isalnum() or char == '_'), bad_string


class LeaderboardsBot(discord.Client):
    """Class to handle the discord client object"""
    def __init__(self, config_settings, **options):
        self.db_path = config_settings['DB_PATH']
        self.bot_color = config_settings['BOT_COLOR']
        self.max_stats_per_guild = config_settings['MAX_STATS_PER_GUILD']
        super().__init__(intents = config_settings['INTENTS'], **options)
        self.tree = app_commands.CommandTree(self)


    async def setup_hook(self):
        # Copy the global commands to guilds we are aware of already on startup
        conn = create_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT id FROM guilds")
            rows = cur.fetchall()
            if rows:
                for row in rows:
                    await sync_commands_to_guild(self, row[0])
        except Exception as e:
            print(f"Error syncing command tree to existing guilds. Error: {e}")
        finally:
            conn.close()


run_env = os.getenv('LEADERBOARDS_BOT_RUN_ENVIRONMENT')
if run_env == 'prod':
    config_vars = prod_vars
else:
    config_vars = dev_vars

if len(sys.argv) > 1:
    config_vars['DB_PATH'] = sys.argv[1]
client = LeaderboardsBot(config_vars)


def get_stat_col(channel, stat_mapping, stat_type, **kwargs):
    stat_cols = []
    for stat in stat_mapping['Mapping']:
        if stat['Type'] == stat_type and \
                (  # Logical block for matching the scope of the stat
                    (stat['Level'] == "Guild" and 'CategoryOnly' not in kwargs and 'ChannelOnly' not in kwargs) or
                    (stat['Level'] == 'Category' and channel.category_id == stat['LevelID'] and 'GuildOnly' not in kwargs and 'ChannelOnly' not in kwargs) or
                    (stat['Level'] == 'Channel' and channel.id == stat['LevelID'] and 'GuildOnly' not in kwargs and 'CategoryOnly' not in kwargs)
                ) \
                and \
                (  # Logical block for matching specifics of the stat type
                    (stat['Type'] == "Dice" and stat['DiceType'] == kwargs['DiceType'] and stat['Target'] == kwargs['DiceResult']) or
                    (stat['Type'] == 'total_messages')
                ):
            stat_cols.append(stat['StatCol'])

    return stat_cols


def update_user_stat(user_id, guild_id, stat_col, value):
    conn = create_connection()
    cur = conn.cursor()

    try:
        if value == 'increment':
            sql = f"""  INSERT INTO guilds_users(guild_id, user_id, {stat_col}) VALUES(?,?,1)
                        ON CONFLICT(guild_id, user_id) DO UPDATE 
                        SET {stat_col} = {stat_col} + 1
                        WHERE guild_id = ? AND user_id = ?
                    """
            params = (guild_id, user_id, guild_id, user_id)
        else:
            sql = f"""  INSERT INTO guilds_users(guild_id, user_id, {stat_col}) VALUES(?,?,?)
                        ON CONFLICT(guild_id, user_id) DO UPDATE 
                        SET {stat_col} = ?
                        WHERE guild_id = ? AND user_id = ?
                    """
            params = (guild_id, user_id, value, value, guild_id, user_id)

        cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        print(f"Failed to update {stat_col} for guild: {guild_id} and user {user_id}\n\tError - {e}")
    finally:
        conn.close()


def update_emote_count(guild_id, emote_id, increment):
    """Update the usage counter for an emote. Set increment True to increment, False to decrement."""
    conn = create_connection()
    cur = conn.cursor()

    try:
        sql = f"""  INSERT INTO guilds_emotes(guild_id, emote_id, emote_count) VALUES(?,?,1)
                    ON CONFLICT(guild_id, emote_id) DO UPDATE 
                    SET emote_count = emote_count {'+' if increment else '-'} 1
                    WHERE guild_id = ? AND emote_id = ?
                """
        params = (guild_id, emote_id, guild_id, emote_id)
        cur.execute(sql, params)
        conn.commit()
    except Exception as e:
        print(f"Failed to update emote count for guild: {guild_id} and emote {emote_id}\n\tError - {e}")
    finally:
        conn.close()


def get_basic_embed(msg):
    return discord.Embed(color=client.bot_color, description=msg)


async def reply(interaction: discord.Interaction, msg: str, title: str = None, ephemeral: bool = False, view: discord.ui.View = discord.utils.MISSING):
    embed_msg = get_basic_embed(msg)
    if title is not None:
        embed_msg.title = title

    if interaction.response.is_done():
        await interaction.edit_original_response(embed=embed_msg, view=view)
    else:
        await interaction.response.send_message(embed=embed_msg, ephemeral=ephemeral, view=view)


async def send_final_message(interaction: discord.Interaction, msg: str, title: str = None, view: discord.ui.View = discord.utils.MISSING):
    embed_msg = get_basic_embed(msg)
    if title is not None:
        embed_msg.title = title

    if interaction.response.is_done():
        await interaction.delete_original_response()
        await interaction.channel.send(embed=embed_msg, view=view)
    else:
        await interaction.response.send_message(embed=embed_msg, view=view)


async def run_button_menu(interaction: discord.Interaction, menu_options: list[menu.MenuOption], title: str, separate_lines = False, page_offset: int = 0):
    view = menu.ButtonMenu(menu_options, page_offset, separate_lines, 30)
    await reply(interaction, None, title=title, view=view)


async def run_select_menu(interaction: discord.Interaction, menu_options: list[menu.SelectOption], title: str, ephemeral = False):
    view = menu.SelectMenu(menu_options)
    await reply(interaction, None, title=title, view=view, ephemeral=ephemeral)


def on_message_retrieve_guild_data(guild_id, retry=False):
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT stat_mapping, config_roles FROM guilds WHERE id = ?", (guild_id,))
        rows = cur.fetchall()
        if rows:
            config_roles = rows[0][1]
            if not config_roles:
                config_roles = []
            else:
                config_roles = [int(v) for v in config_roles.split(',')]
            return loads(rows[0][0]), config_roles
        elif not retry:
            cur.execute("INSERT INTO guilds(id) VALUES (?)", (guild_id,))
            conn.commit()
            return on_message_retrieve_guild_data(guild_id, retry=True)
        else:
            raise Exception(f"Attempted to initialize guild id {guild_id} in database and still no data on retry.")
    except Exception as e:
        print(f"Error retrieving guild data for guild id: {guild_id}\n\t Error: {e}")
    finally:
        conn.close()


def get_stat_mapping(guild_id):
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT stat_mapping FROM guilds WHERE id = ?", (guild_id,))
        rows = cur.fetchall()
        if rows:
            return loads(rows[0][0])
    except Exception as e:
        print(f"Error getting stat mapping from guild with id: {guild_id}\n\t Error: {e}")
    finally:
        conn.close()


async def verify_slow_mode(interaction: discord.Interaction) -> bool:
    delay = interaction.channel.slowmode_delay
    if delay is None or delay <= 0:
        return True

    now = datetime.datetime.now(datetime.UTC)
    delay_delta = datetime.timedelta(seconds=delay)
    cutoff_time = now - delay_delta
    async for message in interaction.channel.history(after=cutoff_time, oldest_first=False):
        # If message is by the current user, or message is a result of the user's former interaction (but not an ephemeral interaction)
        if message.author.id == interaction.user.id or (message.interaction.user.id == interaction.user.id and not message.flags.ephemeral):
            time_since_message_was_sent = now - message.created_at
            remaining_cd = delay_delta - time_since_message_was_sent
            hours, remainder = divmod(remaining_cd.seconds, 3600)
            minutes, seconds = divmod(remainder, 60)
            await reply(interaction, "Must wait for slowmode cooldown. Remaining time: {:02}:{:02}:{:02}".format(int(hours), int(minutes), int(seconds)), ephemeral=True)
            interaction.extras['failed'] = True
            return False

    return True


@client.event
async def on_message(message: discord.Message):
    if message.author.id == client.user.id:
        return

    stat_mapping, _ = on_message_retrieve_guild_data(message.guild.id)
    if stat_mapping:
        stat_cols = get_stat_col(message.channel, stat_mapping, "total_messages")
        if stat_cols:
            for col in stat_cols:
                update_user_stat(message.author.id, message.guild.id, col, "increment")

    # Track any emojis in the message. Count only once evne if multiple occurences exist.
    custom_emojis = set(re.findall(r'<:\w*:\d*>', message.content))
    custom_emojis_ids = [e.split(':')[-1].replace('>', '') for e in custom_emojis]
    for emoji_id in custom_emojis_ids:
        # Verify real emoji and not injection before saving to db
        try:
            await message.guild.fetch_emoji(emoji_id)
            update_emote_count(message.guild.id, emoji_id, True)
        except discord.errors.NotFound:
            print("Failed to update count for emoji not found in the guild.")

    # Attempt to sync commands to the guild if necessary. Guild may not have been in database on startup
    await sync_commands_to_guild(client, message.guild.id)


@client.event
async def on_app_command_completion(interaction: discord.Interaction, command):
    if interaction.user.id == client.user.id:
        return

    if not 'behave_as_message' in command.extras:
        return

    if 'failed' in interaction.extras:
        return

    stat_mapping, _ = on_message_retrieve_guild_data(interaction.guild.id)
    if stat_mapping:
        stat_cols = get_stat_col(interaction.channel, stat_mapping, "total_messages")
        if stat_cols:
            for col in stat_cols:
                update_user_stat(interaction.user.id, interaction.guild.id, col, "increment")


@client.event
async def on_raw_reaction_add(event: discord.RawReactionActionEvent):
    if event.emoji.id is not None: # Server emotes have IDs, standard emojis just have names which are their unicode representation
        update_emote_count(event.guild_id, event.emoji.id, True)


@client.event
async def on_raw_reaction_remove(event: discord.RawReactionActionEvent):
    if event.emoji.id is not None:
        update_emote_count(event.guild_id, event.emoji.id, False)


def get_stat_description(stat, guild_id):
    stat_desc = ""
    if stat['Type'] == 'total_messages':
        stat_desc = "Total messages"
    elif stat['Type'] == 'Dice':
        stat_desc = f"{stat['Target']}'s rolled by d{stat['DiceType']}"

    stat_desc += " "

    if stat['Level'] == 'Guild':
        stat_desc += "server-wide"
    elif stat['Level'] == 'Category':
        cat_name = ""
        for cat in client.get_guild(guild_id).categories:
            if cat.id == stat['LevelID']:
                cat_name = cat.name
                break
        stat_desc += f"in Category '{cat_name}'"
    elif stat['Level'] == 'Channel':
        stat_desc += f"in Channel '{client.get_channel(stat['LevelID']).name}'"

    return stat_desc


def get_server_stats_string(guild_id, stat_mapping):
    if len(stat_mapping['Mapping']) == 0:
        retval = "There are no stats currently being tracked. Try !config to start tracking."
    else:
        retval = ""
        i = 1
        for stat in stat_mapping['Mapping']:
            stat_desc = get_stat_description(stat, guild_id)
            retval += f"\n\t**{i}.** *{stat_desc}*"
            i += 1

    return retval


def get_default_leaderboard(guild_id):
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT default_leaderboard FROM guilds WHERE id = ?", (guild_id,))
        rows = cur.fetchall()
        if rows:
            return rows[0][0]
        else:
            return None
    except Exception as e:
        print(f"Error getting default leaderboard from guild with id: {guild_id}\n\t Error: {e}")
    finally:
        conn.close()


async def display_leaderboard(interaction: discord.Interaction, leaderboard_id: int):
    stat_mapping = get_stat_mapping(interaction.guild.id)
    display_stat = None
    for stat in stat_mapping['Mapping']:
        if int(stat['StatCol'][4:]) == leaderboard_id:
            display_stat = stat
            break

    if display_stat is None:
        await reply(interaction, f"Invalid argument '{leaderboard_id}' to command 'leaderboard'.", ephemeral=True)
        return

    stat_desc = get_stat_description(display_stat, interaction.guild.id)

    conn = create_connection()
    cur = conn.cursor()
    sql = f"SELECT user_id, stat{leaderboard_id} FROM guilds_users ORDER BY stat{leaderboard_id} DESC LIMIT 10"
    cur.execute(sql)
    rows = cur.fetchall()

    desc = ""
    i = 1
    for row in rows:
        try:
            user = await client.fetch_user(row[0])
            username = user.name
        except discord.errors.NotFound:
            username = "DELETED"

        desc += f"**{i}.** {username} - {row[1]}\n"
        i += 1

    await send_final_message(interaction, desc, f"Leaderboard: *{stat_desc}*")


async def get_message_input(interaction: discord.Interaction, description, help_text, target_regex, check_function=None, invalid_input=None):
    retval = None

    msg_embed = get_basic_embed(description)
    msg_embed.set_footer(text=help_text)
    if invalid_input:
        msg_embed.description = f"Try again, invalid input: {invalid_input}\n" + msg_embed.description
    sent_message = await interaction.channel.send(embed=msg_embed)

    def _check(_msg):
        return _msg.author == interaction.user and _msg.channel == interaction.channel

    try:
        response = await client.wait_for('message', timeout=30, check=_check)
    except asyncio.TimeoutError:
        await sent_message.delete()
    else:
        await sent_message.delete()
        res = re.search(target_regex, response.content.lower())
        if res is not None:
            searched_input = res.group()
            if callable(check_function):
                if check_function(searched_input):
                    retval = searched_input
            else:
                retval = searched_input

        if retval is None:  # Note that function can still return None if the response times out.
            retval = await get_message_input(interaction, description, help_text, target_regex, check_function, response.content)

    return retval


async def choose_stat_level(interaction: discord.Interaction, **stat_obj):
    stat_obj['interaction'] = interaction
    menu_options = [
        menu.SelectOption('Track across entire server', guild_level, stat_obj, 0),
        menu.SelectOption("Track only in a category of channels", category_level, stat_obj, 1),
        menu.SelectOption("Track only in one channel", channel_level, stat_obj, 2)
    ]
    await run_select_menu(interaction, menu_options, "Select where the stat is tracked:", True)


async def guild_level(interaction: discord.Interaction, **stat_obj):
    stat_obj['Level'] = 'Guild'
    await add_stat_to_db(interaction, stat_obj)


async def category_level(interaction: discord.Interaction, **stat_obj):
    stat_obj['Level'] = 'Category'
    menu_options = []
    i = 0
    for category in interaction.guild.categories:
        stat_obj_arg = stat_obj.copy()
        stat_obj_arg['LevelID'] = category.id
        menu_options.append(menu.SelectOption(category.name, add_stat_to_db, {'interaction': interaction, 'stat_obj': stat_obj_arg}, i))
        i += 1
    await run_select_menu(interaction, menu_options, "Select the category you would like this stat to be tracked in:", True)


async def channel_level(interaction: discord.Interaction, **stat_obj):
    stat_obj['Level'] = 'Channel'
    menu_options = []
    i = 0
    for channel in interaction.guild.text_channels:
        stat_obj_arg = stat_obj.copy()
        stat_obj_arg['LevelID'] = channel.id
        menu_options.append(menu.SelectOption(channel.name, add_stat_to_db, {'interaction': interaction, 'stat_obj': stat_obj_arg}, i))
        i += 1
    await run_select_menu(interaction, menu_options, "Select the channel you would like this stat to be tracked in:", True)


async def manage_stats(interaction: discord.Interaction):
    menu_options = [
        menu.SelectOption('Track a new stat', add_stat, {'interaction': interaction}, 0),
        menu.SelectOption('Delete a tracked stat', delete_stat, {'interaction': interaction}, 1)
    ]
    await run_select_menu(interaction, menu_options, "Manage Tracked Stats:", True)


async def add_stat(interaction: discord.Interaction):
    menu_options = [
        menu.SelectOption('Total messages', choose_stat_level, {'interaction': interaction, "Type": "total_messages"}, 0),
        menu.SelectOption('Dice roll', setup_die, {'interaction': interaction}, 1, True)
    ]
    await run_select_menu(interaction, menu_options, "Select Stat Type:", True)


async def add_stat_to_db(interaction: discord.Interaction, stat_obj):
    guild_id = interaction.guild.id
    stat_mapping = get_stat_mapping(guild_id)
    num_stats = len(stat_mapping['Mapping'])
    if num_stats >= client.max_stats_per_guild:
        await reply(interaction, f"Error: server already tracking maximum number of stats ({client.max_stats_per_guild}). Delete an existing stat to add another.", view=None)
        return

    statcol = f"stat{num_stats + 1}"
    stat_obj['StatCol'] = statcol
    stat_mapping['Mapping'].append(stat_obj)
    stat_str = dumps(stat_mapping)

    conn = create_connection()
    cur = conn.cursor()
    try:
        sql = "UPDATE guilds SET stat_mapping = ? WHERE id = ?"
        params = (stat_str, guild_id)
        cur.execute(sql, params)
        conn.commit()

        await reply(interaction, f"Successfully added new stat: {get_stat_description(stat_obj, guild_id)}", view=None)
    except Exception as e:
        print(f"Failed to update stat_mapping for guild: {guild_id} - Error - {e}")
    finally:
        conn.close()


async def delete_stat(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    stat_mapping = get_stat_mapping(guild_id)
    num_stats = len(stat_mapping['Mapping'])
    if num_stats == 0:
        await reply(interaction, "There are no stats currently being tracked, you cannot delete a stat.", view=None)
        return

    menu_options = []
    i = 0
    for stat in stat_mapping['Mapping']:
        menu_options.append(menu.SelectOption(get_stat_description(stat, guild_id), delete_stat_from_db, 
                                              {'interaction': interaction, 'stat_mapping': stat_mapping, 'stat_col': stat['StatCol']}, i))
        i += 1

    await run_select_menu(interaction, menu_options, "Select which stat to delete:", True)


async def delete_stat_from_db(interaction: discord.Interaction, stat_mapping, stat_col):
    guild_id = interaction.guild.id
    num_stats = len(stat_mapping['Mapping'])
    delete_stat_col_num = int(stat_col[4:])

    i = 0
    for stat in stat_mapping['Mapping']:
        if stat['StatCol'] == stat_col:
            stat_mapping['Mapping'].pop(i)
            break
        i += 1

    for stat in stat_mapping['Mapping']:
        stat_col_num = int(stat['StatCol'][4:])
        if stat_col_num > delete_stat_col_num:
            stat['StatCol'] = f'stat{stat_col_num - 1}'

    default_leaderboard = get_default_leaderboard(guild_id)
    stat_str = dumps(stat_mapping)
    conn = create_connection()
    cur = conn.cursor()

    try:
        if default_leaderboard is not None:
            if default_leaderboard > delete_stat_col_num:
                cur.execute("UPDATE guilds SET default_leaderboard = default_leaderboard - 1 WHERE id = ?", (guild_id,))
            elif default_leaderboard == delete_stat_col_num:
                cur.execute("UPDATE guilds SET default_leaderboard = NULL WHERE id = ?", (guild_id,))

        sql = """UPDATE guilds SET stat_mapping = ? WHERE id = ?"""
        params = (stat_str, guild_id)
        cur.execute(sql, params)

        params = (guild_id,)
        for i in range(delete_stat_col_num, num_stats):
            sql = f"""UPDATE guilds_users SET stat{i} = stat{i + 1} WHERE guild_id = ?"""
            cur.execute(sql, params)

        sql = f"""UPDATE guilds_users SET stat{num_stats} = 0 WHERE guild_id = ?"""
        cur.execute(sql, params)

        conn.commit()
        await reply(interaction, f"Successfully deleted stat {delete_stat_col_num}.", view=None)
    except Exception as e:
        print(f"Failed to delete a stat and realign stats for guild: {guild_id} - Deleted stat num: {delete_stat_col_num}\n\tError - {e}")
    finally:
        conn.close()


async def setup_die(interaction: discord.Interaction, new_interaction: discord.Interaction):
    await interaction.delete_original_response()

    modal_inputs = [
        modal.ModalInput("Number of sides", None),
        modal.ModalInput("Target value", None)
    ]
    modal_view = modal.get_model(modal_inputs, verify_die_modal, "Configure dice stat")
    await new_interaction.response.send_modal(modal_view)


async def verify_die_modal(interaction: discord.Interaction, values: list[str]):
    """Verify the modal inputs are valid.
    We cannot send a second modal immediately after the first, so we just end the interaction with an error message and a button to try again."""
    dice_type = values[0]
    if not (dice_type.isdigit() and 1 <= int(dice_type)):
        menu_options = [
            menu.SelectOption('Dice roll', setup_die, {'interaction': interaction}, 0, True)
        ]
        await run_select_menu(interaction, menu_options, f"Invalid dice type entered: {dice_type}. Try again:", True)
        return
    dice_type = int(dice_type)

    target = values[1]
    if not (target.isdigit() and 1 <= int(target) <= dice_type):
        menu_options = [
            menu.SelectOption('Dice roll', setup_die, {'interaction': interaction}, 0, True)
        ]
        await run_select_menu(interaction, menu_options, f"Invalid target value entered: {target}. Try again:", True)
        return
    target = int(target)

    stat_obj = {"Type": "Dice", "DiceType": dice_type, "Target": target}
    await choose_stat_level(interaction, **stat_obj)


async def change_default_leaderboard(interaction: discord.Interaction):
    guild_id = interaction.guild.id
    stat_mapping = get_stat_mapping(guild_id)
    if len(stat_mapping['Mapping']) == 0:
        await reply(interaction, "Cannot change default leaderboard when no stats are tracked. Add a stat first!", view=None)
        return

    menu_options = []
    i = 0
    for stat in stat_mapping['Mapping']:
        menu_options.append(menu.SelectOption(get_stat_description(stat, guild_id), change_default_leaderboard_db, 
                                              {'interaction': interaction, 'default_leaderboard_num': int(stat['StatCol'][4:])}, i))
        i += 1

    await run_select_menu(interaction, menu_options, "Select which stat you would like to be shown in the default leaderboard:", True)


async def change_default_leaderboard_db(interaction: discord.Interaction, default_leaderboard_num: int):
    guild_id = interaction.guild.id
    conn = create_connection()
    cur = conn.cursor()
    try:
        sql = "UPDATE guilds SET default_leaderboard = ? WHERE id = ?"
        params = (default_leaderboard_num, guild_id)
        cur.execute(sql, params)
        conn.commit()

        await reply(interaction, "Successfully changed default leaderboard.", view=None)
    except Exception as e:
        print(f"Failed to update default_leaderboard for guild: {guild_id} - Error - {e}")
    finally:
        conn.close()


async def manage_permissions(interaction: discord.Interaction):
    # menu_functions = [add_role_to_config_roles, delete_role_from_config_roles]
    # args_list = [{}, {}]
    # descriptor_list = ['Permit a role', "Remove a role's permission"]
    # title = "Manage who can configure bot settings:"

    # await menu.run_menu(interaction, menu_functions, args_list, descriptor_list, title)
    return

def get_config_roles(guild_id):
    conn = create_connection()
    cur = conn.cursor()
    try:
        cur.execute("SELECT config_roles FROM guilds WHERE id = ?", (guild_id,))
        rows = cur.fetchall()
        if rows:
            return rows[0][0]
        else:
            return None
    except Exception as e:
        print(f"Error getting config_roles from guild with id: {guild_id}\n\t Error: {e}")
    finally:
        conn.close()


def get_role_name(guild_roles, role_id):
    retval = None
    for role in guild_roles:
        if role.id == role_id:
            retval = role.name
            break

    return retval


async def add_role_to_config_roles(interaction: discord.Interaction):
    # title = "Select which role you would like to give permissions."
    # values_list = [v.id for v in interaction.guild.roles]
    # descriptor_list = [v.name for v in interaction.guild.roles]
    # role_id = await menu.get_menu_input(interaction, values_list, descriptor_list, title)

    # guild_id = interaction.guild.id
    # role_name = get_role_name(interaction.guild.roles, role_id)
    # config_roles = get_config_roles(guild_id)

    # if not config_roles:
    #     config_roles = str(role_id)
    # else:
    #     config_roles_list = [int(v) for v in config_roles.split(',')]
    #     if role_id in config_roles_list:
    #         msg_embed = get_basic_embed(f"The role '{role_name}' can already alter bot settings!")
    #         await interaction.channel.send(embed=msg_embed)
    #         return
    #     else:
    #         config_roles += ',' + str(role_id)

    # conn = create_connection()
    # cur = conn.cursor()
    # try:
    #     sql = "UPDATE guilds SET config_roles = ? WHERE id = ?"
    #     params = (config_roles, guild_id)
    #     cur.execute(sql, params)
    #     conn.commit()

    #     msg_embed = get_basic_embed(f"Successfully enabled '{role_name}' to alter bot settings.")
    #     await interaction.channel.send(embed=msg_embed)
    # except Exception as e:
    #     print(f"Failed to add a role to config_roles for guild: {guild_id} - Error - {e}")
    # finally:
    #     conn.close()
    return


async def delete_role_from_config_roles(interaction: discord.Interaction):
    # guild_id = interaction.guild.id
    # config_roles = get_config_roles(guild_id)
    # if not config_roles:
    #     msg_embed = get_basic_embed("No roles have been granted permissions to alter bot settings. Cannot remove a role's permission.")
    #     await interaction.channel.send(embed=msg_embed)
    #     return

    # title = "Select a role to remove their bot configuration permissions."
    # values_list = [int(v) for v in config_roles.split(',')]
    # descriptor_list = [get_role_name(interaction.guild.roles, v) for v in values_list]
    # role_id = await menu.get_menu_input(interaction, values_list, descriptor_list, title)

    # role_name = get_role_name(interaction.guild.roles, role_id)
    # values_list.remove(role_id)
    # config_roles = ','.join(str(v) for v in values_list)

    # conn = create_connection()
    # cur = conn.cursor()
    # try:
    #     sql = "UPDATE guilds SET config_roles = ? WHERE id = ?"
    #     params = (config_roles, guild_id)
    #     cur.execute(sql, params)
    #     conn.commit()

    #     msg_embed = get_basic_embed(f"Successfully removed '{role_name}''s permission to alter bot settings.")
    #     await interaction.channel.send(embed=msg_embed)
    # except Exception as e:
    #     print(f"Failed to remove a role from config_roles for guild: {guild_id} - Error - {e}")
    # finally:
    #     conn.close()
    return


async def _count_channel_history(channel: discord.abc.GuildChannel, users, after: datetime.datetime = None):
    async for message in channel.history(limit=None, after=after):
        if message.author.bot:
            continue

        if message.author.id not in users.keys():
            users[message.author.id] = 1
        else:
            users[message.author.id] += 1


@client.tree.command(name="d", description="Roll a die with the given number of sides", extras={"behave_as_message": True})
@app_commands.describe(sides='Number of sides on the die')
async def dice_roll(interaction: discord.Interaction, sides: int):
    if not await verify_slow_mode(interaction):
        return

    user = interaction.user
    roll_result = randint(1, sides)

    msg_embed = get_basic_embed(f"```🎲 {roll_result}```")
    msg_embed.set_author(name=f"{user.name} rolls d{sides}", icon_url=user.avatar)
    await interaction.response.send_message(embed=msg_embed)
    msg = await interaction.original_response()

    stat_mapping = get_stat_mapping(interaction.guild.id)
    if stat_mapping:
        stat_cols = get_stat_col(interaction.channel, stat_mapping, "Dice", DiceType=sides, DiceResult=roll_result)
        if stat_cols:
            await msg.add_reaction('🎉')
            for col in stat_cols:
                update_user_stat(user.id, interaction.guild.id, col, "increment")


@client.tree.command(name='leaderboard', description="View a leaderboard", extras={"behave_as_message": True})
@app_commands.describe(leaderboard_id='Id of the leaderboard you wish to view')
async def leaderboard(interaction: discord.Interaction, leaderboard_id: Optional[int] = None):
    if not await verify_slow_mode(interaction):
        return

    if leaderboard_id is not None:
        await display_leaderboard(interaction, leaderboard_id)
        return

    default_leaderboard = get_default_leaderboard(interaction.guild.id)
    if default_leaderboard:
        await display_leaderboard(interaction, default_leaderboard)
        return

    stat_mapping = get_stat_mapping(interaction.guild.id)
    num_stats = len(stat_mapping['Mapping'])
    if num_stats == 1:
        await display_leaderboard(interaction, 1)
        return

    i = 1
    menu_options = []
    for stat in stat_mapping['Mapping']:
        menu_options.append(menu.SelectOption(f'{i}. {get_stat_description(stat, interaction.guild.id)}',
                                              display_leaderboard,
                                              {'leaderboard_id': i, 'interaction': interaction},
                                              i - 1))
        i += 1

    await run_select_menu(interaction, menu_options, 'Select Leaderboard:', True)


@client.tree.command(name='config', description="Configure the bot")
@app_commands.default_permissions()
async def start_config(interaction: discord.Interaction):
    menu_options = [
        menu.SelectOption('Manage tracked stats', manage_stats, {'interaction': interaction}, 0),
        menu.SelectOption('Change default leaderboard', change_default_leaderboard, {'interaction': interaction}, 1),
        menu.SelectOption('Change who can alter configuration options', manage_permissions, {'interaction': interaction}, 2)
    ]
    await run_select_menu(interaction, menu_options, "Configuration Options:", True)


@client.tree.command(name='getguildid', description="Get the current guild's ID")
@app_commands.default_permissions()
async def display_guild_id(interaction: discord.Interaction):
    await reply(interaction, interaction.guild_id, ephemeral=True)


@client.tree.command(name='getcategoryid', description="Get the current category's ID")
@app_commands.default_permissions()
async def display_category_id(interaction: discord.Interaction):
    await reply(interaction, interaction.channel.category_id, ephemeral=True)


@client.tree.command(name='getchannelid', description="Get the current channel's ID")
@app_commands.default_permissions()
async def display_channel_id(interaction: discord.Interaction):
    await reply(interaction, interaction.channel_id, ephemeral=True)


@client.tree.command(name='getuserid', description="Get your user ID")
@app_commands.default_permissions()
async def display_user_id(interaction: discord.Interaction):
    await reply(interaction, interaction.user.id, ephemeral=True)


@client.tree.command(name="stats", description="Display the currently tracked stats", extras={"behave_as_message": True})
async def display_tracked_stats(interaction: discord.Interaction):
    if not await verify_slow_mode(interaction):
        return
    await reply(interaction, get_server_stats_string(interaction.guild_id, get_stat_mapping(interaction.guild_id)), "Tracked stats:")


# May be good to put in some type of limit to each message history counter.
# Holding the users object in memory may not work for really large servers with many users.
@client.tree.command(name='countchannelhistory', description="Count the number of historical messages in the current channel")
@app_commands.describe(after='Count history for messages sent after this datetime. UTC datetime in format: YYYY-mm-dd hh:MM')
@app_commands.default_permissions()
async def count_channel_history(interaction: discord.Interaction, after: Optional[str] = None):
    channel_id = interaction.channel_id
    channel = interaction.guild.get_channel(channel_id)
    if channel is None:
        await reply(interaction, f"Channel with ID '{channel_id}' not found. Cannot count history.", ephemeral=True)
        return

    after_datetime = None
    if after is not None:
        try:
            after_datetime = datetime.datetime.strptime(after, "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            await reply(interaction, "Invalid 'after' datetime given. Please verify format is YYYY-mm-dd hh:MM")
            return

    stat_mapping = get_stat_mapping(interaction.guild_id)
    if stat_mapping:
        stat_cols = get_stat_col(channel, stat_mapping, "total_messages", ChannelOnly=True)
        if stat_cols:
            await interaction.response.defer(ephemeral=True, thinking=True)
            users = {}
            await _count_channel_history(channel, users, after_datetime)
            for col in stat_cols:
                for user, user_val in users.items():
                    update_user_stat(user, channel.guild.id, col, user_val)
            await reply(interaction, "Successfully counted channel history.", ephemeral=True)
        else:
            await reply(interaction, f"Messages in channel '{channel.name}' are not tracked. Try config to start tracking.", ephemeral=True)


@client.tree.command(name='countcategoryhistory', description="Count the number of historical messages in the current category")
@app_commands.describe(after='Count history for messages sent after this datetime. UTC datetime in format: YYYY-mm-dd hh:MM')
@app_commands.default_permissions()
async def count_category_history(interaction: discord.Interaction, after: Optional[str] = None):
    category_id = interaction.channel.category_id
    if category_id is None:
        reply(interaction, "This channel is not part of any category. Cannot count category message history.")
        return

    after_datetime = None
    if after is not None:
        try:
            after_datetime = datetime.datetime.strptime(after, "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            await reply(interaction, "Invalid 'after' datetime given. Please verify format is YYYY-mm-dd hh:MM")
            return

    category = None
    for category_it in interaction.guild.categories:
        if category_it.id == category_id:
            category = category_it
            break

    if category is None:
        reply(interaction, f"Category with ID '{category_id}' not found. Cannot count history.")
        return

    channel = category.channels[0]
    stat_mapping = get_stat_mapping(interaction.guild_id)
    if stat_mapping:
        stat_cols = get_stat_col(channel, stat_mapping, "total_messages", CategoryOnly=True)
        if stat_cols:
            await interaction.response.defer(ephemeral=True, thinking=True)
            users = {}
            for channel in channel.category.text_channels:
                await _count_channel_history(channel, users, after_datetime)
            for col in stat_cols:
                for user, user_val in users.items():
                    update_user_stat(user, channel.guild.id, col, user_val)
            await reply(interaction, "Successfully counted category history.", ephemeral=True)
        else:
            await reply(interaction, f"Messages in category '{category.name}' are not tracked. Try config to start tracking.")


@client.tree.command(name='countguildhistory', description="Count the number of historical messages in the guild")
@app_commands.describe(after='Count history for messages sent after this datetime. UTC datetime in format: YYYY-mm-dd hh:MM')
@app_commands.default_permissions()
async def count_guild_history(interaction: discord.Interaction, after: Optional[str] = None):
    after_datetime = None
    if after is not None:
        try:
            after_datetime = datetime.datetime.strptime(after, "%Y-%m-%d %H:%M").replace(tzinfo=datetime.timezone.utc)
        except ValueError:
            await reply(interaction, "Invalid 'after' datetime given. Please verify format is YYYY-mm-dd hh:MM")
            return

    stat_mapping = get_stat_mapping(interaction.guild_id)
    if stat_mapping:
        stat_cols = get_stat_col(interaction.channel, stat_mapping, "total_messages", GuildOnly=True)
        if stat_cols:
            await interaction.response.defer(ephemeral=True, thinking=True)
            users = {}
            for channel in interaction.guild.text_channels:
                await _count_channel_history(channel, users, after_datetime)
            for col in stat_cols:
                for user, user_val in users.items():
                    update_user_stat(user, interaction.guild_id, col, user_val)
            await reply(interaction, "Successfully counted guild history.", ephemeral=True)
        else:
            await reply(interaction, "Total server messages not tracked. Try config to start tracking.")


@client.tree.command(name='emojis', description="View a leaderboard of the most popular server emojis", extras={"behave_as_message": True})
@app_commands.describe(show_all='View all emojis')
async def display_emoji_leaderboard(interaction: discord.Interaction, show_all: Optional[bool] = None):
    conn = create_connection()
    cur = conn.cursor()
    sql = f"SELECT emote_id, emote_count FROM guilds_emotes WHERE guild_id = ? ORDER BY emote_count DESC {'' if show_all else 'LIMIT 10'}"
    cur.execute(sql, (interaction.guild.id,))
    rows = cur.fetchall()

    desc = ""
    i = 1
    for row in rows:
        try:
            emoji = await interaction.guild.fetch_emoji(row[0])
            emoji_name = emoji.name
            emoji_id = emoji.id
        except discord.errors.NotFound:
            emoji_name = "DELETED"
            emoji_id = None

        if emoji_id is not None:
            desc += f"**{i}.** <:{emoji_name}:{emoji_id}> {emoji_name} - {row[1]}\n"
        else:
            desc += f"**{i}.** {emoji_name} - {row[1]}\n"
        i += 1

    await reply(interaction, desc, "Emoji Leaderboard")


client.run(config_vars['BOT_TOKEN'])
