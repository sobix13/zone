# Melee Zone 3.2.0 release notes

## V3.2 access and configuration governance

- Distinct operational moderator and primary-administrator access, configurable by role and named people. Original named primary admin/server owner are preserved; native Discord Administrator alone does not authorize approval.
- Persistent pending/approved/rejected/expired/stale configuration requests, complete old/new values, auditable decisions, seven-day expiry, bounded queues and paginated private views.
- Shared approval guard on all direct/legacy/new setup commands and forms. Approval and settings changes are one transaction; conflicting or duplicate approvals do not overwrite or apply twice.
- Community task creation/closure, per-task cooldown editing, automatic moderator bypass, member cooldown resets and daily MC/report/review tools remain immediate operational actions.
- New `/admin_access`, `/config_requests`, `/config_request` and `/task_cooldown` commands. All V3.1 support/analytics/calculator features are included, not replaced.
- Accepted searchable HTML and Word moderator handbook included unchanged. The internal reference builder uses a separate destination.
- Updated full-source/update packages, integrity verifier, access documentation and backup-first Termius upgrade instructions. No extra runtime requirement.

No live VPS upgrade or Discord gateway test is claimed by this source release. See TEST_REPORT.md and LIVE_ACCEPTANCE.md for the verification boundary.

## V3.1 optional additions

- Disabled-by-default reviewer/member support roles and explicitly volunteered moderator capacities.
- Saved randomized weekly person allocation with least-recent support priority, bounded workload, no self-evaluation and no-penalty skip/pause.
- Frozen previous-week evidence, private integer 1–10 scores, checked-sample validation and explicit insufficient-evidence state.
- Persistent team inboxes in member/Reviews panels, private replies, DM opt-out and bounded notifications with inbox fallback.
- Independent second looks with optional corrections stored separately from original ratings; no MC/role penalties.
- Consecutive 14-day private reports and on-demand 1–90-day XLSX/CSV, with actual ledger flows separate from reward/workload estimates.
- Eight-sheet authored report template with editable proposed settings and recalculating formulas, exact text IDs, typed dates, cached values and safe CSV text.
- Conservative setup suggestions, finite row/queue/time budgets, background file generation, explicit bounded report retry and support-loop health checks.
- Fixed the existing Reviews panel modal path to use an initial interaction response instead of a nonexistent follow-up modal API.
- Existing Python requirements are unchanged. JSON schema and both XLSX templates are included in the verified full update/repository packages.

MC balances and existing guild review settings remain unchanged by the new support layer. An admin explicitly chooses support roles after installation. See REVIEW_SUPPORT.md and UPGRADE_V3_1_FA.md for operating instructions.

## Included V3.0 behavior

- Raw MC reactions resolve channels and threads through cache and REST fallback.
- MC events persist before worker execution; balance, ledger and reward identity commit together.
- Emoji IDs survive custom-name changes; Unicode variation-selector differences do not duplicate rewards.
- Independent admins can award concurrently. Duplicate event delivery and remove/re-add do not repay the same identity.
- `/give_mc` keeps its single `user` option and adds a validated `users` batch of up to 25 recipients.
- Message context actions provide quick 1-MC and custom awards; audit and missed-reaction reconciliation are available.
- Community task member cooldowns reserve acceptance atomically; bots and authorized admins bypass them.
- New task threads use application cooldowns with native slowmode zero. Doctor can repair old owned task slowmode.
- Selected roles receive fresh roster inventory and bounded/resumable historical scanning with four-sheet Excel exports.
- Reviewer onboarding persists progress and provides a role-specific checklist.
- Health checks reflect real readiness; stopped workers and recovery attempts have limits.
- A separate process supports the owner reset pulse, local recovery request, diagnostics and daily consistent backup.
- Post score/showcase finalization and quiz completion now include their MC in the same transaction.
- Assignment creation prevents overfilling/capacity races; rescue handoff is transactional; administrative views recheck access.
- Existing review-window settings now update the active total deadline field instead of an unused legacy setting alone.

## Compatibility

The migration is additive. It backfills normalized X status IDs/URLs and reaction award keys without changing existing balances or ledger records. Repeating initialization is idempotent. The supplied release excludes production `.env`, SQLite/WAL files, exports, logs, backups and virtual environments.

The checked private source snapshot contained 117 user rows, 23 posts, 290 MC transactions, 190 recorded reaction credits and 681.0 total MC. Its existing stored values and monetary total survived migration. These figures describe that recovered backup, not the live server today. Its review/community-task tables were empty; their new behavior was tested with synthetic populated data.

## Validation boundary

Python 3.12 local simulation, real SQLite migration/backup checks, extension/command boot, concurrency/fault injection, XLSX XML validation and visual workbook inspection were performed. No live guild login, deployed systemd operation or real member award was performed in the release workspace. Installation readiness and LIVE_ACCEPTANCE.md cover those environment-specific checks.
