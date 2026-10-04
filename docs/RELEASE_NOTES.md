# Melee Zone 3.0.0 release notes

## Behavior changes

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
