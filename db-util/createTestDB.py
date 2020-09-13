from os import getcwd
from os.path import join, dirname
from createDB import create_db
create_db(join(dirname(getcwd()), "db", "dev_leaderboards.db")))
