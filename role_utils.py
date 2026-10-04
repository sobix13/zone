import discord


def role_manage_error(guild: discord.Guild, role: discord.Role) -> str | None:
    """Return a user-facing reason when the bot cannot manage a role."""
    me = guild.me
    if me is None:
        return "I could not resolve my bot member in this server."
    if role.is_default():
        return "The @everyone role cannot be assigned."
    if role.managed:
        return "This role is managed by an integration and cannot be assigned manually."
    if not me.guild_permissions.manage_roles:
        return "The bot is missing the Manage Roles permission."
    if me.top_role <= role:
        return (
            f"Move the bot role above {role.mention} in Server Settings → Roles. "
            "Discord blocks bots from managing roles at or above their highest role."
        )
    return None


async def resolve_member(guild: discord.Guild, user_id: int) -> discord.Member | None:
    member = guild.get_member(user_id)
    if member is not None:
        return member
    try:
        return await guild.fetch_member(user_id)
    except (discord.NotFound, discord.Forbidden, discord.HTTPException):
        return None
