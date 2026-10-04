import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, get_current_week_id, is_valid_content_url, format_timedelta, mz
from datetime import datetime
import pytz
import logging

log = logging.getLogger('MeleeZone.Review')
TEHRAN = pytz.timezone('Asia/Tehran')


class ReviewCog(BotHelpers, commands.Cog, name="Review"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="my_reviews", description="View posts assigned to you for review")
    async def my_reviews(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.get_config_or_fail(interaction)
        if not config:
            return
        if not self.is_pro(interaction.user, config):
            return await interaction.followup.send(f"This section is for **{Config.pro_role_name(config)}** role only.", ephemeral=True)
        await self.db.get_or_create_user(str(interaction.user.id), str(interaction.guild_id), interaction.user.name, 'pro')
        week_id = get_current_week_id()
        all_assignments = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id)
        pending = [a for a in all_assignments if a['status'] in ('pending','warning')]
        completed = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id, 'completed')
        max_r = Config.get_max_reviews(config)
        mc = Config.mc_name(config)
        if not pending:
            embed = discord.Embed(title="📋 Assignments", description="No pending assignments.", color=mz('secondary'))
            embed.add_field(name="Progress", value=f"{len(completed)}/{max_r} completed")
            return await interaction.followup.send(embed=embed, ephemeral=True)
        embed = discord.Embed(title="📋 Your Assignments", description=f"**{len(pending)}** pending | **{len(completed)}/{max_r}** done", color=mz('primary'))
        now = datetime.now(TEHRAN)
        for i, a in enumerate(pending[:10], 1):
            try:
                due = datetime.fromisoformat(a['due_date'])
                if due.tzinfo is None:
                    due = TEHRAN.localize(due)
                left = due - now
                time_str = f"⏰ {format_timedelta(left)}" if left.total_seconds() > 0 else "⚠️ Overdue"
            except Exception:
                time_str = "Unknown"
            embed.add_field(name=f"{i}. ID: `{a['assignment_id'][:8]}`", value=f"[View Post]({a['tweet_link']}) — {time_str}", inline=False)
        if len(completed) >= max_r:
            embed.add_field(name="🎉 Goal Reached!", value=f"{max_r} reviews done. **{Config.get_review_reward(config)} {mc}** reward incoming!", inline=False)
        embed.set_footer(text="Use the Reviews panel to submit your review")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="review", description="Submit your review for an assigned post")
    @app_commands.describe(assignment_id="First 8 chars of assignment ID", score="Score 1-10", summary="Written feedback", comment="Your X comment URL (optional)")
    async def review(self, interaction: discord.Interaction, assignment_id: str, score: app_commands.Range[int, 1, 10], summary: str, comment: str = None):
        await interaction.response.defer(ephemeral=True)
        config = await self.get_config_or_fail(interaction)
        if not config:
            return
        if not self.is_pro(interaction.user, config):
            return await interaction.followup.send(f"{Config.pro_role_name(config)} role required.", ephemeral=True)
        user = await self.db.get_user(str(interaction.user.id), str(interaction.guild_id))
        if config.get('require_twitter_id', 1) and (not user or not user.get('twitter_username')):
            return await interaction.followup.send("Register your X handle first via the Dashboard.", ephemeral=True)
        if comment and not is_valid_content_url(comment):
            return await interaction.followup.send("Invalid comment URL format.", ephemeral=True)
        assignment = await self.db.get_assignment_by_partial_id(assignment_id, str(interaction.user.id))
        if not assignment:
            return await interaction.followup.send(f"Assignment `{assignment_id}` not found.", ephemeral=True)
        if assignment['status'] not in ('pending','warning'):
            return await interaction.followup.send("Already completed.", ephemeral=True)
        week_id = get_current_week_id()
        min_feedback = int(config.get('min_feedback_length', 30))
        if len(summary.strip()) < min_feedback:
            return await interaction.followup.send(f"Feedback must be at least {min_feedback} characters.", ephemeral=True)
        result = await self.db.submit_review_atomic(assignment['assignment_id'], str(interaction.user.id), score, comment, summary.strip(), week_id)
        if result['status'] != 'created':
            return await interaction.followup.send("This review was already submitted or the assignment is no longer active.", ephemeral=True)
        completed = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id, 'completed')
        max_r = Config.get_max_reviews(config)
        mc = Config.mc_name(config)
        embed = discord.Embed(title="✅ Review Submitted", description=Config.review_received_msg(config), color=mz('green'))
        embed.add_field(name="Score", value=f"**{score}/10**", inline=True)
        embed.add_field(name="Progress", value=f"{len(completed)}/{max_r}", inline=True)
        if comment:
            embed.add_field(name="📎 Comment Link", value=f"[View]({comment}) — counted toward bonus eligibility", inline=False)
        if len(completed) == max_r:
            embed.add_field(name="🎉 Milestone!", value=f"{max_r} reviews complete — **{Config.get_review_reward(config)} {mc}** reward incoming!", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        if config.get('log_channel_id'):
            ch = interaction.guild.get_channel(int(config['log_channel_id']))
            if ch:
                await ch.send(f"🔒 {interaction.user.mention} submitted a review.")
        self.bot.loop.create_task(self._check_post_completion(assignment['post_id'], config, interaction.guild))

    async def _check_post_completion(self, post_id: str, config: dict, guild: discord.Guild):
        try:
            result=await self.db.finalize_review_rewards(post_id)
            if not result:
                return
            post=result['post'];config=result['config'];avg=result['score']
            mc=Config.mc_name(config);guild_id=str(guild.id)
            reviews=await self.db.get_reviews_by_post(post_id)
            if result['showcase']:
                try:
                    await self._post_showcase(post,avg,config,guild)
                except discord.HTTPException:
                    log.warning('Showcase message delivery failed for %s; MC remains committed.',post_id)
            await self._process_comment_bonuses(reviews, config, guild_id, mc)
        except Exception as e:
            log.error(f"Post completion error {post_id}: {e}", exc_info=True)

    async def _process_comment_bonuses(self, reviews: list, config: dict, guild_id: str, mc: str):
        week_id = get_current_week_id()
        bonus = Config.get_comment_bonus(config)
        max_r = Config.get_max_reviews(config)
        seen = set()
        for review in reviews:
            reviewer_id = review['reviewer_id']
            if reviewer_id in seen:
                continue
            seen.add(reviewer_id)
            completed = await self.db.get_assignments_by_reviewer(reviewer_id, week_id, 'completed')
            if len(completed) < max_r:
                continue
            all_reviews = await self.db.get_reviews_by_reviewer(reviewer_id, week_id)
            if not all_reviews:
                continue
            if not all(r.get('twitter_comment') for r in all_reviews):
                continue
            bonus_key = f"Comment bonus - week {week_id}"
            if await self.db.reward_already_given(reviewer_id, guild_id, bonus_key):
                continue
            await self.db.add_mc(reviewer_id, guild_id, bonus, 'regular', bonus_key, reward_key=f"comment:{guild_id}:{reviewer_id}:{week_id}")

    async def _post_showcase(self, post: dict, avg: float, config: dict, guild: discord.Guild):
        if not config.get('showcase_channel_id'):
            return
        ch = guild.get_channel(int(config['showcase_channel_id']))
        if not ch:
            return
        mc = Config.mc_name(config)
        embed = discord.Embed(title="🌟 Featured Post", description=Config.showcase_msg(config), color=mz('gold'))
        embed.add_field(name="Score", value=f"**{avg:.1f}/10** ⭐")
        embed.add_field(name="Post", value=post['tweet_link'])
        author = guild.get_member(int(post['author_id']))
        if author:
            embed.set_author(name=author.display_name, icon_url=author.display_avatar.url)
        content = None
        if config.get('mention_role_id'):
            role = guild.get_role(int(config['mention_role_id']))
            if role:
                content = role.mention
        await ch.send(content=content, embed=embed)


async def setup(bot):
    await bot.add_cog(ReviewCog(bot))
