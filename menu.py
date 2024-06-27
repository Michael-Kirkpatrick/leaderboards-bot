"""Menu creation and management"""

from typing import NamedTuple, Callable, Awaitable, Mapping
import discord


class MenuOption(NamedTuple):
    callback_fn: Callable[..., Awaitable[None]]
    arguments: Mapping
    label: str


class MenuButton(discord.ui.Button):
    def __init__(self, callback_fn, arguments, **options):
        self.callback_fn = callback_fn
        self.arguments = arguments
        super().__init__(**options)


    async def callback(self, interaction: discord.Interaction):
        await self.callback_fn(**self.arguments)
        await interaction.response.defer()


class ButtonMenu(discord.ui.View):
    def __init__(self, menu_options: list[MenuOption], page_offset: int, separate_lines: bool = False, timeout=None):
        self.menu_options = menu_options
        super().__init__(timeout=timeout or 60)

        i = 0 + page_offset
        while i < min(len(menu_options), 9 + page_offset):
            option = menu_options[i]
            self.add_item(MenuButton(option.callback_fn, option.arguments, label=option.label, style=discord.ButtonStyle.secondary, row=i-page_offset if separate_lines else None))
            i += 1


class SelectOption(discord.SelectOption):
    def __init__(self, label: str, callback_fn: Callable[..., Awaitable[None]], arguments: Mapping, value: str = ..., pass_new_interaction: bool = False,
                 description: str | None = None, emoji: str | discord.Emoji | discord.PartialEmoji | None = None, default: bool = False) -> None:
        super().__init__(label=label, value=value, description=description, emoji=emoji, default=default)
        self.callback_fn = callback_fn
        self.arguments = arguments
        self.pass_new_interaction = pass_new_interaction


class SelectMenu(discord.ui.View):
    def __init__(self, select_options: list[SelectOption], max_values: int = 1, min_values: int = 1, placeholder: str = "Select an option", timeout=None):
        super().__init__(timeout=timeout or 60)
        self.add_item(SelectComponent(select_options, max_values=max_values, min_values=min_values, placeholder=placeholder))


class SelectComponent(discord.ui.Select):
    def __init__(self, select_options: list[SelectOption], **options):
        super().__init__(options=select_options, **options)
        self.options_ext = select_options


    async def callback(self, interaction: discord.Interaction):
        option_selected = self.options_ext[int(self.values[0])]
        if option_selected.pass_new_interaction:
            option_selected.arguments['new_interaction'] = interaction
            await option_selected.callback_fn(**option_selected.arguments)
        else:
            await interaction.response.defer()
            await option_selected.callback_fn(**option_selected.arguments)
