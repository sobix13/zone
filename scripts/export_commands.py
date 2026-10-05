#!/usr/bin/env python3
"""Generate the command reference from an offline extension load."""
import asyncio,inspect,os,sys,tempfile
from discord import app_commands
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from release_version import RELEASE_SERIES


async def main():
    with tempfile.TemporaryDirectory(prefix='mz-command-reference-') as temporary:
        os.environ['DATABASE_PATH']=str(Path(temporary)/'test.db')
        from bot import MeleeZoneBot
        async with MeleeZoneBot() as bot:
            await bot.setup_hook()
            roots=bot.tree.get_commands()
            slash=sum(not hasattr(c,'type') for c in roots)
            contexts=len(roots)-slash
            commands=[]
            for command in roots:
                commands.append(command)
                if isinstance(command,app_commands.Group):
                    commands.extend(command.walk_commands())
            result=['# Registered command reference','', f'Generated from the V{RELEASE_SERIES} offline command tree. All commands are server-only. Current saved configuration determines exact roles, amounts and timing.', '',f'{len(roots)} root application commands: {slash} slash roots and {contexts} message context actions. Groups and their executable subcommands are listed below.','']
            for command in sorted(commands,key=lambda c:getattr(c,'qualified_name',c.name).casefold()):
                context=hasattr(command,'type')
                group=isinstance(command,app_commands.Group)
                source=inspect.getsource(command.callback) if not group else ''
                admin=any(text in source for text in ['require_admin','authorized(','Administrator permission','self.is_admin('])
                access='Admin' if admin or context else 'Reviewer role' if command.name in ('review','my_reviews','review_skip','ready_for_more') else 'Member or panel-specific role'
                if command.name in ('backup','recovery_setup'):access='Recovery owner and admin'
                if command.name in ('admin_access','setup_start'):access='Primary administrator (server owner/original named admin/approved role or named people)'
                if command.name in ('config_requests','config_request'):access='Moderator (own requests); primary admin (all requests and approval)'
                if command.name=='task_cooldown':access='Moderator; immediate operation, no configuration approval'
                if getattr(command,'qualified_name','').startswith('support '):access='Admin' if admin else 'Selected volunteer moderator role'
                result += ['## '+(('Message action: '+command.name) if context else '/'+command.qualified_name),'',getattr(command,'description','Message context action'),'', '**Access:** '+access+'.','']
                if not context and not group and command.parameters:
                    result += ['| Option | Required | Default | Details |','|---|---|---|---|']
                    for param in command.parameters:
                        choices=', '.join(str(c.value) for c in param.choices)
                        bounds=''
                        if param.min_value is not None or param.max_value is not None:
                            bounds=f' Range: {param.min_value} to {param.max_value}.'
                        default='' if param.required else str(param.default)
                        details=param.description+(' Choices: '+choices if choices else '')+bounds
                        result += ['| '+ ' | '.join([param.name,'Yes' if param.required else 'No',default,details.replace('|','/')])+' |']
                    result += ['']
            output=Path(__file__).resolve().parents[1]/'docs'/'COMMANDS.md'
            output.write_text('\n'.join(result).replace('—','-')+'\n')
            print('Command reference generated:',len(bot.tree.get_commands()),'commands.')


if __name__=='__main__':
    asyncio.run(main())
