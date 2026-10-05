# Melee Zone 3.2 validation report

Validated on 2026-10-05 using Python 3.12.14, discord.py 2.7.1 and real SQLite. This release includes the previously local V3.1 support/analytics/calculator work and V3.2 access governance. Earlier V3.1 evidence is retained in archive/TEST_REPORT_V3_1.md.

## Local results

The complete suite passed **202 tests, zero failures, zero skips** with the private recovered backup supplied locally. Each suite also passed separately:

| Suite | Passed |
|---|---:|
| Configuration governance and task permissions | 58 |
| MC and thread handling | 29 |
| Volunteer review support | 30 |
| Review analytics/calculation | 23 |
| Role reports and XLSX | 11 |
| Operation edges and concurrency | 17 |
| Health, recovery and compatibility | 22 |
| Installer and rollback | 4 |
| Release validation/accepted handbook preservation | 8 |
| Total | 202 |

`docs/test-results.xml` contains the complete local JUnit result. Public CI has no private backup: **201 tests plus one explicitly skipped private-backup test** is expected there. The private database is not included in the repository or packages.

Offline startup loaded **20 cogs**, registered **57 root application commands** (55 slash roots, including the support group; two message actions), and registered **three persistent views**. Commands/component IDs have no collisions. Python compilation, shell syntax, dependency consistency and whitespace checks passed. Voice-only optional libraries are not installed; the bot has no voice feature.

## Configuration and access evidence

The new suite checks role/named-user/original-admin/owner primary access; native Administrator's lack of approval access; operational moderator access without native Administrator; no self-promotion; denied forged setup confirmations; fresh authorization on stale views/modals; cross-guild and bot rejection; before/after retention; unchanged active settings while pending; approval/rejection/expiry/conflict outcomes; unrelated-field preservation; atomic rollback on injected audit failure; numeric/finite/range/path validation; missing/deleted role/channel protection; bounded queues; paginated own-request privacy; request JSON completeness; and safe concurrent named-admin list edits.

Thirty concurrent duplicate submissions produce one request. Separate SQLite connections concurrently approving the same request produce one decision audit and one application. A full request queue does not prevent operational MC or a healthy local readiness result. A source-level guard checks every cog configuration writer: only runtime-generated panel/leaderboard message pointers and the weekly cursor bypass the shared request service.

Guild and support configuration readers wait for the transaction to finish. Fault-injected approval tests pause after SQL UPDATE but before COMMIT, then roll back; concurrent MC/support readers never receive tentative values. This prevents an uncommitted or failed configuration approval from affecting an operational reward or support process.

Moderator task creation with arbitrary title/body, recurrence and cooldown, immediate cooldown editing, two rapid moderator posts, member cooldown reset, task closure and multiple-recipient MC are tested together without any configuration request. A proposed reaction-rate change does not change the rate used by a concurrent thread reaction. Foreign/closed tasks cannot have their cooldown edited. Moderator configuration visibility and XLSX/CSV download access remain available. Reset requires approval and preserves balances/history/access anchors.

## Existing features and integration

Existing tests cover durable/raw reaction processing, uncached thread/REST resolution, independent admin awards, duplicate reaction identity, multi-recipient validation and atomic ledger operations, snapshot retries, cooldown reservation, post/review capacities, score/quiz financial finalization, notification retry, deletion privacy, bounded historical scans and resumable reporting.

Support tests cover 50-reviewer allocation, volunteers' capacities, skip/pause redistribution, private 1–10 scoring, sample ownership and insufficient evidence, private messages/replies/DM fallback, independent second looks, fortnightly cadence/catch-up/queue limits/restart, and no automatic MC/role/config penalties. Analytics/report tests check window/source/guild boundaries, as-of evidence, reward estimates versus actual ledger flows, exact text IDs, typed dates, cached formulas, configurable scenarios, safe CSV text and eight-sheet XLSX structure. Existing worker/recovery budgets and local health HTTP behavior remain covered.

Installer tests cover manifest/path refusal, a no-write dry run, migration failure before stopping service, and partial-start rollback preserving newly committed MC. System service calls and Discord interactions are simulated; no production unit is restarted.

## Recovered backup migration

A consistent copy of the already recovered private source was migrated and offline-booted separately. Deterministic fingerprints preserve all old columns/rows except the previously documented normalized X ID/URL backfill. Repeated initialization passed and SQLite quick_check returned `ok`.

| Existing record | Preserved |
|---|---:|
| Users | 117 |
| Posts | 23 |
| MC transactions | 290 |
| Guild configurations | 2 |
| Reaction credits | 190 |
| Quizzes / sessions | 1 / 1 |
| Snapshot awards | 8 |
| Regular + golden + assignment MC | 681.0 |

These are recovered backup figures, not the live guild's current totals. Review and community-task tables are empty in that source, so populated synthetic tests cover them. Production data is never copied into a package.

## Artifact checks

The accepted moderator HTML/Word are copied unchanged, with fixed hash checks in the suite. Word passes ZIP integrity validation and matches the previously rendered, visually checked 14-page document. No new installation/repository/roadmap/version or authorization content was inserted into that handbook. Its working file is delivered using an ordinary clickable download link.

The package builder includes source, requirements, templates, tests, installer/rollback, README, access/upgrade documentation and accepted manuals; it excludes credentials, databases/WAL, production exports, logs, virtual environments and backups. `scripts/verify_release.py` verifies source SHA-256 values, document ZIP integrity, every archive entry, exact manifest agreement, private-path exclusion and archive hashes. Installation dry-run and offline startup/migration are repeated from a freshly extracted package, not merely the working directory. Publication is checked against actual GitHub main contents/tree and workflow outcome; a local file is not treated as proof of publication.

## Verification boundary

Local tests use real discord.py UI types and synthetic async Discord surfaces, real SQLite transactions/backups, and actual localhost health/recovery HTTP endpoints. They do not log in to Discord, make real awards, certify guild permissions, or deploy to a VPS. Missing intents/token/role/channel access and a host outage require environment-specific fixes. Run the small, controlled checks in LIVE_ACCEPTANCE.md after installing the published package. No production restart, upgrade or live acceptance is claimed by this report.
