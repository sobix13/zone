import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock,MagicMock
import discord
import pytest
import pytest_asyncio

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from database import Database

GID=100000000000000001
OWNER=100000000000000002
ADMIN2=100000000000000003
AUTHOR=100000000000000004
THREAD=100000000000000005
PARENT=100000000000000006


@pytest_asyncio.fixture
async def db(tmp_path):
    value=Database(str(tmp_path/'test.db'))
    await value.init()
    await value.create_guild_config(str(GID))
    await value.update_guild_config(str(GID),admin_user_id=str(OWNER),reaction_emoji_1='✅',reaction_mc_1=1,
        assignment_channel_id=str(PARENT),is_configured=1)
    yield value
    await value.close()


def member(guild,uid,*,admin=False,roles=None,bot=False):
    return SimpleNamespace(id=uid,name=f'user-{uid}',display_name=f'Display {uid}',guild=guild,bot=bot,
        guild_permissions=discord.Permissions(administrator=admin),roles=roles or [],mention=f'<@{uid}>')


@pytest.fixture
def guild():
    value=MagicMock(spec=discord.Guild)
    value.id=GID;value.name='Test guild';value.owner_id=OWNER
    value.members=[];value.text_channels=[];value.forums=[];value.threads=[]
    value.me=member(value,999,bot=True)
    roster={}
    for uid in [OWNER,ADMIN2,AUTHOR]:
        roster[uid]=member(value,uid,admin=uid in [OWNER,ADMIN2])
    value.get_member.side_effect=lambda uid:roster.get(uid)
    value.fetch_member=AsyncMock(side_effect=lambda uid:roster.get(uid))
    value.get_role.side_effect=lambda rid:None
    value.get_channel.side_effect=lambda cid:None
    value.get_channel_or_thread.side_effect=lambda cid:next((c for c in [*value.text_channels,*value.threads] if c.id==cid),None)
    value.active_threads=AsyncMock(side_effect=lambda:list(value.threads))
    value.roster=roster
    return value


@pytest.fixture
def thread(guild):
    channel=MagicMock(spec=discord.Thread)
    channel.id=THREAD;channel.parent_id=PARENT;channel.name='Trade talk';channel.guild=guild
    channel.mention=f'<#{THREAD}>';channel.slowmode_delay=0
    channel.permissions_for.return_value=discord.Permissions.all()
    channel.fetch_message=AsyncMock()
    channel.send=AsyncMock()
    channel.edit=AsyncMock()
    guild.threads=[channel]
    return channel


@pytest.fixture
def fakebot(db,guild):
    value=MagicMock()
    value.db=db;value.user=SimpleNamespace(id=999)
    value.get_guild.side_effect=lambda gid:guild if gid==guild.id else None
    value.get_channel.side_effect=lambda cid:guild.get_channel_or_thread(cid)
    value.fetch_channel=AsyncMock(side_effect=lambda cid:guild.get_channel_or_thread(cid))
    value.wait_until_ready=AsyncMock()
    value.is_ready.return_value=True;value.is_closed.return_value=False
    return value


def interaction(bot,guild,channel,user_id=OWNER,ident=987654321098765432):
    value=SimpleNamespace(id=ident,client=bot,guild=guild,guild_id=guild.id,channel=channel,
        channel_id=channel.id,user=guild.get_member(user_id),command=None)
    response=SimpleNamespace(send_message=AsyncMock(),send_modal=AsyncMock(),edit_message=AsyncMock(),is_done=lambda:False)
    async def defer(**kwargs):
        response.is_done=lambda:True
    response.defer=AsyncMock(side_effect=defer)
    value.response=response;value.followup=SimpleNamespace(send=AsyncMock());value.edit_original_response=AsyncMock()
    return value
