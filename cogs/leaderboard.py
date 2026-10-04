import discord
from discord import app_commands
from discord.ext import commands, tasks
from helpers import BotHelpers
from config import Config, get_next_utc_midnight, mz
from datetime import datetime, timedelta
import asyncio
import pytz
import logging

log = logging.getLogger('MeleeZone.Leaderboard')
UTC = pytz.utc


class LeaderboardCog(BotHelpers, commands.Cog, name="Leaderboard"):
    def __init__(self, bot):
        self.bot = bot
        self.daily_update.start()

    def cog_unload(self):
        self.daily_update.cancel()

    async def cog_load(self):
        self.bot.add_view(LeaderboardView(self.db, {}))

    @tasks.loop(hours=24)
    async def daily_update(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            await self._refresh_leaderboard(guild)

    @daily_update.before_loop
    async def before_daily(self):
        await self.bot.wait_until_ready()
        now = datetime.now(UTC)
        next_midnight = get_next_utc_midnight()
        wait = (next_midnight - now).total_seconds()
        if wait > 0:
            await asyncio.sleep(wait)

    async def _refresh_leaderboard(self, guild: discord.Guild):
        guild_id = str(guild.id)
        config = await self.db.get_guild_config(guild_id)
        if not config or not config.get('leaderboard_channel_id'):
            return
        ch = guild.get_channel(int(config['leaderboard_channel_id']))
        if not ch:
            log.warning(f"{guild.name}: leaderboard channel not found")
            return
        if not ch.permissions_for(guild.me).send_messages:
            log.warning(f"{guild.name}: no send permission in leaderboard channel")
            return
        embed, view = await self._build_embed(guild_id, config, 'alltime')
        msg_id = config.get('leaderboard_message_id')
        if msg_id:
            try:
                msg = await ch.fetch_message(int(msg_id))
                await msg.edit(embed=embed, view=view)
                return
            except (discord.NotFound, discord.Forbidden):
                pass
        msg = await ch.send(embed=embed, view=view)
        await self.db.update_guild_config(guild_id, leaderboard_message_id=str(msg.id))

    async def _build_embed(self, guild_id: str, config: dict, period: str):
        mc = Config.mc_name(config)
        bot_name = Config.bot_name(config)
        now = datetime.now(UTC)
        if period == 'daily':
            since = now - timedelta(days=1)
            title = f"📊 {bot_name} — Daily Leaderboard"
            footer = "Top earners in the last 24 hours"
        elif period == 'weekly':
            since = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
            title = f"📊 {bot_name} — Weekly Leaderboard"
            footer = "Top earners this week"
        elif period == 'monthly':
            since = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            title = f"📊 {bot_name} — Monthly Leaderboard"
            footer = f"Top earners — {now.strftime('%B %Y')}"
        else:
            since = None
            title = f"🏆 {bot_name} — All-Time Leaderboard"
            footer = f"Updated daily at 00:00 UTC • {now.strftime('%Y-%m-%d %H:%M')} UTC"
        if since:
            leaders = await self.db.get_leaderboard_period(guild_id, since, 10)
            amount_key = 'earned'
        else:
            leaders = await self.db.get_leaderboard(guild_id, 10)
            amount_key = 'total_mc'
        embed = discord.Embed(title=title, color=mz('gold'))
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        if not leaders:
            embed.description = "No data yet. Start earning!"
        else:
            lines = []
            for i, u in enumerate(leaders, 1):
                medal = medals.get(i, f"**{i}.**")
                amount = u.get(amount_key, 0) or 0
                handle = f"@{u['twitter_username']}" if u.get('twitter_username') else u.get('username', '?')
                lines.append(f"{medal} **{u.get('username','?')}** ({handle}) — {amount:.1f} {mc}")
            embed.description = "\n".join(lines)
        day_start = now - timedelta(days=1)
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day_top = await self.db.get_leaderboard_period(guild_id, day_start, 1)
        week_top = await self.db.get_leaderboard_period(guild_id, week_start, 3)
        month_top = await self.db.get_leaderboard_period(guild_id, month_start, 3)
        if day_top:
            u = day_top[0]
            embed.add_field(name="⚡ Best of Yesterday", value=f"**{u.get('username','?')}** — {u.get('earned',0):.1f} {mc}", inline=False)
        if week_top:
            embed.add_field(name="📅 Best This Week", value=" | ".join(f"**{u.get('username','?')}**" for u in week_top), inline=False)
        if month_top:
            embed.add_field(name="🗓️ Best This Month", value=" | ".join(f"**{u.get('username','?')}**" for u in month_top), inline=False)
        embed.set_footer(text=footer)
        return embed, LeaderboardView(self.db, config)

    @app_commands.command(name="setup_leaderboard", description="Post or refresh leaderboard (admin)")
    async def setup_leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        if not self.is_admin(interaction.user, config):
            return await interaction.followup.send("Admin only.", ephemeral=True)
        if not config.get('leaderboard_channel_id'):
            return await interaction.followup.send("Leaderboard channel not set. Run /setup_channels first.", ephemeral=True)
        ch = interaction.guild.get_channel(int(config['leaderboard_channel_id']))
        if not ch:
            return await interaction.followup.send("Leaderboard channel not found.", ephemeral=True)
        if not ch.permissions_for(interaction.guild.me).send_messages:
            return await interaction.followup.send(f"I need **Send Messages** permission in {ch.mention}.", ephemeral=True)
        await self._refresh_leaderboard(interaction.guild)
        await interaction.followup.send("✅ Leaderboard posted/updated.", ephemeral=True)


class LeaderboardView(discord.ui.View):
    def __init__(self, db, config):
        super().__init__(timeout=None)
        self.db = db
        self.config = config

    async def _send_period(self, interaction: discord.Interaction, period: str):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        cog = interaction.client.get_cog('Leaderboard')
        if cog:
            embed, _ = await cog._build_embed(str(interaction.guild_id), config, period)
            await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🏆 All-Time", style=discord.ButtonStyle.primary, custom_id="mz_lb_alltime", row=0)
    async def alltime(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_period(interaction, 'alltime')

    @discord.ui.button(label="📅 Weekly", style=discord.ButtonStyle.secondary, custom_id="mz_lb_weekly", row=0)
    async def weekly(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_period(interaction, 'weekly')

    @discord.ui.button(label="🗓️ Monthly", style=discord.ButtonStyle.secondary, custom_id="mz_lb_monthly", row=0)
    async def monthly(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_period(interaction, 'monthly')

    @discord.ui.button(label="⚡ Daily", style=discord.ButtonStyle.secondary, custom_id="mz_lb_daily", row=0)
    async def daily(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send_period(interaction, 'daily')

    @discord.ui.button(label="🔄 Refresh", style=discord.ButtonStyle.success, custom_id="mz_lb_refresh", row=1)
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        cog = interaction.client.get_cog('Leaderboard')
        if cog:
            await cog._refresh_leaderboard(interaction.guild)
        await interaction.followup.send("✅ Refreshed.", ephemeral=True)

    @discord.ui.button(label="💎 My Balance", style=discord.ButtonStyle.secondary, custom_id="mz_lb_my_mc", row=1)
    async def my_mc(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config = await self.db.get_guild_config(guild_id) or {}
        mc = Config.mc_name(config)
        user = await self.db.get_or_create_user(str(interaction.user.id), guild_id, interaction.user.name)
        rank = await self.db.get_user_rank_alltime(str(interaction.user.id), guild_id)
        embed = discord.Embed(title=f"💎 {interaction.user.display_name}", color=mz('gold'))
        embed.add_field(name=f"🪙 Regular {mc}", value=f"{user.get('mc_regular',0):.1f}", inline=True)
        embed.add_field(name=f"🏆 Golden {mc}", value=f"{user.get('mc_golden',0):.1f}", inline=True)
        embed.add_field(name="🏅 All-Time Rank", value=f"**#{rank}**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


async def setup(bot):
    await bot.add_cog(LeaderboardCog(bot))
