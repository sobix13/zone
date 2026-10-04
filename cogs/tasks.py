import discord
from discord.ext import commands, tasks
from helpers import BotHelpers
from config import Config, get_current_week_id, get_next_saturday_midnight, mz
from datetime import datetime, timedelta
import pytz
import random
import asyncio
import logging

log = logging.getLogger('MeleeZone.Tasks')
TEHRAN = pytz.timezone('Asia/Tehran')


class TasksCog(BotHelpers, commands.Cog, name="Tasks"):
    def __init__(self, bot):
        self.bot = bot
        self.weekly_cycle.start()
        self.daily_check.start()

    def cog_unload(self):
        self.weekly_cycle.cancel()
        self.daily_check.cancel()

    @tasks.loop(hours=1)
    async def weekly_cycle(self):
        await self.bot.wait_until_ready()
        now=datetime.now(TEHRAN)
        if now.weekday() < 5:
            return
        for guild in self.bot.guilds:
            config=await self.db.get_guild_config(str(guild.id)) or {}
            week_id=get_current_week_id()
            if config.get('last_weekly_cycle') != week_id:
                await self.process_guild_weekly(guild, reset_capacity=True)
                await self.db.update_guild_config(str(guild.id),last_weekly_cycle=week_id)

    @weekly_cycle.before_loop
    async def before_weekly(self):
        await self.bot.wait_until_ready()
        await asyncio.sleep(5)

    async def process_guild_weekly(self, guild: discord.Guild, reset_capacity=False):
        guild_id = str(guild.id)
        config = await self.db.get_guild_config(guild_id)
        if not config or not config.get('is_configured'):
            return
        try:
            max_submits = Config.get_max_submits(config)
            if reset_capacity:
                await self.db.reset_weekly_submits(guild_id, max_submits)
            if not config.get('pro_role_id'):
                return
            pro_role = guild.get_role(int(config['pro_role_id']))
            if not pro_role:
                return
            pro_users = [m for m in pro_role.members if not m.bot]
            if len(pro_users) < 3:
                return
            week_id = get_current_week_id()
            min_reviews = Config.get_min_reviews(config)
            review_days = Config.get_review_window(config)
            max_per_user = Config.get_max_reviews(config)
            pending_posts = await self.db.get_all_open_posts_for_assignment(guild_id)
            if not pending_posts:
                return
            due_date = datetime.now(TEHRAN) + timedelta(days=review_days)
            random.shuffle(pending_posts)
            reviewer_load = {}
            for pu in pro_users:
                current = await self.db.get_assignments_by_reviewer(str(pu.id), week_id)
                reviewer_load[str(pu.id)] = len([x for x in current if x['status'] not in ('reassigned','removed')])
            assigned_count = 0
            for post in pending_posts:
                needed=max(0,int(post.get('required_reviews') or min_reviews)-int(post.get('review_count') or 0)-int(post.get('active_assignment_count') or 0))
                if needed == 0: continue
                used_reviewers=await self.db.get_reviewer_ids_for_post(post['post_id'])
                eligible = [p for p in pro_users if str(p.id) != post['author_id'] and str(p.id) not in used_reviewers and reviewer_load.get(str(p.id), 0) < max_per_user]
                if not eligible:
                    continue
                eligible.sort(key=lambda p: reviewer_load.get(str(p.id), 0))
                selected = eligible[:needed]
                created=await asyncio.gather(*[self.db.create_assignment(post['post_id'], str(pu.id), week_id, due_date) for pu in selected])
                for pu,aid in zip(selected,created):
                    if not aid:
                        continue
                    reviewer_load[str(pu.id)] = reviewer_load.get(str(pu.id), 0) + 1
                assigned_count += int(any(created))
            if config.get('log_channel_id'):
                ch = guild.get_channel(int(config['log_channel_id']))
                if ch:
                    await ch.send(embed=discord.Embed(title="🔄 Weekly Cycle Complete", description=f"Week {week_id}: {assigned_count} posts assigned.", color=mz('secondary')))
        except Exception as e:
            log.error(f"Weekly cycle error {guild.name}: {e}", exc_info=True)

    @tasks.loop(minutes=15)
    async def daily_check(self):
        await self.bot.wait_until_ready()
        for guild in self.bot.guilds:
            config = await self.db.get_guild_config(str(guild.id))
            if not config or not config.get('is_configured'):
                continue
            await self.send_reminders(guild, config)
            await self.process_rescue_reviews(guild, config)
            await self.process_rewards(guild, config)
            reviewer=self.bot.get_cog('Review')
            if reviewer:
                # Retry unfinished finalization after a process interruption, in bounded batches.
                conn=await self.db._get_conn()
                async with conn.execute('''SELECT post_id FROM posts WHERE guild_id=? AND status IN ('pending','assigned')
                    AND (SELECT COUNT(*) FROM reviews WHERE reviews.post_id=posts.post_id)>=required_reviews LIMIT 10''',(str(guild.id),)) as cur:
                    ready=[r[0] for r in await cur.fetchall()]
                for post_id in ready:
                    await reviewer._check_post_completion(post_id,config,guild)

    async def process_rescue_reviews(self, guild, config):
        now=datetime.now(TEHRAN); warning_before=now-timedelta(days=int(config.get('primary_review_days',5)))
        for a in await self.db.get_assignments_for_rescue(str(guild.id),warning_before):
            if await self.db.mark_assignment_warning(a['assignment_id'],now):
                member=guild.get_member(int(a['reviewer_id']))
                if member:
                    try: await member.send(f"⚠️ You have {config.get('warning_grace_hours',12)} hours before review `{a['assignment_id'][:8]}` is reassigned.\n{a['tweet_link']}")
                    except discord.Forbidden: pass
        cutoff=now-timedelta(hours=int(config.get('warning_grace_hours',12)))
        ready=await self.db.get_ready_for_more_users(str(guild.id)); limit=int(config.get('rescue_review_limit',3))
        for old in await self.db.get_expired_warnings(str(guild.id),cutoff):
            selected=None;new_id=None
            for candidate in ready:
                uid=candidate['user_id']; items=await self.db.get_assignments_by_reviewer(uid,get_current_week_id())
                if uid in (old['reviewer_id'],old['author_id']) or any(x['post_id']==old['post_id'] for x in items): continue
                if sum(1 for x in items if x.get('assignment_type')=='rescue' and x['status'] not in ('reassigned','removed'))>=limit: continue
                new_id=await self.db.rescue_assignment_atomic(str(guild.id),old['assignment_id'],uid,get_current_week_id(),now+timedelta(hours=24))
                if new_id:
                    selected=candidate;break
            if not selected or not new_id: continue
            member=guild.get_member(int(selected['user_id']))
            if member:
                try: await member.send(f"🛟 Rescue review `{new_id[:8]}` assigned.\n{old['tweet_link']}")
                except discord.Forbidden: pass

    async def send_reminders(self, guild: discord.Guild, config: dict):
        if not config.get('log_channel_id'):
            return
        ch = guild.get_channel(int(config['log_channel_id']))
        if not ch:
            return
        hours = Config.get_reminder_hours(config)
        overdue = await self.db.get_overdue_assignments(hours)
        reminder_text = Config.reminder_msg(config)
        for a in overdue:
            post = await self.db.get_post(a['post_id'])
            if not post or post['guild_id'] != str(guild.id):
                continue
            try:
                reviewer = guild.get_member(int(a['reviewer_id']))
                if not reviewer:
                    continue
                embed = discord.Embed(title="⏰ Review Reminder", description=f"{reminder_text}\n\nAssignment ID: `{a['assignment_id'][:8]}`\n[View Post]({a['tweet_link']})", color=mz('primary'))
                await ch.send(content=reviewer.mention, embed=embed)
                await self.db.mark_reminder_sent(a['assignment_id'])
            except Exception as e:
                log.warning(f"Reminder failed: {e}")

    async def process_rewards(self, guild: discord.Guild, config: dict):
        if not config.get('pro_role_id'):
            return
        pro_role = guild.get_role(int(config['pro_role_id']))
        if not pro_role:
            return
        week_id = get_current_week_id()
        max_r = Config.get_max_reviews(config)
        reward = Config.get_review_reward(config)
        mc = Config.mc_name(config)
        for member in pro_role.members:
            if member.bot:
                continue
            completed = await self.db.get_assignments_by_reviewer(str(member.id), week_id, 'completed')
            if len(completed) >= max_r:
                reward_key = f"Completed {max_r} reviews - week {week_id}"
                if not await self.db.reward_already_given(str(member.id), str(guild.id), reward_key):
                    await self.db.add_mc(str(member.id), str(guild.id), reward, 'regular', reward_key, reward_key=f"review_goal:{guild.id}:{member.id}:{week_id}")
                    if config.get('log_channel_id'):
                        ch = guild.get_channel(int(config['log_channel_id']))
                        if ch:
                            await ch.send(f"{member.mention} earned **{reward} {mc}** for completing {max_r} reviews! 🎉")


async def setup(bot):
    await bot.add_cog(TasksCog(bot))
