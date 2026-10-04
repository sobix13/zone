# Root causes and corrections

## MC reactions in community task threads

The old reaction listener resolved its destination using `guild.get_channel(channel_id)`. Discord threads have a separate cache lookup. Consequently, a thread reaction returned no destination and the listener stopped before fetching the message or crediting its author. A slash command or snapshot worked in the same thread because it already held the interaction's channel object. The successful command did not prove that the reaction listener could resolve that thread.

V3 resolves destinations with `get_channel_or_thread`, the bot cache and a REST fallback. It checks that the returned destination belongs to the intended guild and that message history is readable. The raw reaction listener persists the event. A bounded worker rechecks admin eligibility, fetches the target message and commits the reward.

A reaction's financial identity is message ID, awarding admin ID and normalized emoji ID. Custom emoji names can change without changing identity. Unicode variation selectors do not create extra identities. Existing recorded awards are backfilled into this identity table during migration. Two authorized admins produce two awards. Repeated delivery or removing and re-adding the same admin reaction produces one award.

MC is credited to the message author. Bot messages and self-awards through reactions are excluded. Only configured MC emojis have an MC value. The raffle emoji takes its separate role-granting path; use a different emoji for raffle access and MC.

## Cooldown also restricting admins

The old task message handler checked the task's saved cooldown before exempting bot administrators. A configured bot-admin role can be a normal Discord role and does not automatically bypass Discord's own native thread slowmode.

V3 bypasses the application cooldown for the configured admin user, configured admin role and Discord administrators. Bots are ignored. Member acceptance reserves the cooldown and participation record in one transaction, so simultaneous messages cannot both consume the same available slot. New task threads have native slowmode set to zero; Melee Zone enforces the longer application cooldown. Run `/doctor repair:true` inside an existing bot-owned task thread to clear an old native slowmode value when Manage Threads is available.

Discord split the former slowmode permission into `BYPASS_SLOWMODE` in February 2026. Relying on unrelated permissions is therefore insufficient. This release avoids that dependency for its own task threads by using the application cooldown.

## What the 720-hour limit meant

720 hours was the bot's Snapshot form validation, not a blanket Discord history retention limit. Snapshot still retains that bounded award workflow. Role reports use paginated history and can request `days:0` for all accessible retained history, or a longer explicit window. Scans remain bounded and resumable.

The bot cannot reconstruct messages deleted before observation, channels it cannot view, private threads it cannot access, old member joins superseded by rejoining, or historical reaction timestamps. No user token or undocumented search endpoint is used. Excel makes these coverage limits visible.

## Additional integrity corrections

- The MC ledger entry and balance increment are committed together.
- Multi-recipient awards and Snapshot confirmation are all-or-nothing transactions.
- Score/showcase MC and post finalization now commit together. A restart cannot mark a post finalized before paying its reward.
- Quiz result, completed session and quiz MC now commit together. Concurrent completions cannot pay twice.
- Assignment creation enforces post slots and weekly primary capacity inside the transaction.
- Rescue handoff creates its replacement and retires its original together.
- Administrative views and modals recheck access when used.
- Health reports real database, gateway, extension, worker and event-loop state; it no longer returns unconditional OK.

## Primary documentation

- [Discord threads](https://docs.discord.com/developers/topics/threads)
- [Get channel messages](https://docs.discord.com/developers/resources/message#get-channel-messages)
- [Discord changelog](https://docs.discord.com/developers/change-log)
- [discord.py API](https://discordpy.readthedocs.io/en/stable/api.html)

Local regression tests reproduce the original thread-cache failure. Live guild permissions and gateway delivery still require installation acceptance checks.
