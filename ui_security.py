import discord
from runtime_utils import authorized


class AdminView(discord.ui.View):
    async def interaction_check(self,interaction):
        return await authorized(interaction)


class AdminModal(discord.ui.Modal):
    async def interaction_check(self,interaction):
        return await authorized(interaction)
