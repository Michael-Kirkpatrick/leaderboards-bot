"""Modal creation and management"""


from typing import Callable, NamedTuple, Awaitable
import discord


class ModalInput(NamedTuple):
    Label: str
    Placeholder: str


class Modal(discord.ui.Modal):
    def __init__(self, title: str, submit_function: Callable[[discord.Interaction, list[str]], Awaitable[None]], **options) -> None:
        self.submit_function = submit_function
        super().__init__(title=title, **options)

    async def on_submit(self, interaction: discord.Interaction):
        values = [child.value for child in self.children]
        await self.submit_function(interaction, values)


def get_model(inputs: list[ModalInput], submit_function: Callable[[discord.Interaction, list[str]], Awaitable[None]], title: str) -> Modal:
    modal = Modal(title, submit_function)
    for textinput in inputs:
        modal.add_item(discord.ui.TextInput(label=textinput.Label, placeholder=textinput.Placeholder))
    return modal
