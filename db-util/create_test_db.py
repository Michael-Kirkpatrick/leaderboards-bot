""" Create a test environment database """

from os import getcwd
from os.path import join, dirname
from create_db import create_db
create_db(join(dirname(getcwd()), "db", "dev_leaderboards.db"))
