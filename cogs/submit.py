import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, get_current_week_id, is_valid_content_url, parse_x_post_url, mz
from datetime import datetime
from database import DuplicateSubmissionError
import pytz
import re

TEHRAN = pytz.timezone('Asia/Tehran')


class SubmitCog(BotHelpers, commands.Cog, name="Submit"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="register_twitter", description="Register or update your X/Twitter handle")
    @app_commands.describe(twitter_username="Your X/Twitter username (without @)")
    async def register_twitter(self, interaction: discord.Interaction, twitter_username: str):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        tw = twitter_username.lstrip('@').strip()
        if not re.match(r'^\w{1,50}$', tw):
            return await interaction.followup.send("Invalid username format.", ephemeral=True)
        user = await self.db.get_or_create_user(str(interaction.user.id), guild_id, interaction.user.name)
        changes_used = user.get('twitter_changes_used', 0)
        old = user.get('twitter_username')
        if changes_used >= 2:
            return await interaction.followup.send("All allowed changes used. Contact an admin.", ephemeral=True)
        if await self.db.twitter_already_registered(guild_id, tw) and tw.lower() != (old or '').lower():
            return await interaction.followup.send("This handle is already registered by another user.", ephemeral=True)
        await self.db.update_user_twitter(str(interaction.user.id), guild_id, tw)
        changes_left = max(0, 1 - changes_used) if old else 1
        msg = (f"Updated: **@{old}** → **@{tw}**\n⚠️ {changes_left} change(s) remaining." if old
               else f"Registered as **@{tw}**\n⚠️ You have 1 change remaining.")
        await interaction.followup.send(embed=discord.Embed(title="✅ X Handle Registered", description=msg, color=mz('green')), ephemeral=True)

    @app_commands.command(name="submit", description="Submit a post for review")
    @app_commands.describe(link="Twitter/X post URL")
    async def submit(self, interaction: discord.Interaction, link: str):
        await interaction.response.defer(ephemeral=False)
        config = await self.get_config_or_fail(interaction)
        if not config:
            return
        bot_ch_id = config.get('bot_content_channel_id') or config.get('submit_channel_id')
        if bot_ch_id and interaction.channel_id != int(bot_ch_id):
            ch = interaction.guild.get_channel(int(bot_ch_id))
            return await interaction.followup.send(f"Please use {ch.mention if ch else 'the bot channel'}.", ephemeral=True)
        if not is_valid_content_url(link):
            return await interaction.followup.send("Invalid URL. Must be a valid X/Twitter post link.", ephemeral=True)
        parsed = parse_x_post_url(link)
        role_type = 'pro' if self.is_pro(interaction.user, config) else 'basic'
        user = await self.db.get_or_create_user(str(interaction.user.id), str(interaction.guild_id), interaction.user.name, role_type)
        if config.get('require_twitter_id', 1) and not user.get('twitter_username'):
            return await interaction.followup.send("Register your X handle first with `/register_twitter`.", ephemeral=True)
        if user.get('twitter_username') and parsed['username'] != 'i':
            tw = user['twitter_username'].lower()
            if parsed['username'] != tw:
                return await interaction.followup.send(f"Link doesn't match your registered handle **@{user['twitter_username']}**.", ephemeral=True)
        max_s = Config.get_max_submits(config)
        if user.get('weekly_submits', 0) <= 0:
            return await interaction.followup.send(f"Weekly limit reached ({max_s}/{max_s}). Resets every Saturday.", ephemeral=True)
        week_id = get_current_week_id()
        guild_id = str(interaction.guild_id)
        if await self.db.has_user_submitted_status(str(interaction.user.id), guild_id, parsed['status_id']):
            return await interaction.followup.send("You already submitted this X post. Each post can only be submitted once.", ephemeral=True)
        try: post_id = await self.db.create_post(str(interaction.user.id), guild_id, link, week_id, parsed['status_id'], parsed['normalized_url'], Config.get_min_reviews(config))
        except DuplicateSubmissionError: return await interaction.followup.send("You already submitted this X post. Each post can only be submitted once.",ephemeral=True)
        await self.db.decrement_submits(str(interaction.user.id), guild_id)
        remaining = user['weekly_submits'] - 1
        mc = Config.mc_name(config)
        embed = discord.Embed(title="✅ Post Recorded", description=Config.submit_success_msg(config), color=mz('green'), timestamp=datetime.now(TEHRAN))
        embed.add_field(name="ID", value=f"`{post_id[:8]}`", inline=True)
        embed.add_field(name="Remaining", value=f"{remaining}/{max_s}", inline=True)
        embed.add_field(name="Link", value=link, inline=False)
        await interaction.followup.send(embed=embed)
        if config.get('log_channel_id'):
            ch = interaction.guild.get_channel(int(config['log_channel_id']))
            if ch:
                await ch.send(f"{interaction.user.mention} submitted a new post.")

        # Weekly completion bonus — configurable, once per user/week.
        user_after = await self.db.get_user(str(interaction.user.id), guild_id)
        if user_after and user_after.get('weekly_submits', 1) == 0:
            bonus_key = f"submit_completion:{guild_id}:{interaction.user.id}:{week_id}"
            bonus = Config.get_submit_completion_reward(config)
            if await self.db.add_mc(str(interaction.user.id), guild_id, bonus, 'regular', f"Weekly submission completion - {week_id}", reward_key=bonus_key):
                if config.get('log_channel_id'):
                    ch = interaction.guild.get_channel(int(config['log_channel_id']))
                    if ch:
                        await ch.send(f"🎯 {interaction.user.mention} completed all weekly submissions! +{bonus:g} {mc} bonus.")

        assigner = self.bot.get_cog('Assigner')
        if assigner:
            self.bot.loop.create_task(assigner.assign_post(post_id, interaction.guild))

    @app_commands.command(name="my_submits", description="View your submissions this week")
    async def my_submits(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.get_config_or_fail(interaction)
        if not config:
            return
        week_id = get_current_week_id()
        guild_id = str(interaction.guild_id)
        posts = await self.db.get_posts_by_week(guild_id, week_id)
        mine = sorted([p for p in posts if p['author_id'] == str(interaction.user.id)], key=lambda x: x['submitted_at'], reverse=True)
        if not mine:
            return await interaction.followup.send("No submissions this week.", ephemeral=True)
        mc = Config.mc_name(config)
        embed = discord.Embed(title=f"📋 Your Submissions — {week_id}", color=mz('primary'))
        status_emoji = {'approved': '✅', 'rejected': '❌', 'pending': '⏳', 'assigned': '🔍'}
        for i, p in enumerate(mine[:5], 1):
            e = status_emoji.get(p['status'], '⏳')
            val = f"[View]({p['tweet_link']}) — {e} {p['status'].title()}"
            if p.get('final_score'):
                val += f" | **{p['final_score']:.1f}/10**"
            if p.get('mc_earned'):
                val += f" | +{p['mc_earned']} {mc}"
            embed.add_field(name=f"{i}. `{p['post_id'][:8]}`", value=val, inline=False)
        user = await self.db.get_user(str(interaction.user.id), guild_id)
        embed.set_footer(text=f"{user['weekly_submits']} / {Config.get_max_submits(config)} submits remaining")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="my_mc", description="Check your Melee Credit balance")
    async def my_mc(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config = await self.db.get_guild_config(guild_id) or {}
        mc = Config.mc_name(config)
        user = await self.db.get_or_create_user(str(interaction.user.id), guild_id, interaction.user.name)
        embed = discord.Embed(title=f"💎 {interaction.user.display_name}'s {mc}", color=mz('gold'))
        embed.add_field(name=f"🪙 Regular {mc}", value=f"{user.get('mc_regular', 0):.1f}", inline=True)
        embed.add_field(name=f"🏆 Golden {mc}", value=f"{user.get('mc_golden', 0):.1f}", inline=True)
        embed.add_field(name="💎 Total", value=f"{user.get('mc_regular', 0) + user.get('mc_golden', 0):.1f}", inline=True)
        if user.get('twitter_username'):
            embed.add_field(name="X Handle", value=f"@{user['twitter_username']}", inline=False)
        txs = await self.db.get_mc_transactions(str(interaction.user.id), guild_id, 5)
        if txs:
            lines = [f"{'🏆' if t['mc_type'] == 'golden' else '🪙'} +{t['amount']} — {t['reason'][:50]}" for t in txs]
            embed.add_field(name="Recent Transactions", value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="leaderboard", description="Top MC earners")
    async def leaderboard(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        guild_id = str(interaction.guild_id)
        config = await self.db.get_guild_config(guild_id) or {}
        mc = Config.mc_name(config)
        leaders = await self.db.get_leaderboard(guild_id, 10)
        if not leaders:
            return await interaction.followup.send("No data yet.", ephemeral=True)
        medals = {1: "🥇", 2: "🥈", 3: "🥉"}
        embed = discord.Embed(title=f"🏆 {Config.bot_name(config)} Leaderboard", color=mz('gold'))
        for i, u in enumerate(leaders, 1):
            total = u['mc_regular'] + u['mc_golden']
            embed.add_field(name=f"{medals.get(i, f'{i}.')} {u['username']}", value=f"**{total:.1f}** {mc} — 🪙{u['mc_regular']:.1f} 🏆{u['mc_golden']:.1f}", inline=False)
        await interaction.followup.send(embed=embed)


async def setup(bot):
    await bot.add_cog(SubmitCog(bot))
