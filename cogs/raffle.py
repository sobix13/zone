"""
cogs/raffle.py — Raffle Access Role management
- Granted via: reaction (separate emoji), command, admin panel
- Skips if user already has it
- Manual reset only (command or admin panel)
"""
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, mz
from role_utils import role_manage_error, resolve_member
import logging

log = logging.getLogger('MeleeZone.Raffle')


class RaffleCog(BotHelpers, commands.Cog, name="Raffle"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_raffle_role", description="Set the raffle access role (admin)")
    @app_commands.describe(role="Role granted for raffle access")
    async def setup_raffle_role(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        await self.db.update_guild_config(str(interaction.guild_id), raffle_role_id=str(role.id))
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Raffle Role Set",
                description=(
                    f"Raffle access role: {role.mention}\n\n"
                    f"Grant it via reaction, `/give_raffle`, or the admin panel.\n"
                    f"Reset it anytime via `/revoke_all_raffle` or the admin panel."
                ),
                color=mz('green')
            ),
            ephemeral=True
        )

    @app_commands.command(name="give_raffle", description="Give raffle role to one or more users (admin)")
    @app_commands.describe(users="Mention users separated by spaces")
    async def give_raffle(self, interaction: discord.Interaction, users: str):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        role_id = config.get('raffle_role_id')
        if not role_id:
            return await interaction.followup.send(
                "No raffle role set. Use `/setup_raffle_role` first.", ephemeral=True
            )
        role = interaction.guild.get_role(int(role_id))
        if not role:
            return await interaction.followup.send("Raffle role not found in server.", ephemeral=True)
        manage_error = role_manage_error(interaction.guild, role)
        if manage_error:
            return await interaction.followup.send(f"❌ {manage_error}", ephemeral=True)

        # Parse mentions
        member_ids = [int(x) for x in __import__('re').findall(r'<@!?(\d+)>', users)]
        if not member_ids:
            return await interaction.followup.send(
                "No valid user mentions found. Example: `/give_raffle users:@a @b`", ephemeral=True
            )

        given, skipped, failed = 0, 0, 0
        for uid in member_ids:
            member = await resolve_member(interaction.guild, uid)
            if not member:
                failed += 1
                continue
            if role in member.roles:
                skipped += 1
                continue
            try:
                await member.add_roles(role, reason=f"Raffle command by {interaction.user.id}")
                given += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException as e:
                log.warning("Raffle role grant failed for %s: %s", uid, e)
                failed += 1

        embed = discord.Embed(title="🎟️ Raffle Role", color=mz('green'))
        embed.description = (
            f"✅ Granted: **{given}**\n"
            f"⏭️ Already had it: **{skipped}**\n"
            f"❌ Failed: **{failed}**"
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="revoke_all_raffle", description="Remove raffle role from ALL users (admin)")
    async def revoke_all_raffle(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        role_id = config.get('raffle_role_id')
        if not role_id:
            return await interaction.followup.send(
                "No raffle role set. Use `/setup_raffle_role` first.", ephemeral=True
            )
        role = interaction.guild.get_role(int(role_id))
        if not role:
            return await interaction.followup.send("Raffle role not found in server.", ephemeral=True)

        revoked = 0
        for member in list(role.members):
            try:
                await member.remove_roles(role, reason=f"Raffle reset by {interaction.user.id}")
                revoked += 1
            except Exception:
                pass

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Raffle Roles Revoked",
                description=f"Removed raffle role from **{revoked}** users.",
                color=mz('green')
            ),
            ephemeral=True
        )
        if config.get('log_channel_id'):
            ch = interaction.guild.get_channel(int(config['log_channel_id']))
            if ch:
                await ch.send(f"🎟️ {interaction.user.mention} revoked raffle role from {revoked} users.")


async def setup(bot):
    await bot.add_cog(RaffleCog(bot))
