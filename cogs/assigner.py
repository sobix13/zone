import discord
from discord.ext import commands
from helpers import BotHelpers
from config import Config, get_current_week_id, mz
from datetime import datetime, timedelta
import pytz
import random
import logging

log = logging.getLogger('MeleeZone.Assigner')
TEHRAN = pytz.timezone('Asia/Tehran')


class AssignerCog(BotHelpers, commands.Cog, name="Assigner"):
    def __init__(self, bot):
        self.bot = bot

    async def assign_post(self, post_id: str, guild: discord.Guild):
        guild_id = str(guild.id)
        config = await self.db.get_guild_config(guild_id)
        if not config or not config.get('pro_role_id'):
            return
        pro_role = guild.get_role(int(config['pro_role_id']))
        if not pro_role:
            return
        pro_users = [m for m in pro_role.members if not m.bot]
        if not pro_users:
            return
        post = await self.db.get_post(post_id)
        if not post:
            return
        week_id = get_current_week_id()
        min_reviews = Config.get_min_reviews(config)
        max_per_user = Config.get_max_reviews(config)
        review_days = Config.get_review_window(config)
        due_date = datetime.now(TEHRAN) + timedelta(days=review_days)
        eligible = []
        used=await self.db.get_reviewer_ids_for_post(post_id)
        used.update(r['reviewer_id'] for r in await self.db.get_reviews_by_post(post_id))
        for member in pro_users:
            if str(member.id) == post['author_id'] or str(member.id) in used:
                continue
            current = await self.db.get_assignments_by_reviewer(str(member.id), week_id, 'pending')
            completed = await self.db.get_assignments_by_reviewer(str(member.id), week_id, 'completed')
            if len(current) + len(completed) < max_per_user:
                eligible.append(member)
        if not eligible:
            return
        count = min(min_reviews, len(eligible))
        selected = random.sample(eligible, count)
        created=[]
        for member in selected:
            if await self.db.create_assignment(post_id, str(member.id), week_id, due_date):
                created.append(member)
        selected=created
        for member in selected:
            assignments = await self.db.get_assignments_by_reviewer(str(member.id), week_id, 'pending')
            assignment = next((a for a in assignments if a['post_id'] == post_id), None)
            if not assignment:
                continue
            embed = discord.Embed(
                title="📋 New Review Assignment",
                description=f"You have a new post to review!\n[View Post]({post['tweet_link']})",
                color=mz('primary')
            )
            embed.add_field(name="Assignment ID", value=f"`{assignment['assignment_id'][:8]}`")
            embed.add_field(name="Due in", value=f"{review_days} days")
            embed.set_footer(text="Open the bot panel → Reviews → Assignments to submit your review.")
            try:
                await member.send(embed=embed)
            except discord.Forbidden:
                if config.get('review_channel_id'):
                    ch = guild.get_channel(int(config['review_channel_id']))
                    if ch:
                        await ch.send(content=member.mention, embed=embed, delete_after=60)


async def setup(bot):
    await bot.add_cog(AssignerCog(bot))
