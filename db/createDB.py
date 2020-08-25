import sqlite3
import os
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

def main():
    database = os.getcwd() + "\leaderboards.db"

    sql_create_users_table = """CREATE TABLE users (
                                    user_id text PRIMARY KEY,
                                    created_date text DEFAULT (strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime')),
                                    updated_date text DEFAULT (strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime')),
                                    score integer default 0,
                                    total_messages integer default 0
                                ); """

    sql_create_users_update_trigger = """
                                CREATE TRIGGER update_users_updated_date BEFORE UPDATE ON users
                                begin
                                    UPDATE users SET updated_date = strftime('%Y-%m-%d %H:%M:%S:%s','now', 'localtime') where user_id = old.user_id;
                                end """

    conn = create_connection(database)

    if conn is not None:
        execute_sql(conn, sql_create_users_table)
        execute_sql(conn, sql_create_users_update_trigger)
        conn.commit()
    else:
        print("Error! cannot create the database connection.")

    conn.close()
    return


if __name__ == '__main__':
    main()
