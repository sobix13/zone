# Melee Zone V3

Melee Zone runs community post reviews, MC rewards, quizzes, raffle access and community task threads on Discord. V3 adds thread-safe MC reactions, awards for multiple recipients, selected-role activity reports, reviewer onboarding, real health checks and an independent recovery process.

Version: **3.0.0**. Python **3.12** is validated; Python 3.11 or later is required. Persistent state remains in SQLite. No paid X API or second Discord bot is required.

## Upgrade the existing bot

Extract the update into a separate directory. Keep the currently installed `.env` and database in their existing application folder.

```bash
tar -xzf Melee-Zone-V3-update.tar.gz -C /tmp
sudo bash /tmp/melee-zone-v3/install.sh --app-dir /root/Melee-Zone
```

Change `--app-dir` if your deployment uses another folder. Use `--service your-name.service` for a custom main service. The installer preserves the existing systemd service user. `--owner-id DISCORD_USER_ID` can explicitly pin the recovery owner. To choose an installed interpreter, set `MZ_INSTALL_PYTHON=/usr/bin/python3.12` before invoking the installer.

The installer verifies release hashes, builds an isolated Python environment, backs up SQLite consistently, tests migration on a copy and loads every extension before stopping the main service. It then installs the release, verifies the actual migration and waits for Discord readiness. Failure restores the previous code and service units. It preserves current MC after an attempted service start. The original `.env` is never replaced.

```bash
bash /tmp/melee-zone-v3/install.sh --app-dir /root/Melee-Zone --dry-run
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

To rebuild the standalone manual, install `requirements-docs.txt` and run `python scripts/build_manual.py`. The runtime XLSX template is included in `assets/` and needs no Excel dependency on the server.

Normal CI skips the private-backup test unless `LEGACY_TEST_DB` is provided. Tests use real SQLite and synthetic Discord interfaces; they do not log in to Discord or issue real awards.

For a new deployment, copy `.env.example` to `.env`, supply the bot token, install requirements in a venv and run `bot.py` once to initialize SQLite. Enable Server Members and Message Content intents in the Developer Portal. Stop that initial process, then use a separately extracted release with `install.sh` to install the two services. Configure roles/channels through `/setup_start`, `/setup_roles` and `/setup_channels`. Existing deployments use their preserved configuration.

## Documentation

- [Moderator manual and FAQ](docs/MODERATOR_MANUAL.md)
- [Reviewer and member guide](docs/USER_GUIDE.md)
- [All registered commands](docs/COMMANDS.md)
- [Operations, recovery and rollback](docs/OPERATIONS.md)
- [Root causes](docs/ROOT_CAUSES.md)
- [Architecture and state](docs/ARCHITECTURE.md)
- [Live acceptance checks](docs/LIVE_ACCEPTANCE.md)
- [Rollout and roadmap](docs/ROADMAP.md)
- [Release notes](docs/RELEASE_NOTES.md)
- [Validation evidence](docs/TEST_REPORT.md)

Historical V2 notes are in `docs/archive/`; this README and V3 manuals describe the current release.
