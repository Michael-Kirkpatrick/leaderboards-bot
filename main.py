import discord
import os
from random import randint
from time import gmtime, strftime
import re
import sqlite3
from string import capwords

DB_PATH = os.getcwd() + "\db\leaderboards.db"

""" TO DO LIST
 - Create method of storing server config settings, and then a way for admins to set them up.
    - Need config settings for who can alter config settings (what permissions/roles), default is admins only
    - Need setting for first character to signal command instead of always being "!"
    - Track last time !count_history was used, limit to once a week or something like that.
    - Need to let admins create fields to be tracked, as well as what they track (a dice roll, number of message in a channel or server, etc.)
 - Create a help function

"""


def create_connection(db_file):
    conn = None
    try:
        conn = sqlite3.connect(db_file)
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


def get_display_name(str):
    return capwords(" ".join(str.split('_')))


class LeaderboardsBot(discord.Client):

    def update_user_attribute(self, user_id, attribute, value):
        conn = create_connection(DB_PATH)
        cur = conn.cursor()
        sql = "SELECT user_id FROM users WHERE user_id = ?"
        cur.execute(sql, (str(user_id),))
        rows = cur.fetchall()
        if not rows:
            self.add_user_to_db(cur, user_id)

        clean_attribute, bad_string = cleanse_string(attribute)
        if value == 'increment':
            sql = "UPDATE users SET {0} = {0} + 1 WHERE user_id = ?".format(clean_attribute)
            params = (str(user_id),)
        else:
            sql = "UPDATE users SET {} = ? WHERE user_id = ?".format(clean_attribute)
            params = (value, str(user_id))
        try:
            cur.execute(sql, params)
            conn.commit()
        except Exception:
            print("Failed to update user attribute '{}' - cleansed to '{}'".format(attribute, clean_attribute))
        finally:
            conn.close()
        return

    def add_user_to_db(self, cur, user_id):
        sql = "INSERT INTO users(user_id) VALUES(?)"
        cur.execute(sql, (str(user_id),))
        return

    async def display_leaderboard(self, channel, args):
        if not args:
            await self.send_message(channel, """```Command "!leaderboard" requires an argument for the leaderboard type.\nTry "!leaderboard total_messages".```""")
            return

        attribute_clean = cleanse_string(args[0])[0]
        display_name = get_display_name(attribute_clean)

        leaderboard = """```ml\n{} Leaderboard\n{}\n""".format(display_name, '-' * (len(display_name) + 12))

        conn = create_connection(DB_PATH)
        cur = conn.cursor()
        sql = "SELECT user_id, {0} FROM users ORDER BY {0} DESC LIMIT 10".format(attribute_clean)
        cur.execute(sql)
        rows = cur.fetchall()

        i = 1
        for row in rows:
            try:
                user = await self.fetch_user(row[0])
                username = user.name
            except discord.errors.NotFound:
                username = "DELETED"

            leaderboard += "{}. {} - {}\n".format(i, username, row[1])
            i += 1

        leaderboard += "```"
        await self.send_message(channel, leaderboard)

        return

    async def dice_roll(self, message):
        dice_type = re.search('^!d\d{1,10}', message.content.lower()).group()[1:]
        roll_result = randint(1, int(dice_type[1:]))
        await self.send_message(message.channel, "```py\n{} rolls {}\n> {}```".format(message.author.name, dice_type, roll_result))

        if dice_type == 'd420': # and roll_result == 69:
            self.update_user_attribute(message.author.id, "score", "increment")

        return

    async def send_message(self, channel, message):
        await channel.send(message)

    async def count_history(self, channel):
        users = {}
        async for message in channel.history(limit=None):
            if message.author.bot:
                continue

            if message.author.id not in users.keys():
                users[message.author.id] = 1
            else:
                users[message.author.id] += 1

        for user in users.keys():
            self.update_user_attribute(user, "total_messages", users[user])

        await self.display_leaderboard(channel, ["total_messages"])

        return

    async def on_ready(self):
        print("Logged on: {}".format(self.user))
        return

    async def on_message(self, message):
        if not message.author.bot:
            self.update_user_attribute(message.author.id, "total_messages", "increment")

        if not message.content.startswith('!'):
            return

        print("Message from {0.author}: {0.content} --- AuthorID: {0.author.id} --- {1.name}, {1.id} --- {2}".format(message, message.channel, message.author.permissions_in(message.channel)))

        command = message.content.lower().split(' ')[0]
        args = message.content.lower().split(' ')[1:]
        has_permission = message.author.permissions_in(message.channel).administrator
        if re.match("^!d\d{1,10}", command):
            await self.dice_roll(message)
        elif command == '!count_history' and has_permission:
            await self.count_history(message.channel)
        elif command == '!leaderboard':
            await self.display_leaderboard(message.channel, args)

        return


if __name__ == '__main__':
    client = LeaderboardsBot()
    client.run(os.getenv('LEADERBOARDS_BOT_TOKEN'))
