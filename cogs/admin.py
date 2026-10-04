import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, get_current_week_id, mz
from datetime import datetime, timedelta
import pytz
import io
import csv
import logging
from runtime_utils import parse_member_ids
from award_service import manual_award

log = logging.getLogger('MeleeZone.Admin')
TEHRAN = pytz.timezone('Asia/Tehran')
UTC = pytz.utc


class AdminCog(BotHelpers, commands.Cog, name="Admin"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="stats", description="Weekly statistics (admin)")
    async def stats(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        week_id = get_current_week_id()
        guild_id = str(interaction.guild_id)
        mc = Config.mc_name(config)
        posts = await self.db.get_posts_by_week(guild_id, week_id)
        review_count = await self.db.get_review_count(week_id)
        stalled = await self.db.get_stalled_posts(guild_id, week_id, Config.get_min_reviews(config))
        scored = [p for p in posts if p.get('final_score')]
        embed = discord.Embed(title=f"📊 Stats — {week_id}", color=mz('secondary'))
        embed.add_field(name="Posts", value=f"Total: **{len(posts)}**\n✅ {len([p for p in posts if p['status']=='approved'])} approved\n❌ {len([p for p in posts if p['status']=='rejected'])} rejected\n⏳ {len([p for p in posts if p['status'] in ('pending','assigned')])} pending", inline=True)
        embed.add_field(name="Reviews", value=f"Total: **{review_count}**", inline=True)
        if scored:
            avg = sum(p['final_score'] for p in scored) / len(scored)
            embed.add_field(name="Avg Score", value=f"**{avg:.1f}/10**", inline=True)
        if stalled:
            embed.add_field(name=f"⚠️ Stalled ({len(stalled)})", value="\n".join(f"`{p['post_id'][:8]}` — {p.get('review_count',0)} reviews" for p in stalled[:5]), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="give_mc", description="Manually award MC (admin)")
    @app_commands.describe(user="One member", users="Multiple member mentions or IDs, up to 25", amount="Amount per member", reason="Reason", mc_type="Credit type")
    @app_commands.choices(mc_type=[app_commands.Choice(name="Regular", value="regular"), app_commands.Choice(name="Golden", value="golden"), app_commands.Choice(name="Assignment", value="assignment")])
    async def give_mc(self, interaction: discord.Interaction, amount: app_commands.Range[float, 0.1, 1000.0], reason: str, user: discord.Member = None, users: str = None, mc_type: str = "regular"):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        try:
            ids=parse_member_ids(' '.join(x for x in [str(user.id) if user else '',users or ''] if x))
            result=await manual_award(interaction,ids,amount,mc_type,reason)
        except ValueError as exc:
            return await interaction.followup.send(str(exc),ephemeral=True)
        if result is not None:
            await interaction.followup.send(f"Awarded {amount:g} {mc_type} MC each to {len(result['created'])} member(s). Already recorded: {result['already_exists']}.",ephemeral=True)

    @app_commands.command(name="user_info", description="View user details (admin)")
    @app_commands.describe(user="User to inspect")
    async def user_info(self, interaction: discord.Interaction, user: discord.Member):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        guild_id = str(interaction.guild_id)
        mc = Config.mc_name(config)
        db_user = await self.db.get_or_create_user(str(user.id), guild_id, user.name)
        week_id = get_current_week_id()
        is_pro = self.is_pro(user, config)
        embed = discord.Embed(title=f"👤 {user.display_name}", color=mz('secondary'))
        embed.set_thumbnail(url=user.display_avatar.url)
        embed.add_field(name="X Handle", value=f"@{db_user.get('twitter_username','Not registered')}", inline=True)
        embed.add_field(name="Role", value=Config.pro_role_name(config) if is_pro else Config.basic_role_name(config), inline=True)
        embed.add_field(name=f"{mc} Balance", value=f"🪙 {db_user.get('mc_regular',0):.1f} / 🏆 {db_user.get('mc_golden',0):.1f}", inline=True)
        if is_pro:
            reviews = await self.db.get_reviews_by_reviewer(str(user.id), week_id)
            completed = await self.db.get_assignments_by_reviewer(str(user.id), week_id, 'completed')
            pending = await self.db.get_assignments_by_reviewer(str(user.id), week_id, 'pending')
            embed.add_field(name="This Week", value=f"Reviews: {len(reviews)} | Done: {len(completed)} | Pending: {len(pending)}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="export_data", description="Export data as CSV (admin)")
    @app_commands.choices(data_type=[app_commands.Choice(name="Posts", value="posts"), app_commands.Choice(name="Users & MC", value="users"), app_commands.Choice(name="Reviews", value="reviews")])
    async def export_data(self, interaction: discord.Interaction, data_type: str = "posts"):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        guild_id = str(interaction.guild_id)
        week_id = get_current_week_id()
        mc = Config.mc_name(config)
        output = io.StringIO()
        writer = csv.writer(output)
        if data_type == "posts":
            posts = await self.db.get_posts_by_week(guild_id, week_id)
            writer.writerow(['Post ID', 'Author ID', 'Link', 'Status', 'Score', f'{mc} Earned', 'Submitted At'])
            for p in posts:
                writer.writerow([p['post_id'], p['author_id'], p['tweet_link'], p['status'], p.get('final_score',''), p.get('mc_earned',''), p['submitted_at']])
        elif data_type == "users":
            users = await self.db.get_all_users(guild_id)
            writer.writerow(['User ID', 'Username', 'X Handle', 'Role', f'Regular {mc}', f'Golden {mc}', f'Total {mc}'])
            for u in users:
                writer.writerow([u['user_id'], u.get('username',''), u.get('twitter_username',''), u.get('role_type',''), u.get('mc_regular',0), u.get('mc_golden',0), u.get('mc_regular',0)+u.get('mc_golden',0)])
        elif data_type == "reviews":
            posts = await self.db.get_posts_by_week(guild_id, week_id)
            writer.writerow(['Review ID', 'Post ID', 'Reviewer ID', 'Score', 'Has X Comment', 'Summary Preview', 'Submitted At'])
            for p in posts:
                for r in await self.db.get_reviews_by_post(p['post_id']):
                    writer.writerow([r['review_id'], r['post_id'], r['reviewer_id'], r['score'], bool(r.get('twitter_comment')), (r.get('summary') or '')[:60], r['submitted_at']])
        output.seek(0)
        file = discord.File(io.BytesIO(output.getvalue().encode()), filename=f"{data_type}_{week_id}.csv")
        await interaction.followup.send(f"📊 Export: `{data_type}_{week_id}.csv`", file=file, ephemeral=True)

    @app_commands.command(name="manual_assign", description="Trigger assignment cycle now (admin)")
    async def manual_assign(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        tasks_cog = self.bot.get_cog('Tasks')
        if not tasks_cog:
            return await interaction.followup.send("Tasks cog not loaded.", ephemeral=True)
        await tasks_cog.process_guild_weekly(interaction.guild)
        await interaction.followup.send("✅ Assignment cycle complete.", ephemeral=True)


async def setup(bot):
    await bot.add_cog(AdminCog(bot))
