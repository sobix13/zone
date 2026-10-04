#!/usr/bin/env python3
"""Generate the command reference from an offline extension load."""
import asyncio,inspect,os,sys,tempfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))


async def main():
    with tempfile.TemporaryDirectory(prefix='mz-command-reference-') as temporary:
        os.environ['DATABASE_PATH']=str(Path(temporary)/'test.db')
        from bot import MeleeZoneBot
        async with MeleeZoneBot() as bot:
            await bot.setup_hook()
            result=['# Registered command reference','', 'Generated from the V3 offline command tree. All commands are server-only. Current saved configuration determines exact roles, amounts and timing.', '',f'{len(bot.tree.get_commands())} application commands: 46 slash commands and 2 message context actions.','']
            for command in sorted(bot.tree.get_commands(),key=lambda c:c.name.casefold()):
                context=hasattr(command,'type')
                source=inspect.getsource(command.callback)
                admin=any(text in source for text in ['require_admin','authorized(','Administrator permission','self.is_admin('])
                access='Admin' if admin or context else 'Reviewer role' if command.name in ('review','my_reviews','review_skip','ready_for_more') else 'Member or panel-specific role'
                if command.name in ('backup','recovery_setup'):access='Recovery owner and admin'
                result += ['## '+(('Message action: '+command.name) if context else '/'+command.name),'',getattr(command,'description','Message context action'),'', '**Access:** '+access+'.','']
                if not context and command.parameters:
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
