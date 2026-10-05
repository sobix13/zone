import discord
from typing import Optional
from database import Database


class BotHelpers:
    bot: discord.ext.commands.Bot

    @property
    def db(self) -> Database:
        return self.bot.db

    def is_admin(self, member: discord.Member, config: dict) -> bool:
        from access_policy import is_operator
        return is_operator(member, config)

    def is_primary_admin(self, member: discord.Member, config: dict) -> bool:
        from access_policy import is_primary
        return is_primary(member, config)

    def is_pro(self, member: discord.Member, config: dict) -> bool:
        if not config.get('pro_role_id'):
            return False
        role = member.guild.get_role(int(config['pro_role_id']))
        return bool(role and role in member.roles)

    async def get_config_or_fail(self, interaction: discord.Interaction) -> Optional[dict]:
        guild_id = str(interaction.guild_id)
        if not await self.db.is_guild_configured(guild_id):
            msg = "Bot not configured. Ask an admin to run `/setup_start`."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
            return None
        return await self.db.get_guild_config(guild_id)

    async def require_admin(self, interaction: discord.Interaction) -> Optional[dict]:
        from role_utils import resolve_member
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        member = await resolve_member(interaction.guild, interaction.user.id) if interaction.guild else None
        if not self.is_admin(member, config):
            msg = "Administrator permission required."
            try:
                if interaction.response.is_done():
                    await interaction.followup.send(msg, ephemeral=True)
                else:
                    await interaction.response.send_message(msg, ephemeral=True)
            except Exception:
                pass
            return None
        return config
