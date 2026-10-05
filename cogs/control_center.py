"""Unified admin panel, setup center and canonical admin guide."""
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, get_current_week_id, mz
from ui_security import AdminView,AdminModal
from config_service import request_config_change, reply


def role_ref(guild, role_id):
    role = guild.get_role(int(role_id)) if role_id else None
    return role.mention if role else "Not set"


def channel_ref(guild, channel_id):
    channel = guild.get_channel(int(channel_id)) if channel_id else None
    return channel.mention if channel else "Not set"


def config_embed(guild, c):
    mc = Config.mc_name(c)
    e = discord.Embed(title="⚙️ Full Configuration", color=mz('secondary'))
    e.add_field(name="Roles & Access", value=(
        f"Reviewer: {role_ref(guild,c.get('pro_role_id'))}\nBasic: {role_ref(guild,c.get('basic_role_id'))}\n"
        f"Legacy admin: {role_ref(guild,c.get('admin_role_id'))}\nModerator panel: {role_ref(guild,c.get('moderator_role_id'))}\n"
        f"Primary admin role: {role_ref(guild,c.get('super_admin_role_id'))}\nQuiz: {role_ref(guild,c.get('quiz_pass_role_id'))}\n"
        f"Raffle: {role_ref(guild,c.get('raffle_role_id'))}"), inline=False)
    e.add_field(name="Channels", value=(
        f"Panel: {channel_ref(guild,c.get('bot_content_channel_id'))}\nShowcase: {channel_ref(guild,c.get('showcase_channel_id'))}\n"
        f"Leaderboard: {channel_ref(guild,c.get('leaderboard_channel_id'))}\nReview fallback: {channel_ref(guild,c.get('review_channel_id'))}\n"
        f"Community tasks: {channel_ref(guild,c.get('assignment_channel_id'))}\nSystem log: {channel_ref(guild,c.get('log_channel_id'))}\n"
        f"Credit log: {channel_ref(guild,c.get('credit_log_channel_id'))}"), inline=False)
    e.add_field(name="Content & Reviews", value=(
        f"Submissions: **{c.get('max_submits_per_week',5)}/week** | Reviews: **{c.get('max_reviews_per_week',7)}/week**\n"
        f"Reviews/post: **{c.get('min_reviews',5)}** | Main period: **{c.get('primary_review_days',5)}d** | Total: **{c.get('total_review_days',7)}d**\n"
        f"Showcase: **{c.get('showcase_threshold',8.0)}/10** | Require X: **{'Yes' if c.get('require_twitter_id',1) else 'No'}**"), inline=False)
    e.add_field(name=f"{mc} Values", value=(
        f"Score 4–6 / 6–8 / 8–10: **{c.get('mc_score_low',1)} / {c.get('mc_score_medium',3)} / {c.get('mc_score_high',5)}**\n"
        f"Full submission capacity: **{c.get('mc_submit_completion',2)}**\n"
        f"Review goal: **{c.get('mc_review_reward',2)}** | Comment: **{c.get('mc_comment_bonus',1)}** | Showcase: **{c.get('mc_showcase_reward',3)}**\n"
        f"Quiz 40/70/80/90: **{c.get('quiz_mc_40',1)} / {c.get('quiz_mc_70',2)} / {c.get('quiz_mc_80',3)} / {c.get('quiz_mc_90',5)}**"), inline=False)
    reactions = [f"{c.get(f'reaction_emoji_{i}') or '—'}→{c.get(f'reaction_mc_{i}',i)}" for i in range(1,6)]
    e.add_field(name="Reactions", value=" | ".join(reactions)+f"\nRaffle: **{c.get('raffle_reaction_emoji') or 'Not set'}**", inline=False)
    e.add_field(name="Names & Branding", value=(
        f"Bot: **{c.get('txt_bot_name','Melee Zone')}** | Currency: **{mc}**\n"
        f"Reviewer: **{c.get('txt_pro_role','Reviewer')}** | Basic: **{c.get('txt_basic_role','Basic')}**\n"
        f"Panel: **{c.get('txt_panel_title','Melee Zone')}**"), inline=False)
    e.set_footer(text="All values remain stored in your existing database.")
    return e


class RulesModal(AdminModal, title="Content & Review Rules"):
    submits=discord.ui.TextInput(label="Max submissions per week",max_length=3)
    reviews=discord.ui.TextInput(label="Max reviews per week",max_length=3)
    minimum=discord.ui.TextInput(label="Minimum reviews per post",max_length=2)
    showcase=discord.ui.TextInput(label="Showcase score threshold",max_length=4)
    def __init__(self,db,c):
        super().__init__();self.db=db
        for a,k,d in [('submits','max_submits_per_week',5),('reviews','max_reviews_per_week',7),('minimum','min_reviews',5),('showcase','showcase_threshold',8.0)]:getattr(self,a).default=str(c.get(k,d))
    async def on_submit(self,i):
        try:u={'max_submits_per_week':max(1,int(self.submits.value)),'max_reviews_per_week':max(1,int(self.reviews.value)),'min_reviews':max(1,int(self.minimum.value)),'showcase_threshold':min(10,max(1,float(self.showcase.value)))}
        except ValueError:return await i.response.send_message("Use valid numbers.",ephemeral=True)
        if await request_config_change(i,**u):await reply(i,"✅ Rules updated.")


class ScoreRewardsModal(AdminModal,title="Post & Review Rewards"):
    low=discord.ui.TextInput(label="MC for average 4 to under 6",max_length=8);medium=discord.ui.TextInput(label="MC for average 6 to under 8",max_length=8)
    high=discord.ui.TextInput(label="MC for average 8 to 10",max_length=8);completion=discord.ui.TextInput(label="MC for full weekly submission capacity",max_length=8)
    review=discord.ui.TextInput(label="MC for completing review goal",max_length=8)
    def __init__(self,db,c):
        super().__init__();self.db=db
        for a,k,d in [('low','mc_score_low',1),('medium','mc_score_medium',3),('high','mc_score_high',5),('completion','mc_submit_completion',2),('review','mc_review_reward',2)]:getattr(self,a).default=str(c.get(k,d))
    async def on_submit(self,i):
        try:v=[float(x.value) for x in [self.low,self.medium,self.high,self.completion,self.review]];assert all(x>=0 for x in v)
        except (ValueError,AssertionError):return await i.response.send_message("Use zero or positive numbers.",ephemeral=True)
        if await request_config_change(i,mc_score_low=v[0],mc_score_medium=v[1],mc_score_high=v[2],mc_submit_completion=v[3],mc_review_reward=v[4]):await reply(i,"✅ Rewards updated.")


class BonusModal(AdminModal,title="Bonus & Quiz Rewards"):
    comment=discord.ui.TextInput(label="Comment bonus MC",max_length=8);showcase=discord.ui.TextInput(label="Showcase Golden MC",max_length=8)
    q40=discord.ui.TextInput(label="Quiz MC for 40 to 69 percent",max_length=8);q70=discord.ui.TextInput(label="Quiz MC for 70 to 79 percent",max_length=8);q90=discord.ui.TextInput(label="Quiz MC for 90 to 100 percent",max_length=8)
    def __init__(self,db,c):
        super().__init__();self.db=db
        for a,k,d in [('comment','mc_comment_bonus',1),('showcase','mc_showcase_reward',3),('q40','quiz_mc_40',1),('q70','quiz_mc_70',2),('q90','quiz_mc_90',5)]:getattr(self,a).default=str(c.get(k,d))
    async def on_submit(self,i):
        try:v=[float(x.value) for x in [self.comment,self.showcase,self.q40,self.q70,self.q90]];assert all(x>=0 for x in v)
        except (ValueError,AssertionError):return await i.response.send_message("Use zero or positive numbers.",ephemeral=True)
        if await request_config_change(i,mc_comment_bonus=v[0],mc_showcase_reward=v[1],quiz_mc_40=v[2],quiz_mc_70=v[3],quiz_mc_90=v[4]):await reply(i,"✅ Bonuses updated.")


class QuizRewardsModal(AdminModal,title="Complete Quiz Reward Setup"):
    minimum=discord.ui.TextInput(label="Minimum percent to earn Quiz MC",max_length=5)
    q40=discord.ui.TextInput(label="Quiz MC for 40 to 69 percent",max_length=8)
    q70=discord.ui.TextInput(label="Quiz MC for 70 to 79 percent",max_length=8)
    q80=discord.ui.TextInput(label="Quiz MC for 80 to 89 percent",max_length=8)
    q90=discord.ui.TextInput(label="Quiz MC for 90 to 100 percent",max_length=8)
    def __init__(self,db,c):
        super().__init__();self.db=db
        for a,k,d in [('minimum','quiz_mc_min_pct',40),('q40','quiz_mc_40',1),('q70','quiz_mc_70',2),('q80','quiz_mc_80',3),('q90','quiz_mc_90',5)]:getattr(self,a).default=str(c.get(k,d))
    async def on_submit(self,i):
        try:v=[float(x.value) for x in [self.minimum,self.q40,self.q70,self.q80,self.q90]];assert 0<=v[0]<=100 and all(x>=0 for x in v[1:])
        except (ValueError,AssertionError):return await i.response.send_message("Use valid zero or positive values and a percent from 0 to 100.",ephemeral=True)
        if await request_config_change(i,quiz_mc_min_pct=v[0],quiz_mc_40=v[1],quiz_mc_70=v[2],quiz_mc_80=v[3],quiz_mc_90=v[4]):await reply(i,"✅ Quiz rewards updated.")


class TimingModal(AdminModal,title="Timing & Validation"):
    main_days=discord.ui.TextInput(label="Main review period in days",max_length=2)
    total_days=discord.ui.TextInput(label="Total review deadline in days",max_length=2)
    grace=discord.ui.TextInput(label="Warning grace period in hours",max_length=3)
    rescue=discord.ui.TextInput(label="Maximum rescue reviews per week",max_length=2)
    feedback=discord.ui.TextInput(label="Minimum feedback characters",max_length=3)
    def __init__(self,db,c):
        super().__init__();self.db=db
        for a,k,d in [('main_days','primary_review_days',5),('total_days','total_review_days',7),('grace','warning_grace_hours',12),('rescue','rescue_review_limit',3),('feedback','min_feedback_length',30)]:getattr(self,a).default=str(c.get(k,d))
    async def on_submit(self,i):
        try:v=[int(x.value) for x in [self.main_days,self.total_days,self.grace,self.rescue,self.feedback]];assert all(x>0 for x in v) and v[1]>=v[0]
        except (ValueError,AssertionError):return await i.response.send_message("Use positive numbers. Total days must be at least the main period.",ephemeral=True)
        if await request_config_change(i,primary_review_days=v[0],total_review_days=v[1],warning_grace_hours=v[2],rescue_review_limit=v[3],min_feedback_length=v[4]):await reply(i,"✅ Review timing updated.")


class ConfigRoleSelect(discord.ui.RoleSelect):
    def __init__(self,db,key,label):super().__init__(placeholder=label,min_values=1,max_values=1);self.db=db;self.key=key
    async def callback(self,i):
        if self.values[0].is_default():return await reply(i,'Select a specific role, not @everyone.')
        if await request_config_change(i,**{self.key:str(self.values[0].id)}):await reply(i,f"✅ {self.values[0].mention} saved.")
class RolesView(AdminView):
    def __init__(self,db):
        super().__init__(timeout=300)
        for k,l in [('pro_role_id','Reviewer role'),('basic_role_id','Basic role'),('admin_role_id','Admin role'),('quiz_pass_role_id','Quiz pass role'),('raffle_role_id','Raffle access role')]:self.add_item(ConfigRoleSelect(db,k,l))


class ConfigChannelSelect(discord.ui.ChannelSelect):
    def __init__(self,db,key,label):super().__init__(placeholder=label,channel_types=[discord.ChannelType.text],min_values=1,max_values=1);self.db=db;self.key=key
    async def callback(self,i):
        if await request_config_change(i,**{self.key:str(self.values[0].id)}):await reply(i,f"✅ {self.values[0].mention} saved.")
class ChannelsView(AdminView):
    def __init__(self,db,page):
        super().__init__(timeout=300)
        a=[('bot_content_channel_id','Panel channel'),('showcase_channel_id','Showcase channel'),('leaderboard_channel_id','Leaderboard channel'),('review_channel_id','Review fallback channel')]
        b=[('assignment_channel_id','Community tasks channel'),('log_channel_id','System log channel'),('credit_log_channel_id','Credit log channel')]
        for k,l in (a if page==1 else b):self.add_item(ConfigChannelSelect(db,k,l))


class SetupCenterView(AdminView):
    def __init__(self,db):super().__init__(timeout=300);self.db=db
    @discord.ui.button(label="📋 View All",style=discord.ButtonStyle.primary,row=0)
    async def view(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_message(embed=config_embed(i.guild,c),ephemeral=True)
    @discord.ui.button(label="👥 Roles",style=discord.ButtonStyle.secondary,row=0)
    async def roles(self,i,b):await i.response.send_message("Set every access role below.",view=RolesView(self.db),ephemeral=True)
    @discord.ui.button(label="💬 Core Channels",style=discord.ButtonStyle.secondary,row=0)
    async def ch1(self,i,b):await i.response.send_message("Set core channels.",view=ChannelsView(self.db,1),ephemeral=True)
    @discord.ui.button(label="💬 More Channels",style=discord.ButtonStyle.secondary,row=0)
    async def ch2(self,i,b):await i.response.send_message("Set task and log channels.",view=ChannelsView(self.db,2),ephemeral=True)
    @discord.ui.button(label="📝 Rules",style=discord.ButtonStyle.secondary,row=1)
    async def rules(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_modal(RulesModal(self.db,c))
    @discord.ui.button(label="💎 Score Rewards",style=discord.ButtonStyle.secondary,row=1)
    async def score(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_modal(ScoreRewardsModal(self.db,c))
    @discord.ui.button(label="🎁 Bonus & Quiz",style=discord.ButtonStyle.secondary,row=1)
    async def bonus(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_modal(BonusModal(self.db,c))
    @discord.ui.button(label="📚 Full Quiz Values",style=discord.ButtonStyle.secondary,row=2)
    async def quiz_values(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_modal(QuizRewardsModal(self.db,c))
    @discord.ui.button(label="⏰ Timing & X",style=discord.ButtonStyle.secondary,row=2)
    async def timing(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_modal(TimingModal(self.db,c))
    @discord.ui.button(label="✏️ Names & Messages",style=discord.ButtonStyle.secondary,row=3)
    async def text(self,i,b):
        from cogs.panel import AdvancedSettingsMenuView
        c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_message("Edit names, messages, reactions and About.",view=AdvancedSettingsMenuView(self.db,c),ephemeral=True)
    @discord.ui.button(label="😀 Reaction Setup",style=discord.ButtonStyle.secondary,row=3)
    async def react(self,i,b):await i.response.send_message("Use `/setup_reactions` for MC and `/setup_raffle_reaction` for raffle. Both remain stored in this setup.",ephemeral=True)

    @discord.ui.button(label='Access management',style=discord.ButtonStyle.danger,row=4)
    async def access(self,i,b):
        from cogs.governance import AccessView, require_primary
        if await require_primary(i):await reply(i,'Only primary admins manage moderator access, the primary-admin role and named primary admins.',view=AccessView())


class GuideView(AdminView):
    def __init__(self):super().__init__(timeout=300)
    async def send(self,i,t,d):await i.response.send_message(embed=discord.Embed(title=t,description=d,color=mz('secondary')),ephemeral=True)
    @discord.ui.button(label="🚀 Setup",style=discord.ButtonStyle.primary,row=0)
    async def setup(self,i,b):await self.send(i,"🚀 Setup","Run `/setup`. Configure Roles, Channels, Rules, Rewards, Names and Reactions. View All shows old and new settings together.")
    @discord.ui.button(label="📝 Reviews",style=discord.ButtonStyle.secondary,row=0)
    async def reviews(self,i,b):await self.send(i,"📝 Content & Reviews","Reviewers manually verify X posts. The bot has no X API or AI validation. Distribute Reviews assigns submitted posts to reviewers.")
    @discord.ui.button(label="💎 Rewards",style=discord.ButtonStyle.secondary,row=0)
    async def rewards(self,i,b):await self.send(i,"💎 Rewards","Score MC, review MC, bonuses, Quiz MC, reactions and Snapshot rewards are separate and configurable.")
    @discord.ui.button(label="📚 Quiz & Raffle",style=discord.ButtonStyle.secondary,row=1)
    async def qr(self,i,b):await self.send(i,"📚 Quiz & Raffle","Quiz grants its pass role. Raffle access comes from admin reaction, command or panel. The bot role must be above both roles.")
    @discord.ui.button(label="📋 Community Tasks",style=discord.ButtonStyle.secondary,row=1)
    async def tasks(self,i,b):await self.send(i,"📋 Community Tasks","Thread-based member tasks are separate from review distribution. They support cooldowns and participation counts.")
    @discord.ui.button(label="🛠 Fix Problems",style=discord.ButtonStyle.danger,row=1)
    async def fix(self,i,b):await self.send(i,"🛠 Troubleshooting","Roles: check Manage Roles and role order. Tasks: check thread permissions. Use `/setup` → View All for missing values.")


class ContentView(AdminView):
    def __init__(self,db,c):super().__init__(timeout=300);self.db=db;self.c=c
    @discord.ui.button(label="🔄 Distribute Reviews",style=discord.ButtonStyle.primary)
    async def distribute(self,i,b):await i.response.defer(ephemeral=True);cog=i.client.get_cog('Tasks');await cog.process_guild_weekly(i.guild) if cog else None;await i.followup.send("✅ Review distribution completed.",ephemeral=True)
    @discord.ui.button(label="📋 Community Tasks",style=discord.ButtonStyle.secondary)
    async def tasks(self,i,b):
        from cogs.assignments import AssignmentAdminView
        await i.response.send_message("Community task manager",view=AssignmentAdminView(self.db,self.c,i.guild),ephemeral=True)
    @discord.ui.button(label="📚 Quiz",style=discord.ButtonStyle.secondary)
    async def quiz(self,i,b):
        from cogs.quiz import AdminQuizView
        await i.response.send_message("Quiz manager",view=AdminQuizView(self.db,self.c,i.guild),ephemeral=True)


class RewardsView(AdminView):
    def __init__(self,db,c):super().__init__(timeout=300);self.db=db;self.c=c
    @discord.ui.button(label="💰 Award MC",style=discord.ButtonStyle.primary)
    async def award(self,i,b):
        from cogs.panel import GiveMCModal
        await i.response.send_modal(GiveMCModal(self.db,self.c))
    @discord.ui.button(label="🎟️ Raffle",style=discord.ButtonStyle.secondary)
    async def raffle(self,i,b):
        from cogs.panel import RaffleAdminView
        await i.response.send_message("Raffle role manager",view=RaffleAdminView(self.db,self.c,i.guild),ephemeral=True)
    @discord.ui.button(label="📸 Snapshot",style=discord.ButtonStyle.secondary)
    async def snap(self,i,b):await i.response.send_message("Run `/snapshot` in the target channel or thread.",ephemeral=True)


class UnifiedAdminView(AdminView):
    def __init__(self,db):super().__init__(timeout=None);self.db=db
    @discord.ui.button(label="📊 Overview",style=discord.ButtonStyle.primary,custom_id="mz_hub_overview",row=0)
    async def overview(self,i,b):
        c=await self.db.get_guild_config(str(i.guild_id)) or {};week=get_current_week_id();posts=await self.db.get_posts_by_week(str(i.guild_id),week);users=await self.db.get_all_users(str(i.guild_id));e=discord.Embed(title="📊 Overview",description=f"Week: **{week}**\nPosts: **{len(posts)}**\nReviews: **{await self.db.get_review_count(week)}**\nUsers: **{len(users)}**",color=mz('secondary'));await i.response.send_message(embed=e,ephemeral=True)
    @discord.ui.button(label="📝 Content",style=discord.ButtonStyle.secondary,custom_id="mz_hub_content",row=0)
    async def content(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_message("Content and review tools",view=ContentView(self.db,c),ephemeral=True)
    @discord.ui.button(label="💎 Rewards",style=discord.ButtonStyle.secondary,custom_id="mz_hub_rewards",row=0)
    async def rewards(self,i,b):c=await self.db.get_guild_config(str(i.guild_id)) or {};await i.response.send_message("Reward and access tools",view=RewardsView(self.db,c),ephemeral=True)
    @discord.ui.button(label="⚙️ Setup",style=discord.ButtonStyle.secondary,custom_id="mz_hub_setup",row=1)
    async def setup(self,i,b):await i.response.send_message(embed=discord.Embed(title="⚙️ Setup Center",description="View current settings or submit a change. Moderator changes wait for primary-admin approval; primary admins apply directly.",color=mz('primary')),view=SetupCenterView(self.db),ephemeral=True)
    @discord.ui.button(label="📖 Guide",style=discord.ButtonStyle.success,custom_id="mz_hub_guide",row=1)
    async def guide(self,i,b):await i.response.send_message(embed=discord.Embed(title="📖 Admin Guide",description="One guide organized by feature.",color=mz('secondary')),view=GuideView(),ephemeral=True)

    @discord.ui.button(label='Role report',style=discord.ButtonStyle.secondary,custom_id='mz_hub_role_report',row=2)
    async def role_report(self,i,b):
        from cogs.activity import RoleReportView
        await i.response.send_message('Choose a role. The default scan covers 30 days and 20,000 messages. Use /role_report for a different window or full history.',view=RoleReportView(),ephemeral=True)

    @discord.ui.button(label='Health and recovery',style=discord.ButtonStyle.secondary,custom_id='mz_hub_health',row=2)
    async def health(self,i,b):
        from cogs.health import HealthView,health_embed
        await i.response.send_message(embed=health_embed(i.client.health.snapshot()),view=HealthView(),ephemeral=True)

    @discord.ui.button(label='Review support and analytics',style=discord.ButtonStyle.secondary,custom_id='mz_hub_review_support',row=2)
    async def review_support(self,i,b):
        from cogs.review_support import SupportAdminView
        await i.response.send_message('Private fortnightly Excel/CSV reports, editable setup calculator and volunteer weekly support.',view=SupportAdminView(),ephemeral=True)

    @discord.ui.button(label='Change requests',style=discord.ButtonStyle.secondary,custom_id='mz_hub_config_requests',row=3)
    async def change_requests(self,i,b):
        from cogs.governance import show_requests
        await show_requests(i)


class ControlCenterCog(BotHelpers,commands.Cog,name="ControlCenter"):
    def __init__(self,bot):self.bot=bot
    async def cog_load(self):self.bot.add_view(UnifiedAdminView(self.db))
    @app_commands.command(name="setup",description="Open the unified setup center")
    async def setup_command(self,i):
        c=await self.require_admin(i)
        if c is None:return
        await i.response.send_message(embed=discord.Embed(title="⚙️ Setup Center",description="All roles, channels, rules, rewards and texts.",color=mz('primary')),view=SetupCenterView(self.db),ephemeral=True)


async def setup(bot):await bot.add_cog(ControlCenterCog(bot))
