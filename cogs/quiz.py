from ui_security import AdminView,AdminModal
"""
cogs/quiz.py — Melee Zone Quiz Feature (tested)
- Admin loads article JSON via admin panel
- Users take quiz from main panel (Basic role only)
- MC awarded immediately based on score percentage
- Quiz pass role assigned on 70%+ score
- Role revoked when new quiz is loaded or admin triggers revoke
- Full admin stats: participants, scores, time-to-complete
"""
import discord
from discord import app_commands
from discord.ext import commands
from helpers import BotHelpers
from config import Config, mz
from datetime import datetime, timezone
import pytz
import json
import io
import csv
import asyncio
import logging

log = logging.getLogger('MeleeZone.Quiz')
UTC = timezone.utc
TEHRAN = pytz.timezone('Asia/Tehran')


# ── MC Calculation ────────────────────────────────────────────────────────────

def _calc_quiz_mc(score_pct: float, config: dict) -> float:
    """All thresholds read from DB — none hardcoded."""
    if score_pct >= 90:
        return float(Config.g(config, 'quiz_mc_90', 5.0))
    elif score_pct >= 80:
        return float(Config.g(config, 'quiz_mc_80', 3.0))
    elif score_pct >= 70:
        return float(Config.g(config, 'quiz_mc_70', 2.0))
    elif score_pct >= float(Config.g(config, 'quiz_mc_min_pct', 40.0)):
        return float(Config.g(config, 'quiz_mc_40', 1.0))
    return 0.0


def _shuffle(lst: list) -> list:
    import random
    out = lst[:]
    for i in range(len(out) - 1, 0, -1):
        j = random.randint(0, i)
        out[i], out[j] = out[j], out[i]
    return out


def _validate_quiz_json(raw: str):
    """Returns (data, error_message). error_message is None if valid."""
    try:
        data = json.loads(raw.strip())
    except json.JSONDecodeError as e:
        return None, f"Invalid JSON: {e}"
    if not isinstance(data, dict) or 'questions' not in data:
        return None, "JSON must have format: `{article, title, questions: [...]}`"
    questions = data.get('questions', [])
    if len(questions) < 3:
        return None, f"Need at least 3 questions, got {len(questions)}."
    for i, q in enumerate(questions):
        for key in ('question', 'correct_answer', 'incorrect_answers'):
            if key not in q:
                return None, f"Question {i+1} is missing field: `{key}`"
        if not isinstance(q['incorrect_answers'], list) or len(q['incorrect_answers']) < 2:
            return None, f"Question {i+1} needs at least 2 incorrect answers."
    return data, None


# ── Modals ────────────────────────────────────────────────────────────────────

class LoadQuizModal(AdminModal, title="Load Quiz — Paste JSON"):
    json_input = discord.ui.TextInput(
        label="Article quiz JSON",
        style=discord.TextStyle.paragraph,
        placeholder='{"article":"slug","title":"Title","questions":[...]}',
        max_length=4000
    )

    def __init__(self, db, guild: discord.Guild):
        super().__init__()
        self.db = db
        self.guild = guild

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)

        data, err = _validate_quiz_json(self.json_input.value)
        if err:
            return await interaction.followup.send(f"❌ {err}", ephemeral=True)

        questions = data['questions']
        article_slug = data.get('article', f"article_{int(datetime.now(UTC).timestamp())}")
        article_title = data.get('title', article_slug)
        config = await self.db.get_guild_config(guild_id) or {}

        # Revoke quiz role from all current holders
        revoked = 0
        role_id = config.get('quiz_pass_role_id')
        if role_id:
            role = self.guild.get_role(int(role_id))
            if role:
                for member in list(role.members):
                    try:
                        await member.remove_roles(role, reason="New quiz loaded")
                        revoked += 1
                    except Exception:
                        pass

        # Save new quiz (deactivates old ones)
        await self.db.create_quiz(
            guild_id=guild_id,
            article_slug=article_slug,
            title=article_title,
            questions=questions,
            loaded_by=str(interaction.user.id)
        )

        embed = discord.Embed(title="✅ Quiz Loaded", color=mz('green'))
        embed.add_field(name="Article", value=article_title, inline=False)
        embed.add_field(name="Questions", value=str(len(questions)), inline=True)
        embed.add_field(name="Slug", value=f"`{article_slug}`", inline=True)
        if revoked > 0:
            embed.add_field(
                name="Roles Revoked",
                value=f"Removed quiz role from **{revoked}** users.",
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)

        if config.get('log_channel_id'):
            ch = self.guild.get_channel(int(config['log_channel_id']))
            if ch:
                await ch.send(
                    f"📚 New quiz loaded by {interaction.user.mention}: **{article_title}** "
                    f"({len(questions)} questions). Quiz role revoked from {revoked} users."
                )


class QuizMCModal(AdminModal, title="Edit Quiz MC Values"):
    mc_min = discord.ui.TextInput(label="Min % to earn any MC (default 40)", placeholder="40", required=False, max_length=3)
    mc_40 = discord.ui.TextInput(label="MC for 40–69% score (default 1.0)", placeholder="1.0", required=False, max_length=5)
    mc_70 = discord.ui.TextInput(label="MC for 70–79% score (default 2.0)", placeholder="2.0", required=False, max_length=5)
    mc_80 = discord.ui.TextInput(label="MC for 80–89% score (default 3.0)", placeholder="3.0", required=False, max_length=5)
    mc_90 = discord.ui.TextInput(label="MC for 90–100% score (default 5.0)", placeholder="5.0", required=False, max_length=5)

    def __init__(self, db):
        super().__init__()
        self.db = db

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        updates, changed = {}, []
        for key, val, label in [
            ('quiz_mc_min_pct', self.mc_min.value, "Min % for MC"),
            ('quiz_mc_40', self.mc_40.value, "MC 40–69%"),
            ('quiz_mc_70', self.mc_70.value, "MC 70–79%"),
            ('quiz_mc_80', self.mc_80.value, "MC 80–89%"),
            ('quiz_mc_90', self.mc_90.value, "MC 90–100%"),
        ]:
            if val.strip():
                try:
                    updates[key] = float(val.strip())
                    changed.append(f"{label}: **{val.strip()}**")
                except ValueError:
                    pass
        if updates:
            await self.db.update_guild_config(guild_id, **updates)
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Quiz MC Values Updated",
                description="\n".join(changed) or "No changes.",
                color=mz('green')
            ), ephemeral=True
        )


# ── User Quiz View ────────────────────────────────────────────────────────────

class QuizUserView(discord.ui.View):
    """Shown when user clicks 📚 Quiz in main panel."""

    def __init__(self, db, config: dict, quiz: dict):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.quiz = quiz

    @discord.ui.button(label="🎯 Start Quiz", style=discord.ButtonStyle.primary, row=0)
    async def start_quiz(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        uid = str(interaction.user.id)
        mc = Config.mc_name(self.config)

        # Already taken?
        existing = await self.db.get_quiz_result(guild_id, uid, self.quiz['id'])
        if existing:
            pct = existing['score_pct']
            earned = existing['mc_earned']
            elapsed = existing['elapsed_seconds']
            mins, secs = elapsed // 60, elapsed % 60
            embed = discord.Embed(
                title="📚 Already Completed",
                description=(
                    f"You already completed this quiz.\n\n"
                    f"**Score:** {pct:.0f}% ({existing['correct_count']}/{existing['total_questions']})\n"
                    f"**{mc} earned:** {earned}\n"
                    f"**Time:** {mins}m {secs}s\n"
                    f"**Date:** {existing['completed_at'][:10]}"
                ),
                color=mz('secondary')
            )
            return await interaction.followup.send(embed=embed, ephemeral=True)

        questions = json.loads(self.quiz['questions_json'])
        shuffled = _shuffle(questions)
        started_at = datetime.now(UTC)
        mc_name = Config.mc_name(self.config)
        min_pct = int(Config.g(self.config, 'quiz_mc_min_pct', 40))

        session_id = await self.db.create_quiz_session(
            guild_id=guild_id,
            user_id=uid,
            quiz_id=self.quiz['id'],
            questions=shuffled,
            started_at=started_at
        )

        # Onboarding embed
        embed = discord.Embed(
            title=f"📚 {self.quiz['title']}",
            color=mz('primary')
        )
        embed.description = (
            f"**{len(shuffled)} questions.** Read each carefully.\n\n"
            f"🪙 Score {min_pct}%+ → earn {mc_name}\n"
            f"🏅 Score 70%+ → earn {mc_name} + quiz role\n\n"
            f"Questions appear one by one. Only you can see them.\nNo time limit."
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
        await asyncio.sleep(1.5)

        # Run questions
        correct = 0
        for i, q in enumerate(shuffled):
            is_correct = await self._run_question(
                interaction, q, i + 1, len(shuffled), uid
            )
            if is_correct:
                correct += 1

        # Score
        finished_at = datetime.now(UTC)
        elapsed_seconds = int((finished_at - started_at).total_seconds())
        score_pct = round((correct / len(shuffled)) * 100, 1)
        mc_earned = _calc_quiz_mc(score_pct, self.config)
        passed = score_pct >= 70

        created=await self.db.complete_quiz_atomic(
            guild_id=guild_id,user_id=uid,quiz_id=self.quiz['id'],session_id=session_id,
            correct=correct,total=len(shuffled),score_pct=score_pct,mc_earned=mc_earned,
            elapsed_seconds=elapsed_seconds,completed_at=finished_at,title=self.quiz['title'])
        if not created:
            return await interaction.followup.send('This quiz was already completed. Its MC reward was recorded once.',ephemeral=True)

        # Assign pass role
        role_assigned = False
        if passed:
            role_id = self.config.get('quiz_pass_role_id')
            if role_id:
                role = interaction.guild.get_role(int(role_id))
                if role:
                    try:
                        member = interaction.guild.get_member(int(uid))
                        if member and role not in member.roles:
                            await member.add_roles(role, reason="Quiz passed")
                            role_assigned = True
                    except Exception as e:
                        log.warning(f"Could not assign quiz role to {uid}: {e}")

        # Result embed
        mins, secs = elapsed_seconds // 60, elapsed_seconds % 60
        color = mz('green') if mc_earned > 0 else mz('red')

        result = discord.Embed(
            title="🎯 Quiz Complete!",
            color=color
        )
        result.add_field(name="Score", value=f"**{correct}/{len(shuffled)} ({score_pct:.0f}%)**", inline=True)
        result.add_field(name=f"{mc_name} Earned", value=f"**{mc_earned}**", inline=True)
        result.add_field(name="Time", value=f"{mins}m {secs}s", inline=True)

        if passed and role_assigned:
            result.add_field(name="🏅 Role Assigned", value="You earned the quiz pass role!", inline=False)
        elif passed:
            result.add_field(name="✅ Passed", value="Great score!", inline=False)
        elif mc_earned > 0:
            result.add_field(
                name=f"🪙 +{mc_earned} {mc_name}",
                value=f"Score 70%+ next time to also earn the quiz role.",
                inline=False
            )
        else:
            result.add_field(
                name="📖 Keep Reading",
                value=f"Score {min_pct}%+ to earn {mc_name}.",
                inline=False
            )

        await interaction.followup.send(embed=result, ephemeral=True)

        if self.config.get('log_channel_id'):
            ch = interaction.guild.get_channel(int(self.config['log_channel_id']))
            if ch:
                member = interaction.guild.get_member(int(uid))
                tag = member.mention if member else uid
                await ch.send(
                    f"📚 {tag} finished **{self.quiz['title']}**: "
                    f"{score_pct:.0f}% ({correct}/{len(shuffled)}) | "
                    f"+{mc_earned} {mc_name} | {mins}m {secs}s"
                )

    async def _run_question(
        self,
        interaction: discord.Interaction,
        question: dict,
        num: int,
        total: int,
        uid: str
    ) -> bool:
        answers = _shuffle(
            list(question['incorrect_answers']) + [question['correct_answer']]
        )
        correct_index = answers.index(question['correct_answer'])
        labels = ['A', 'B', 'C', 'D']
        id_prefix = f"mzq_{interaction.id}_{num}_{uid}"

        answer_list = "\n".join(f"**{labels[i]}.** {a}" for i, a in enumerate(answers))
        difficulty = question.get('difficulty', 'medium')

        embed = discord.Embed(
            title=f"Question {num} of {total}",
            description=f"**{question['question']}**\n\n{answer_list}",
            color=mz('primary')
        )
        embed.set_footer(text=f"{difficulty} difficulty — pick your answer")

        view = discord.ui.View(timeout=14 * 60)
        for i, a in enumerate(answers):
            btn = discord.ui.Button(
                custom_id=f"{id_prefix}_{i}",
                label=f"{labels[i]}: {a[:70]}{'...' if len(a) > 70 else ''}",
                style=discord.ButtonStyle.secondary
            )
            view.add_item(btn)

        await interaction.followup.send(embed=embed, view=view, ephemeral=True)

        try:
            resp = await interaction.client.wait_for(
                'interaction',
                check=lambda i: (
                    i.type == discord.InteractionType.component
                    and i.user.id == int(uid)
                    and i.data.get('custom_id', '').startswith(id_prefix)
                ),
                timeout=14 * 60
            )
        except asyncio.TimeoutError:
            return False

        chosen_index = int(resp.data['custom_id'].split('_')[-1])
        is_correct = chosen_index == correct_index

        # Show result
        result_view = discord.ui.View()
        for i, a in enumerate(answers):
            if i == correct_index:
                style = discord.ButtonStyle.success
            elif i == chosen_index and not is_correct:
                style = discord.ButtonStyle.danger
            else:
                style = discord.ButtonStyle.secondary
            result_view.add_item(discord.ui.Button(
                custom_id=f"done_{i}",
                label=f"{labels[i]}: {a[:70]}{'...' if len(a) > 70 else ''}",
                style=style,
                disabled=True
            ))

        feedback = (
            "✅ Correct!" if is_correct
            else f"❌ The answer was **{labels[correct_index]}. {question['correct_answer']}**"
        )
        result_embed = discord.Embed(
            title=f"Question {num} of {total}",
            description=f"**{question['question']}**\n\n{answer_list}\n\n{feedback}",
            color=mz('green') if is_correct else mz('red')
        )
        await resp.response.edit_message(embed=result_embed, view=result_view)
        await asyncio.sleep(1.5)
        return is_correct

    @discord.ui.button(label="📊 My Quiz History", style=discord.ButtonStyle.secondary, row=0)
    async def my_history(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        uid = str(interaction.user.id)
        mc = Config.mc_name(self.config)
        results = await self.db.get_user_quiz_results(guild_id, uid, limit=10)
        if not results:
            return await interaction.followup.send(
                embed=discord.Embed(
                    title="📚 Quiz History",
                    description="No quiz history yet.\nTake your first quiz to start earning MC!",
                    color=mz('secondary')
                ), ephemeral=True
            )
        embed = discord.Embed(title="📚 Your Quiz History", color=mz('primary'))
        for r in results:
            mins, secs = r['elapsed_seconds'] // 60, r['elapsed_seconds'] % 60
            passed_icon = "✅" if r['score_pct'] >= 70 else ("🟡" if r['score_pct'] >= 40 else "❌")
            embed.add_field(
                name=f"{passed_icon} {r['title'][:40]}",
                value=(
                    f"**{r['score_pct']:.0f}%** ({r['correct_count']}/{r['total_questions']}) | "
                    f"+{r['mc_earned']} {mc} | {mins}m {secs}s\n"
                    f"{r['completed_at'][:10]}"
                ),
                inline=False
            )
        await interaction.followup.send(embed=embed, ephemeral=True)


class QuizNoActiveView(discord.ui.View):
    """Shown when no active quiz exists."""
    def __init__(self):
        super().__init__(timeout=60)

    @discord.ui.button(label="🔔 Got It", style=discord.ButtonStyle.secondary)
    async def dismiss(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)


# ── Admin Quiz View ───────────────────────────────────────────────────────────

class AdminQuizView(AdminView):
    """Full quiz management — lives inside admin panel."""

    def __init__(self, db, config: dict, guild: discord.Guild):
        super().__init__(timeout=120)
        self.db = db
        self.config = config
        self.guild = guild

    @discord.ui.button(label="📂 Load Quiz (JSON)", style=discord.ButtonStyle.primary, row=0)
    async def load_quiz(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(LoadQuizModal(self.db, self.guild))

    @discord.ui.button(label="📋 Active Quiz Info", style=discord.ButtonStyle.secondary, row=0)
    async def active_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        quiz = await self.db.get_active_quiz(guild_id)
        if not quiz:
            return await interaction.followup.send("No active quiz.", ephemeral=True)
        mc = Config.mc_name(self.config)
        questions = json.loads(quiz['questions_json'])
        stats = await self.db.get_quiz_stats(guild_id, quiz['id'])

        embed = discord.Embed(title=f"📚 Active Quiz", color=mz('primary'))
        embed.add_field(name="Title", value=quiz['title'], inline=False)
        embed.add_field(name="Slug", value=f"`{quiz['article_slug']}`", inline=True)
        embed.add_field(name="Questions", value=str(len(questions)), inline=True)
        embed.add_field(name="Loaded", value=quiz['loaded_at'][:10], inline=True)
        embed.add_field(name="Participants", value=str(stats['total_participants'] or 0), inline=True)
        embed.add_field(name="Passed (70%+)", value=str(stats['passed'] or 0), inline=True)
        avg = stats['avg_score']
        embed.add_field(name="Avg Score", value=f"{avg:.1f}%" if avg else "—", inline=True)
        embed.add_field(name=f"Total {mc} Awarded", value=str(stats['total_mc'] or 0), inline=True)
        avg_t = stats['avg_time']
        embed.add_field(
            name="Avg Time",
            value=f"{int(avg_t)//60}m {int(avg_t)%60}s" if avg_t else "—",
            inline=True
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="👥 User Progress", style=discord.ButtonStyle.secondary, row=0)
    async def user_progress(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        quiz = await self.db.get_active_quiz(guild_id)
        if not quiz:
            return await interaction.followup.send("No active quiz.", ephemeral=True)
        mc = Config.mc_name(self.config)
        results = await self.db.get_all_quiz_results(guild_id, quiz['id'])
        if not results:
            return await interaction.followup.send("No participants yet.", ephemeral=True)

        embed = discord.Embed(
            title=f"👥 Participants — {quiz['title'][:40]}",
            color=mz('secondary')
        )
        lines = []
        for r in results[:15]:
            member = self.guild.get_member(int(r['user_id']))
            name = member.display_name if member else r['user_id']
            mins, secs = r['elapsed_seconds'] // 60, r['elapsed_seconds'] % 60
            icon = "✅" if r['score_pct'] >= 70 else ("🟡" if r['score_pct'] >= 40 else "❌")
            lines.append(
                f"{icon} **{name}** — {r['score_pct']:.0f}% | "
                f"+{r['mc_earned']} {mc} | {mins}m {secs}s"
            )
        embed.description = "\n".join(lines)
        if len(results) > 15:
            embed.set_footer(text=f"Showing 15/{len(results)} — use Export for full list")
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="📤 Export Quiz CSV", style=discord.ButtonStyle.secondary, row=1)
    async def export(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        guild_id = str(interaction.guild_id)
        quiz = await self.db.get_active_quiz(guild_id)
        if not quiz:
            return await interaction.followup.send("No active quiz.", ephemeral=True)
        mc = Config.mc_name(self.config)
        results = await self.db.get_all_quiz_results(guild_id, quiz['id'])

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([
            'Username', 'User ID', 'Quiz Title',
            'Score %', 'Correct', 'Total', f'{mc} Earned',
            'Time (sec)', 'Time (readable)', 'Passed', 'Completed At'
        ])
        for r in results:
            member = self.guild.get_member(int(r['user_id']))
            name = member.display_name if member else r['user_id']
            mins, secs = r['elapsed_seconds'] // 60, r['elapsed_seconds'] % 60
            writer.writerow([
                name, r['user_id'], quiz['title'],
                f"{r['score_pct']:.1f}", r['correct_count'], r['total_questions'],
                r['mc_earned'], r['elapsed_seconds'], f"{mins}m {secs}s",
                "Yes" if r['score_pct'] >= 70 else "No",
                r['completed_at'][:19]
            ])
        output.seek(0)
        slug = quiz['article_slug']
        file = discord.File(
            io.BytesIO(output.getvalue().encode()),
            filename=f"quiz_{slug}.csv"
        )
        await interaction.followup.send(
            f"📊 Export: `quiz_{slug}.csv`",
            file=file, ephemeral=True
        )

    @discord.ui.button(label="💎 Quiz MC Values", style=discord.ButtonStyle.secondary, row=1)
    async def mc_values(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(QuizMCModal(self.db))

    @discord.ui.button(label="⚙️ Quiz Config Info", style=discord.ButtonStyle.secondary, row=1)
    async def config_info(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        mc = Config.mc_name(config)
        role_id = config.get('quiz_pass_role_id')
        role = self.guild.get_role(int(role_id)) if role_id else None
        embed = discord.Embed(title="⚙️ Quiz Configuration", color=mz('secondary'))
        embed.add_field(name="Pass Role", value=role.mention if role else "Not set — use `/setup_quiz_role`", inline=False)
        embed.add_field(
            name=f"{mc} Thresholds",
            value=(
                f"Min % for any {mc}: **{Config.g(config,'quiz_mc_min_pct',40):.0f}%**\n"
                f"40–69%: **{Config.g(config,'quiz_mc_40',1.0)} {mc}**\n"
                f"70–79%: **{Config.g(config,'quiz_mc_70',2.0)} {mc}**\n"
                f"80–89%: **{Config.g(config,'quiz_mc_80',3.0)} {mc}**\n"
                f"90–100%: **{Config.g(config,'quiz_mc_90',5.0)} {mc}**"
            ),
            inline=False
        )
        embed.add_field(name="Pass Threshold", value="70% (fixed)", inline=True)
        await interaction.followup.send(embed=embed, ephemeral=True)

    @discord.ui.button(label="🗑️ Revoke All Quiz Roles", style=discord.ButtonStyle.danger, row=2)
    async def revoke_all(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        config = await self.db.get_guild_config(str(interaction.guild_id)) or {}
        role_id = config.get('quiz_pass_role_id')
        if not role_id:
            return await interaction.followup.send(
                "No quiz pass role configured. Use `/setup_quiz_role` first.", ephemeral=True
            )
        role = self.guild.get_role(int(role_id))
        if not role:
            return await interaction.followup.send("Quiz pass role not found in server.", ephemeral=True)

        revoked = 0
        for member in list(role.members):
            try:
                await member.remove_roles(role, reason=f"Quiz role reset by {interaction.user.id}")
                revoked += 1
            except Exception:
                pass

        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Quiz Roles Revoked",
                description=f"Removed quiz pass role from **{revoked}** users.",
                color=mz('green')
            ), ephemeral=True
        )
        if config.get('log_channel_id'):
            ch = self.guild.get_channel(int(config['log_channel_id']))
            if ch:
                await ch.send(
                    f"🗑️ {interaction.user.mention} manually revoked quiz role from {revoked} users."
                )


# ── Cog ───────────────────────────────────────────────────────────────────────

class QuizCog(BotHelpers, commands.Cog, name="Quiz"):
    def __init__(self, bot):
        self.bot = bot

    @app_commands.command(
        name="setup_quiz_role",
        description="Set the quiz pass role — given to users who score 70%+ (admin only)"
    )
    @app_commands.describe(role="Role assigned to users who score 70%+")
    async def setup_quiz_role(self, interaction: discord.Interaction, role: discord.Role):
        await interaction.response.defer(ephemeral=True)
        config = await self.require_admin(interaction)
        if config is None:
            return
        await self.db.update_guild_config(str(interaction.guild_id), quiz_pass_role_id=str(role.id))
        await interaction.followup.send(
            embed=discord.Embed(
                title="✅ Quiz Pass Role Set",
                description=(
                    f"Role: {role.mention}\n\n"
                    f"Users scoring 70%+ will receive this role automatically.\n"
                    f"The role is removed when a new quiz is loaded or via **Admin Panel → Quiz → Revoke All**."
                ),
                color=mz('green')
            ), ephemeral=True
        )


async def setup(bot):
    await bot.add_cog(QuizCog(bot))
