import sqlite3
from os import getcwd
from os.path import join, dirname
from sqlite3 import Error


def create_connection(db_file):
    conn = None
    try:
        conn = sqlite3.connect(db_file)
        return conn
    except Error as e:
        print(e)

    return conn


def execute_sql(conn, create_table_sql):
    try:
        c = conn.cursor()
        c.execute(create_table_sql)
    except Error as e:
        print(e)

    return


def create_db(db_path):

    sql_create_guilds_table = """CREATE TABLE guilds (
                                    id integer NOT NULL PRIMARY KEY,
                                    created_date text DEFAULT (strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime')),
                                    updated_date text DEFAULT (strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime')),
                                    config_roles text DEFAULT NULL,
                                    command_prefix text DEFAULT "!",
                                    default_leaderboard integer DEFAULT NULL,
                                    stat_mapping text DEFAULT '{"Mapping":[]}'
                                ); """

    sql_create_guilds_users_table = """CREATE TABLE guilds_users (
                                        guild_id integer NOT NULL,
                                        user_id integer NOT NULL,
                                        created_date text DEFAULT (strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime')),
                                        updated_date text DEFAULT (strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime')),
                                        stat1 integer DEFAULT 0,
                                        stat2 integer DEFAULT 0,
                                        stat3 integer DEFAULT 0,
                                        FOREIGN KEY (guild_id) REFERENCES guilds(id),
                                        PRIMARY KEY (guild_id, user_id)
                                    ); """

    sql_create_guilds_update_trigger = """
                                CREATE TRIGGER update_guilds_updated_date AFTER UPDATE ON guilds
                                begin
                                    UPDATE guilds SET updated_date = strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime') where id = old.id;
                                end """

    sql_create_guilds_users_update_trigger = """
                                CREATE TRIGGER update_guilds_users_updated_date AFTER UPDATE ON guilds_users
                                begin
                                    UPDATE guilds_users SET updated_date = strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime') where guild_id = old.guild_id AND user_id = old.user_id;
                                end """

    conn = create_connection(db_path)

    if conn is not None:
        execute_sql(conn, sql_create_guilds_table)
        execute_sql(conn, sql_create_guilds_users_table)
        execute_sql(conn, sql_create_guilds_update_trigger)
        execute_sql(conn, sql_create_guilds_users_update_trigger)
        conn.commit()
    else:
        print("Error! cannot create the database connection.")

    conn.close()
    return


if __name__ == '__main__':
    create_db(join(dirname(getcwd()), "db", "leaderboards.db"))
    
