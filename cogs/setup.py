import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, mz
from datetime import datetime


class SetupCog(BotHelpers, commands.Cog, name="Setup"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(name="setup_start", description="Start configuration wizard")
    async def setup_start(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        await self.db.create_guild_config(guild_id)
        config = await self.db.get_guild_config(guild_id) or {}
        if not self.is_admin(interaction.user, config):
            return await interaction.followup.send("Administrator permission required.", ephemeral=True)
        if await self.db.is_guild_configured(guild_id):
            return await interaction.followup.send("Already configured. Use `/setup_view` or `/setup_reset`.", ephemeral=True)
        embed = discord.Embed(title="⚙️ Melee Zone — Setup Step 1/3", description="**Who has admin access to this bot?**\n\nAfter this:\n→ `/setup_roles` → `/setup_channels`\n→ `/panel` in bot channel\n→ `/setup_leaderboard` in leaderboard channel", color=mz('primary'))
        view = discord.ui.View(timeout=120)
        async def just_me(btn: discord.Interaction):
            await self.db.update_guild_config(guild_id, admin_user_id=str(interaction.user.id))
            await btn.response.edit_message(embed=discord.Embed(title="✅ Admin set to you", description="Now run `/setup_roles`.", color=mz('green')), view=None)
        b = discord.ui.Button(label="Just Me", style=discord.ButtonStyle.primary)
        b.callback = just_me
        view.add_item(b)
        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="setup_roles", description="Configure roles")
    @app_commands.describe(pro_role="Reviewer role", basic_role="Basic role (optional)", admin_role="Admin role (optional)")
    async def setup_roles(self, interaction: discord.Interaction, pro_role: discord.Role, basic_role: discord.Role = None, admin_role: discord.Role = None):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        updates = {'pro_role_id': str(pro_role.id)}
        if basic_role:
            updates['basic_role_id'] = str(basic_role.id)
        if admin_role:
            updates['admin_role_id'] = str(admin_role.id)
        await self.db.update_guild_config(str(interaction.guild_id), **updates)
        lines = [f"✅ Reviewer: {pro_role.mention}"]
        if basic_role:
            lines.append(f"✅ Basic: {basic_role.mention}")
        if admin_role:
            lines.append(f"✅ Admin: {admin_role.mention}")
        lines.append("\n➡️ Next: run `/setup_channels`")
        await interaction.followup.send(embed=discord.Embed(title="Roles Saved", description="\n".join(lines), color=mz('green')), ephemeral=True)

    @app_commands.command(name="setup_channels", description="Configure all channels")
    @app_commands.describe(bot_content_channel="Main bot channel", showcase_channel="Featured posts channel", mention_role="Role pinged for showcase", leaderboard_channel="Leaderboard channel (auto-updates)", log_channel="System log (optional)", credit_log_channel="Credit log (optional)", review_channel="Review notifications fallback (optional)")
    async def setup_channels(self, interaction: discord.Interaction, bot_content_channel: discord.TextChannel, showcase_channel: discord.TextChannel, mention_role: discord.Role, leaderboard_channel: discord.TextChannel, log_channel: discord.TextChannel = None, credit_log_channel: discord.TextChannel = None, review_channel: discord.TextChannel = None):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        updates = {'bot_content_channel_id': str(bot_content_channel.id), 'submit_channel_id': str(bot_content_channel.id), 'showcase_channel_id': str(showcase_channel.id), 'mention_role_id': str(mention_role.id), 'leaderboard_channel_id': str(leaderboard_channel.id), 'is_configured': 1, 'configured_at': datetime.now().isoformat()}
        if log_channel:
            updates['log_channel_id'] = str(log_channel.id)
        if credit_log_channel:
            updates['credit_log_channel_id'] = str(credit_log_channel.id)
        if review_channel:
            updates['review_channel_id'] = str(review_channel.id)
        await self.db.update_guild_config(str(interaction.guild_id), **updates)
        embed = discord.Embed(title="✅ Setup Complete", description=f"Bot Panel: {bot_content_channel.mention}\nShowcase: {showcase_channel.mention}\nLeaderboard: {leaderboard_channel.mention}\n\n→ Run `/panel` in bot content channel\n→ Run `/setup_leaderboard` in leaderboard channel", color=mz('green'))
        await interaction.followup.send(embed=embed, ephemeral=True)

    @app_commands.command(name="setup_reactions", description="Set MC reaction emojis (up to 5)")
    @app_commands.describe(emoji_1="Emoji 1", mc_1="MC for emoji 1", emoji_2="Emoji 2", mc_2="MC for emoji 2", emoji_3="Emoji 3", mc_3="MC for emoji 3", emoji_4="Emoji 4 (optional)", mc_4="MC for emoji 4", emoji_5="Emoji 5 (optional)", mc_5="MC for emoji 5")
    async def setup_reactions(self, interaction: discord.Interaction, emoji_1: str, mc_1: float, emoji_2: str, mc_2: float, emoji_3: str, mc_3: float, emoji_4: str = None, mc_4: float = None, emoji_5: str = None, mc_5: float = None):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        mc = Config.mc_name(config)
        updates = dict(reaction_emoji_1=emoji_1, reaction_mc_1=mc_1, reaction_emoji_2=emoji_2, reaction_mc_2=mc_2, reaction_emoji_3=emoji_3, reaction_mc_3=mc_3)
        lines = [f"{emoji_1} → {mc_1} {mc}", f"{emoji_2} → {mc_2} {mc}", f"{emoji_3} → {mc_3} {mc}"]
        if emoji_4 and mc_4 is not None:
            updates['reaction_emoji_4'] = emoji_4; updates['reaction_mc_4'] = mc_4
            lines.append(f"{emoji_4} → {mc_4} {mc}")
        if emoji_5 and mc_5 is not None:
            updates['reaction_emoji_5'] = emoji_5; updates['reaction_mc_5'] = mc_5
            lines.append(f"{emoji_5} → {mc_5} {mc}")
        await self.db.update_guild_config(str(interaction.guild_id), **updates)
        await interaction.followup.send(embed=discord.Embed(title="✅ Reaction Emojis Set", description="\n".join(lines), color=mz('green')), ephemeral=True)

    @app_commands.command(name="setup_raffle_reaction", description="Set the emoji that grants the raffle role")
    @app_commands.describe(emoji="Emoji that grants raffle role when admin reacts")
    async def setup_raffle_reaction(self, interaction: discord.Interaction, emoji: str):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        await self.db.update_guild_config(str(interaction.guild_id), raffle_reaction_emoji=emoji.strip())
        await interaction.followup.send(embed=discord.Embed(title="✅ Raffle Reaction Set", description=f"React with {emoji} to grant the raffle role.\nSet the role first with `/setup_raffle_role`.", color=mz('green')), ephemeral=True)

    @app_commands.command(name="setup_settings", description="Tune all numeric parameters")
    @app_commands.describe(max_submits="Max posts/user/week", max_reviews="Max reviews/reviewer/week", review_window_days="Days to complete a review", reminder_hours="Hours before reminder", min_reviews="Min reviews needed per post", showcase_threshold="Min avg score for showcase", require_twitter_id="Require X handle")
    async def setup_settings(self, interaction: discord.Interaction, max_submits: app_commands.Range[int, 1, 20] = None, max_reviews: app_commands.Range[int, 1, 20] = None, review_window_days: app_commands.Range[int, 1, 14] = None, reminder_hours: app_commands.Range[int, 12, 168] = None, min_reviews: app_commands.Range[int, 1, 10] = None, showcase_threshold: app_commands.Range[float, 5.0, 10.0] = None, require_twitter_id: bool = None):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        updates, changed = {}, []
        if max_submits is not None:
            updates['max_submits_per_week'] = max_submits; changed.append(f"Max submits/week: **{max_submits}**")
        if max_reviews is not None:
            updates['max_reviews_per_week'] = max_reviews; changed.append(f"Max reviews/week: **{max_reviews}**")
        if review_window_days is not None:
            updates['review_window_days'] = review_window_days; changed.append(f"Review window: **{review_window_days} days**")
        if reminder_hours is not None:
            updates['reminder_hours'] = reminder_hours; changed.append(f"Reminder after: **{reminder_hours}h**")
        if min_reviews is not None:
            updates['min_reviews'] = min_reviews; changed.append(f"Min reviews/post: **{min_reviews}**")
        if showcase_threshold is not None:
            updates['showcase_threshold'] = showcase_threshold; changed.append(f"Showcase threshold: **{showcase_threshold}/10**")
        if require_twitter_id is not None:
            updates['require_twitter_id'] = int(require_twitter_id); changed.append(f"Require X handle: **{require_twitter_id}**")
        if not updates:
            return await interaction.followup.send("No changes provided.", ephemeral=True)
        await self.db.update_guild_config(str(interaction.guild_id), **updates)
        await interaction.followup.send(embed=discord.Embed(title="✅ Settings Updated", description="\n".join(changed), color=mz('green')), ephemeral=True)

    @app_commands.command(name="setup_view", description="View current configuration")
    async def setup_view(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        from cogs.control_center import config_embed, SetupCenterView
        await interaction.followup.send(embed=config_embed(interaction.guild, config), view=SetupCenterView(self.db), ephemeral=True)

    @app_commands.command(name="setup_reset", description="Reset all configuration (keeps user data)")
    async def setup_reset(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        view = discord.ui.View(timeout=30)
        async def confirm(btn: discord.Interaction):
            await self.db.update_guild_config(str(interaction.guild_id), is_configured=0, pro_role_id=None, basic_role_id=None, admin_role_id=None, bot_content_channel_id=None, submit_channel_id=None, showcase_channel_id=None, leaderboard_channel_id=None, review_channel_id=None, log_channel_id=None, credit_log_channel_id=None, mention_role_id=None, reaction_emoji_1=None, reaction_emoji_2=None, reaction_emoji_3=None, reaction_emoji_4=None, reaction_emoji_5=None, raffle_reaction_emoji=None, raffle_role_id=None, assignment_channel_id=None, leaderboard_message_id=None, panel_message_id=None)
            await btn.response.edit_message(content="✅ Reset complete. Run `/setup_start` to reconfigure.", embed=None, view=None)
        async def cancel(btn: discord.Interaction):
            await btn.response.edit_message(content="Cancelled.", embed=None, view=None)
        b1 = discord.ui.Button(label="Confirm Reset", style=discord.ButtonStyle.danger)
        b2 = discord.ui.Button(label="Cancel", style=discord.ButtonStyle.secondary)
        b1.callback = confirm; b2.callback = cancel
        view.add_item(b1); view.add_item(b2)
        await interaction.followup.send(embed=discord.Embed(title="⚠️ Reset Configuration?", description="Erases all settings. User MC balances and post history are **kept**.", color=mz('red')), view=view, ephemeral=True)


async def setup(bot):
    await bot.add_cog(SetupCog(bot))
