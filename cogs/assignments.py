from ui_security import AdminView,AdminModal
"""
cogs/assignments.py — Assignment Manager
- Admin creates assignment from panel: name, body, cooldown, recurring flag
- Bot creates a thread in the assignments channel (name = title, body = first message)
- Users may only post inside threads, not the main channel
- Non-admin messages in the main assignments channel are deleted + ephemeral warning
- Per-thread cooldown enforced
- Admin can list active/closed assignments with participant counts, and close them
"""
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config_service import request_config_change, reply
from config import Config, mz
from runtime_utils import authorized, utc_iso
from datetime import datetime, timezone, timedelta
import logging

log = logging.getLogger('MeleeZone.Assignments')
UTC = timezone.utc


def parse_task_cooldown(text):
    import re
    match = re.fullmatch(r'(\d+)([mhd]?)', (text or '0').strip().lower())
    if not match:
        raise ValueError('Use 0, seconds, or a duration such as 30m, 1h, 24h or 7d.')
    seconds = int(match[1]) * {'':1, 'm':60, 'h':3600, 'd':86400}[match[2]]
    if not 0 <= seconds <= 7 * 86400:
        raise ValueError('Task cooldown must be between zero and seven days.')
    return seconds


async def change_task_cooldown(interaction, assignment_id, cooldown):
    if not interaction.response.is_done():await interaction.response.defer(ephemeral=True)
    if not await authorized(interaction):return
    try:
        seconds = parse_task_cooldown(cooldown)
        aid = int(assignment_id)
    except (ValueError, TypeError) as exc:
        return await reply(interaction, str(exc))
    items = await interaction.client.db.get_assignments_mgr(str(interaction.guild_id), status='active')
    target = next((a for a in items if a['id'] == aid), None)
    if not target:return await reply(interaction, 'Active task not found in this server.')
    changed = await interaction.client.db.edit_task_cooldown(str(interaction.guild_id), aid, seconds)
    if not changed:return await reply(interaction, 'This task closed before the change. Refresh the task list.')
    note = ''
    from runtime_utils import resolve_channel
    thread = await resolve_channel(interaction.client, interaction.guild, target['thread_id']) if target.get('thread_id') else None
    if thread and getattr(thread, 'slowmode_delay', 0):
        try:
            await thread.edit(slowmode_delay=0, reason='Use bot-managed task cooldown; moderators bypass it')
        except discord.HTTPException:
            note = '\nDiscord native slowmode is still active. Ask an admin to grant Manage Threads and run /doctor repair:true.'
    await interaction.client.db.record_operation('task_cooldown', 'updated', guild_id=str(interaction.guild_id),
        detail=f"Task {aid}; actor {interaction.user.id}; {target['cooldown_seconds']} -> {seconds} seconds")
    await reply(interaction, f'Task #{aid} cooldown: {_fmt_cooldown(seconds)}. Moderator bypass is unchanged.' + note)


class TaskCooldownModal(AdminModal, title='Change task cooldown'):
    assignment_id = discord.ui.TextInput(label='Active task ID', max_length=10)
    cooldown = discord.ui.TextInput(label='Cooldown: 0, 30m, 1h, 24h, or 7d', max_length=10)
    async def on_submit(self, interaction):
        await change_task_cooldown(interaction, self.assignment_id.value, self.cooldown.value)


def _fmt_cooldown(seconds: int) -> str:
    if seconds <= 0:
        return "None"
    if seconds < 3600:
        return f"{seconds // 60}m"
    if seconds < 86400:
        return f"{seconds // 3600}h"
    return f"{seconds // 86400}d"


# ── Create Assignment Modal ───────────────────────────────────────────────────

class CreateAssignmentModal(AdminModal, title="New Community Task"):
    name = discord.ui.TextInput(
        label="Assignment name (thread title)",
        placeholder="Daily Screenshot",
        max_length=100
    )
    body = discord.ui.TextInput(
        label="Assignment text (thread first message)",
        placeholder="Post your daily screenshot here. Tag @role if needed.",
        style=discord.TextStyle.paragraph,
        max_length=2000
    )
    cooldown = discord.ui.TextInput(
        label="Post cooldown: 0, 1h, 24h, or 7d",
        placeholder="24h",
        required=False,
        max_length=10
    )
    recurring = discord.ui.TextInput(
        label="Recurring assignment? Type yes or no",
        placeholder="yes / no",
        required=False,
        max_length=4
    )

    def __init__(self, db, config, guild):
        super().__init__()
        self.db = db
        self.config = config
        self.guild = guild

    def _parse_cooldown(self, text: str) -> int:
        return parse_task_cooldown(text)

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await authorized(interaction):
            return
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        channel_id = config.get('assignment_channel_id')
        if not channel_id:
            return await interaction.followup.send(
                "Assignment channel not set. Use `/setup_assignment_channel` first.",
                ephemeral=True
            )
        channel = self.guild.get_channel(int(channel_id))
        if not channel:
            return await interaction.followup.send("Assignment channel not found.", ephemeral=True)

        try:
            cooldown_seconds = self._parse_cooldown(self.cooldown.value)
        except ValueError as exc:
            return await reply(interaction, str(exc))
        is_recurring = 1 if self.recurring.value.strip().lower() in ('yes', 'y', 'true', '1') else 0

        permissions = channel.permissions_for(self.guild.me)
        missing = []
        if not permissions.view_channel:
            missing.append("View Channel")
        if not permissions.send_messages:
            missing.append("Send Messages")
        if not permissions.create_public_threads:
            missing.append("Create Public Threads")
        if not permissions.send_messages_in_threads:
            missing.append("Send Messages in Threads")
        if missing:
            return await interaction.followup.send(
                "Missing permissions in the assignment channel: **" + ", ".join(missing) + "**.",
                ephemeral=True
            )

        # Create the thread
        try:
            thread = await channel.create_thread(
                name=self.name.value[:100],
                type=discord.ChannelType.public_thread,
                auto_archive_duration=10080,  # 7 days
                slowmode_delay=0
            )
        except Exception as e:
            log.error(f"Thread creation failed: {e}")
            return await interaction.followup.send(
                f"Could not create thread: {e}", ephemeral=True
            )

        # Post the body as the first message
        body_embed = discord.Embed(
            title=f"📋 {self.name.value}",
            description=self.body.value,
            color=mz('primary')
        )
        footer_bits = []
        if cooldown_seconds > 0:
            footer_bits.append(f"Cooldown: {_fmt_cooldown(cooldown_seconds)}")
        if is_recurring:
            footer_bits.append("Recurring")
        if footer_bits:
            body_embed.set_footer(text=" • ".join(footer_bits))
        await thread.send(embed=body_embed)

        # Save to DB
        try:
            assignment_id = await self.db.create_assignment_mgr(
                guild_id=str(interaction.guild_id),
                name=self.name.value,
                body=self.body.value,
                thread_id=str(thread.id),
                cooldown_seconds=cooldown_seconds,
                is_recurring=is_recurring,
                created_by=str(interaction.user.id)
            )
        except Exception as e:
            log.error("Assignment database save failed", exc_info=True)
            try:
                await thread.delete(reason="Assignment database save failed")
            except Exception:
                pass
            return await interaction.followup.send(
                f"The thread was rolled back because the assignment could not be saved: `{type(e).__name__}`.",
                ephemeral=True
            )

        embed = discord.Embed(title="✅ Assignment Created", color=mz('green'))
        embed.add_field(name="Name", value=self.name.value, inline=False)
        embed.add_field(name="Thread", value=thread.mention, inline=True)
        embed.add_field(name="Cooldown", value=_fmt_cooldown(cooldown_seconds), inline=True)
        embed.add_field(name="Recurring", value="Yes" if is_recurring else "No", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)


# ── Admin Assignment View ─────────────────────────────────────────────────────

class AssignmentAdminView(AdminView):
    def __init__(self, db, config, guild):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.guild = guild

    async def interaction_check(self, interaction):
        return await authorized(interaction)

    @discord.ui.button(label="➕ New Task", style=discord.ButtonStyle.primary, row=0)
    async def new_assignment(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not self.config.get('assignment_channel_id'):
            return await interaction.response.send_message(
                "Set the assignment channel first with `/setup_assignment_channel`.",
                ephemeral=True
            )
        await interaction.response.send_modal(
            CreateAssignmentModal(self.db, self.config, interaction.guild)
        )

    @discord.ui.button(label="📋 Active Tasks", style=discord.ButtonStyle.secondary, row=0)
    async def active_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        items = await self.db.get_assignments_mgr(str(interaction.guild_id), status='active')
        if not items:
            return await interaction.followup.send("No active assignments.", ephemeral=True)
        embed = discord.Embed(title="📋 Active Assignments", color=mz('primary'))
        for a in items[:15]:
            count = await self.db.get_assignment_participant_count(a['id'])
            thread = interaction.guild.get_thread(int(a['thread_id'])) if a['thread_id'] else None
            thread_ref = thread.mention if thread else "thread archived"
            embed.add_field(
                name=f"#{a['id']} — {a['name'][:40]}",
                value=(
                    f"{thread_ref} | 👥 {count} participants | "
                    f"CD: {_fmt_cooldown(a['cooldown_seconds'])}"
                    f"{' | 🔁 recurring' if a['is_recurring'] else ''}"
                ),
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🗂️ Past Tasks", style=discord.ButtonStyle.secondary, row=0)
    async def past_list(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        items = await self.db.get_assignments_mgr(str(interaction.guild_id), status='closed')
        if not items:
            return await interaction.followup.send("No closed assignments.", ephemeral=True)
        embed = discord.Embed(title="🗂️ Past Assignments", color=mz('secondary'))
        for a in items[:15]:
            count = await self.db.get_assignment_participant_count(a['id'])
            embed.add_field(
                name=f"#{a['id']} — {a['name'][:40]}",
                value=f"👥 {count} participants | closed {a['closed_at'][:10] if a.get('closed_at') else '—'}",
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🔒 Close Task", style=discord.ButtonStyle.danger, row=1)
    async def close_assignment(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(CloseAssignmentModal(self.db, interaction.guild))

    @discord.ui.button(label='Change cooldown',style=discord.ButtonStyle.secondary,row=1)
    async def edit_cooldown(self,interaction,button):
        await interaction.response.send_modal(TaskCooldownModal())

    @discord.ui.button(label='Skip member cooldown',style=discord.ButtonStyle.secondary,row=1)
    async def skip_cooldown(self,interaction,button):
        await reply(interaction,'In the task thread, use `/task_reset_cooldown user:` to let a member post immediately. Moderators already bypass task cooldown automatically.')


class CloseAssignmentModal(AdminModal, title="Close Assignment"):
    assignment_id = discord.ui.TextInput(label="Assignment ID (e.g. 3)", max_length=10)
    archive = discord.ui.TextInput(
        label="Archive thread too? yes/no",
        placeholder="yes",
        required=False,
        max_length=4
    )

    def __init__(self, db, guild):
        super().__init__()
        self.db = db
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        if not await authorized(interaction):
            return
        try:
            aid = int(self.assignment_id.value.strip())
        except ValueError:
            return await interaction.followup.send("Invalid ID.", ephemeral=True)
        items = await self.db.get_assignments_mgr(str(interaction.guild_id))
        target = next((a for a in items if a['id'] == aid), None)
        if not target:
            return await interaction.followup.send(f"Assignment #{aid} not found.", ephemeral=True)
        await self.db.close_assignment_mgr(aid)

        archived = False
        if self.archive.value.strip().lower() in ('yes', 'y', '') and target.get('thread_id'):
            thread = self.guild.get_thread(int(target['thread_id']))
            if thread:
                try:
                    await thread.edit(archived=True, locked=True)
                    archived = True
                except Exception:
                    pass

        embed = discord.Embed(
            title="✅ Assignment Closed",
            description=f"**{target['name']}** closed." + (" Thread archived." if archived else ""),
            color=mz('green')
        )
        await interaction.followup.send(embed=embed, ephemeral=True)


# ── Cog with message guard ────────────────────────────────────────────────────

class AssignmentsCog(BotHelpers, commands.Cog, name="Assignments"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup_assignment_channel",
        description="Set the assignments channel where threads are posted (admin)"
    )
    @app_commands.describe(channel="The assignments channel")
    async def setup_assignment_channel(self, interaction: discord.Interaction, channel: discord.TextChannel):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        if not await request_config_change(interaction, assignment_channel_id=str(channel.id)):return
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Assignment Channel Set",
                description=(
                    f"Assignments channel: {channel.mention}\n\n"
                    f"Only admins can post in the main channel.\n"
                    f"Users post inside assignment threads.\n\n"
                    f"Make sure I have **Manage Messages**, **Create Public Threads**, "
                    f"and **Send Messages in Threads** here."
                ),
                color=mz('green')
            ),
            ephemeral=True
        )

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot or not message.guild:
            return
        config = await self.db.get_guild_config(str(message.guild.id))
        if not config:
            return
        channel_id = config.get('assignment_channel_id')
        if not channel_id:
            return

        # ── Guard: main assignments channel — only admins may post ───
        if str(message.channel.id) == str(channel_id):
            if self.is_admin(message.author, config):
                return
            try:
                await message.delete()
            except Exception:
                pass
            try:
                warn = await message.channel.send(
                    f"{message.author.mention} please post inside the assignment threads, not here.",
                    delete_after=8
                )
            except Exception:
                pass
            return

        # ── Inside an assignment thread ──────────────────────────────
        if isinstance(message.channel, discord.Thread):
            assignment = await self.db.get_assignment_by_thread(str(message.channel.id))
            if not assignment:
                return
            if assignment['status'] != 'active':
                return

            uid = str(message.author.id)
            aid = assignment['id']

            # Bot administrators moderate and award MC without member cooldowns.
            if self.is_admin(message.author,config):
                await self.db.record_assignment_participant(aid,uid)
                return

            remaining=await self.db.accept_task_message(assignment,uid,utc_iso(message.created_at))
            if remaining:
                try:
                    await message.delete()
                except discord.HTTPException as exc:
                    await self.db.record_operation('task_cooldown','missing_delete_permission',guild_id=str(message.guild.id),detail=type(exc).__name__)
                try:
                    await message.channel.send(f'{message.author.mention} next post in {_fmt_cooldown(remaining)}.',delete_after=8,
                        allowed_mentions=discord.AllowedMentions.none())
                except discord.HTTPException:
                    pass
            return



async def setup(bot):
    await bot.add_cog(AssignmentsCog(bot))
