from ui_security import AdminView,AdminModal
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, get_current_week_id, is_valid_content_url, parse_x_post_url, format_timedelta, mz
from datetime import datetime, timedelta
import pytz
import re
import io
import csv
import logging
from database import DuplicateSubmissionError
from role_utils import role_manage_error, resolve_member

log = logging.getLogger('MeleeZone.Panel')
TEHRAN = pytz.timezone('Asia/Tehran')
UTC = pytz.utc


def _is_pro(member, config):
    if not config.get('pro_role_id'):
        return False
    role = member.guild.get_role(int(config['pro_role_id']))
    return bool(role and role in member.roles)

def _is_admin(member, config):
    if member.guild_permissions.administrator:
        return True
    if config.get('admin_role_id'):
        role = member.guild.get_role(int(config['admin_role_id']))
        if role and role in member.roles:
            return True
    if config.get('admin_user_id') and str(member.id) == str(config.get('admin_user_id')):
        return True
    return False

async def _cfg(interaction):
    return await interaction.client.db.get_guild_config(str(interaction.guild_id)) or {}

async def _require_x(interaction, db, config) -> bool:
    if not config.get('require_twitter_id', 1):
        return True
    user = await db.get_user(str(interaction.user.id), str(interaction.guild_id))
    if not user or not user.get('twitter_username'):
        embed = discord.Embed(title="⚠️ X Handle Required", description="Register your X/Twitter handle first.\n\nClick **Dashboard** → **Register X Handle**.", color=mz('primary'))
        try:
            if interaction.response.is_done():
                await interaction.followup.send(embed=embed, ephemeral=True)
            else:
                await interaction.response.send_message(embed=embed, ephemeral=True)
        except Exception:
            pass
        return False
    return True


class RegisterXModal(discord.ui.Modal, title="Register X / Twitter Handle"):
    username = discord.ui.TextInput(label="Your X/Twitter username (without @)", placeholder="yourhandle", min_length=1, max_length=50)
    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        tw = self.username.value.lstrip('@').strip()
        if not re.match(r'^\w{1,50}$', tw):
            return await interaction.followup.send("Invalid username format.", ephemeral=True)
        guild_id = str(interaction.guild_id)
        user = await self.db.get_or_create_user(str(interaction.user.id), guild_id, interaction.user.name)
        changes_used = user.get('twitter_changes_used', 0)
        old = user.get('twitter_username')
        if changes_used >= 2:
            return await interaction.followup.send("All allowed changes used. Contact an admin.", ephemeral=True)
        if await self.db.twitter_already_registered(guild_id, tw) and tw.lower() != (old or '').lower():
            return await interaction.followup.send("This handle is already registered.", ephemeral=True)
        await self.db.update_user_twitter(str(interaction.user.id), guild_id, tw)
        changes_left = max(0, 1 - changes_used) if old else 1
        msg = (f"Updated: **@{old}** → **@{tw}**\n⚠️ {changes_left} change(s) remaining." if old
               else f"Registered as **@{tw}**\n⚠️ You have 1 change remaining.")
        await interaction.followup.send(embed=discord.Embed(title="✅ X Handle Registered", description=msg, color=mz('green')), ephemeral=True)


class SubmitPostModal(discord.ui.Modal, title="Submit a Post"):
    link = discord.ui.TextInput(label="X / Twitter Post URL", placeholder="https://x.com/yourhandle/status/...", min_length=10, max_length=200)
    def __init__(self, db, config, guild):
        super().__init__()
        self.db = db
        self.config = config
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        link = self.link.value.strip()
        config = self.config
        if not is_valid_content_url(link):
            return await interaction.followup.send("Invalid URL. Must be a valid X/Twitter post link.", ephemeral=True)
        parsed = parse_x_post_url(link)
        role_type = 'pro' if _is_pro(interaction.user, config) else 'basic'
        user = await self.db.get_or_create_user(str(interaction.user.id), str(interaction.guild_id), interaction.user.name, role_type)
        if config.get('require_twitter_id', 1) and not user.get('twitter_username'):
            return await interaction.followup.send("Register your X handle first via the Dashboard.", ephemeral=True)
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
        await interaction.followup.send(embed=embed, ephemeral=True)
        if remaining == 0:
            bonus = Config.get_submit_completion_reward(config)
            key = f"submit_completion:{guild_id}:{interaction.user.id}:{week_id}"
            await self.db.add_mc(str(interaction.user.id), guild_id, bonus, 'regular', f"Weekly submission completion - {week_id}", reward_key=key)
        if config.get('log_channel_id'):
            ch = self.guild.get_channel(int(config['log_channel_id']))
            if ch:
                await ch.send(f"{interaction.user.mention} submitted a new post.")
        assigner = interaction.client.get_cog('Assigner')
        if assigner:
            interaction.client.loop.create_task(assigner.assign_post(post_id, self.guild))


class ReviewSubmitModal(discord.ui.Modal, title="Submit Review"):
    assignment_id = discord.ui.TextInput(label="Assignment ID (first 8 chars)", placeholder="e.g. a1b2c3d4", min_length=4, max_length=36)
    score = discord.ui.TextInput(label="Score (1-10)", placeholder="e.g. 8", min_length=1, max_length=2)
    summary = discord.ui.TextInput(label="Your Written Feedback", placeholder="Be fair — give feedback you would like to receive.", style=discord.TextStyle.paragraph, min_length=30, max_length=800)
    comment_url = discord.ui.TextInput(label="X comment URL (optional bonus)", placeholder="https://x.com/you/status/...", required=False, max_length=200)

    def __init__(self, db, config):
        super().__init__()
        self.db = db
        self.config = config

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        try:
            score_val = int(self.score.value.strip())
            if not 1 <= score_val <= 10:
                raise ValueError
        except ValueError:
            return await interaction.followup.send("Score must be between 1 and 10.", ephemeral=True)
        comment = self.comment_url.value.strip() or None
        if comment and not is_valid_content_url(comment):
            return await interaction.followup.send("Invalid comment URL format.", ephemeral=True)
        assignment = await self.db.get_assignment_by_partial_id(self.assignment_id.value.strip(), str(interaction.user.id))
        if not assignment:
            return await interaction.followup.send("Assignment not found. Check your assignments list.", ephemeral=True)
        if assignment['status'] not in ('pending','warning'):
            return await interaction.followup.send("Already completed.", ephemeral=True)
        week_id = get_current_week_id()
        result = await self.db.submit_review_atomic(assignment['assignment_id'], str(interaction.user.id), score_val, comment, self.summary.value.strip(), week_id)
        if result['status'] != 'created':
            return await interaction.followup.send("This review was already submitted or the assignment is no longer active.", ephemeral=True)
        completed = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id, 'completed')
        max_r = Config.get_max_reviews(self.config)
        mc = Config.mc_name(self.config)
        embed = discord.Embed(title="✅ Review Submitted", description=Config.review_received_msg(self.config), color=mz('green'))
        embed.add_field(name="Score", value=f"**{score_val}/10**", inline=True)
        embed.add_field(name="Progress", value=f"{len(completed)}/{max_r}", inline=True)
        if comment:
            embed.add_field(name="📎 Comment Linked", value=f"[View]({comment}) — counts toward bonus", inline=False)
        if len(completed) == max_r:
            embed.add_field(name="🎉 Milestone!", value=f"{max_r} reviews complete — **{Config.get_review_reward(self.config)} {mc}** incoming!", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)
        if self.config.get('log_channel_id'):
            ch = interaction.guild.get_channel(int(self.config['log_channel_id']))
            if ch:
                await ch.send(f"🔒 {interaction.user.mention} submitted a review.")
        review_cog = interaction.client.get_cog('Review')
        if review_cog:
            interaction.client.loop.create_task(review_cog._check_post_completion(assignment['post_id'], self.config, interaction.guild))


class GiveMCModal(AdminModal, title="Award Melee Credit"):
    user_id_input = discord.ui.TextInput(label="Member mentions or IDs (up to 25)", min_length=10, max_length=800, style=discord.TextStyle.paragraph)
    amount = discord.ui.TextInput(label="Amount", placeholder="e.g. 5.0", min_length=1, max_length=8)
    credit_type = discord.ui.TextInput(label="Type: regular, golden, or assignment", placeholder="regular", min_length=4, max_length=11)
    reason = discord.ui.TextInput(label="Reason", max_length=100)

    def __init__(self, db, config):
        super().__init__()
        self.db = db
        self.config = config

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        from award_service import manual_award
        from runtime_utils import parse_member_ids
        try:
            result=await manual_award(interaction,parse_member_ids(self.user_id_input.value),
                self.amount.value.strip(),self.credit_type.value.strip().lower(),self.reason.value)
        except ValueError as exc:
            return await interaction.followup.send(str(exc),ephemeral=True)
        if result is not None:
            await interaction.followup.send(f"MC recorded for {len(result['created'])} member(s). Already recorded: {result['already_exists']}.",ephemeral=True)


class UserInfoModal(AdminModal, title="View User Info"):
    user_id_input = discord.ui.TextInput(label="User ID (right-click → Copy ID)", min_length=10, max_length=25)

    def __init__(self, db, config):
        super().__init__()
        self.db = db
        self.config = config

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        uid = self.user_id_input.value.strip()
        guild_id = str(interaction.guild_id)
        mc = Config.mc_name(self.config)
        try:
            member = interaction.guild.get_member(int(uid)) or await interaction.guild.fetch_member(int(uid))
        except Exception:
            return await interaction.followup.send("User not found.", ephemeral=True)
        db_user = await self.db.get_or_create_user(uid, guild_id, member.name)
        week_id = get_current_week_id()
        is_pro = _is_pro(member, self.config)
        embed = discord.Embed(title=f"👤 {member.display_name}", color=mz('secondary'))
        embed.set_thumbnail(url=member.display_avatar.url)
        embed.add_field(name="X Handle", value=f"@{db_user.get('twitter_username','Not registered')}", inline=True)
        embed.add_field(name="Role", value=Config.pro_role_name(self.config) if is_pro else Config.basic_role_name(self.config), inline=True)
        embed.add_field(name=f"{mc} Balance", value=f"🪙 {db_user.get('mc_regular',0):.1f} / 🏆 {db_user.get('mc_golden',0):.1f} / 🎯 {db_user.get('mc_assignment',0):.1f}", inline=True)
        if is_pro:
            reviews = await self.db.get_reviews_by_reviewer(uid, week_id)
            completed = await self.db.get_assignments_by_reviewer(uid, week_id, 'completed')
            pending = await self.db.get_assignments_by_reviewer(uid, week_id, 'pending')
            embed.add_field(name="This Week", value=f"Reviews: {len(reviews)} | Done: {len(completed)} | Pending: {len(pending)}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)


class EditAboutModal(AdminModal, title="Edit About Text"):
    about_text = discord.ui.TextInput(label="About text (shown to all users)", style=discord.TextStyle.paragraph, max_length=1500, required=False)

    def __init__(self, db, current_text: str = ''):
        super().__init__()
        self.db = db
        self.about_text.default = current_text

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.db.update_guild_config(str(interaction.guild_id), txt_about=self.about_text.value.strip())
        await interaction.followup.send(embed=discord.Embed(title="✅ About Updated", color=mz('green')), ephemeral=True)


class NumberSettingsModal(AdminModal, title="Update Numeric Settings"):
    max_submits = discord.ui.TextInput(label="Max submits per week", placeholder="5", required=False, max_length=3)
    max_reviews = discord.ui.TextInput(label="Max reviews per week", placeholder="7", required=False, max_length=3)
    review_window = discord.ui.TextInput(label="Review window (days)", placeholder="5", required=False, max_length=2)
    min_reviews = discord.ui.TextInput(label="Min reviews per post", placeholder="5", required=False, max_length=2)
    showcase_threshold = discord.ui.TextInput(label="Showcase threshold (e.g. 8.0)", placeholder="8.0", required=False, max_length=4)

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        updates, changed = {}, []
        for key, val, cast, label in [('max_submits_per_week', self.max_submits.value, int, "Max submits"), ('max_reviews_per_week', self.max_reviews.value, int, "Max reviews"), ('review_window_days', self.review_window.value, int, "Review window"), ('min_reviews', self.min_reviews.value, int, "Min reviews"), ('showcase_threshold', self.showcase_threshold.value, float, "Showcase threshold")]:
            if val.strip():
                try:
                    updates[key] = cast(val.strip()); changed.append(f"{label}: **{val.strip()}**")
                except ValueError:
                    pass
        if updates:
            await self.db.update_guild_config(str(interaction.guild_id), **updates)
        await interaction.followup.send(embed=discord.Embed(title="✅ Updated", description="\n".join(changed) or "No changes.", color=mz('green')), ephemeral=True)


class CreditValuesModal(AdminModal, title="Edit MC Credit Values"):
    score_6 = discord.ui.TextInput(label="MC for average 4 to under 6", placeholder="1.0", required=False, max_length=5)
    score_7 = discord.ui.TextInput(label="MC for average 6 to under 8", placeholder="3.0", required=False, max_length=5)
    score_8 = discord.ui.TextInput(label="MC for average 8 to 10", placeholder="5.0", required=False, max_length=5)
    review_reward = discord.ui.TextInput(label="MC for completing all reviews", placeholder="2.0", required=False, max_length=5)
    comment_bonus = discord.ui.TextInput(label="MC for full weekly submission capacity", placeholder="2.0", required=False, max_length=5)

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        updates, changed = {}, []
        for key, val, label in [('mc_score_low', self.score_6.value, "Low tier"), ('mc_score_medium', self.score_7.value, "Medium tier"), ('mc_score_high', self.score_8.value, "High tier"), ('mc_review_reward', self.review_reward.value, "Review reward"), ('mc_submit_completion', self.comment_bonus.value, "Submission completion")]:
            if val.strip():
                try:
                    updates[key] = float(val.strip()); changed.append(f"{label}: **{val.strip()}**")
                except ValueError:
                    pass
        if updates:
            await self.db.update_guild_config(str(interaction.guild_id), **updates)
        await interaction.followup.send(embed=discord.Embed(title="✅ MC Values Updated", description="\n".join(changed) or "No changes.", color=mz('green')), ephemeral=True)


class TextsModal(AdminModal, title="Edit Texts & Names"):
    bot_name = discord.ui.TextInput(label="Bot name", placeholder="Melee Zone", required=False, max_length=32)
    currency_name = discord.ui.TextInput(label="Currency name", placeholder="MC", required=False, max_length=16)
    pro_role = discord.ui.TextInput(label="Reviewer role display name", placeholder="Reviewer", required=False, max_length=32)
    basic_role = discord.ui.TextInput(label="Basic role display name", placeholder="Basic", required=False, max_length=32)
    panel_title = discord.ui.TextInput(label="Panel title", placeholder="Melee Zone", required=False, max_length=50)

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        updates, changed = {}, []
        for key, val, label in [('txt_bot_name', self.bot_name.value, "Bot name"), ('txt_mc_name', self.currency_name.value, "Currency name"), ('txt_pro_role', self.pro_role.value, "Reviewer role"), ('txt_basic_role', self.basic_role.value, "Basic role"), ('txt_panel_title', self.panel_title.value, "Panel title")]:
            if val.strip():
                updates[key] = val.strip(); changed.append(f"{label}: **{val.strip()}**")
        if updates:
            await self.db.update_guild_config(str(interaction.guild_id), **updates)
        await interaction.followup.send(embed=discord.Embed(title="✅ Texts Updated", description="\n".join(changed) or "No changes.", color=mz('green')), ephemeral=True)


class AutoMessagesModal(AdminModal, title="Edit Automated Messages"):
    welcome = discord.ui.TextInput(label="Welcome message", required=False, max_length=200, style=discord.TextStyle.paragraph)
    submit_success = discord.ui.TextInput(label="Submit success message", required=False, max_length=200)
    review_received = discord.ui.TextInput(label="Review received message", required=False, max_length=200)
    showcase = discord.ui.TextInput(label="Showcase message", required=False, max_length=200)
    reminder = discord.ui.TextInput(label="Reminder message", required=False, max_length=200)

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        updates, changed = {}, []
        for key, val, label in [('txt_welcome', self.welcome.value, "Welcome"), ('txt_submit_success', self.submit_success.value, "Submit success"), ('txt_review_received', self.review_received.value, "Review received"), ('txt_showcase', self.showcase.value, "Showcase"), ('txt_reminder', self.reminder.value, "Reminder")]:
            if val.strip():
                updates[key] = val.strip(); changed.append(f"{label} updated")
        if updates:
            await self.db.update_guild_config(str(interaction.guild_id), **updates)
        await interaction.followup.send(embed=discord.Embed(title="✅ Messages Updated", description="\n".join(changed) or "No changes.", color=mz('green')), ephemeral=True)


class ReactionSettingsModal(AdminModal, title="Edit Reaction Emojis & MC"):
    emoji_1 = discord.ui.TextInput(label="Emoji 1", placeholder="e.g. ⭐", required=False, max_length=10)
    credit_1 = discord.ui.TextInput(label="MC for emoji 1", placeholder="1.0", required=False, max_length=5)
    emoji_2 = discord.ui.TextInput(label="Emoji 2", placeholder="e.g. 🔥", required=False, max_length=10)
    credit_2 = discord.ui.TextInput(label="MC for emoji 2", placeholder="2.0", required=False, max_length=5)
    emoji_3_credit = discord.ui.TextInput(label="Emoji 3 and MC (format: emoji,mc)", placeholder="e.g. 💎,3.0", required=False, max_length=20)

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        updates, changed = {}, []
        if self.emoji_1.value.strip():
            updates['reaction_emoji_1'] = self.emoji_1.value.strip(); changed.append(f"Emoji 1: {self.emoji_1.value.strip()}")
        if self.credit_1.value.strip():
            try:
                updates['reaction_mc_1'] = float(self.credit_1.value.strip()); changed.append(f"MC 1: {self.credit_1.value.strip()}")
            except ValueError: pass
        if self.emoji_2.value.strip():
            updates['reaction_emoji_2'] = self.emoji_2.value.strip(); changed.append(f"Emoji 2: {self.emoji_2.value.strip()}")
        if self.credit_2.value.strip():
            try:
                updates['reaction_mc_2'] = float(self.credit_2.value.strip()); changed.append(f"MC 2: {self.credit_2.value.strip()}")
            except ValueError: pass
        if self.emoji_3_credit.value.strip() and ',' in self.emoji_3_credit.value:
            parts = self.emoji_3_credit.value.split(',')
            if len(parts) == 2:
                try:
                    updates['reaction_emoji_3'] = parts[0].strip()
                    updates['reaction_mc_3'] = float(parts[1].strip())
                    changed.append(f"Emoji 3: {parts[0].strip()} → {parts[1].strip()}")
                except ValueError: pass
        if updates:
            await self.db.update_guild_config(str(interaction.guild_id), **updates)
        await interaction.followup.send(embed=discord.Embed(title="✅ Reactions Updated", description="\n".join(changed) or "No changes.", color=mz('green')), ephemeral=True)


class DashboardView(discord.ui.View):
    def __init__(self, db, config):
        super().__init__(timeout=120)
        self.db = db
        self.config = config

    @discord.ui.button(label="🐦 Register X Handle", style=discord.ButtonStyle.primary, row=0)
    async def register_x(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RegisterXModal(self.db))

    @discord.ui.button(label="💎 My Balance", style=discord.ButtonStyle.secondary, row=0)
    async def my_balance(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        config = await self.db.get_guild_config(guild_id) or {}
        mc = Config.mc_name(config)
        user = await self.db.get_or_create_user(str(interaction.user.id), guild_id, interaction.user.name)
        embed = discord.Embed(title=f"💎 {interaction.user.display_name}'s Balance", color=mz('gold'))
        embed.add_field(name=f"🪙 Regular {mc}", value=f"{user.get('mc_regular',0):.1f}", inline=True)
        embed.add_field(name=f"🏆 Golden {mc}", value=f"{user.get('mc_golden',0):.1f}", inline=True)
        embed.add_field(name=f"🎯 Assignment {mc}", value=f"{user.get('mc_assignment',0):.1f}", inline=True)
        embed.add_field(name="💎 Total", value=f"{user.get('mc_regular',0)+user.get('mc_golden',0)+user.get('mc_assignment',0):.1f}", inline=True)
        if user.get('twitter_username'):
            embed.add_field(name="X Handle", value=f"@{user['twitter_username']}", inline=False)
        txs = await self.db.get_mc_transactions(str(interaction.user.id), guild_id, 10)
        if txs:
            lines = [f"{'🏆' if t['mc_type']=='golden' else '🪙'} +{t['amount']} — {t['reason'][:45]}" for t in txs]
            embed.add_field(name="Recent", value="\n".join(lines), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="📊 My Rank", style=discord.ButtonStyle.secondary, row=1)
    async def my_rank(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        uid = str(interaction.user.id)
        now = datetime.now(UTC)
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        rank_all = await self.db.get_user_rank_alltime(uid, guild_id)
        rank_week = await self.db.get_user_rank_period(uid, guild_id, week_start)
        rank_month = await self.db.get_user_rank_period(uid, guild_id, month_start)
        embed = discord.Embed(title=f"📊 {interaction.user.display_name}'s Rank", color=mz('primary'))
        embed.add_field(name="🏆 All-Time", value=f"**#{rank_all}**", inline=True)
        embed.add_field(name="📅 This Week", value=f"**#{rank_week}**", inline=True)
        embed.add_field(name="🗓️ This Month", value=f"**#{rank_month}**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="📈 My Performance", style=discord.ButtonStyle.secondary, row=1)
    async def my_perf(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        uid = str(interaction.user.id)
        config = await self.db.get_guild_config(guild_id) or {}
        mc = Config.mc_name(config)
        now = datetime.now(UTC)
        week_start = (now - timedelta(days=now.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        earned_week = await self.db.get_user_mc_period(uid, guild_id, week_start)
        earned_month = await self.db.get_user_mc_period(uid, guild_id, month_start)
        all_posts = await self.db.get_posts_by_author_count(uid, guild_id)
        week_id = get_current_week_id()
        posts_week = await self.db.get_posts_by_week(guild_id, week_id)
        mine = [p for p in posts_week if p['author_id'] == uid]
        all_txs = await self.db.get_mc_transactions(uid, guild_id, 100)
        golden_count = sum(1 for t in all_txs if t['mc_type'] == 'golden')
        embed = discord.Embed(title=f"📈 {interaction.user.display_name}'s Performance", color=mz('secondary'))
        embed.add_field(name=f"{mc} This Week", value=f"**{earned_week:.1f}**", inline=True)
        embed.add_field(name=f"{mc} This Month", value=f"**{earned_month:.1f}**", inline=True)
        embed.add_field(name="🏆 Golden Credits", value=f"**{golden_count}x**", inline=True)
        embed.add_field(name="📝 Total Posts", value=f"**{all_posts}**", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


class SubmissionView(discord.ui.View):
    def __init__(self, db, config, guild):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.guild = guild

    @discord.ui.button(label="📝 Submit Post", style=discord.ButtonStyle.primary, row=0)
    async def submit_post(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_x(interaction, self.db, self.config):
            return
        config = await _cfg(interaction)
        await interaction.response.send_modal(SubmitPostModal(self.db, config, interaction.guild))

    @discord.ui.button(label="📋 My Last Submissions", style=discord.ButtonStyle.secondary, row=0)
    async def my_submissions(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not await _require_x(interaction, self.db, self.config):
            return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        uid = str(interaction.user.id)
        total = await self.db.get_posts_by_author_count(uid, guild_id)
        if total == 0:
            return await interaction.followup.send("No submissions yet.", ephemeral=True)
        posts = await self.db.get_posts_by_author(uid, guild_id, limit=5, offset=0)
        view = SubmissionsPageView(self.db, self.config, uid, guild_id, 0, total)
        embed = await view.build_embed(posts)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


class SubmissionsPageView(discord.ui.View):
    def __init__(self, db, config, uid, guild_id, offset, total):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.uid = uid
        self.guild_id = guild_id
        self.offset = offset
        self.total = total
        self.page_size = 5
        self.max_posts = 50
        self._update_buttons()

    def _update_buttons(self):
        self.prev_btn.disabled = self.offset == 0
        self.next_btn.disabled = (self.offset + self.page_size >= min(self.total, self.max_posts))

    async def build_embed(self, posts) -> discord.Embed:
        mc = Config.mc_name(self.config)
        page = self.offset // self.page_size + 1
        total_pages = (min(self.total, self.max_posts) + self.page_size - 1) // self.page_size
        embed = discord.Embed(title=f"📋 My Submissions — Page {page}/{total_pages}", color=mz('primary'))
        status_emoji = {'approved': '✅', 'rejected': '❌', 'pending': '⏳', 'assigned': '🔍'}
        for p in posts:
            e = status_emoji.get(p['status'], '⏳')
            val = f"[View Post]({p['tweet_link']})\n{e} {p['status'].title()}"
            if p.get('final_score'):
                val += f" | Score: **{p['final_score']:.1f}/10**"
            if p.get('mc_earned'):
                val += f" | +{p['mc_earned']} {mc}"
            reviews = await self.db.get_reviews_by_post(p['post_id'])
            if reviews:
                avg = sum(r['score'] for r in reviews) / len(reviews)
                val += f"\n📊 Avg: **{avg:.1f}/10** ({len(reviews)} reviews)"
            embed.add_field(name=f"`{p['post_id'][:8]}` — {p['submitted_at'][:10]}", value=val, inline=False)
        embed.set_footer(text=f"Showing {self.offset+1}–{min(self.offset+self.page_size, self.total)} of {min(self.total, self.max_posts)}")
        return embed

    @discord.ui.button(label="◀ Previous", style=discord.ButtonStyle.secondary, row=0)
    async def prev_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.offset = max(0, self.offset - self.page_size)
        self._update_buttons()
        posts = await self.db.get_posts_by_author(self.uid, self.guild_id, limit=self.page_size, offset=self.offset)
        embed = await self.build_embed(posts)
        await interaction.edit_original_response(embed=embed, view=self)

    @discord.ui.button(label="Next ▶", style=discord.ButtonStyle.secondary, row=0)
    async def next_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        self.offset = min(self.offset + self.page_size, self.max_posts - self.page_size)
        self._update_buttons()
        posts = await self.db.get_posts_by_author(self.uid, self.guild_id, limit=self.page_size, offset=self.offset)
        embed = await self.build_embed(posts)
        await interaction.edit_original_response(embed=embed, view=self)


class ReviewsView(discord.ui.View):
    def __init__(self, db, config):
        super().__init__(timeout=120)
        self.db = db
        self.config = config

    @discord.ui.button(label="📋 Assignments", style=discord.ButtonStyle.primary, row=0)
    async def assignments(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = self.config
        if not _is_pro(interaction.user, config):
            return await interaction.followup.send(f"{Config.pro_role_name(config)} role required.", ephemeral=True)
        week_id = get_current_week_id()
        all_assignments = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id)
        pending = [a for a in all_assignments if a['status'] in ('pending','warning')]
        completed = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id, 'completed')
        max_r = Config.get_max_reviews(config)
        if not pending:
            embed = discord.Embed(title="📋 Assignments", description="No pending assignments.", color=mz('secondary'))
            embed.add_field(name="Progress", value=f"{len(completed)}/{max_r} completed")
            return await interaction.followup.send(embed=embed, ephemeral=True)
        now = datetime.now(TEHRAN)
        embed = discord.Embed(title="📋 Your Assignments", description=f"**{len(pending)}** pending | **{len(completed)}/{max_r}** done\n\nCopy the ID, then click **Submit a Review**.", color=mz('primary'))
        for i, a in enumerate(pending[:5], 1):
            try:
                due = datetime.fromisoformat(a['due_date'])
                if due.tzinfo is None:
                    due = TEHRAN.localize(due)
                left = due - now
                time_str = f"⏰ {format_timedelta(left)}" if left.total_seconds() > 0 else "⚠️ Overdue"
            except Exception:
                time_str = "Unknown"
            embed.add_field(name=f"{i}. ID: `{a['assignment_id'][:8]}`", value=f"[View Post]({a['tweet_link']}) — {time_str}", inline=False)
        embed.set_footer(text="Copy the ID above, then click Submit a Review")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="✍️ Submit a Review", style=discord.ButtonStyle.success, row=0)
    async def submit_review(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = self.config
        if not _is_pro(interaction.user, config):
            return await interaction.response.send_message(f"{Config.pro_role_name(config)} role required.", ephemeral=True)
        if not await _require_x(interaction, self.db, config):
            return
        embed = discord.Embed(title="✍️ Submit a Review", description="**Be fair — give the feedback you would like to receive.**\n\n📌 Written feedback required.\n🔗 Provide X comment link on ALL reviews to earn the bonus.", color=mz('primary'))
        await interaction.response.send_message(embed=embed, ephemeral=True)
        await interaction.followup.send_modal(ReviewSubmitModal(self.db, config))

    @discord.ui.button(label="🙋 Ready for More", style=discord.ButtonStyle.secondary, row=1)
    async def ready_for_more(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = self.config
        if not _is_pro(interaction.user, config):
            return await interaction.followup.send(f"{Config.pro_role_name(config)} role required.", ephemeral=True)
        guild_id = str(interaction.guild_id)
        uid = str(interaction.user.id)
        user = await self.db.get_user(uid, guild_id)
        if user and user.get('ready_for_more'):
            queue = await self.db.get_ready_for_more_users(guild_id)
            pos = next((i+1 for i, u in enumerate(queue) if u['user_id'] == uid), len(queue))
            return await interaction.followup.send(f"✅ Already in queue at position **#{pos}**.", ephemeral=True)
        await self.db.set_ready_for_more(uid, guild_id, 1)
        queue = await self.db.get_ready_for_more_users(guild_id)
        pos = len(queue)
        config_data = await self.db.get_guild_config(guild_id) or {}
        if config_data.get('log_channel_id'):
            ch = interaction.guild.get_channel(int(config_data['log_channel_id']))
            if ch:
                await ch.send(f"📬 {interaction.user.mention} is ready for more assignments. Queue: #{pos}")
        await interaction.followup.send(embed=discord.Embed(title="✅ Request Sent", description=f"You are requesting more assignments.\nQueue position: **#{pos}**", color=mz('green')), ephemeral=True)


class SettingsMenuView(AdminView):
    def __init__(self, db, config):
        super().__init__(timeout=120)
        self.db = db
        self.config = config

    @discord.ui.button(label="📊 View Config", style=discord.ButtonStyle.primary, row=0)
    async def view_config(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        g = interaction.guild
        def rn(rid): r = g.get_role(int(rid)) if rid else None; return r.mention if r else "Not set"
        def cn(cid): c = g.get_channel(int(cid)) if cid else None; return c.mention if c else "Not set"
        mc = config.get('txt_mc_name', 'MC')
        embed = discord.Embed(title="⚙️ Current Configuration", color=mz('secondary'))
        embed.add_field(name="Roles", value=f"Reviewer: {rn(config.get('pro_role_id'))}\nBasic: {rn(config.get('basic_role_id'))}\nAdmin: {rn(config.get('admin_role_id'))}", inline=True)
        embed.add_field(name="Channels", value=f"Bot Panel: {cn(config.get('bot_content_channel_id'))}\nShowcase: {cn(config.get('showcase_channel_id'))}\nLeaderboard: {cn(config.get('leaderboard_channel_id'))}\nLog: {cn(config.get('log_channel_id'))}", inline=True)
        embed.add_field(name="Parameters", value=f"Max Submits: {config.get('max_submits_per_week',5)}/week\nMax Reviews: {config.get('max_reviews_per_week',7)}/week\nReview Window: {config.get('review_window_days',5)} days\nMin Reviews: {config.get('min_reviews',5)}\nShowcase: {config.get('showcase_threshold',8.0)}/10", inline=False)
        embed.add_field(name=f"{mc} Values", value=f"Average 4–6: {config.get('mc_score_low',1.0)} | 6–8: {config.get('mc_score_medium',3.0)} | 8–10: {config.get('mc_score_high',5.0)}\nReview goal: {config.get('mc_review_reward',2.0)} | Full submissions: {config.get('mc_submit_completion',2.0)}", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔢 Numbers", style=discord.ButtonStyle.secondary, row=0)
    async def numbers(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(NumberSettingsModal(self.db))

    @discord.ui.button(label="📣 Channel / Role Setup", style=discord.ButtonStyle.secondary, row=1)
    async def channels_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("Use `/setup_channels` to update channels and `/setup_roles` to update roles.", ephemeral=True)


class AdvancedSettingsMenuView(AdminView):
    def __init__(self, db, config):
        super().__init__(timeout=120)
        self.db = db
        self.config = config

    @discord.ui.button(label="📝 Texts & Names", style=discord.ButtonStyle.primary, row=0)
    async def texts(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(TextsModal(self.db))

    @discord.ui.button(label="💎 MC Values", style=discord.ButtonStyle.secondary, row=0)
    async def credit_values(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CreditValuesModal(self.db))

    @discord.ui.button(label="😀 Reaction Emojis & MC", style=discord.ButtonStyle.secondary, row=0)
    async def reaction_settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(ReactionSettingsModal(self.db))

    @discord.ui.button(label="💬 Automated Messages", style=discord.ButtonStyle.secondary, row=1)
    async def auto_messages(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(AutoMessagesModal(self.db))

    @discord.ui.button(label="✏️ Edit About Text", style=discord.ButtonStyle.secondary, row=1)
    async def edit_about(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        await interaction.response.send_modal(EditAboutModal(self.db, config.get('txt_about', '')))


class MainPanelView(discord.ui.View):
    def __init__(self, db):
        super().__init__(timeout=None)
        self.db = db

    @discord.ui.button(label="Dashboard", style=discord.ButtonStyle.primary, custom_id="mz_main_dashboard", row=0)
    async def dashboard(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await _cfg(interaction)
        user = await self.db.get_or_create_user(str(interaction.user.id), str(interaction.guild_id), interaction.user.name)
        mc = Config.mc_name(config)
        has_x = bool(user.get('twitter_username'))
        changes_left = max(0, 2 - user.get('twitter_changes_used', 0))
        embed = discord.Embed(title=f"👤 {interaction.user.display_name}", color=mz('primary'))
        if has_x:
            embed.description = f"X Handle: **@{user['twitter_username']}** | {changes_left} change(s) remaining"
        else:
            embed.description = "⚠️ **Register your X handle to unlock all features.**"
        embed.add_field(name=f"💎 {mc} Balance", value=f"{user.get('mc_regular',0)+user.get('mc_golden',0)+user.get('mc_assignment',0):.1f} {mc}", inline=True)
        await interaction.followup.send(embed=embed, view=DashboardView(self.db, config), ephemeral=True)

    @discord.ui.button(label="Submission", style=discord.ButtonStyle.danger, custom_id="mz_main_submission", row=0)
    async def submission(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await _cfg(interaction)
        if not await _require_x(interaction, self.db, config):
            return
        max_s = Config.get_max_submits(config)
        user = await self.db.get_user(str(interaction.user.id), str(interaction.guild_id))
        remaining = user.get('weekly_submits', max_s) if user else max_s
        embed = discord.Embed(title="📝 Submission", description=f"Submit your posts for review.\n\n**Remaining this week:** {remaining}/{max_s}", color=mz('secondary'))
        await interaction.followup.send(embed=embed, view=SubmissionView(self.db, config, interaction.guild), ephemeral=True)

    @discord.ui.button(label="Reviews", style=discord.ButtonStyle.secondary, custom_id="mz_main_reviews", row=0)
    async def reviews(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await _cfg(interaction)
        if not await _require_x(interaction, self.db, config):
            return
        if not _is_pro(interaction.user, config):
            return await interaction.followup.send(f"Reviews section is for **{Config.pro_role_name(config)}** role only.", ephemeral=True)
        week_id = get_current_week_id()
        all_assignments = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id)
        pending = [a for a in all_assignments if a['status'] in ('pending','warning')]
        completed = await self.db.get_assignments_by_reviewer(str(interaction.user.id), week_id, 'completed')
        max_r = Config.get_max_reviews(config)
        mc = Config.mc_name(config)
        embed = discord.Embed(title="⭐ Reviews", description=f"**Be fair — give the feedback you would like to receive.**\n\nProgress: **{len(completed)}/{max_r}** | Pending: **{len(pending)}**\nComplete {max_r} reviews → earn **{Config.get_review_reward(config)} {mc}**", color=mz('primary'))
        await interaction.followup.send(embed=embed, view=ReviewsView(self.db, config), ephemeral=True)

    @discord.ui.button(label="❓ FAQ & Guide", style=discord.ButtonStyle.secondary, custom_id="mz_main_faq", row=1)
    async def faq(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await _cfg(interaction)
        mc = Config.mc_name(config)
        bot_name = Config.bot_name(config)
        pro = Config.pro_role_name(config)
        threshold = Config.get_showcase_threshold(config)
        max_s = Config.get_max_submits(config)
        max_r = Config.get_max_reviews(config)
        window = Config.get_review_window(config)
        review_reward = Config.get_review_reward(config)
        comment_bonus = Config.get_comment_bonus(config)
        showcase_reward = Config.get_showcase_reward(config)
        is_pro = _is_pro(interaction.user, config)
        embed = discord.Embed(title=f"❓ {bot_name} — FAQ & Guide", color=mz('primary'))
        embed.add_field(name="Step 1 — Register", value="Click **Dashboard** → **Register X Handle**.\nYou get 1 free change after registration.", inline=False)
        embed.add_field(name="Step 2 — Submit", value=f"Click **Submission** → **Submit Post** and paste your X link.\nMax {max_s} posts/week. Resets every Saturday.", inline=False)
        if is_pro:
            embed.add_field(name=f"Reviews ({pro})", value=f"Click **Reviews** → **Assignments** to see your posts.\nScore + written feedback required.\nProvide X comment on ALL reviews → earn **+{comment_bonus} {mc} bonus**.\nComplete {max_r} reviews in {window} days → earn **{review_reward} {mc}**.", inline=False)
        embed.add_field(name=f"🪙 {mc} Rewards", value=(
            f"Average 4–6 → {Config.g(config, 'mc_score_low', 1.0)} {mc}\n"
            f"Average 6–8 → {Config.g(config, 'mc_score_medium', 3.0)} {mc}\n"
            f"Average 8–10 → {Config.g(config, 'mc_score_high', 5.0)} {mc}\n"
            f"Score {threshold:.0f}+ → 🌟 Showcase + **{showcase_reward} {mc}** bonus"
        ), inline=False)
        embed.add_field(name="❓ Common Questions", value=(
            "**Q: Why can't I submit?**\nA: Register your X handle first via Dashboard.\n\n"
            "**Q: When do submits reset?**\nA: Every Saturday midnight.\n\n"
            "**Q: How do I earn the comment bonus?**\nA: Provide X comment link on ALL your reviews this week.\n\n"
            "**Q: Where is the leaderboard?**\nA: Check the dedicated leaderboard channel."
        ), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="ℹ️ About", style=discord.ButtonStyle.secondary, custom_id="mz_main_about", row=1)
    async def about(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await _cfg(interaction)
        bot_name = Config.bot_name(config)
        about_text = config.get('txt_about', '')
        embed = discord.Embed(title=f"ℹ️ About {bot_name}", color=mz('secondary'))
        if about_text:
            embed.description = about_text
        else:
            embed.description = "No about text set yet.\nAdmins can set this via **Admin Panel** → **Advanced Settings** → **Edit About Text**."
        await interaction.followup.send(embed=embed, ephemeral=True)



    @discord.ui.button(label="📚 Quiz", style=discord.ButtonStyle.secondary, custom_id="mz_main_quiz", row=1)
    async def quiz(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await _cfg(interaction)
        quiz = await self.db.get_active_quiz(str(interaction.guild_id))
        mc = Config.mc_name(config)
        min_pct = int(Config.g(config, 'quiz_mc_min_pct', 40))
        if not quiz:
            embed = discord.Embed(
                title="📚 Quiz",
                description="No active quiz right now.\n\nCheck back when a new article drops.",
                color=mz('secondary')
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)
        import json as _json
        questions = _json.loads(quiz['questions_json'])
        uid = str(interaction.user.id)
        guild_id = str(interaction.guild_id)
        existing = await self.db.get_quiz_result(guild_id, uid, quiz['id'])
        embed = discord.Embed(title=f"📚 {quiz['title']}", color=mz('primary'))
        if existing:
            mins, secs = existing['elapsed_seconds'] // 60, existing['elapsed_seconds'] % 60
            icon = "✅" if existing['score_pct'] >= 70 else ("🟡" if existing['score_pct'] >= 40 else "❌")
            embed.description = (
                f"{icon} You already completed this quiz.\n\n"
                f"**Score:** {existing['score_pct']:.0f}% ({existing['correct_count']}/{existing['total_questions']})\n"
                f"**{mc} earned:** {existing['mc_earned']}\n"
                f"**Time:** {mins}m {secs}s"
            )
        else:
            embed.description = (
                f"**{len(questions)} questions** on this week's article.\n\n"
                f"🪙 Score {min_pct}%+ → earn {mc}\n"
                f"🏅 Score 70%+ → earn {mc} + quiz role\n\n"
                f"Only you can see the questions. No time limit."
            )
        from cogs.quiz import QuizUserView
        view = QuizUserView(self.db, config, quiz)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)


    @discord.ui.button(label="Guide and next steps",style=discord.ButtonStyle.secondary,custom_id="mz_user_guide_v3",row=2)
    async def user_guide(self,interaction:discord.Interaction,button:discord.ui.Button):
        await interaction.client.get_cog("Guide").open_guide(interaction,resume=True)


class RaffleAdminView(AdminView):
    def __init__(self, db, config, guild):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.guild = guild

    @discord.ui.button(label="🎟️ Give to User", style=discord.ButtonStyle.primary, row=0)
    async def give(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(RaffleGiveModal(self.db, self.config))

    @discord.ui.button(label="🗑️ Revoke All", style=discord.ButtonStyle.danger, row=0)
    async def revoke_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        role_id = config.get('raffle_role_id')
        if not role_id:
            return await interaction.followup.send("No raffle role set. Use `/setup_raffle_role`.", ephemeral=True)
        role = interaction.guild.get_role(int(role_id))
        if not role:
            return await interaction.followup.send("Raffle role not found.", ephemeral=True)
        manage_error = role_manage_error(interaction.guild, role)
        if manage_error:
            return await interaction.followup.send(f"❌ {manage_error}", ephemeral=True)
        revoked = 0
        for member in list(role.members):
            try:
                await member.remove_roles(role, reason=f"Raffle reset by {interaction.user.id}")
                revoked += 1
            except Exception:
                pass
        await interaction.followup.send(
            embed=discord.Embed(title="✅ Revoked", description=f"Removed raffle role from **{revoked}** users.", color=mz('green')),
            ephemeral=True
        )

    @discord.ui.button(label="ℹ️ Current Holders", style=discord.ButtonStyle.secondary, row=0)
    async def holders(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        role_id = config.get('raffle_role_id')
        if not role_id:
            return await interaction.followup.send("No raffle role set.", ephemeral=True)
        role = interaction.guild.get_role(int(role_id))
        if not role:
            return await interaction.followup.send("Raffle role not found.", ephemeral=True)
        count = len(role.members)
        embed = discord.Embed(title="🎟️ Raffle Role Holders", color=mz('secondary'))
        embed.add_field(name="Total", value=str(count), inline=False)
        if count and count <= 30:
            embed.add_field(name="Members", value=" ".join(m.mention for m in role.members), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)


class RaffleGiveModal(AdminModal, title="Give Raffle Role"):
    user_ids = discord.ui.TextInput(
        label="User IDs or mentions (space separated)",
        placeholder="@user1 @user2 or 123456 789012",
        style=discord.TextStyle.paragraph,
        max_length=500
    )

    def __init__(self, db, config):
        super().__init__()
        self.db = db
        self.config = config

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        role_id = config.get('raffle_role_id')
        if not role_id:
            return await interaction.followup.send("No raffle role set. Use `/setup_raffle_role`.", ephemeral=True)
        role = interaction.guild.get_role(int(role_id))
        if not role:
            return await interaction.followup.send("Raffle role not found.", ephemeral=True)
        raw = self.user_ids.value
        ids = re.findall(r'(\d{15,25})', raw)
        if not ids:
            return await interaction.followup.send("No valid user IDs found.", ephemeral=True)
        given, skipped, failed = 0, 0, 0
        for uid in ids:
            member = await resolve_member(interaction.guild, int(uid))
            if not member:
                failed += 1
                continue
            if role in member.roles:
                skipped += 1
                continue
            try:
                await member.add_roles(role, reason=f"Raffle panel by {interaction.user.id}")
                given += 1
            except discord.Forbidden:
                failed += 1
            except discord.HTTPException as e:
                log.warning("Raffle role grant failed for %s: %s", uid, e)
                failed += 1
        await interaction.followup.send(
            embed=discord.Embed(
                title="🎟️ Raffle Role",
                description=f"✅ Granted: **{given}**\n⏭️ Already had: **{skipped}**\n❌ Failed: **{failed}**",
                color=mz('green')
            ),
            ephemeral=True
        )


class AdminHelpView(AdminView):
    """Guided help — click a section to see instructions."""
    def __init__(self, db, config):
        super().__init__(timeout=180)
        self.db = db
        self.config = config

    async def _send(self, interaction, title, lines):
        embed = discord.Embed(title=title, description="\n".join(lines), color=mz('secondary'))
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @discord.ui.button(label="⚙️ Setup", style=discord.ButtonStyle.primary, row=0)
    async def setup_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "⚙️ Setup", [
            "**Order:**",
            "1. `/setup_start` — pick admin",
            "2. `/setup_roles` — Reviewer, Basic, Admin roles",
            "3. `/setup_channels` — bot, showcase, leaderboard, log",
            "4. `/panel` — post user panel",
            "5. `/setup_leaderboard` — post leaderboard",
            "",
            "**Optional:**",
            "`/setup_quiz_role`, `/setup_raffle_role`, `/setup_raffle_reaction`, `/setup_assignment_channel`, `/setup_reactions`",
        ])

    @discord.ui.button(label="📝 Content & Reviews", style=discord.ButtonStyle.secondary, row=0)
    async def content_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "📝 Content & Reviews", [
            "Users submit X posts via the panel.",
            "Posts are randomly assigned to Reviewers who score 1-10 with written feedback.",
            "Average score gives MC to the author. Score 8+ goes to the showcase channel.",
            "",
            "**Submission MC (score from 4):**",
            f"All weekly submissions used: {Config.get_submit_completion_reward(config)} {mc}",
            "Avg 4-6 / 6-8 / 8-10: set in Settings.",
        ])

    @discord.ui.button(label="🪙 MC & Reactions", style=discord.ButtonStyle.secondary, row=0)
    async def mc_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "🪙 MC & Reactions", [
            "**Three MC types:** 🪙 Regular, 🏆 Golden, 🎯 Assignment.",
            "All three count toward the leaderboard total.",
            "",
            "**Give MC:** Admin panel → Award MC, or via reactions.",
            "**Reactions:** up to 5 MC emojis (`/setup_reactions`). Admin reacts to a post to award.",
            "One award per admin per emoji per message.",
        ])

    @discord.ui.button(label="📚 Quiz", style=discord.ButtonStyle.secondary, row=1)
    async def quiz_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "📚 Quiz", [
            "Admin panel → Quiz → Load Quiz (paste JSON).",
            "Loading a new quiz revokes the quiz role from everyone.",
            "Users take it from the panel — one attempt each.",
            "",
            "**MC:** 40-69% → 1, 70-79% → 2, 80-89% → 3, 90%+ → 5 (adjustable).",
            "Score 70%+ grants the quiz role. Set it with `/setup_quiz_role`.",
        ])

    @discord.ui.button(label="📋 Assignments", style=discord.ButtonStyle.secondary, row=1)
    async def assign_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "📋 Assignments", [
            "Set the channel with `/setup_assignment_channel`.",
            "Admin panel → Assignments → New Assignment.",
            "Bot creates a thread (name = title, body = first message).",
            "",
            "Users post only inside threads. Main channel is admin-only.",
            "Cooldown (up to 7d) limits posts per user per thread.",
            "Recurring assignments stay open. Close them anytime.",
        ])

    @discord.ui.button(label="🎟️ Raffle & 📸 Snapshot", style=discord.ButtonStyle.secondary, row=1)
    async def raffle_snap_help(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self._send(interaction, "🎟️ Raffle & 📸 Snapshot", [
            "**Raffle role:** grant via reaction, `/give_raffle`, or the panel.",
            "Reset anytime with `/revoke_all_raffle` or the panel. Skips users who already have it.",
            "",
            "**Snapshot:** run `/snapshot` in a channel/thread.",
            "Pick MC type, hours back, amount, reason. Preview, then confirm.",
            "Everyone who posted in the window gets MC once.",
        ])


class AdminMainView(AdminView):
    def __init__(self, db):
        super().__init__(timeout=None)
        self.db = db

    async def _check_admin(self, interaction):
        config = await _cfg(interaction)
        if not _is_admin(interaction.user, config):
            await interaction.response.send_message("Admin only.", ephemeral=True)
            return None
        return config

    @discord.ui.button(label="📊 Stats", style=discord.ButtonStyle.primary, custom_id="mz_adm_stats", row=0)
    async def stats(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        week_id = get_current_week_id()
        guild_id = str(interaction.guild_id)
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
            embed.add_field(name=f"⚠️ Stalled ({len(stalled)})", value="\n".join(f"`{p['post_id'][:8]}`" for p in stalled[:5]), inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="👥 Reviewer Status", style=discord.ButtonStyle.secondary, custom_id="mz_adm_pro", row=0)
    async def reviewer_status(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        if not config.get('pro_role_id'):
            return await interaction.followup.send("Reviewer role not configured.", ephemeral=True)
        pro_role = interaction.guild.get_role(int(config['pro_role_id']))
        if not pro_role:
            return await interaction.followup.send("Reviewer role not found.", ephemeral=True)
        week_id = get_current_week_id()
        y, w = week_id.split('-W'); w = int(w)
        prev_week = f"{y}-W{w-1:02d}" if w > 1 else f"{int(y)-1}-W52"
        inactive = []
        month_ago = datetime.now(TEHRAN) - timedelta(days=30)
        for member in pro_role.members:
            if member.bot: continue
            this_w = await self.db.get_reviews_by_reviewer(str(member.id), week_id)
            prev_w = await self.db.get_reviews_by_reviewer(str(member.id), prev_week)
            if len(this_w) == 0 and len(prev_w) == 0:
                inactive.append(member.display_name)
        embed = discord.Embed(title=f"👥 {Config.pro_role_name(config)} Monitor", color=mz('primary'))
        embed.add_field(name="Summary", value=f"Total: {len(pro_role.members)} | Inactive 2wks: {len(inactive)}", inline=False)
        if inactive:
            embed.add_field(name="⚠️ Inactive", value="\n".join(inactive[:15]), inline=False)
        else:
            embed.description = "✅ All reviewers performed recently!"
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔄 Distribute Reviews", style=discord.ButtonStyle.secondary, custom_id="mz_adm_assign", row=0)
    async def assign_now(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        tasks_cog = interaction.client.get_cog('Tasks')
        if tasks_cog:
            await tasks_cog.process_guild_weekly(interaction.guild)
        await interaction.followup.send("✅ Assignment cycle complete.", ephemeral=True)

    @discord.ui.button(label="💰 Award MC", style=discord.ButtonStyle.secondary, custom_id="mz_adm_give_mc", row=1)
    async def give_mc(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.send_modal(GiveMCModal(self.db, config))

    @discord.ui.button(label="👤 User Info", style=discord.ButtonStyle.secondary, custom_id="mz_adm_user_info", row=1)
    async def user_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.send_modal(UserInfoModal(self.db, config))

    @discord.ui.button(label="📤 Export CSV", style=discord.ButtonStyle.secondary, custom_id="mz_adm_export", row=1)
    async def export_csv(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        week_id = get_current_week_id()
        mc = Config.mc_name(config)
        users = await self.db.get_all_users(guild_id)
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(['Username', 'X Handle', 'Role', f'Regular {mc}', f'Golden {mc}', f'Assignment {mc}', f'Total {mc}'])
        for u in users:
            writer.writerow([u.get('username',''), u.get('twitter_username',''), u.get('role_type',''), u.get('mc_regular',0), u.get('mc_golden',0), u.get('mc_assignment',0), u.get('mc_regular',0)+u.get('mc_golden',0)+u.get('mc_assignment',0)])
        output.seek(0)
        file = discord.File(io.BytesIO(output.getvalue().encode()), filename=f"users_{week_id}.csv")
        await interaction.followup.send(f"📊 Export: `users_{week_id}.csv`", file=file, ephemeral=True)

    @discord.ui.button(label="📖 Admin Guide", style=discord.ButtonStyle.primary, custom_id="mz_adm_guide", row=2)
    async def admin_guide(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        mc = Config.mc_name(config)
        embed = discord.Embed(title="🔧 Admin Reference", color=mz('red'))
        embed.add_field(name="Setup Order", value="`/setup_start` → `/setup_roles` → `/setup_channels`\nThen `/panel` in bot channel and `/setup_leaderboard` in leaderboard channel.", inline=False)
        embed.add_field(name="Settings", value="Use **Settings** to view config and change numeric values.\nUse **Advanced Settings** to change texts, MC values, messages, and About.", inline=False)
        embed.add_field(name="MC Reactions", value="Set 3 emojis with `/setup_reactions`.\nOnly admins can trigger. No self-credits.", inline=False)
        embed.add_field(name="Comment Bonus Rule", value="Reviewers earn the bonus ONLY if ALL reviews this week have an X comment link.", inline=False)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="⚙️ Settings", style=discord.ButtonStyle.secondary, custom_id="mz_adm_settings", row=2)
    async def settings(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=discord.Embed(title="⚙️ Settings", color=mz('secondary')), view=SettingsMenuView(self.db, config), ephemeral=True)

    @discord.ui.button(label="🔧 Advanced Settings", style=discord.ButtonStyle.danger, custom_id="mz_adm_advanced", row=2)
    async def advanced(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        await interaction.followup.send(embed=discord.Embed(title="🔧 Advanced Settings", color=mz('red')), view=AdvancedSettingsMenuView(self.db, config), ephemeral=True)



    @discord.ui.button(label="📚 Quiz", style=discord.ButtonStyle.primary, custom_id="mz_adm_quiz", row=3)
    async def quiz_section(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        from cogs.quiz import AdminQuizView
        embed = discord.Embed(
            title="📚 Quiz Management",
            description=(
                "**Load Quiz** — paste article JSON to activate a new quiz.\n"
                "Loading a new quiz automatically revokes the old quiz role from all holders.\n\n"
                "**Revoke All** — manually remove the quiz role from everyone."
            ),
            color=mz('primary')
        )
        await interaction.followup.send(
            embed=embed,
            view=AdminQuizView(self.db, config, interaction.guild),
            ephemeral=True
        )

    @discord.ui.button(label="📋 Community Tasks", style=discord.ButtonStyle.primary, custom_id="mz_adm_assignments", row=3)
    async def assignments_section(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        from cogs.assignments import AssignmentAdminView
        embed = discord.Embed(
            title="📋 Community Task Manager",
            description=(
                "**New Task** — creates a thread in the community tasks channel.\n"
                "Users post inside the thread. The main channel stays admin-only.\n\n"
                "View active and past assignments with participant counts, or close one."
            ),
            color=mz('primary')
        )
        await interaction.followup.send(
            embed=embed,
            view=AssignmentAdminView(self.db, config, interaction.guild),
            ephemeral=True
        )

    @discord.ui.button(label="🎟️ Raffle", style=discord.ButtonStyle.secondary, custom_id="mz_adm_raffle", row=3)
    async def raffle_section(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="🎟️ Raffle Role",
            description=(
                "Grant or revoke the raffle access role.\n\n"
                "Also grantable via reaction (`/setup_raffle_reaction`) or "
                "`/give_raffle`. Set the role first with `/setup_raffle_role`."
            ),
            color=mz('primary')
        )
        await interaction.followup.send(
            embed=embed,
            view=RaffleAdminView(self.db, config, interaction.guild),
            ephemeral=True
        )

    @discord.ui.button(label="📸 Snapshot", style=discord.ButtonStyle.secondary, custom_id="mz_adm_snapshot", row=4)
    async def snapshot_section(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.send_message(
            embed=discord.Embed(
                title="📸 Snapshot MC",
                description=(
                    "Run `/snapshot` in the channel or thread you want to scan.\n\n"
                    "The bot asks for MC type, time window, amount, and reason, then "
                    "shows a preview before awarding MC to everyone who posted."
                ),
                color=mz('primary')
            ),
            ephemeral=True
        )

    @discord.ui.button(label="📖 Help & Guide", style=discord.ButtonStyle.success, custom_id="mz_adm_help", row=4)
    async def help_menu(self, interaction: discord.Interaction, button: discord.ui.Button):
        config = await self._check_admin(interaction)
        if not config: return
        await interaction.response.defer(ephemeral=True)
        embed = discord.Embed(
            title="📖 Admin Help & Guide",
            description="Pick a section below to see how it works.",
            color=mz('secondary')
        )
        await interaction.followup.send(
            embed=embed,
            view=AdminHelpView(self.db, config),
            ephemeral=True
        )


class PanelCog(BotHelpers, commands.Cog, name="Panel"):
    def __init__(self, bot):
        self.bot = bot

    async def cog_load(self):
        self.bot.add_view(MainPanelView(self.db))
        log.info("Persistent panel views registered")

    @app_commands.command(name="panel", description="Post the user panel in this channel")
    async def panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=False)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        mc = Config.mc_name(config)
        threshold = Config.get_showcase_threshold(config)
        max_s = Config.get_max_submits(config)
        max_r = Config.get_max_reviews(config)
        embed = discord.Embed(title=Config.panel_title(config), description=Config.panel_desc(config), color=mz('primary'))
        embed.add_field(name="📝 Submission", value=f"Record your posts for review (max {max_s}/week)", inline=True)
        embed.add_field(name="⭐ Reviews", value=f"Complete {max_r} reviews → earn {Config.get_review_reward(config)} {mc}", inline=True)
        embed.add_field(name=f"💎 {mc} Rewards", value=f"Score {threshold:.0f}+ → Showcase + bonus\nReview + comment bonus available", inline=False)
        embed.set_footer(text="All responses are private — only you can see them")
        await interaction.followup.send(embed=embed, view=MainPanelView(self.db))

    @app_commands.command(name="admin_panel", description="Open the admin panel (admin only)")
    async def admin_panel(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        if not _is_admin(interaction.user, config):
            return await interaction.followup.send("Admin only.", ephemeral=True)
        from cogs.control_center import UnifiedAdminView
        embed = discord.Embed(
            title="🔧 Admin Control Center",
            description="Choose a section. All actions and responses are private.",
            color=mz('red')
        )
        await interaction.followup.send(embed=embed, view=UnifiedAdminView(self.db), ephemeral=True)


async def setup(bot):
    await bot.add_cog(PanelCog(bot))
