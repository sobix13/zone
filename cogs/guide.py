"""Role-aware user onboarding, progress and practical answers."""
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config,get_current_week_id
from role_utils import resolve_member


def user_guide(config,is_reviewer,section=0):
    mc=Config.mc_name(config)
    pages=[
        ('Start here', 'Open the Melee Zone panel. Register your X handle in Dashboard. Submit your own X posts in Submission. Open Reviews to see assigned posts.' if is_reviewer else 'Open the Melee Zone panel. Register your X handle in Dashboard, then use Submission to submit your own X posts.'),
        ('Submit a post',f"Paste a direct X status link. Links using /i/status/ are supported. Each post is accepted once per member across all weeks. Weekly capacity: {Config.get_max_submits(config)}. Using all slots earns {Config.get_submit_completion_reward(config):g} {mc}, once per week."),
        ('Review a post',f"Open Reviews, then Assignments. Open the post and check its author and content. Submit a score from 1 to 10 and at least {config.get('min_feedback_length',30)} feedback characters. Explain your score. Use /review_skip if you cannot access or fairly review the post. Only assigned reviewers submit reviews."),
        ('Deadlines and rescue',f"The main review period is {config.get('primary_review_days',5)} days. A warning lasts {config.get('warning_grace_hours',12)} hours. Reassigned work is no longer yours. Finish your main reviews before selecting Ready for More. Rescue capacity: {config.get('rescue_review_limit',3)} per week. Your assignment panel shows the actual deadline."),
        ('MC and community tasks',f"Score below 4: 0 {mc}. Score from 4 to below 6: {config.get('mc_score_low',1)}. From 6 to below 8: {config.get('mc_score_medium',3)}. From 8 to 10: {config.get('mc_score_high',5)}. Showcase and review rewards are separate. Post community task entries inside the task thread. Its cooldown applies to members. Admin reactions award MC after processing."),
        ('Common questions','Missing assignment: open Reviews and refresh. Closed or inaccessible post: use /review_skip and select a reason. MC delayed: check your Dashboard, then ask a moderator with the message link. An admin removes a reaction: the recorded MC stays. Two admins react: each admin gives a separate award. Missing X handle: register it in Dashboard. An /i/status/ link does not identify the author, so the reviewer checks ownership.'),
    ]
    title,text=pages[section]
    e=discord.Embed(title=title,description=text,color=0x8C303A)
    e.set_footer(text=f'Melee Zone guide | {section+1}/{len(pages)}')
    return e


class UserGuideView(discord.ui.View):
    def __init__(self,user_id,config,is_reviewer,section=0):
        super().__init__(timeout=600)
        self.user_id=user_id;self.config=config;self.is_reviewer=is_reviewer;self.section=section

    async def interaction_check(self,interaction):
        if interaction.user.id==self.user_id:
            return True
        await interaction.response.send_message('Open your own guide with /guide.',ephemeral=True)
        return False

    async def show(self,interaction):
        await interaction.client.db.set_onboarding(str(interaction.guild_id),str(interaction.user.id),self.section)
        await interaction.response.edit_message(embed=user_guide(self.config,self.is_reviewer,self.section),view=self)

    @discord.ui.button(label='Previous',style=discord.ButtonStyle.secondary)
    async def previous(self,interaction,button):
        self.section=max(0,self.section-1);await self.show(interaction)

    @discord.ui.button(label='Next',style=discord.ButtonStyle.primary)
    async def next(self,interaction,button):
        self.section=min(5,self.section+1);await self.show(interaction)

    @discord.ui.button(label='My next steps',style=discord.ButtonStyle.success)
    async def checklist(self,interaction,button):
        await interaction.response.defer(ephemeral=True)
        db=interaction.client.db
        guild_id=str(interaction.guild_id);uid=str(interaction.user.id)
        user=await db.get_user(uid,guild_id) or {}
        assignments=await db.get_assignments_by_reviewer(uid,get_current_week_id()) if self.is_reviewer else []
        pending=[a for a in assignments if a['status'] in ('pending','warning')]
        text='X handle: '+('@'+user['twitter_username'] if user.get('twitter_username') else 'register in Dashboard')
        text+=f"\nWeekly submission slots remaining: {user.get('weekly_submits',Config.get_max_submits(self.config))}"
        if self.is_reviewer:
            text+=f'\nPending reviews: {len(pending)}. Open Reviews to finish them.'
            if pending:
                text+='\nEarliest deadline: '+min(a['due_date'] for a in pending)
            else:
                text+='\nNo pending reviews in this cycle. Select Ready for More when you want rescue reviews.'
        await interaction.followup.send(text,ephemeral=True)


class GuideCog(BotHelpers,commands.Cog,name='Guide'):
    def __init__(self,bot):
        self.bot=bot

    async def open_guide(self,interaction,resume=False):
        config=await self.db.get_guild_config(str(interaction.guild_id)) or {}
        is_reviewer=self.is_pro(interaction.user,config)
        section=await self.db.get_onboarding(str(interaction.guild_id),str(interaction.user.id)) if resume else 0
        section=max(0,min(5,section))
        await interaction.response.send_message(embed=user_guide(config,is_reviewer,section),
            view=UserGuideView(interaction.user.id,config,is_reviewer,section),ephemeral=True)

    @app_commands.command(name='guide',description='Open the user guide and answers')
    async def guide(self,interaction:discord.Interaction):
        await self.open_guide(interaction)

    @app_commands.command(name='quick_start',description='Open the first steps for your role')
    async def quick_start(self,interaction:discord.Interaction):
        await self.open_guide(interaction)

    @app_commands.command(name='onboard',description='Continue your Melee Zone introduction')
    async def onboard(self,interaction:discord.Interaction):
        await self.open_guide(interaction,resume=True)

    @app_commands.command(name='admin_guide',description='Open the moderator reference')
    async def admin_guide(self,interaction:discord.Interaction):
        config=await self.require_admin(interaction)
        if config is None:
            return
        from cogs.control_center import GuideView
        await interaction.response.send_message(embed=discord.Embed(title='Moderator reference',description='Choose a feature. The full manual is included in the release docs folder.',color=0x8C303A),view=GuideView(),ephemeral=True)

    @app_commands.command(name='review_skip',description='Return an assigned post you cannot review')
    @app_commands.choices(reason=[app_commands.Choice(name=n,value=n) for n in ('Cannot access post','Conflict of interest','Language issue','Other')])
    async def review_skip(self,interaction:discord.Interaction,assignment_id:str,reason:str):
        await interaction.response.defer(ephemeral=True)
        config=await self.db.get_guild_config(str(interaction.guild_id)) or {}
        if not self.is_pro(interaction.user,config):
            return await interaction.followup.send('Reviewer access required.',ephemeral=True)
        if len(assignment_id)<6:
            return await interaction.followup.send('Copy the assignment ID from Reviews.',ephemeral=True)
        assignment=await self.db.get_assignment_by_partial_id(assignment_id,str(interaction.user.id))
        if not assignment:
            return await interaction.followup.send('Active assignment not found.',ephemeral=True)
        changed=await self.db.decline_review(str(interaction.guild_id),str(interaction.user.id),assignment['assignment_id'],reason)
        if changed:
            cog=self.bot.get_cog('Assigner')
            if cog:
                await cog.assign_post(assignment['post_id'],interaction.guild)
        await interaction.followup.send('Assignment returned for another reviewer. No review reward was added.' if changed else 'This assignment is no longer active.',ephemeral=True)

    @commands.Cog.listener()
    async def on_member_update(self,before,after):
        config=await self.db.get_guild_config(str(after.guild.id)) or {}
        if self.is_pro(after,config) and not self.is_pro(before,config):
            if await self.db.claim_onboarding_notice(str(after.guild.id),str(after.id)):
                try:
                    await after.send('You received the Meleeionaires reviewer role. In the server, run /onboard for your steps, assignments, deadlines and rewards. Use /guide at any time.')
                except discord.HTTPException:
                    await self.db.record_operation('onboarding','dm_unavailable',guild_id=str(after.guild.id),actor_id=str(after.id),detail='The member still has /onboard and the panel Guide button.')


async def setup(bot):
    await bot.add_cog(GuideCog(bot))
