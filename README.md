# Melee Zone V3.2

Melee Zone runs community post reviews, MC rewards, quizzes, raffle access and community task threads on Discord. V3 adds thread-safe MC reactions, awards for multiple recipients, selected-role activity reports, reviewer onboarding, real health checks and an independent recovery process.

Version: **3.2.0**. Python **3.12** is validated; Python 3.11 or later is required. Persistent state remains in SQLite. No paid X API or second Discord bot is required. This release includes all V3.1 volunteer oversight, private team feedback with 1–10 scores, 14-day XLSX/CSV analysis and editable setup/MC calculator features, plus primary-admin approval for sensitive configuration changes.

## Upgrade the existing bot

Extract the update into a separate directory. Keep the currently installed `.env` and database in their existing application folder.

```bash
MZ_STAGE=$(mktemp -d /tmp/melee-v32-XXXXXX)
tar -xzf Melee-Zone-V3.2-update.tar.gz -C "$MZ_STAGE"
sudo bash "$MZ_STAGE/melee-zone-v3.2/install.sh" --app-dir /root/Melee-Zone
```

Change `--app-dir` if your deployment uses another folder. Use `--service your-name.service` for a custom main service. The installer preserves the existing systemd service user. `--owner-id DISCORD_USER_ID` can explicitly pin the recovery owner. To choose an installed interpreter, set `MZ_INSTALL_PYTHON=/usr/bin/python3.12` before invoking the installer.

The installer verifies release hashes, builds an isolated Python environment, backs up SQLite consistently, tests migration on a copy and loads every extension before stopping the main service. It then installs the release, verifies the actual migration and waits for Discord readiness. Failure restores the previous code and service units. It preserves current MC after an attempted service start. The original `.env` is never replaced.

```bash
bash "$MZ_STAGE/melee-zone-v3.2/install.sh" --app-dir /root/Melee-Zone --dry-run
```

Dry run checks release integrity and the target path. It does not install dependencies, test migration or contact Discord.

After upgrade:

1. Open `/setup_view` and verify existing roles, channels and reward values.
2. Run `/doctor` in the main bot channel and in a community task thread.
3. In each old task with native slowmode, run `/doctor repair:true`.
4. Run `/recovery_setup channel:#private-admin-control` as the recovery owner.
5. Run the [live acceptance procedure](docs/LIVE_ACCEPTANCE.md) using test members before regular use.

The delivered release has passed local simulations and private-backup migration checks. It has not been connected to your live Discord guild from this workspace.

## Daily shortcuts

```text
/give_mc amount:2 reason:Helpful participation users:@Alice @Bob mc_type:regular
/role_report role:@Meleeionaires days:90 max_messages:20000
/role_report_status job_id:THE_RETURNED_ID
/role_report_resume job_id:THE_RETURNED_ID extra_messages:20000
/mc_audit user:@Alice
/mc_reconcile hours:24
/health
/doctor repair:true
/onboard
```

Use Discord's argument picker. `user` remains available for the previous single-recipient `/give_mc` workflow. `users` accepts mentions or IDs, deduplicates them and permits up to 25 recipients. Each recipient receives the entered amount. A missing, invalid or bot recipient prevents the entire batch.

Message context menu: **Apps > Award 1 MC** or **Award MC**. The quick 1-MC action is once per admin per message. A new custom award submission is a new explicit award.

The admin panel includes **Role report** and **Health and recovery**. The user panel includes **Guide and next steps**.

## Excel role reports

Select one specific role. The bot fetches a fresh full roster, then scans readable text channels, active threads and accessible archived threads once, filtering messages for those members. It does not repeat the entire guild scan separately for every person.

The workbook has four sheets:

- **Members:** Discord ID, username, display name, saved X handle, current server join date, last observed activity/message, window and known message counts, three MC balances and formula total.
- **Recent messages:** five indexed, retained messages per person, with dates, excerpts and source URLs.
- **Coverage:** every discovered destination, status, examined message count and reason for skipped or incomplete history.
- **Recent activity:** five observed reactions or bot actions per person, with dates and channel/source URLs.

Default scan: 30 days, 20,000 messages, one serial worker and a 20-minute processing budget. `days:0` requests all accessible history. Resume extends the message allowance and retains each channel cursor. Known counts mean indexed messages; they are not an unconditional historical total. See [the report definitions](docs/MODERATOR_MANUAL.md#role-analysis-and-excel).

## Repository and local development

The repository ZIP includes Python source, requirements, dev requirements, tests, GitHub Actions, the XLSX template, setup examples, installer, rollback script and full documentation. It contains no production token, database, member export or live MC data.

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q .
```

The accepted moderator handbook is supplied unchanged as self-contained searchable HTML and Word under `docs/`. It contains only Discord usage and member support, not installation or repository instructions. `scripts/build_manual.py` generates a separate internal operations reference; it must not replace the approved handbook. Runtime XLSX templates are included in `assets/` and need no Excel dependency on the server.

Normal CI skips the private-backup test unless `LEGACY_TEST_DB` is provided. Tests use real SQLite and synthetic Discord interfaces; they do not log in to Discord or issue real awards.

## Review support and calculator

Open **Review support** in `/admin_panel`, select reviewer and volunteer-moderator roles, optionally select a content-member role, then save. Each moderator opts in and chooses their own capacity. Default: ten reviewers/week, zero content members. Fifty reviewers with five available moderators offering ten slots each are distributed evenly; skips redistribute only within spare capacity. Private scores/feedback never automatically change MC or roles.

```text
/support panel
/support availability reviewers:10 members:0
/support status
/review_analytics days:14
/review_analytics_status job_id:REPORT_ID
/review_calculator days:14 max_reviews:7 min_reviews:3
/team_messages
```

The bot privately prepares a report every 14 days after activation; admins request the download. Eight XLSX sheets include participation, MC balances, detailed source records, moderator evidence and a formula-driven **Calculator**. Amber inputs are what-if proposals, not an automatic setup change. CSV combines person-level metrics. Missing evidence is blank, not zero. **Team messages** in the member/Reviews panel supports private replies, DM opt-out and independent second looks.

Read the [complete support/calculation guide, including Persian setup instructions](docs/REVIEW_SUPPORT.md) for rubric, limits, fairness and metric definitions. The [mobile upgrade guide](docs/UPGRADE_V3_2_FA.md) explains backup-first installation in Termius. Runtime exports add no Python requirements; both authored XLSX templates are shipped in `assets/`.

## Moderator operations and primary-admin approval

`/admin_access` (or Setup → Access management) lets the existing named primary admin or server owner select an operational moderator role, select a primary-admin role and add/remove named primary admins. The original primary-admin ID and server ownership remain recovery anchors. A native Discord Administrator keeps operational access but is **not** automatically a primary approver.

Moderators keep every daily tool: free-form community-task creation and closure, direct task cooldown changes, automatic moderator cooldown bypass, member cooldown resets, MC awards/reactions/snapshots, review allocation and report downloads. Use Community Tasks → Change cooldown, or `/task_cooldown cooldown:30m task_id:ID`. These actions do not wait for configuration approval.

Sensitive global rules, reward rates, role/channel mappings, automated texts, support settings and configuration resets submit a durable request instead. Nothing changes until approval. Primary admins open Admin Panel → Change requests or `/config_requests`, inspect the author and complete before/after JSON, then approve/reject with a note. Moderator requests/history are visible only to their author and primary admins. Direct changes by primary admins are audited as applied. Expired/conflicting requests cannot silently overwrite current values. Access grants themselves are primary-admin-only, never self-promotion proposals. [Full access policy](docs/ADMIN_ACCESS.md).

For a new deployment, copy `.env.example` to `.env`, supply the bot token, install requirements in a venv and run `bot.py` once to initialize SQLite. Enable Server Members and Message Content intents in the Developer Portal. Stop that initial process, then use a separately extracted release with `install.sh` to install the two services. Configure roles/channels through `/setup_start`, `/setup_roles` and `/setup_channels`. Existing deployments use their preserved configuration.

## Documentation

- [Searchable moderator handbook](docs/Melee-Zone-Moderator-Manual.html)
- [Moderator handbook in Word](docs/Melee-Zone-Moderator-Handbook.docx)
- [Reviewer and member guide](docs/USER_GUIDE.md)
- [Weekly support, analysis and calculator](docs/REVIEW_SUPPORT.md)
- [V3.2 upgrade in Termius (فارسی)](docs/UPGRADE_V3_2_FA.md)
- [Access and configuration approvals](docs/ADMIN_ACCESS.md)
- [All registered commands](docs/COMMANDS.md)
- [Operations, recovery and rollback](docs/OPERATIONS.md)
- [Root causes](docs/ROOT_CAUSES.md)
- [Architecture and state](docs/ARCHITECTURE.md)
- [Live acceptance checks](docs/LIVE_ACCEPTANCE.md)
- [Rollout and roadmap](docs/ROADMAP.md)
- [Release notes](docs/RELEASE_NOTES.md)
- [Validation evidence](docs/TEST_REPORT.md)

Historical notes and earlier upgrade reports remain available as history. The current entry points are this README, the access policy and the V3.2 upgrade guide.
