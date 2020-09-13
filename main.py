import discord
import os
from random import randint
import re
import sqlite3
from json import loads, dumps
import asyncio
from config.env_vars import prod_vars, dev_vars

REACT_MENU_OPTIONS = ['1️⃣', '2️⃣', '3️⃣', '4️⃣', '5️⃣', '6️⃣', '7️⃣', '8️⃣', '9️⃣']
BLANK_SPACE = '\u200B'

""" TO DO LIST
 - Implement proper logging to log files.
 - Track last time !count_history was used, limit to once a week or something like that.
 - Create a help function - this may involve turning commands into a dictionary with a help attribute, options, etc.
 - Develop more stats to track (Regex message matching? or just simple message matching?)
 - Possible get_from_guild function to reduce repeat code between stuff like get_stat_mapping and get_config_roles
 - Create proper migration method for database
 - Write testing library
"""


def cleanse_string(string):
    bad_string = False
    i = 0
    while i < len(string) and not bad_string:
        char = string[i]
        if not char.isalnum() or not char == '_':
            bad_string = True
        i += 1

    return "".join(char for char in string if char.isalnum() or char == '_'), bad_string


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


class LeaderboardsBot(discord.Client):

    def __init__(self, config_settings, **options):
        self.db_path = config_settings['DB_PATH']
        self.bot_color = config_settings['BOT_COLOR']
        self.max_stats_per_guild = config_settings['MAX_STATS_PER_GUILD']
        super().__init__(**options)

    def create_connection(self):
        conn = None
        try:
            conn = sqlite3.connect(self.db_path)
            return conn
        except sqlite3.Error as e:
            print(e)

        return conn

    def update_user_stat(self, user_id, guild_id, stat_col, value):
        conn = self.create_connection()
        cur = conn.cursor()

        try:
            if value == 'increment':
                sql = """   INSERT INTO guilds_users(guild_id, user_id, {0}) VALUES(?,?,1) 
                            ON CONFLICT(guild_id, user_id) DO UPDATE 
                            SET {0} = {0} + 1 
                            WHERE guild_id = ? AND user_id = ?
                        """.format(stat_col)
                params = (guild_id, user_id, guild_id, user_id)
            else:
                sql = """   INSERT INTO guilds_users(guild_id, user_id, {0}) VALUES(?,?,?) 
                            ON CONFLICT(guild_id, user_id) DO UPDATE 
                            SET {0} = ? 
                            WHERE guild_id = ? AND user_id = ?
                        """.format(stat_col)
                params = (guild_id, user_id, value, value, guild_id, user_id)

            cur.execute(sql, params)
            conn.commit()
        except Exception as e:
            print("Failed to update {} for guild: {} and user {}\n\tError - {}".format(stat_col, guild_id, user_id, e))
        finally:
            conn.close()
        return

    def get_config_roles(self, guild_id):
        conn = self.create_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT config_roles FROM guilds WHERE id = ?", (guild_id,))
            rows = cur.fetchall()
            if rows:
                return rows[0][0]
            else:
                return None
        except Exception as e:
            print("Error getting config_roles from guild with id: {}\n\t Error: {}".format(guild_id, e))
        finally:
            conn.close()
        return

    def get_stat_mapping(self, guild_id):
        conn = self.create_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT stat_mapping FROM guilds WHERE id = ?", (guild_id,))
            rows = cur.fetchall()
            if rows:
                return loads(rows[0][0])
            else:
                return None
        except Exception as e:
            print("Error getting stat mapping from guild with id: {}\n\t Error: {}".format(guild_id, e))
        finally:
            conn.close()
        return

    def get_basic_embed(self, msg):
        return discord.Embed(color=self.bot_color, description=msg)

    def on_message_retrieve_guild_data(self, guild_id, retry=False):
        conn = self.create_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT stat_mapping, command_prefix, config_roles FROM guilds WHERE id = ?", (guild_id,))
            rows = cur.fetchall()
            if rows:
                config_roles = rows[0][2]
                if not config_roles:
                    config_roles = []
                else:
                    config_roles = [int(v) for v in config_roles.split(',')]
                return loads(rows[0][0]), rows[0][1], config_roles
            elif not retry:
                cur.execute("INSERT INTO guilds(id) VALUES (?)", (guild_id,))
                conn.commit()
                return self.on_message_retrieve_guild_data(guild_id, retry=True)
            else:
                raise Exception(
                    "Attempted to initialize guild id {} in database and still no data on retry.".format(guild_id))
        except Exception as e:
            print("Error retrieving guild data for guild id: {}\n\t Error: {}".format(guild_id, e))
        finally:
            conn.close()

    def get_stat_description(self, stat, guild_id):
        stat_desc = ""
        if stat['Type'] == 'total_messages':
            stat_desc = "Total messages"
        elif stat['Type'] == 'Dice':
            stat_desc = "{}'s rolled by d{}".format(stat['Target'], stat['DiceType'])

        stat_desc += " "

        if stat['Level'] == 'Guild':
            stat_desc += "server-wide"
        elif stat['Level'] == 'Category':
            cat_name = ""
            for cat in self.get_guild(guild_id).categories:
                if cat.id == stat['LevelID']:
                    cat_name = cat.name
                    break
            stat_desc += "in Category '{}'".format(cat_name)
        elif stat['Level'] == 'Channel':
            stat_desc += "in Channel '{}'".format(self.get_channel(stat['LevelID']).name)

        return stat_desc

    def get_server_stats_string(self, guild_id, stat_mapping):
        if len(stat_mapping['Mapping']) == 0:
            retval = "There are no stats currently being tracked. Try !config to start tracking."
        else:
            retval = ""
            i = 1
            for stat in stat_mapping['Mapping']:
                stat_desc = self.get_stat_description(stat, guild_id)
                retval += "\n\t**{}.** *{}*".format(i, stat_desc)
                i += 1

        return retval

    def get_default_leaderboard(self, guild_id):
        conn = self.create_connection()
        cur = conn.cursor()
        try:
            cur.execute("SELECT default_leaderboard FROM guilds WHERE id = ?", (guild_id,))
            rows = cur.fetchall()
            if rows:
                return rows[0][0]
            else:
                return None
        except Exception as e:
            print("Error getting default leaderboard from guild with id: {}\n\t Error: {}".format(guild_id, e))
        finally:
            conn.close()
        return

    def get_role_name(self, guild_roles, role_id):
        retval = None
        for role in guild_roles:
            if role.id == role_id:
                retval = role.name
                break

        return retval

    def user_has_config_role(self, user, config_roles):
        retval = False
        try:
            for role in user.roles:
                if role.id in config_roles:
                    retval = True
                    break
        except Exception as e:
            print("Could not check user roles for user id {}".format(user.id))
        finally:
            return retval

    async def display_leaderboard(self, message, args):
        stat_num = None
        if not args:
            default_leaderboard = self.get_default_leaderboard(message.guild.id)
            if default_leaderboard:
                stat_num = str(default_leaderboard)
            else:
                stat_mapping = self.get_stat_mapping(message.guild.id)
                num_stats = len(stat_mapping['Mapping'])
                if num_stats == 1:
                    await self.display_leaderboard(message, '1')
                else:
                    server_stats_string = self.get_server_stats_string(message.guild.id, stat_mapping)

                    msg_embed = self.get_basic_embed("{}".format(server_stats_string))
                    msg_embed.title = 'Select Leaderboard:'
                    msg = await message.channel.send(embed=msg_embed)
                    for i in range(num_stats):
                        await msg.add_reaction(REACT_MENU_OPTIONS[i])

                    def _check(_reaction, _user):
                        return _user == message.author and str(_reaction.emoji) in REACT_MENU_OPTIONS[:num_stats]

                    try:
                        reaction, user = await self.wait_for('reaction_add', timeout=30, check=_check)
                    except asyncio.TimeoutError:
                        await msg.delete()
                    else:
                        await msg.delete()
                        await self.display_leaderboard(message, str(REACT_MENU_OPTIONS.index(str(reaction.emoji)) + 1))

                return

        if stat_num is None:
            stat_num = args[0]
        stat_mapping = self.get_stat_mapping(message.guild.id)
        display_stat = None
        for stat in stat_mapping['Mapping']:
            if stat['StatCol'][4:] == stat_num:
                display_stat = stat
                break

        if display_stat is None:
            msg_embed = self.get_basic_embed("Invalid argument '{}' to command 'leaderboard'.".format(stat_num))
            await message.channel.send(embed=msg_embed)
            return

        stat_desc = self.get_stat_description(display_stat, message.guild.id)
        clean_arg, bad_string = cleanse_string(stat_num)

        conn = self.create_connection()
        cur = conn.cursor()
        sql = "SELECT user_id, {0} FROM guilds_users ORDER BY {0} DESC LIMIT 10".format("stat" + clean_arg)
        cur.execute(sql)
        rows = cur.fetchall()

        desc = ""
        i = 1
        for row in rows:
            try:
                user = await self.fetch_user(row[0])
                username = user.name
            except discord.errors.NotFound:
                username = "DELETED"

            desc += "**{}.** {} - {}\n".format(i, username, row[1])
            i += 1

        msg_embed = self.get_basic_embed(desc)
        msg_embed.title = "Leaderboard: *{}*".format(stat_desc)
        await message.channel.send(embed=msg_embed)

        return

    async def dice_roll(self, message):
        dice_type = int(re.search('^!d\d{1,10}', message.content.lower()).group()[2:])
        roll_result = randint(1, dice_type)

        msg_embed = self.get_basic_embed("```🎲 {}```".format(roll_result))
        msg_embed.set_author(name="{} rolls d{}".format(message.author.name, dice_type), icon_url=message.author.avatar_url)
        msg = await message.channel.send(embed=msg_embed)

        stat_mapping = self.get_stat_mapping(message.guild.id)
        if stat_mapping:
            stat_cols = get_stat_col(message.channel, stat_mapping, "Dice", DiceType=dice_type, DiceResult=roll_result)
            if stat_cols:
                await msg.add_reaction('🎉')
                for col in stat_cols:
                    self.update_user_stat(message.author.id, message.guild.id, col, "increment")

        return

    async def _count_channel_history(self, channel, users):
        async for message in channel.history(limit=None):
            if message.author.bot:
                continue

            if message.author.id not in users.keys():
                users[message.author.id] = 1
            else:
                users[message.author.id] += 1

    # May be good to put in some type of limit to each message history counter.
    # Holding the users object in memory may not work for really large servers with many users.
    async def count_channel_history(self, message, args):
        if not args:
            channel = message.channel
        else:
            try:
                channel_id = int(args[0])
            except ValueError:
                channel_id = None
            channel = message.guild.get_channel(channel_id)
            if channel is None:
                msg_embed = self.get_basic_embed("Channel with ID '{}' not found. Cannot count history.".format(args[0]))
                await message.channel.send(embed=msg_embed)
                return

        stat_mapping = self.get_stat_mapping(message.guild.id)
        if stat_mapping:
            stat_cols = get_stat_col(channel, stat_mapping, "total_messages", ChannelOnly=True)
            if stat_cols:
                async with message.channel.typing():
                    users = {}
                    await self._count_channel_history(channel, users)
                    for col in stat_cols:
                        for user in users.keys():
                            self.update_user_stat(user, channel.guild.id, col, users[user])
                    await self.display_leaderboard(message, stat_cols[0][4:])
            else:
                msg_embed = self.get_basic_embed("Messages in channel '{}' are not tracked. Try !config to start tracking.".format(channel.name))
                await message.channel.send(embed=msg_embed)

        return

    async def count_category_history(self, message, args):
        if not args:
            channel = message.channel
        else:
            channel = None
            try:
                category_id = int(args[0])
                for category in message.guild.categories:
                    if category.id == category_id:
                        channel = category.text_channels[0]
            except ValueError:
                pass

            if channel is None:
                msg_embed = self.get_basic_embed("Category with ID '{}' not found. Cannot count history.".format(args[0]))
                await message.channel.send(embed=msg_embed)
                return

        if channel.category is None:
            msg_embed = self.get_basic_embed("This channel is not part of any category. Cannot count category message history.")
            await message.channel.send(embed=msg_embed)
            return

        stat_mapping = self.get_stat_mapping(channel.guild.id)
        if stat_mapping:
            stat_cols = get_stat_col(channel, stat_mapping, "total_messages", CategoryOnly=True)
            if stat_cols:
                async with message.channel.typing():
                    users = {}
                    for channel in channel.category.text_channels:
                        await self._count_channel_history(channel, users)
                    for col in stat_cols:
                        for user in users.keys():
                            self.update_user_stat(user, channel.guild.id, col, users[user])
                    await self.display_leaderboard(message, stat_cols[0][4:])
            else:
                msg_embed = self.get_basic_embed("Messages in category '{}' are not tracked. Try !config to start tracking.".format(channel.category.name))
                await message.channel.send(embed=msg_embed)
        return

    async def count_guild_history(self, message):
        channel = message.channel
        stat_mapping = self.get_stat_mapping(channel.guild.id)
        if stat_mapping:
            stat_cols = get_stat_col(channel, stat_mapping, "total_messages", GuildOnly=True)
            if stat_cols:
                async with channel.typing():
                    users = {}
                    for channel in channel.guild.text_channels:
                        await self._count_channel_history(channel, users)
                    for col in stat_cols:
                        for user in users.keys():
                            self.update_user_stat(user, channel.guild.id, col, users[user])
                    await self.display_leaderboard(message, stat_cols[0][4:])
            else:
                msg_embed = self.get_basic_embed('Total server messages not tracked. Try !config to start tracking.')
                await channel.send(embed=msg_embed)
        return

    async def display_tracked_stats(self, channel, guild_id):
        msg_embed = self.get_basic_embed("{}".format(self.get_server_stats_string(guild_id, self.get_stat_mapping(guild_id))))
        msg_embed.title = "Tracked Stats:"
        await channel.send(embed=msg_embed)
        return

    async def display_config_roles(self, message):
        config_roles = self.get_config_roles(message.guild.id)
        if not config_roles:
            msg_embed = self.get_basic_embed("No roles have been granted permissions to alter bot settings.")
            await message.channel.send(embed=msg_embed)
            return

        description = ''
        i = 1
        role_ids = [int(v) for v in config_roles.split(',')]
        for role_id in role_ids:
            description += "\n\t**{}.** *{}*".format(i, self.get_role_name(message.guild.roles, role_id))
            i += 1

        msg_embed = self.get_basic_embed(description)
        msg_embed.title = "Permitted roles:"
        await message.channel.send(embed=msg_embed)
        return

    async def setup_menu(self, message, descriptor_list, title, page_offset):
        next_page_button = False
        previous_page_button = False
        description = ""
        i = 1 + page_offset
        while i <= min(len(descriptor_list), 9 + page_offset):
            description += "**{}.** *{}*\n".format(i - page_offset, descriptor_list[i - 1])
            i += 1

        if page_offset > 0:
            description += "\n⏮️ Previous Page"
            previous_page_button = True
        if len(descriptor_list) > 9 + page_offset:
            description += "\n⏭️ Next Page"
            next_page_button = True

        msg_embed = self.get_basic_embed(description)
        msg_embed.title = title
        msg = await message.channel.send(embed=msg_embed)

        num_options = min(len(descriptor_list) - page_offset, 9)
        for i in range(num_options):
            await msg.add_reaction(REACT_MENU_OPTIONS[i])

        if previous_page_button:
            await msg.add_reaction('⏮️')
        if next_page_button:
            await msg.add_reaction('⏭️')

        def _check(_reaction, _user):
            return _user == message.author and _reaction.message.id == msg.id and \
                   (str(_reaction.emoji) in REACT_MENU_OPTIONS[:num_options] or
                    (next_page_button and str(_reaction.emoji) == '⏭️') or
                    (previous_page_button and str(_reaction.emoji) == '⏮️'))

        return msg, _check

    async def run_menu(self, message, functions_list, args_list, descriptor_list, title, page_offset=0):
        msg, _check = await self.setup_menu(message, descriptor_list, title, page_offset)

        try:
            reaction, user = await self.wait_for('reaction_add', timeout=30, check=_check)
        except asyncio.TimeoutError:
            await msg.delete()
        else:
            await msg.delete()
            try:
                func_num = REACT_MENU_OPTIONS.index(str(reaction.emoji))
                await functions_list[func_num + page_offset](message, **args_list[func_num + page_offset])
            except ValueError:
                await self.run_menu(message, functions_list, args_list, descriptor_list, title,
                                    page_offset + 9 if str(reaction.emoji) == '⏭️' else page_offset - 9)

        return

    async def get_menu_input(self, message, values_list, descriptor_list, title, page_offset=0):
        retval = None
        msg, _check = await self.setup_menu(message, descriptor_list, title, page_offset)

        try:
            reaction, user = await self.wait_for('reaction_add', timeout=30, check=_check)
        except asyncio.TimeoutError:
            await msg.delete()
        else:
            await msg.delete()
            try:
                value_num = REACT_MENU_OPTIONS.index(str(reaction.emoji))
                retval = values_list[value_num + page_offset]
            except ValueError:
                retval = await self.get_menu_input(message, values_list, descriptor_list, title,
                                                   page_offset + 9 if str(reaction.emoji) == '⏭️' else page_offset - 9)

        return retval

    async def get_message_input(self, message, description, help_text, target_regex, check_function=None, invalid_input=None):
        retval = None

        msg_embed = self.get_basic_embed(description)
        msg_embed.set_footer(text=help_text)
        if invalid_input:
            msg_embed.description = "Try again, invalid input: {}\n".format(invalid_input) + msg_embed.description
        sent_message = await message.channel.send(embed=msg_embed)

        def _check(_msg):
            return _msg.author == message.author and _msg.channel == message.channel

        try:
            response = await self.wait_for('message', timeout=30, check=_check)
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
                retval = await self.get_message_input(message, description, help_text, target_regex, check_function, response.content)

        return retval

    async def start_config(self, message):
        menu_functions = [self.manage_stats, self.change_command_prefix, self.change_default_leaderboard,
                          self.manage_permissions]
        args_list = [{}, {}, {}, {}]
        descriptor_list = ['Manage tracked stats', 'Change command prefix', 'Change default leaderboard',
                           'Change who can alter configuration options']
        title = "Configuration Options:"

        await self.run_menu(message, menu_functions, args_list, descriptor_list, title)
        return

    async def manage_stats(self, message):
        menu_functions = [self.add_stat, self.delete_stat]
        args_list = [{}, {}]
        descriptor_list = ['Track a new stat', 'Delete a tracked stat']
        title = "Manage Tracked Stats:"

        await self.run_menu(message, menu_functions, args_list, descriptor_list, title)
        return

    async def add_stat(self, message):
        menu_functions = [self.choose_stat_level, self.setup_die]
        args_list = [{"Type": "total_messages"}, {}]
        descriptor_list = ['Total messages', "Dice roll"]
        title = "Select Stat Type:"

        await self.run_menu(message, menu_functions, args_list, descriptor_list, title)
        return

    async def setup_die(self, message):
        description = "Enter the dice type you would like in a message below."
        help_text = "I.e. type '6' for a standard six sided die."
        target_regex = '\d{1,10}'
        dice_type = await self.get_message_input(message, description, help_text, target_regex)
        if dice_type is None:
            return
        else:
            dice_type = int(dice_type)

        def _target_check_function(val):
            return val.isdigit() and 1 <= int(val) <= dice_type

        description = "Enter the die's target value. Must be between 1 and {}.".format(dice_type)
        help_text = "I.e. type '1' to track when people roll 1 with this die."
        target_regex = '\d{1,10}'
        target = await self.get_message_input(message, description, help_text, target_regex, _target_check_function)
        if target is None:
            return
        else:
            target = int(target)

        stat_obj = {"Type": "Dice", "DiceType": dice_type, "Target": target}
        await self.choose_stat_level(message, **stat_obj)
        return

    async def choose_stat_level(self, message, **stat_obj):
        menu_functions = [self.guild_level, self.category_level, self.channel_level]
        args_list = [stat_obj, stat_obj, stat_obj]
        descriptor_list = ['Track across entire server', "Track only in a category of channels", "Track only in one channel"]
        title = "Select where the stat is tracked:"

        await self.run_menu(message, menu_functions, args_list, descriptor_list, title)
        return

    async def guild_level(self, message, **stat_obj):
        stat_obj['Level'] = 'Guild'
        await self.add_stat_to_db(message, stat_obj)
        return

    async def category_level(self, message, **stat_obj):
        title = "Select the category you would like this stat to be tracked in:"
        values_list = [category.id for category in message.guild.categories]
        descriptor_list = [category.name for category in message.guild.categories]

        category_id = await self.get_menu_input(message, values_list, descriptor_list, title)
        stat_obj['Level'] = 'Category'
        stat_obj['LevelID'] = category_id
        await self.add_stat_to_db(message, stat_obj)
        return

    async def channel_level(self, message, **stat_obj):
        title = "Select the channel you would like this stat to be tracked in:"
        values_list = [channel.id for channel in message.guild.text_channels]
        descriptor_list = [channel.name for channel in message.guild.text_channels]

        channel_id = await self.get_menu_input(message, values_list, descriptor_list, title)
        stat_obj['Level'] = 'Channel'
        stat_obj['LevelID'] = channel_id
        await self.add_stat_to_db(message, stat_obj)
        return

    async def add_stat_to_db(self, message, stat_obj):
        guild_id = message.guild.id
        stat_mapping = self.get_stat_mapping(guild_id)
        num_stats = len(stat_mapping['Mapping'])
        if num_stats >= self.max_stats_per_guild:
            msg_embed = self.get_basic_embed("Cannot add stat. Server already tracking maximum number of stats ({}). Delete an existing stat to add another.".format(self.max_stats_per_guild))
            await message.channel.send(embed=msg_embed)
            return

        statcol = "stat{}".format(num_stats + 1)
        stat_obj['StatCol'] = statcol
        stat_mapping['Mapping'].append(stat_obj)
        stat_str = dumps(stat_mapping)

        conn = self.create_connection()
        cur = conn.cursor()
        try:
            sql = "UPDATE guilds SET stat_mapping = ? WHERE id = ?"
            params = (stat_str, guild_id)
            cur.execute(sql, params)
            conn.commit()

            msg_embed = self.get_basic_embed("Successfully added new stat: {}".format(self.get_stat_description(stat_obj, guild_id)))
            await message.channel.send(embed=msg_embed)
        except Exception as e:
            print("Failed to update stat_mapping for guild: {} - Error - {}".format(guild_id, e))
        finally:
            conn.close()
        return

    async def delete_stat(self, message):
        guild_id = message.guild.id
        stat_mapping = self.get_stat_mapping(guild_id)
        num_stats = len(stat_mapping['Mapping'])
        if num_stats == 0:
            msg_embed = self.get_basic_embed("There are no stats currently being tracked, you cannot delete a stat.")
            await message.channel.send(embed=msg_embed)
            return

        title = "Select which stat to delete:"
        values_list = []
        descriptor_list = []
        for stat in stat_mapping['Mapping']:
            values_list.append(stat['StatCol'])
            descriptor_list.append(self.get_stat_description(stat, guild_id))

        delete_stat_col = await self.get_menu_input(message, values_list, descriptor_list, title)
        if delete_stat_col is None:
            return

        delete_stat_col_num = int(delete_stat_col[4:])

        i = 0
        for stat in stat_mapping['Mapping']:
            if stat['StatCol'] == delete_stat_col:
                stat_mapping['Mapping'].pop(i)
                break
            i += 1

        for stat in stat_mapping['Mapping']:
            stat_col_num = int(stat['StatCol'][4:])
            if stat_col_num > delete_stat_col_num:
                stat['StatCol'] = 'stat{}'.format(stat_col_num - 1)

        default_leaderboard = self.get_default_leaderboard(guild_id)
        stat_str = dumps(stat_mapping)
        conn = self.create_connection()
        cur = conn.cursor()

        try:
            if default_leaderboard > delete_stat_col_num:
                cur.execute("UPDATE guilds SET default_leaderboard = default_leaderboard - 1 WHERE id = ?", (guild_id,))
            elif default_leaderboard == delete_stat_col_num:
                cur.execute("UPDATE guilds SET default_leaderboard = NULL WHERE id = ?", (guild_id,))

            sql = """UPDATE guilds SET stat_mapping = ? WHERE id = ?"""
            params = (stat_str, guild_id)
            cur.execute(sql, params)

            params = (guild_id,)
            for i in range(delete_stat_col_num, num_stats):
                sql = """UPDATE guilds_users SET stat{} = stat{} WHERE guild_id = ?""".format(i, i + 1)
                cur.execute(sql, params)

            sql = """UPDATE guilds_users SET stat{} = 0 WHERE guild_id = ?""".format(num_stats)
            cur.execute(sql, params)

            conn.commit()
            msg_embed = self.get_basic_embed("Successfully deleted stat {}.".format(delete_stat_col_num))
            await message.channel.send(embed=msg_embed)
        except Exception as e:
            print("Failed to delete a stat and realign stats for guild: {} - Deleted stat num: {}\n\tError - {}".format(guild_id, delete_stat_col_num, e))
        finally:
            conn.close()

        return

    async def change_command_prefix(self, message):
        description = "Enter a character to use as the command prefix."
        target_regex = "^\S"
        new_prefix = await self.get_message_input(message, description, "", target_regex)

        conn = self.create_connection()
        cur = conn.cursor()
        try:
            sql = """UPDATE guilds SET command_prefix = ? WHERE id = ?"""
            params = (new_prefix, message.guild.id)
            cur.execute(sql, params)
            conn.commit()

            msg_embed = self.get_basic_embed("Command prefix changed to '{}' successfully.".format(new_prefix))
            await message.channel.send(embed=msg_embed)
        except Exception as e:
            print("Failed to change command character for guild: {}\n\tError - {}".format(message.guild.id, e))
        finally:
            conn.close()

        return

    async def change_default_leaderboard(self, message):
        guild_id = message.guild.id
        stat_mapping = self.get_stat_mapping(guild_id)
        if len(stat_mapping['Mapping']) == 0:
            msg_embed = self.get_basic_embed("Cannot change default leaderboard when no stats are tracked. Add a stat first!")
            await message.channel.send(embed=msg_embed)
            return

        title = "Select which stat you would like to be shown in the default leaderboard:"
        values_list = []
        descriptor_list = []
        for stat in stat_mapping['Mapping']:
            descriptor_list.append(self.get_stat_description(stat, guild_id))
            values_list.append(int(stat['StatCol'][4:]))

        default_leaderboard_num = await self.get_menu_input(message, values_list, descriptor_list, title)

        conn = self.create_connection()
        cur = conn.cursor()
        try:
            sql = "UPDATE guilds SET default_leaderboard = ? WHERE id = ?"
            params = (default_leaderboard_num, guild_id)
            cur.execute(sql, params)
            conn.commit()

            msg_embed = self.get_basic_embed("Successfully changed default leaderboard.")
            await message.channel.send(embed=msg_embed)
        except Exception as e:
            print("Failed to update default_leaderboard for guild: {} - Error - {}".format(guild_id, e))
        finally:
            conn.close()
        return

    async def manage_permissions(self, message):
        menu_functions = [self.add_role_to_config_roles, self.delete_role_from_config_roles]
        args_list = [{}, {}]
        descriptor_list = ['Permit a role', "Remove a role's permission"]
        title = "Manage who can configure bot settings:"

        await self.run_menu(message, menu_functions, args_list, descriptor_list, title)
        return

    async def add_role_to_config_roles(self, message):
        title = "Select which role you would like to give permissions."
        values_list = [v.id for v in message.guild.roles]
        descriptor_list = [v.name for v in message.guild.roles]
        role_id = await self.get_menu_input(message, values_list, descriptor_list, title)

        guild_id = message.guild.id
        role_name = self.get_role_name(message.guild.roles, role_id)
        config_roles = self.get_config_roles(guild_id)

        if not config_roles:
            config_roles = str(role_id)
        else:
            config_roles_list = [int(v) for v in config_roles.split(',')]
            if role_id in config_roles_list:
                msg_embed = self.get_basic_embed("The role '{}' can already alter bot settings!".format(role_name))
                await message.channel.send(embed=msg_embed)
                return
            else:
                config_roles += ',' + str(role_id)

        conn = self.create_connection()
        cur = conn.cursor()
        try:
            sql = "UPDATE guilds SET config_roles = ? WHERE id = ?"
            params = (config_roles, guild_id)
            cur.execute(sql, params)
            conn.commit()

            msg_embed = self.get_basic_embed("Successfully enabled '{}' to alter bot settings.".format(role_name))
            await message.channel.send(embed=msg_embed)
        except Exception as e:
            print("Failed to add a role to config_roles for guild: {} - Error - {}".format(guild_id, e))
        finally:
            conn.close()
        return

    async def delete_role_from_config_roles(self, message):
        guild_id = message.guild.id
        config_roles = self.get_config_roles(guild_id)
        if not config_roles:
            msg_embed = self.get_basic_embed("No roles have been granted permissions to alter bot settings. Cannot remove a role's permission.")
            await message.channel.send(embed=msg_embed)
            return

        title = "Select a role to remove their bot configuration permissions."
        values_list = [int(v) for v in config_roles.split(',')]
        descriptor_list = [self.get_role_name(message.guild.roles, v) for v in values_list]
        role_id = await self.get_menu_input(message, values_list, descriptor_list, title)

        role_name = self.get_role_name(message.guild.roles, role_id)
        values_list.remove(role_id)
        config_roles = ','.join(str(v) for v in values_list)

        conn = self.create_connection()
        cur = conn.cursor()
        try:
            sql = "UPDATE guilds SET config_roles = ? WHERE id = ?"
            params = (config_roles, guild_id)
            cur.execute(sql, params)
            conn.commit()

            msg_embed = self.get_basic_embed("Successfully removed '{}''s permission to alter bot settings.".format(role_name))
            await message.channel.send(embed=msg_embed)
        except Exception as e:
            print("Failed to remove a role from config_roles for guild: {} - Error - {}".format(guild_id, e))
        finally:
            conn.close()
        return

    async def on_ready(self):
        print("Logged on: {} - Self.guilds: {}".format(self.user, self.guilds))
        print(self.db_path)
        return

    async def on_message(self, message):
        if message.author.id == self.user.id:
            return

        stat_mapping, command_prefix, config_roles = self.on_message_retrieve_guild_data(message.guild.id)
        if stat_mapping:
            stat_cols = get_stat_col(message.channel, stat_mapping, "total_messages")
            if stat_cols:
                for col in stat_cols:
                    self.update_user_stat(message.author.id, message.guild.id, col, "increment")

        if not message.content.startswith(command_prefix):
            return

        print("Message from {0.author}: {0.content} --- AuthorID: {0.author.id} --- {1.name}, {1.id} --- {2}".format(message, message.channel, message.author.permissions_in(message.channel)))

        command = message.content.lower().split(' ')[0][1:]
        args = message.content.lower().split(' ')[1:]
        has_permission = message.author.permissions_in(message.channel).administrator or self.user_has_config_role(message.author, config_roles)

        if re.match("^d\d{1,10}", command):
            await self.dice_roll(message)
        elif command == 'count_channel_history' and has_permission:
            await self.count_channel_history(message, args)
        elif command == 'count_category_history' and has_permission:
            await self.count_category_history(message, args)
        elif command == 'count_server_history' and has_permission:
            await self.count_guild_history(message)
        elif command == 'leaderboard':
            await self.display_leaderboard(message, args)
        elif command == 'guild_id':
            await message.channel.send(embed=self.get_basic_embed(message.guild.id))
        elif command == 'category_id':
            await message.channel.send(embed=self.get_basic_embed(message.channel.category_id))
        elif command == 'channel_id':
            await message.channel.send(embed=self.get_basic_embed(message.channel.id))
        elif command == 'user_id':
            await message.channel.send(embed=self.get_basic_embed(message.author.id))
        elif command == 'stats':
            await self.display_tracked_stats(message.channel, message.guild.id)
        elif command == 'config':
            await self.start_config(message)
        elif command == 'permitted_roles':
            await self.display_config_roles(message)
        elif command == 'test':
            for i in range(1):
                print(i)
        else:
            msg_embed = self.get_basic_embed("Command '{0}{1}' is not valid. Try {0}help for a list of commands.".format(command_prefix, command))
            await message.channel.send(embed=msg_embed)

        return


if __name__ == '__main__':
    run_env = os.getenv('RUN_ENVIRONMENT')
    if run_env == 'prod':
        config_vars = prod_vars
    else:
        config_vars = dev_vars

    client = LeaderboardsBot(config_vars)
    client.run(config_vars['BOT_TOKEN'])
