# Melee Zone V3 validation report

Version 3.0.0 | Local validation environment: Python 3.12, Linux, real SQLite, discord.py 2.7.1

## Result

**83 tests passed, 0 failed, 0 skipped** with the private recovered database supplied for migration verification. The run took approximately 1.2 seconds after dependencies were installed. Test cases and an XML results file are included. Standard public CI runs the synthetic tests and skips the private-backup case when no private fixture is supplied.

Offline boot loaded **18 extensions**, registered **48 application commands** and registered **3 persistent views**. Command names/types and persistent component IDs were checked for collisions. Python compilation, shell syntax and installed-dependency consistency checks passed.

## Simulation coverage

| Area | Evidence |
|---|---|
| Thread reactions | Cached and uncached thread resolution, REST fallback, readable history, denied permissions, missing member cache |
| Award identity | Fifty concurrent duplicate events pay once; independent admins pay independently; emoji renaming/variation normalization |
| Multi-recipient MC | Full validation before credit, idempotent operation keys, invalid-recipient rejection and injected transaction rollback |
| Cooldowns | Thirty simultaneous member submissions reserve one slot; authorized admins remain exempt |
| Reports | History older than 720 hours, window counts versus known counts, budget pause/resume without duplicate index rows, permissions/HTTP faults, fresh full roster |
| Report lifecycle | Restart requeue, guild isolation, queue bound and cancellation guard |
| XLSX | Exact text IDs, typed UTC dates, literal user strings, cached SUM totals, filters/frozen headings, native Discord hyperlinks, four empty/populated sheets |
| Activity privacy | Observed deletion clears excerpts; deletion before indexing prevents later text retention |
| Financial finalization | Post score/showcase finalization and quiz completion roll back together with MC on injected failures; concurrent completions pay once |
| Assignment capacity | Concurrent post/weekly limits, transactional rescue handoff and primary-work eligibility |
| Outbox/read consistency | Failed log delivery preserves MC, exhausted retries can requeue, readers do not observe an uncommitted balance or notice |
| Recovery | Real localhost health server, owner/secret rejection, restart budgets, corrupt DB refusal, independent REST pulse with main bot absent, fatal configuration protection |
| Installer | Tamper/path rejection, no-write dry run, migration failure before service stop, partial-start rollback preserving newly committed MC |
| Compatibility | Existing duplicate X status handling and reward tier boundaries remain tested |

The simulated Discord surfaces use real discord.py interfaces/types with controlled async responses. SQLite transactions, backups, HTTP endpoint behavior and exported XML are exercised directly. This is not a replacement for a live gateway/permission test.

## Private recovered snapshot

A consistent SQLite backup included committed WAL state. Before and after migration:

| Table or total | Preserved |
|---|---:|
| User rows | 117 |
| Posts | 23 |
| MC transactions | 290 |
| Guild configurations | 2 |
| Recorded reaction credits | 190 |
| Quizzes | 1 |
| Quiz sessions | 1 |
| Snapshot awards | 8 |
| Total regular + golden + assignment MC | 681.0 |

Existing columns/rows were compared by deterministic fingerprints. Only the permitted normalized X status ID/URL backfill is excluded from those fingerprints. Repeating migration passed, and SQLite quick_check returned `ok`. Reviews and community-task records were empty in this recovered snapshot, so their behavior uses populated synthetic scenarios. These are backup figures, not a claim about the current live guild.

## Artifact checks

All four workbook sheets were rendered from a populated synthetic export and visually checked. Native SpreadsheetML string/date/formula types, exact ID content and hyperlink relationships were independently verified. The rendering importer can infer numeric-looking text; XML types and exact text are the authority for ID precision in the supplied XLSX.

The standalone HTML reference has 92 valid internal navigation links and 31 tables, no duplicate IDs and no external stylesheet/script dependency. Its content is generated from the repository's manuals and command reference. A browser executable was unavailable for an automated HTML screenshot, so its structural checks are recorded separately from workbook visual verification.

Release manifests contain SHA-256 hashes for distributed files. Both archives are checked for integrity, matching manifest contents and absence of production token/config/database files. The installer verifies those hashes again before mutation.

## Reproduce

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
.venv/bin/python -m compileall -q bot.py cogs scripts tests
bash -n install.sh watchdog.sh
.venv/bin/python -m pip check
```

To include the private migration case, point `LEGACY_TEST_DB` at a private consistent database copy. Never commit that fixture. `scripts/preflight.py --database COPY.db` separately boots all extensions, checks component/command uniqueness and verifies repeated migration. It is a write operation on the supplied copy, not on a production database during an unapproved live test.

## Still requiring the deployed environment

No live Discord login, production message/reaction, real member award, real role change, server systemd action or server restart was executed from this workspace. The installer waits for real readiness, and LIVE_ACCEPTANCE.md provides controlled guild checks. Real guild permissions, Developer Portal intents, traffic capacity, owner recovery permissions and hosting outages cannot be certified by these local tests.
