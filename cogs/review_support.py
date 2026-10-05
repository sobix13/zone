"""Volunteer oversight, private feedback, fortnightly exports and setup calculator."""
import asyncio
import json
import logging
import os
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import discord
from discord import app_commands
from discord.ext import commands, tasks

from config import mz
from helpers import BotHelpers
from review_analytics import analyze, snapshot, participation_csv, estimate
from runtime_utils import authorized, parse_time, utc_iso
from ui_security import AdminView
from config_service import request_config_change

log = logging.getLogger('MeleeZone.ReviewSupport')


async def respond(i, text, **kwargs):
    if i.response.is_done():
        return await i.followup.send(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kwargs)
    return await i.response.send_message(text, ephemeral=True, allowed_mentions=discord.AllowedMentions.none(), **kwargs)


def cog(i):
    return i.client.get_cog('ReviewSupport')


class RolePicker(discord.ui.RoleSelect):
    def __init__(self, parent, key, label, row):
        super().__init__(placeholder=label, min_values=1, max_values=1, row=row)
        self.parent_view, self.key = parent, key

    async def callback(self, i):
        if not await authorized(i):
            return
        role = self.values[0]
        if role.is_default():
            return await respond(i, 'Select a specific role, not @everyone.')
        self.parent_view.selected[self.key] = str(role.id)
        await respond(i, f'{self.key.replace("_", " ")}: {role.name} selected. Save when finished.')


class SupportSetupView(AdminView):
    def __init__(self, existing):
        super().__init__(timeout=300)
        self.selected = {key: existing.get(key) for key in ('reviewer_role_id', 'moderator_role_id', 'member_role_id')}
        self.cap, self.samples = existing.get('weekly_cap', 10), existing.get('sample_size', 3)
        self.add_item(RolePicker(self, 'reviewer_role_id', 'Reviewer role', 0))
        self.add_item(RolePicker(self, 'moderator_role_id', 'Volunteer moderator role', 1))
        self.add_item(RolePicker(self, 'member_role_id', 'Optional member/content role', 2))

    @discord.ui.button(label='Save and enable', style=discord.ButtonStyle.success, row=3)
    async def save(self, i, button):
        await i.response.defer(ephemeral=True)
        try:
            if not await request_config_change(i, scope='support', enabled=True, weekly_cap=self.cap, sample_size=self.samples, **self.selected):return
            await cog(i).refresh_roster(i.guild)
            await i.client.db.start_support_cycle(str(i.guild_id))
        except (ValueError, discord.HTTPException, asyncio.TimeoutError) as exc:
            return await respond(i, f'Setup not completed: {str(exc)[:180]}. No partial roster was used.')
        await respond(i, 'Saved. Moderators choose their availability in `/support panel`. Private reports are prepared every 14 days and downloaded on request.')

    @discord.ui.button(label='Reviewers only', style=discord.ButtonStyle.secondary, row=3)
    async def reviewers_only(self, i, button):
        self.selected['member_role_id'] = None
        await respond(i, 'Optional member oversight cleared. Save to apply.')


class SupportAdminView(AdminView):
    def __init__(self):
        super().__init__(timeout=300)

    @discord.ui.button(label='Setup roles', style=discord.ButtonStyle.primary, row=0)
    async def setup_roles(self, i, button):
        cfg = await i.client.db.support_settings(str(i.guild_id))
        general = await i.client.db.get_guild_config(str(i.guild_id)) or {}
        cfg.setdefault('reviewer_role_id', general.get('pro_role_id'))
        await respond(i, 'Select roles, then save. Member oversight is optional. Default capacity: 10 people per moderator per week for each opted-in scope.', view=SupportSetupView(cfg))

    @discord.ui.button(label='14-day report', style=discord.ButtonStyle.secondary, row=0)
    async def report(self, i, button):
        await i.response.defer(ephemeral=True)
        await cog(i).queue_report(i, 14)

    @discord.ui.button(label='Latest Excel and CSV', style=discord.ButtonStyle.secondary, row=0)
    async def download(self, i, button):
        await i.response.defer(ephemeral=True)
        await cog(i).download_report(i)

    @discord.ui.button(label='Calculator', style=discord.ButtonStyle.secondary, row=1)
    async def calculator(self, i, button):
        await i.response.defer(ephemeral=True)
        job = await i.client.db.get_support_report(str(i.guild_id))
        if not job or job['state'] != 'completed':
            return await respond(i, 'Prepare a report first. Its Excel Calculator includes editable what-if settings. `/review_calculator` compares proposed limits without changing setup.')
        payload = json.loads(job['payload_json'])
        await cog(i).send_estimate(i, payload['estimate'], payload['recommendations'])

    @discord.ui.button(label='Refresh weekly allocation', style=discord.ButtonStyle.secondary, row=1)
    async def allocation(self, i, button):
        await i.response.defer(ephemeral=True)
        try:
            await cog(i).refresh_roster(i.guild)
            await i.client.db.start_support_cycle(str(i.guild_id))
        except (ValueError, discord.HTTPException, asyncio.TimeoutError) as exc:
            return await respond(i, f'Inventory unavailable: {type(exc).__name__}. Existing assignments remain unchanged.')
        await cog(i).send_status(i)

    @discord.ui.button(label='Second-look requests', style=discord.ButtonStyle.secondary, row=1)
    async def second_looks(self, i, button):
        rows = await i.client.db.second_looks(str(i.guild_id))
        text = '\n\n'.join(f"{r['id']}\nMember: {r['user_id']}\n{r['reason'][:150]}" for r in rows[:8]) or 'No open second-look requests.'
        await respond(i, text + '\nResolve with `/support resolve` after checking the evidence. The original rating remains in the audit history.')

    @discord.ui.button(label='Pause support', style=discord.ButtonStyle.secondary, row=2)
    async def pause_support(self, i, button):
        settings=await i.client.db.support_settings(str(i.guild_id))
        if not settings['enabled']:
            return await respond(i, 'Support is already paused. Saved messages, evaluations and reports are retained.')
        if not await request_config_change(i,scope='support',enabled=False,
            reviewer_role_id=settings['reviewer_role_id'],moderator_role_id=settings['moderator_role_id'],
            member_role_id=settings['member_role_id'],weekly_cap=settings['weekly_cap'],sample_size=settings['sample_size']):return
        await respond(i, 'Support scheduling, task scoring and optional DMs are paused. Existing MC, review cycle, inboxes and reports are unchanged. Save setup to resume.')


class ModeratorPanelView(discord.ui.View):
    def __init__(self, user_id, work=None, page=0):
        super().__init__(timeout=300)
        self.user_id, self.page = str(user_id), page
        pending = [w for w in (work or []) if w['state'] == 'pending']
        self.pages = max(1, (len(pending) + 9) // 10)
        selected = pending[page * 10:(page + 1) * 10]
        if selected:
            self.add_item(TaskPicker(selected))

    async def interaction_check(self, i):
        return str(i.user.id) == self.user_id and await cog(i).require_moderator(i)

    @discord.ui.button(label='I am available', style=discord.ButtonStyle.success, row=1)
    async def available(self, i, button):
        await i.response.defer(ephemeral=True)
        cfg = await i.client.db.support_settings(str(i.guild_id))
        try:
            await i.client.db.support_volunteer(str(i.guild_id), str(i.user.id), available=True, reviewer_capacity=min(10, cfg['weekly_cap']))
            await cog(i).refresh_roster(i.guild)
            await i.client.db.start_support_cycle(str(i.guild_id))
        except (ValueError, discord.HTTPException, asyncio.TimeoutError) as exc:
            return await respond(i, f'Allocation deferred: {type(exc).__name__}. No partial role inventory was applied. Try again later.')
        await cog(i).open_moderator(i)

    @discord.ui.button(label='Pause my workload', style=discord.ButtonStyle.secondary, row=1)
    async def pause(self, i, button):
        await i.client.db.support_volunteer(str(i.guild_id), str(i.user.id), available=False, reviewer_capacity=0)
        await i.client.db.start_support_cycle(str(i.guild_id))
        await respond(i, 'Paused without penalty. Unfinished tasks move to available volunteers within their capacities. Completed work stays recorded.')

    @discord.ui.button(label='Next tasks', style=discord.ButtonStyle.secondary, row=1)
    async def next_page(self, i, button):
        await cog(i).open_moderator(i, page=(self.page + 1) % self.pages)

    @discord.ui.button(label='Team messages', style=discord.ButtonStyle.secondary, row=2)
    async def messages(self, i, button):
        await cog(i).open_inbox(i)


class TaskPicker(discord.ui.Select):
    def __init__(self, items):
        options = [discord.SelectOption(label=f"{w['display_name'] or w['user_id']} ({w['kind']})"[:100], value=w['id']) for w in items]
        super().__init__(placeholder='Choose a person to support', options=options, min_values=1, max_values=1, row=0)

    async def callback(self, i):
        await cog(i).open_task(i, self.values[0])


class RatingModal(discord.ui.Modal, title='Private review and friendly feedback'):
    score = discord.ui.TextInput(label='Score 1-10. Blank only if no samples exist', required=False, max_length=2)
    checked = discord.ui.TextInput(label='Full IDs of samples you checked', style=discord.TextStyle.paragraph, required=False, max_length=300)
    feedback = discord.ui.TextInput(label='One strength and one helpful suggestion', style=discord.TextStyle.paragraph, min_length=30, max_length=1500)

    def __init__(self, item, moderator_id):
        super().__init__(timeout=300)
        self.item, self.moderator_id = item, str(moderator_id)
        self.checked.default = ', '.join(s['id'] for s in json.loads(item['samples_json']))

    async def interaction_check(self, i):
        return str(i.user.id) == self.moderator_id and await cog(i).require_moderator(i)

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        try:
            score = int(self.score.value.strip()) if self.score.value.strip() else None
            ids = [value.strip() for value in self.checked.value.split(',') if value.strip()]
            ident = await i.client.db.rate_support(str(i.guild_id), self.item['id'], self.moderator_id, score, self.feedback.value, ids)
        except ValueError as exc:
            return await respond(i, str(exc))
        await respond(i, f'Private feedback saved: {ident}. It is in the member\'s Team messages. An optional DM will be attempted. MC and roles stay unchanged.')


class TaskActions(discord.ui.View):
    def __init__(self, item, moderator_id):
        super().__init__(timeout=300)
        self.item, self.moderator_id = item, str(moderator_id)

    async def interaction_check(self, i):
        return str(i.user.id) == self.moderator_id and await cog(i).require_moderator(i)

    @discord.ui.button(label='Score and feedback', style=discord.ButtonStyle.primary)
    async def rate(self, i, button):
        item = await i.client.db.support_assignment(str(i.guild_id), self.item['id'])
        if not item or item['moderator_id'] != str(i.user.id) or item['state'] != 'pending':
            return await respond(i, 'This task is no longer assigned to you.')
        await i.response.send_modal(RatingModal(item, i.user.id))

    @discord.ui.button(label='Skip without penalty', style=discord.ButtonStyle.secondary)
    async def skip(self, i, button):
        await i.response.defer(ephemeral=True)
        try:
            await i.client.db.skip_support(str(i.guild_id), self.item['id'], str(i.user.id))
        except ValueError as exc:
            return await respond(i, str(exc))
        await respond(i, 'Skipped. Redistributed if another moderator has room, otherwise queued. No penalty was recorded.')


class MessageModal(discord.ui.Modal):
    body = discord.ui.TextInput(label='Your message', style=discord.TextStyle.paragraph, max_length=1000)

    def __init__(self, owner, message, action):
        super().__init__(title='Reply to the team' if action == 'reply' else 'Request a second look', timeout=300)
        self.owner, self.message, self.action = str(owner), message, action

    async def interaction_check(self, i):
        return str(i.user.id) == self.owner and bool(i.guild)

    async def on_submit(self, i):
        await i.response.defer(ephemeral=True)
        try:
            if self.action == 'reply':
                await i.client.db.reply_team_message(str(i.guild_id), self.owner, self.message['id'], self.body.value, str(i.id))
                text = 'Your private reply is saved for the sender.'
            else:
                ident = await i.client.db.request_second_look(str(i.guild_id), self.owner, self.message['evaluation_id'], self.body.value)
                text = f'Second-look request {ident} saved for the admins. No MC or role change occurs.'
        except ValueError as exc:
            return await respond(i, str(exc))
        await respond(i, text)


class MessagePicker(discord.ui.Select):
    def __init__(self, rows):
        super().__init__(placeholder='Choose a message to reply or request a second look',
                         options=[discord.SelectOption(label=f"{r['created_at'][:10]} from {r['sender_id']}"[:100], value=r['id']) for r in rows], row=0)
        self.rows = {r['id']: r for r in rows}

    async def callback(self, i):
        parent = self.view
        parent.selected = self.rows[self.values[0]]
        await respond(i, parent.selected['body'] + '\n\nChoose Reply or Request a second look below.')


class TeamInboxView(discord.ui.View):
    def __init__(self, user_id, rows, page=0):
        super().__init__(timeout=300)
        self.user_id, self.page = str(user_id), page
        self.selected = rows[0] if rows else None
        if rows:
            self.add_item(MessagePicker(rows))

    async def interaction_check(self, i):
        return bool(i.guild) and str(i.user.id) == self.user_id

    @discord.ui.button(label='Reply', style=discord.ButtonStyle.primary, row=1)
    async def reply(self, i, button):
        if not self.selected:
            return await respond(i, 'Your inbox is empty.')
        await i.response.send_modal(MessageModal(self.user_id, self.selected, 'reply'))

    @discord.ui.button(label='Request a second look', style=discord.ButtonStyle.secondary, row=1)
    async def second_look(self, i, button):
        if not self.selected:
            return await respond(i, 'Select an evaluation message first.')
        await i.response.send_modal(MessageModal(self.user_id, self.selected, 'second_look'))

    @discord.ui.button(label='Older messages', style=discord.ButtonStyle.secondary, row=1)
    async def older(self, i, button):
        await cog(i).open_inbox(i, page=self.page + 1)

    @discord.ui.button(label='Newest messages', style=discord.ButtonStyle.secondary, row=1)
    async def newest(self, i, button):
        await cog(i).open_inbox(i)

    @discord.ui.button(label='Keep feedback in the panel only', style=discord.ButtonStyle.secondary, row=2)
    async def no_dms(self, i, button):
        await i.client.db.team_dm_preference(str(i.guild_id), self.user_id, False)
        await respond(i, 'DM notifications disabled. Your private Team messages remain available in the panel.')


class ReviewSupportCog(BotHelpers, commands.Cog, name='ReviewSupport'):
    support = app_commands.Group(name='support', description='Private weekly review support and volunteer moderation')

    def __init__(self, bot):
        self.bot = bot
        self._roster_locks = {}

    async def cog_load(self):
        self.support_scheduler.start()
        self.support_worker.start()
        self.support_message_worker.start()

    async def cog_unload(self):
        loops = (self.support_scheduler, self.support_worker, self.support_message_worker)
        for loop in loops:
            loop.cancel()
        await asyncio.gather(*(loop.get_task() for loop in loops if loop.get_task()), return_exceptions=True)

    async def require_moderator(self, i):
        if not i.guild:
            return False
        cfg = await self.db.support_settings(str(i.guild_id))
        # Fetch on sensitive actions, rather than trusting a stale message's role snapshot.
        try:
            member = await asyncio.wait_for(i.guild.fetch_member(i.user.id), timeout=1)
        except (discord.HTTPException, asyncio.TimeoutError):
            member = None
        valid = member and not member.bot and cfg.get('moderator_role_id') and any(str(r.id) == cfg['moderator_role_id'] for r in member.roles)
        if not valid or not cfg['enabled']:
            await respond(i, 'This section requires the selected moderator role and enabled review support.')
            return False
        return True

    async def refresh_roster(self, guild):
        gid = str(guild.id)
        lock = self._roster_locks.setdefault(gid, asyncio.Lock())
        if lock.locked():
            raise ValueError('A role inventory is already running. Try again after it finishes.')
        async with lock:
            cfg = await self.db.support_settings(gid)
            roles = {kind: cfg.get(kind + '_role_id') for kind in ('reviewer', 'member', 'moderator')}
            for kind in ('reviewer', 'moderator'):
                if not roles[kind] or guild.get_role(int(roles[kind])) is None:
                    raise ValueError(f'Selected {kind} role is missing. Update support setup.')
            if roles['member'] and guild.get_role(int(roles['member'])) is None:
                raise ValueError('Selected member role is missing. Update support setup.')
            people = []
            async with asyncio.timeout(180):
                async for member in guild.fetch_members(limit=None):
                    if member.bot:
                        continue
                    held = {str(r.id) for r in member.roles}
                    for kind, rid in roles.items():
                        if rid and rid in held:
                            people.append({'id': str(member.id), 'kind': kind, 'username': member.name,
                                           'display_name': member.display_name, 'joined_at': utc_iso(member.joined_at) if member.joined_at else None})
                    if len(people) > 15000:
                        raise ValueError('Selected-role inventory exceeds the processing budget.')
            await self.db.save_support_roster(gid, people)

    @tasks.loop(minutes=15)
    async def support_scheduler(self):
        for guild in self.bot.guilds:
            cfg = await self.db.support_settings(str(guild.id))
            if not cfg['enabled']:
                continue
            try:
                if not cfg.get('roster_at') or parse_time(cfg['roster_at']) < datetime.now(timezone.utc) - timedelta(hours=24):
                    await self.refresh_roster(guild)
                await self.db.start_support_cycle(str(guild.id))
                await self.db.queue_due_support_report(str(guild.id))
            except Exception as exc:
                log.warning('Support scheduler deferred for guild %s: %s', guild.id, type(exc).__name__)
                await self.db.record_operation('review_support', 'deferred', guild_id=str(guild.id), detail=type(exc).__name__)

    @support_scheduler.before_loop
    async def before_scheduler(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=10)
    async def support_worker(self):
        job = await self.db.next_support_report()
        if not job:
            return
        try:
            guild = self.bot.get_guild(int(job['guild_id']))
            if guild is None:
                raise ValueError('The report server is not available to this bot.')
            settings = await self.db.support_settings(job['guild_id'])
            if not settings.get('roster_at') or parse_time(settings['roster_at']) < datetime.now(timezone.utc)-timedelta(minutes=1):
                await self.refresh_roster(guild)
            data = await asyncio.wait_for(snapshot(self.db.db_path, job['guild_id'], job['starts_at'], job['ends_at']), timeout=45)
            payload = await asyncio.to_thread(analyze, data)
            from review_support_xlsx import export_support_report
            base = Path(os.getenv('REPORT_DIR', 'runtime/reports')).resolve() / 'review-support'
            base.mkdir(parents=True, exist_ok=True, mode=0o700)
            path = base / (job['id'] + '.xlsx')
            await asyncio.to_thread(export_support_report, payload, path)
            path.chmod(0o600)
            csv_path = path.with_suffix('.csv')
            await asyncio.to_thread(csv_path.write_bytes, participation_csv(payload))
            csv_path.chmod(0o600)
            await self.db.finish_support_report(job['id'], payload=payload, path=path)
        except asyncio.CancelledError:
            db = await self.db._get_conn()
            async with self.db._lock:
                await db.execute("UPDATE support_report_jobs SET state=CASE WHEN attempts>=3 THEN 'failed' ELSE 'queued' END WHERE id=?", (job['id'],))
                await db.commit()
            raise
        except Exception as exc:
            log.exception('Review analytics job failed: %s', job['id'])
            await self.db.finish_support_report(job['id'], error=f'{type(exc).__name__}: {str(exc)[:250]}')

    @support_worker.before_loop
    async def before_worker(self):
        await self.bot.wait_until_ready()

    @tasks.loop(seconds=15)
    async def support_message_worker(self):
        for item in await self.db.pending_support_dms():
            if not item['dm_enabled'] or not (await self.db.support_settings(item['guild_id']))['enabled']:
                await self.db.support_dm_result(item['id'], state='inbox_only')
                continue
            guild = self.bot.get_guild(int(item['guild_id']))
            if not guild:
                await self.db.support_dm_result(item['id'], state='inbox_only')
                continue
            await self.db.support_dm_result(item['id'], state='sending', attempts=item['dm_attempts'])
            try:
                async with asyncio.timeout(20):
                    recipient = await guild.fetch_member(int(item['recipient_id']))
                    if recipient.bot:
                        raise ValueError('Bot recipient')
                    await recipient.send(f"A private team message in {guild.name[:80]}\nFrom Discord ID: {item['sender_id']}\n\n{item['body']}\n\nOpen Team messages in the server panel to reply or switch off DM notifications.", allowed_mentions=discord.AllowedMentions.none())
                await self.db.support_dm_result(item['id'], state='sent', attempts=item['dm_attempts'] + 1)
            except asyncio.CancelledError:
                await self.db.support_dm_result(item['id'], state='pending', attempts=item['dm_attempts'])
                raise
            except (discord.Forbidden, discord.NotFound, ValueError):
                await self.db.support_dm_result(item['id'], state='inbox_only', attempts=item['dm_attempts'] + 1)
            except (discord.HTTPException, asyncio.TimeoutError, OSError):
                attempts = item['dm_attempts'] + 1
                await self.db.support_dm_result(item['id'], state='inbox_only' if attempts >= 3 else 'pending', attempts=attempts, delay=60 * 2 ** attempts)

    @support_message_worker.before_loop
    async def before_messages(self):
        await self.bot.wait_until_ready()

    async def open_moderator(self, i, page=0):
        work = await self.db.support_work(str(i.guild_id), str(i.user.id))
        counts = Counter(w['state'] for w in work)
        await respond(i, f"Your weekly support: {counts['pending']} pending, {counts['completed']} completed. Choose a person below. Availability and skips have no penalty. Use `/support availability` for your own reviewer and member capacities.", view=ModeratorPanelView(i.user.id, work, page))

    async def open_task(self, i, assignment_id):
        if not await self.require_moderator(i):
            return
        item = await self.db.support_assignment(str(i.guild_id), assignment_id)
        if not item or item['moderator_id'] != str(i.user.id) or item['state'] != 'pending':
            return await respond(i, 'This task is no longer assigned to you.')
        embed = discord.Embed(title='Private support evidence', color=mz('secondary'))
        embed.description = f"Member ID: {item['user_id']}\nScope: {item['kind']}\nPrevious week\nRead the saved samples before rating. Judge specific feedback and context, not message volume."
        samples = json.loads(item['samples_json'])
        for sample in samples:
            text = (sample.get('text') or '')[:550]
            embed.add_field(name=sample['id'], value=f"{sample['at']}\n{sample['url']}\nRecorded content score: {sample.get('score') or 'not scored'}\n{text}"[:1000], inline=False)
        if not samples:
            embed.add_field(name='No recorded samples', value='Leave the score blank. Record a friendly check-in or skip. Missing evidence is not a score of zero.', inline=False)
        await respond(i, '', embed=embed, view=TaskActions(item, i.user.id))

    async def open_inbox(self, i, page=0):
        rows = await self.db.team_inbox(str(i.guild_id), str(i.user.id), offset=page * 5)
        embed = discord.Embed(title='Your private team messages', description='Reply when useful. Feedback has no automatic effect on MC or roles.', color=mz('secondary'))
        for row in rows:
            score = f"Private {row['kind']} score: {row['score']}/10" if row['score'] is not None else 'No score; no recorded samples'
            if row.get('original_score') is not None and row['original_score'] != row['score']:
                score += f". Independently revised from {row['original_score']}/10."
            if row['limited_evidence'] and row['score'] is not None:
                score += f". Limited sample: {row['sample_count']} checked."
            embed.add_field(name=f"{row['created_at'][:10]} from {row['sender_id']}", value=f"{score}\n{row['body'][:850]}", inline=False)
        if not rows:
            embed.description = 'No messages on this page. Your feedback stays here even when Discord DMs are closed.'
        await respond(i, '', embed=embed, view=TeamInboxView(i.user.id, rows, page))
        await self.db.team_read(str(i.guild_id), str(i.user.id), [r['id'] for r in rows])

    async def send_status(self, i):
        rows = await self.db.support_work(str(i.guild_id))
        counts = Counter(r['state'] for r in rows)
        open_looks = await self.db.second_looks(str(i.guild_id))
        await respond(i, f"Weekly allocation: {len(rows)} people/scopes. Pending {counts['pending']}, completed {counts['completed']}, queued {counts['queued']}, withdrawn {counts['withdrawn']}. Open second looks: {len(open_looks)}. Only opted-in moderators receive work; queues remain when capacity is insufficient.", view=SupportAdminView())

    async def queue_report(self, i, days):
        cfg = await self.db.support_settings(str(i.guild_id))
        if not cfg.get('reviewer_role_id'):
            return await respond(i, 'Configure review support roles first.', view=SupportAdminView())
        try:
            await self.refresh_roster(i.guild)
        except (ValueError, discord.HTTPException, asyncio.TimeoutError) as exc:
            return await respond(i, f'Complete inventory failed: {type(exc).__name__}. No report with a partial role list was queued.')
        end = datetime.now(timezone.utc).replace(microsecond=0)
        try:
            job = await self.db.queue_support_report(str(i.guild_id), end - timedelta(days=days), end, str(i.user.id))
        except ValueError as exc:
            return await respond(i, str(exc))
        await respond(i, f"Report {job['id']} queued. Use `/review_analytics_status job_id:{job['id']}` for Excel and CSV. Recommendations do not change setup.")

    async def download_report(self, i, ident=None):
        job = await self.db.get_support_report(str(i.guild_id), ident)
        if not job:
            return await respond(i, 'No saved report. Use `/review_analytics` first.')
        if job['state'] != 'completed':
            return await respond(i, f"Report {job['id']}: {job['state']}. {job.get('error') or ''}")
        base = Path(os.getenv('REPORT_DIR', 'runtime/reports')).resolve() / 'review-support'
        path = Path(job['output_path']).resolve()
        csv_path = path.with_suffix('.csv')
        if not path.is_relative_to(base) or not path.is_file() or not csv_path.is_file():
            return await respond(i, 'The saved report files are unavailable on this server.')
        if max(path.stat().st_size, csv_path.stat().st_size) > 8 * 1024 * 1024:
            return await respond(i, 'Export exceeds the attachment allowance. Retrieve this report from the private server reports folder.')
        await respond(i, f"Report {job['id']}: {job['starts_at']} to {job['ends_at']} (end exclusive, UTC).", files=[discord.File(path, filename='Melee-review-analysis.xlsx'), discord.File(csv_path, filename='Melee-participation.csv')])

    async def send_estimate(self, i, result, recommendations=()):
        lines = [f"Approximate regular MC: {result['estimated_regular_mc']:.2f}", f"Approximate golden MC: {result['showcase_golden_mc']:.2f}",
                 f"Score rewards: {result['score_regular_mc']:.2f}; review goals: {result['review_goal_mc']:.2f}; comments: {result['comment_bonus_mc']:.2f}; submit goals: {result['submission_goal_mc']:.2f}."]
        lines.extend(f"{r['setting']}: {r['current']} -> {r['suggested']}. {r['reason']}" for r in recommendations)
        await respond(i, '\n\n'.join(lines)[:1800] + '\n\nCurrent-rule estimate, not a missing-payment audit. No setup, MC balance or role was changed. Editable calculations are in the Excel Calculator.')

    @support.command(name='setup', description='Configure roles and automatic private review support (admin)')
    async def support_setup(self, i: discord.Interaction, moderator_role: discord.Role, reviewer_role: discord.Role = None,
                            member_role: discord.Role = None, weekly_cap: app_commands.Range[int, 1, 50] = 10,
                            samples: app_commands.Range[int, 1, 5] = 3, enabled: bool = True):
        if not await authorized(i):
            return
        await i.response.defer(ephemeral=True)
        general = await self.db.get_guild_config(str(i.guild_id)) or {}
        rid = str(reviewer_role.id) if reviewer_role else general.get('pro_role_id')
        if moderator_role.is_default() or (reviewer_role and reviewer_role.is_default()) or (member_role and member_role.is_default()):
            return await respond(i, 'Select specific roles, not @everyone.')
        try:
            if not await request_config_change(i, scope='support', enabled=enabled, reviewer_role_id=rid, moderator_role_id=str(moderator_role.id),
                                            member_role_id=str(member_role.id) if member_role else None, weekly_cap=weekly_cap, sample_size=samples):return
            if enabled:
                await self.refresh_roster(i.guild)
                await self.db.start_support_cycle(str(i.guild_id))
        except (ValueError, discord.HTTPException, asyncio.TimeoutError) as exc:
            return await respond(i, f'Setup needs attention: {str(exc)[:180]}. Existing MC and main review settings are unchanged.')
        await respond(i, 'Review support configured. Moderators opt in through `/support panel`. Reports are prepared every 14 days and kept private until requested.', view=SupportAdminView())

    @support.command(name='panel', description='Open your volunteer moderator workload')
    async def support_panel(self, i: discord.Interaction):
        if await self.require_moderator(i):
            await self.open_moderator(i)

    @support.command(name='availability', description='Choose your own weekly capacities or pause without penalty')
    async def support_availability(self, i: discord.Interaction, available: bool = True,
                                   reviewers: app_commands.Range[int, 0, 50] = 10, members: app_commands.Range[int, 0, 50] = 0):
        if not await self.require_moderator(i):
            return
        await i.response.defer(ephemeral=True)
        try:
            await self.db.support_volunteer(str(i.guild_id), str(i.user.id), available=available, reviewer_capacity=reviewers, member_capacity=members)
            await self.refresh_roster(i.guild)
            await self.db.start_support_cycle(str(i.guild_id))
        except (ValueError, discord.HTTPException, asyncio.TimeoutError) as exc:
            return await respond(i, f'Availability saved only if valid. Allocation deferred: {type(exc).__name__}.')
        await self.open_moderator(i)

    @support.command(name='status', description='Weekly workload and second-look overview (admin)')
    async def support_status(self, i: discord.Interaction):
        if await authorized(i):
            await self.send_status(i)

    @support.command(name='resolve', description='Record and privately deliver a second-look resolution (admin)')
    async def support_resolve(self, i: discord.Interaction, request_id: str, resolution: str,
                              revised_score: app_commands.Range[int, 1, 10] = None):
        if not await authorized(i):
            return
        try:
            await self.db.resolve_second_look(str(i.guild_id), request_id, str(i.user.id), resolution, revised_score)
        except ValueError as exc:
            return await respond(i, str(exc))
        await respond(i, 'Resolution saved in the member\'s private inbox. Any corrected score is recorded separately; the original evidence and score remain in the audit history.')

    @app_commands.command(name='review_analytics', description='Prepare participation, moderator and setup reports as Excel and CSV (admin)')
    async def review_analytics(self, i: discord.Interaction, days: app_commands.Range[int, 1, 90] = 14):
        if await authorized(i):
            await i.response.defer(ephemeral=True)
            await self.queue_report(i, days)

    @app_commands.command(name='review_analytics_status', description='Download a private saved Excel and CSV participation report (admin)')
    async def review_analytics_status(self, i: discord.Interaction, job_id: str = None, retry: bool = False):
        if await authorized(i):
            await i.response.defer(ephemeral=True)
            if retry:
                if not job_id:
                    return await respond(i, 'Choose the failed report job_id before retrying.')
                try:
                    await self.db.retry_support_report(str(i.guild_id), job_id)
                except ValueError as exc:
                    return await respond(i, str(exc))
            await self.download_report(i, job_id)

    @app_commands.command(name='review_calculator', description='Preview workload and MC assumptions without applying changes (admin)')
    async def review_calculator(self, i: discord.Interaction, days: app_commands.Range[int, 1, 90] = 14,
                                max_reviews: app_commands.Range[int, 1, 20] = None, max_submits: app_commands.Range[int, 1, 20] = None,
                                min_reviews: app_commands.Range[int, 1, 10] = None, review_reward: app_commands.Range[float, 0, 1000] = None):
        if not await authorized(i):
            return
        await i.response.defer(ephemeral=True)
        try:
            await self.refresh_roster(i.guild)
        except (ValueError, discord.HTTPException, asyncio.TimeoutError) as exc:
            return await respond(i, f'Calculator needs a complete selected-role inventory: {type(exc).__name__}. Check support setup.')
        end = datetime.now(timezone.utc)
        overrides = {k: v for k, v in [('max_reviews_per_week', max_reviews), ('max_submits_per_week', max_submits), ('min_reviews', min_reviews), ('mc_review_reward', review_reward)] if v is not None}
        try:
            data = await asyncio.wait_for(snapshot(self.db.db_path, str(i.guild_id), end - timedelta(days=days), end), timeout=45)
            payload = await asyncio.to_thread(analyze, data, overrides)
        except (ValueError, asyncio.TimeoutError) as exc:
            return await respond(i, f'Calculation unavailable: {str(exc)[:250] or "snapshot timed out"}. No settings were changed.')
        await self.send_estimate(i, payload['estimate'], payload['recommendations'])

    @app_commands.command(name='team_messages', description='Read private team feedback, reply or change DM notifications')
    async def team_messages(self, i: discord.Interaction, dm_notifications: bool = None):
        if dm_notifications is not None:
            await self.db.team_dm_preference(str(i.guild_id), str(i.user.id), dm_notifications)
        await self.open_inbox(i)


async def setup(bot):
    await bot.add_cog(ReviewSupportCog(bot))
