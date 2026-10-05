# Melee Zone V3.1 validation report

Version 3.1.0 | Local validation environment: Python 3.12, Linux, real SQLite, discord.py 2.7.1

## Result

**136 tests passed, 0 failed, 0 skipped** with the private recovered database supplied for migration verification. The recorded run took approximately 2.4 seconds after dependencies were installed. Test cases and an XML results file are included. Standard public CI runs 135 synthetic tests and skips the private-backup case when no private fixture is supplied.

Offline boot loaded **19 extensions**, registered **53 root application commands** (51 slash roots, including the support group; 2 message actions) and registered **3 persistent views**. The support group contains five executable subcommands. Command names/types and persistent component IDs were checked for collisions. Python compilation, shell syntax and installed-dependency consistency checks passed.

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
| Weekly support | Fifty reviewers/five moderators/ten each; saved allocations and samples; self-rating exclusion; rotation; spare/full-capacity skip; pause; removed roles; 100-new-task batches |
| Support ratings | Integer range including bool/NaN rejection; no-sample blank versus limited score; sample ownership; deadline/current-owner checks; concurrent submission commits one evaluation/message with unchanged MC/settings |
| Private feedback | Guild/recipient ownership, read/reply checks, idempotent/rate-limited replies, DM opt-out/Forbidden fallback, independent second-look correction and original-score history |
| Fortnightly jobs | Persisted cadence, downtime catch-up without storm, queue budget, cross-connection atomic claim, restart state, three-attempt retries and private worker XLSX/CSV generation |
| Review analytics | Half-open windows, SQLite/ISO/offset dates, foreign-guild exclusion, future/removed opportunity context, short-window old completions, as-of review/appeal cutoffs, unrounded reward tiers, zero/invalid overrides and visible row-budget failure |
| New XLSX/CSV | Eight sheets; source-range extension; editable validated cells; current/scenario caches; text IDs; numeric dates; empty data without phantom posts; zero/blank distinctions; private file mode; formula-injection-safe UTF-8 CSV |
| UI/health | Revoked moderator rejects old view/modal; review modal uses initial response; three support loops detected/repaired with the existing repair budget |

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

The four existing role-report sheets and all eight new analysis sheets were rendered from populated synthetic exports and visually checked. Native SpreadsheetML string/date/formula types, exact ID content and relationships were independently verified. The renderer can infer numeric-looking text; the QA script uses quoted display-only fixture IDs for exact visible digits, while delivered XLSX IDs remain unmodified inline strings. XML types/exact text are the authority for precision.

The new Calculator was independently recalculated: the synthetic 50-reviewer source produces 167 regular + 9 golden = 176 estimated MC. Setting all proposed rewards to zero recomputes proposed total to zero without changing baseline. Fifty reviewers × proposed ten/week recomputes theoretical capacity to 500. Formula-error scans found no matches. Editable-input checks are in memory and are not exported; runtime workbook/formula caches are separately checked by tests. Native desktop Excel was not available for a separate application-engine test.

The standalone HTML reference is rebuilt from the manuals, support guide and generated command tree. Internal navigation targets, duplicate IDs and absence of external stylesheet/script dependencies are checked separately from workbook visual QA. No native browser screenshot is claimed for this reference.

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
