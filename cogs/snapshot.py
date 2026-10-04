"""
cogs/snapshot.py — Snapshot MC
Admin runs /snapshot in any channel/thread.
Bot asks: hours back, MC amount, MC type, description.
Scans messages, shows preview, awards MC to each unique poster once.
"""
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, mz
from datetime import datetime, timedelta, timezone
import uuid
import math
import logging
from runtime_utils import authorized,valid_amount

log = logging.getLogger('MeleeZone.Snapshot')
UTC = timezone.utc

MAX_LIST_MENTIONS = 30  # above this, show count only


class SnapshotConfigModal(discord.ui.Modal, title="Snapshot MC Setup"):
    hours = discord.ui.TextInput(label="How many hours back?", placeholder="6", max_length=4)
    amount = discord.ui.TextInput(label="MC amount per user", placeholder="2.0", max_length=6)
    description = discord.ui.TextInput(
        label="Reason / description",
        placeholder="Thread participation reward",
        style=discord.TextStyle.short,
        max_length=100
    )

    def __init__(self, db, config, channel, mc_type):
        super().__init__()
        self.db = db
        self.config = config
        self.channel = channel
        self.mc_type = mc_type

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await authorized(interaction):
            return
        # Validate
        try:
            hours = float(self.hours.value.strip())
            if not math.isfinite(hours) or hours <= 0 or hours > 720:
                raise ValueError
        except ValueError:
            return await interaction.followup.send("Hours must be between 0 and 720.", ephemeral=True)
        try:
            amount = valid_amount(self.amount.value.strip())
        except ValueError:
            return await interaction.followup.send("Invalid MC amount.", ephemeral=True)

        reason = self.description.value.strip()
        mc = Config.mc_name(self.config)
        cutoff = datetime.now(UTC) - timedelta(hours=hours)

        # Scan messages
        posters = {}
        scanned = 0
        try:
            async for msg in self.channel.history(limit=None, after=cutoff):
                scanned += 1
                if msg.author.bot:
                    continue
                posters[str(msg.author.id)] = msg.author.name
                if scanned >= 10000:
                    break
        except discord.Forbidden:
            return await interaction.followup.send(
                "I can't read message history in that channel. Check my permissions.",
                ephemeral=True
            )
        except Exception as e:
            log.error(f"Snapshot scan error: {e}")
            return await interaction.followup.send("Error scanning messages.", ephemeral=True)

        if not posters:
            return await interaction.followup.send(
                f"No user messages found in the last {hours:.0f}h.", ephemeral=True
            )

        # Preview
        type_label = {'regular': '🪙 Regular', 'golden': '🏆 Golden', 'assignment': '🎯 Assignment'}.get(self.mc_type, self.mc_type)
        embed = discord.Embed(title="📸 Snapshot Preview", color=mz('secondary'))
        embed.add_field(name="Channel", value=self.channel.mention, inline=True)
        embed.add_field(name="Window", value=f"Last {hours:.0f}h", inline=True)
        embed.add_field(name="Users found", value=str(len(posters)), inline=True)
        embed.add_field(name="MC each", value=f"{amount} {mc}", inline=True)
        embed.add_field(name="Type", value=type_label, inline=True)
        embed.add_field(name="Reason", value=reason, inline=False)

        if len(posters) <= MAX_LIST_MENTIONS:
            mentions = " ".join(f"<@{uid}>" for uid in posters.keys())
            embed.add_field(name="Recipients", value=mentions, inline=False)
        else:
            embed.add_field(
                name="Recipients",
                value=f"**{len(posters)}** users (too many to list)",
                inline=False
            )
        embed.set_footer(text=f"Scanned {scanned} messages. Scan limit: 10,000. Confirm to award MC, or cancel.")

        if scanned >= 10000:
            embed.add_field(name='Partial scan',value='The 10,000-message scan limit was reached. Only posters in the scanned messages receive this award.',inline=False)

        view = SnapshotConfirmView(
            self.db, self.config, posters, amount, self.mc_type, reason, hours
        )
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class SnapshotConfirmView(discord.ui.View):
    def __init__(self, db, config, posters, amount, mc_type, reason, hours):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.posters = posters
        self.amount = amount
        self.mc_type = mc_type
        self.reason = reason
        self.hours = hours
        self.snapshot_id = str(uuid.uuid4())

    async def interaction_check(self,interaction):
        return await authorized(interaction)

    @discord.ui.button(label="✅ Confirm & Award", style=discord.ButtonStyle.success)
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        mc = Config.mc_name(self.config)
        if not await authorized(interaction):
            return
        result=await self.db.award_batch_atomic(guild_id,str(interaction.user.id),
            [{'id':uid,'name':uname} for uid,uname in self.posters.items()],self.amount,self.mc_type,
            f'Snapshot: {self.reason}',self.snapshot_id,notice_channel=self.config.get('credit_log_channel_id'),snapshot_id=self.snapshot_id)
        awarded=len(result['created'])

        for item in self.children:
            item.disabled = True

        embed = discord.Embed(
            title="✅ Snapshot Complete",
            description=(
                f"Awarded **{self.amount} {mc}** to **{awarded}** users.\n"
                f"Type: {self.mc_type} | Reason: {self.reason}"
            ),
            color=mz('green')
        )
        await interaction.edit_original_response(embed=embed, view=self)


    @discord.ui.button(label="❌ Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button):
        for item in self.children:
            item.disabled = True
        await interaction.response.edit_message(
            embed=discord.Embed(title="Cancelled", color=mz('red')), view=self
        )


class SnapshotTypeView(discord.ui.View):
    """First step: pick MC type."""
    def __init__(self, db, config, channel):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.channel = channel

    async def _open(self, interaction, mc_type):
        await interaction.response.send_modal(
            SnapshotConfigModal(self.db, self.config, self.channel, mc_type)
        )

    @discord.ui.button(label="🪙 Regular", style=discord.ButtonStyle.primary)
    async def regular(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, 'regular')

    @discord.ui.button(label="🏆 Golden", style=discord.ButtonStyle.secondary)
    async def golden(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, 'golden')

    @discord.ui.button(label="🎯 Assignment", style=discord.ButtonStyle.secondary)
    async def assignment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._open(interaction, 'assignment')


class SnapshotCog(BotHelpers, commands.Cog, name="Snapshot"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="snapshot",
        description="Award MC to everyone who posted in a channel/thread within a time window (admin)"
    )
    @app_commands.describe(channel="Channel or thread to scan (default: current)")
    async def snapshot(self, interaction: discord.Interaction, channel: discord.abc.GuildChannel = None):
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        if not self.is_admin(interaction.user, config):
            return await interaction.response.send_message("Admin only.", ephemeral=True)
        target = channel or interaction.channel
        embed = discord.Embed(
            title="📸 Snapshot MC",
            description=(
                f"Target: {target.mention}\n\n"
                f"First, pick the **MC type** to award.\n"
                f"Then set the time window, amount, and reason."
            ),
            color=mz('primary')
        )
        await interaction.response.send_message(
            embed=embed,
            view=SnapshotTypeView(self.db, config, target),
            ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(SnapshotCog(bot))
