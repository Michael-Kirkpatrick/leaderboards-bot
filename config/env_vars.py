from os import getcwd, getenv

prod_vars = {
    'DB_PATH': getcwd() + "\db\leaderboards.db",
    'BOT_COLOR': 0xF04747,
    'MAX_STATS_PER_GUILD': 3,
    'BOT_TOKEN': getenv('PROD_BOT_TOKEN')
}

dev_vars = {
    'DB_PATH': getcwd() + "\db\dev_leaderboards.db",
    'BOT_COLOR': 0x2EB684,
    'MAX_STATS_PER_GUILD': 3,
    'BOT_TOKEN': getenv('DEV_BOT_TOKEN')
}