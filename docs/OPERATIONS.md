# Melee Zone operations and recovery

## Processes and ownership

The installer manages two systemd units:

- `melee-zone.service`: gateway connection, commands, MC, task rules, role scans and localhost health.
- `melee-zone-recovery.service`: independent health watcher, owner pulse polling, restart control and daily SQLite backup.

Custom main-service names produce the corresponding `NAME-recovery.service`. Both units use the preserved deployment user and an isolated release Python environment. They are separate processes. The recovery process imports neither `bot.py` nor any cog, so a main-bot import/cog failure does not require the main process to execute the rescue.

The units have bounded failure restarts, private temporary directories, restrictive file creation, a 128-task process limit and memory pressure/maximum settings. MemoryHigh is 384 MiB and MemoryMax is 768 MiB per unit. These are initial ceilings, not a measured production capacity guarantee. Observe the real guild before changing them.

The installer stops an old shell `watchdog.sh` running from this exact application directory. The replacement watchdog entrypoint delegates to the new daemon; its file lock permits one watcher. Remove obsolete third-party watchdog services or cron rules if they invoke a different script. Do not run competing restart loops.

## Health definitions

Both HTTP services bind only to `127.0.0.1`.

| Endpoint | Port | Meaning |
|---|---:|---|
| Main `/health` | 3020 | Database query, event-loop responsiveness, disk headroom, required extensions and worker health |
| Main `/ready` | 3020 | All health conditions and a ready Discord gateway |
| Recovery `/health` | 3021 | Independent process responds; includes its latest recovery result |
| Recovery `POST /recover` | 3021 | Secret-authenticated, owner-identified, bounded restart request |

Ports are configurable with `HEALTH_PORT` and `RECOVERY_PORT`. A disconnected gateway is visible immediately in readiness. Short connection loss uses discord.py reconnection. The independent watcher considers a disconnect lasting at least five minutes, or three failed health polls after a two-minute startup allowance, before automatic recovery.

The main process writes a private atomic heartbeat every ten seconds. Loop delay over ten seconds or an old monitor tick is unhealthy. SQLite gets a three-second check timeout. Stopped known background loops can restart up to three times per hour each. A continuously failing loop remains visible as unhealthy instead of restarting indefinitely.

Invalid token and missing privileged intents are marked fatal configuration errors. Automatic recovery does not repeatedly restart such failures. The owner must correct the configuration. Missing channel permissions require a Discord permission fix; the bot cannot grant itself permission.

## First recovery setup

1. Confirm the independent recovery unit is running.
2. Choose a private admin text channel where `@everyone` cannot view it.
3. Allow the bot View Channel, Send Messages, Read Message History, Add Reactions and Manage Messages in that channel.
4. Run `/recovery_setup channel:#private-admin-control` as the configured recovery owner.
5. Keep the returned message link available. The control is a saved message with a reset reaction.

The recovery owner can be pinned with `--owner-id` during installation or `RESCUE_OWNER_ID` in the deployment environment. Otherwise the configured bot admin user is used until setup pins the owner; if no configured admin user exists, the guild owner is the fallback. Only that ID's pulse is accepted. Multiple guild administrators do not automatically obtain this authority. This deployment uses one saved recovery control/owner; setting it up again replaces that control configuration.

## Owner recovery when the main bot is stopped

Click the reset reaction on the saved control message once. The separate daemon polls Discord REST every 15 seconds with the existing bot token, removes the owner's reaction to acknowledge the pulse, performs a read-only SQLite integrity check and requests a fixed systemd restart. It posts the accepted/failure result in the control channel when Discord is reachable.

When the main process is alive, the **Recover main bot** button under `/health` calls the same local recovery service. Its request is acknowledged before the main process is stopped. Non-owners are rejected. There is no arbitrary shell command field.

The recovery daemon permits at most three attempts in 15 minutes, with at least two minutes between attempts. The budget is saved across daemon restarts. A second concurrent request is rejected. Discord 429 responses defer pulse polling using `retry_after`.

The pulse requires the host, recovery daemon, valid token, control message and Discord REST API to remain available. It cannot work through a powered-off host, total network failure, removed control message or revoked token. Server-console access is the independent fallback for those conditions.

## Server-console fallback

Use an authorized SSH/server console. Commands below assume the default service names.

```bash
sudo systemctl status melee-zone.service melee-zone-recovery.service --no-pager
sudo journalctl -u melee-zone.service -n 100 --no-pager
sudo journalctl -u melee-zone-recovery.service -n 100 --no-pager
curl --fail --max-time 5 http://127.0.0.1:3020/ready
curl --fail --max-time 5 http://127.0.0.1:3021/health
```

For a deliberate owner restart after inspecting the cause:

```bash
sudo systemctl reset-failed melee-zone.service
sudo systemctl restart melee-zone.service
```

For the independent route without Discord UI, use `scripts/control.py recover` from the application environment. It reads the local private secret and configured owner and calls the recovery endpoint without exposing the secret in output. `scripts/control.py status` prints both endpoints.

```bash
cd /root/Melee-Zone
/path/to/the-installed-release/venv/bin/python scripts/control.py status
/path/to/the-installed-release/venv/bin/python scripts/control.py recover
```

Find the installed interpreter in `systemctl show melee-zone.service -p ExecStart`. Do not source `.env` as a shell script or paste its contents into a ticket.

## Safe repair policy

`/doctor repair:true` retries exhausted reaction/notification jobs, starts stopped supported loops within their budget and clears native slowmode in the current bot-owned task thread when authorized and permitted. It does not reset balances, delete queues, change saved application cooldowns or overwrite role settings.

Reaction retries revalidate the admin, destination and current configured emoji. Permission/REST errors stay pending with exponential backoff; after eight failed attempts they are marked failed for manual repair. Non-eligible targets are completed without an award. Notification retries never rerun an MC transaction. Credit-log delivery is at least once: if a process dies after Discord accepts the log message but before the outbox acknowledgement, a duplicate log message is possible. Financial reward identities still prevent duplicate credit.

Long role scans use channel checkpoints and bounded pages. A running report interrupted by shutdown requeues at startup. A deliberate pause retains its cursor until resumed. Financial and report transactions are short; Discord REST calls do not run inside the MC write lock.

## Backup, upgrade and rollback

The recovery daemon creates one consistent SQLite backup per day, including committed WAL state, and keeps seven daily files. A healthy initialized database and a functioning recovery service are required. `/backup` creates an additional owner-only local backup while the main bot is running. The command reports the filename; it does not publish the database into Discord.

Before an update, the installer records:

- `before.db`: consistent backup refreshed after the services stop.
- `migration-test.db`: independent migration check copy.
- `previous-code.tar.gz`: private previous application archive.
- Original systemd unit files, when present.
- `rollback.json`: application/service/database locations for code rollback.

Upgrade backups are under `APP/backups/upgrade-TIMESTAMP`. They are private and can contain the old `.env` inside the previous-code archive. Never attach them to a public issue or commit them. The distributed release contains no production configuration or member database.

To restore previous code while preserving current MC and `.env`:

```bash
sudo python3 /root/Melee-Zone/scripts/rollback.py /root/Melee-Zone/backups/upgrade-TIMESTAMP
```

The additive V3 tables can remain in the database used by V2. Code rollback restores the previous unit and does not rewind legitimate MC awarded after the update. Automatic install rollback also preserves the current database after any attempted service start. A failure before any service start can restore the final pre-upgrade DB because no new gateway awards could have been processed.

Database restoration is a different operation. Stop both services, preserve the damaged/current files, choose a verified backup and use SQLite's backup API to restore consistently. Remove stale WAL/SHM only while all connections are closed and after saving evidence. A DB restore rewinds data after that backup; require a specific owner decision and reconcile subsequent awards. Recovery does not automatically erase or replace a corrupt database.

The installer restores main/recovery unit files it manages. Custom systemd drop-ins and unrelated watchers are not automatically rewritten. Inspect them if they override paths, ports, users, environment or restart policy. An optional non-root recovery sudo rule permits only reset-failed/restart of the selected main unit.

## Operational fault table

| Fault | Automated behavior | Owner action |
|---|---|---|
| Short gateway/network loss | Gateway reconnect, durable queues preserved | Observe readiness; avoid repeated resets |
| Stopped supported worker | Up to three loop starts per hour | Inspect traceback if it stops again |
| Main process dead/stalled | Bounded independent restart | Use pulse or console and inspect logs |
| Discord REST rate limit | Library handling; pulse honors retry-after | Wait; reduce repeated manual scans |
| Invalid token/intents | Fatal marker, no automatic restart storm | Correct token/Developer Portal settings |
| SQLite corruption | Diagnostics reject recovery restart | Preserve evidence and restore verified DB |
| Disk nearly full | Unhealthy below 100 MiB | Free safe logs/old exports and inspect backups |
| Missing history permission | Reaction retries/report coverage | Fix overwrites and run doctor/new report |
| Missing role hierarchy | Role action error | Move bot role above managed role |
| Whole host unreachable | No local service can execute | Hosting console or provider recovery |

## Retention and capacity

Operation audit keeps roughly the newest 10,000 rows. Completed reaction inbox rows age out after seven days; permanent award keys remain. Completed notification rows age out after 30 days. Recent non-message activity is limited to 50 events per tracked member, with five exported. Message IDs/timestamps/excerpts remain indexed until the owner implements a retention policy; observed deletion clears message excerpts.

Report workbooks and manual/upgrade backups are not automatically removed by the seven-day daily-backup policy. The owner should periodically archive or remove old exports and upgrade bundles after verification. Track runtime disk use and queue state. This release serializes heavy history scans and bounds financial fetch batches, but it has not been benchmarked against your real guild's peak traffic.
