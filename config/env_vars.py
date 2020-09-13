from os import getcwd, getenv
from os.path import join

prod_vars = {
    'DB_PATH': join(getcwd(), "db", "leaderboards.db"),
    'BOT_COLOR': 0xF04747,
    'MAX_STATS_PER_GUILD': 3,
    'BOT_TOKEN': getenv('PROD_BOT_TOKEN')
}

dev_vars = {
    'DB_PATH': join(getcwd(), "db", "dev_leaderboards.db"),
    'BOT_COLOR': 0x2EB684,
    'MAX_STATS_PER_GUILD': 3,
    'BOT_TOKEN': getenv('DEV_BOT_TOKEN')
}
