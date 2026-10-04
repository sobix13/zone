import os
from typing import Optional
from datetime import datetime, timedelta
import pytz
import re

TEHRAN = pytz.timezone('Asia/Tehran')
UTC = pytz.utc


def get_current_week_id() -> str:
    now = datetime.now(TEHRAN)
    return f"{now.year}-W{now.isocalendar()[1]:02d}"


def get_current_month_id() -> str:
    return datetime.now(UTC).strftime('%Y-%m')


def get_next_saturday_midnight() -> datetime:
    now = datetime.now(TEHRAN)
    days_until = (5 - now.weekday()) % 7
    if days_until == 0:
        days_until = 7
    target = now + timedelta(days=days_until)
    return target.replace(hour=0, minute=0, second=0, microsecond=0)


def get_next_utc_midnight() -> datetime:
    now = datetime.now(UTC)
    tomorrow = now + timedelta(days=1)
    return tomorrow.replace(hour=0, minute=0, second=0, microsecond=0)


def is_valid_content_url(url: str) -> bool:
    patterns = [r'^https?://(www\.)?(twitter|x)\.com/[A-Za-z0-9_]+/status/\d+']
    return any(re.match(p, url) for p in patterns)


def parse_x_post_url(url: str):
    """Return a stable status id and URL username. Query strings are ignored."""
    m = re.match(r'^https?://(?:www\.)?(?:twitter|x)\.com/([A-Za-z0-9_]+)/status/(\d+)', (url or '').strip(), re.I)
    if not m:
        return None
    return {'username': m.group(1).lower(), 'status_id': m.group(2),
            'normalized_url': f"https://x.com/i/status/{m.group(2)}"}


def format_timedelta(td: timedelta) -> str:
    total = int(td.total_seconds())
    if total < 0:
        return "Overdue"
    d, rem = divmod(total, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d > 0:
        return f"{d}d {h}h"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def btn_style(color_str: str):
    import discord
    mapping = {
        'blurple': discord.ButtonStyle.primary,
        'blue':    discord.ButtonStyle.primary,
        'green':   discord.ButtonStyle.success,
        'red':     discord.ButtonStyle.danger,
        'gray':    discord.ButtonStyle.secondary,
        'grey':    discord.ButtonStyle.secondary,
    }
    return mapping.get((color_str or 'gray').lower(), discord.ButtonStyle.secondary)


def mz(variant: str = 'primary'):
    """Melee Zone color palette."""
    import discord
    colors = {
        'primary':   discord.Color.from_rgb(220, 50, 50),
        'secondary': discord.Color.from_rgb(255, 120, 0),
        'gold':      discord.Color.from_rgb(255, 215, 0),
        'green':     discord.Color.from_rgb(0, 200, 100),
        'red':       discord.Color.from_rgb(220, 60, 60),
        'dark':      discord.Color.from_rgb(20, 20, 30),
        'purple':    discord.Color.from_rgb(130, 80, 220),
    }
    return colors.get(variant, colors['primary'])


# Alias so any cog can import either name
color = mz


class Config:
    DISCORD_TOKEN: Optional[str] = os.getenv('DISCORD_TOKEN')
    MAX_SUBMIT_PER_WEEK: int = 5
    MAX_REVIEW_PER_WEEK: int = 7
    SHOWCASE_THRESHOLD: float = 8.0
    SHOWCASE_REWARD: float = 3.0
    BASE_REVIEW_REWARD: float = 2.0
    COMMENT_BONUS: float = 1.0
    REMINDER_HOURS: int = 72
    REVIEW_WINDOW_DAYS: int = 5
    MIN_REVIEWS_PER_POST: int = 5

    @staticmethod
    def g(config: dict, key: str, default):
        if not config:
            return default
        v = config.get(key)
        return v if v is not None else default

    @staticmethod
    def txt(config: dict, key: str, default: str) -> str:
        return str(Config.g(config, key, default))

    # ── MC values — always from DB ──────────────────────────────────────────

    @staticmethod
    def calculate_mc_from_score(score: float, config: dict = None) -> float:
        c = config or {}
        if score >= 8.0:
            return float(Config.g(c, 'mc_score_high', 5.0))
        if score >= 6.0:
            return float(Config.g(c, 'mc_score_medium', 3.0))
        if score >= 4.0:
            return float(Config.g(c, 'mc_score_low', 1.0))
        return 0.0

    @staticmethod
    def get_submit_completion_reward(config: dict = None) -> float:
        return float(Config.g(config, 'mc_submit_completion', 2.0))

    @staticmethod
    def get_showcase_threshold(config: dict = None) -> float:
        return float(Config.g(config, 'showcase_threshold', Config.SHOWCASE_THRESHOLD))

    @staticmethod
    def get_showcase_reward(config: dict = None) -> float:
        return float(Config.g(config, 'mc_showcase_reward', Config.SHOWCASE_REWARD))

    @staticmethod
    def get_review_reward(config: dict = None) -> float:
        return float(Config.g(config, 'mc_review_reward', Config.BASE_REVIEW_REWARD))

    @staticmethod
    def get_comment_bonus(config: dict = None) -> float:
        return float(Config.g(config, 'mc_comment_bonus', Config.COMMENT_BONUS))

    @staticmethod
    def get_review_window(config: dict = None) -> int:
        return int(Config.g(config, 'total_review_days', 7))

    @staticmethod
    def get_reminder_hours(config: dict = None) -> int:
        return int(Config.g(config, 'reminder_hours', Config.REMINDER_HOURS))

    @staticmethod
    def get_min_reviews(config: dict = None) -> int:
        return int(Config.g(config, 'min_reviews', Config.MIN_REVIEWS_PER_POST))

    @staticmethod
    def get_max_submits(config: dict = None) -> int:
        return int(Config.g(config, 'max_submits_per_week', Config.MAX_SUBMIT_PER_WEEK))

    @staticmethod
    def get_max_reviews(config: dict = None) -> int:
        return int(Config.g(config, 'max_reviews_per_week', Config.MAX_REVIEW_PER_WEEK))

    # ── Text helpers — all from DB ──────────────────────────────────────────

    @staticmethod
    def mc_name(config: dict) -> str:
        return Config.txt(config, 'txt_mc_name', 'MC')

    @staticmethod
    def bot_name(config: dict) -> str:
        return Config.txt(config, 'txt_bot_name', 'Melee Zone')

    @staticmethod
    def pro_role_name(config: dict) -> str:
        return Config.txt(config, 'txt_pro_role', 'Reviewer')

    @staticmethod
    def basic_role_name(config: dict) -> str:
        return Config.txt(config, 'txt_basic_role', 'Basic')

    @staticmethod
    def welcome_msg(config: dict) -> str:
        return Config.txt(config, 'txt_welcome', 'Welcome to Melee Zone! You are now on record.')

    @staticmethod
    def submit_success_msg(config: dict) -> str:
        return Config.txt(config, 'txt_submit_success', 'Your post has been recorded!')

    @staticmethod
    def review_received_msg(config: dict) -> str:
        return Config.txt(config, 'txt_review_received', 'Thank you for your review!')

    @staticmethod
    def showcase_msg(config: dict) -> str:
        return Config.txt(config, 'txt_showcase', 'Outstanding content featured!')

    @staticmethod
    def reminder_msg(config: dict) -> str:
        return Config.txt(config, 'txt_reminder', 'You have a pending review. Please complete it.')

    @staticmethod
    def panel_title(config: dict) -> str:
        return Config.txt(config, 'txt_panel_title', 'Melee Zone')

    @staticmethod
    def panel_desc(config: dict) -> str:
        return Config.txt(config, 'txt_panel_desc', 'Use the buttons below. All responses are private.')

    @staticmethod
    def dashboard_btn(config: dict) -> str:
        return Config.txt(config, 'txt_dashboard_btn', 'Dashboard')

    @staticmethod
    def submission_btn(config: dict) -> str:
        return Config.txt(config, 'txt_submission_btn', 'Submission')

    @staticmethod
    def reviews_btn(config: dict) -> str:
        return Config.txt(config, 'txt_reviews_btn', 'Reviews')
