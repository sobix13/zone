# Rollout and roadmap

## Included in V3

Thread-aware MC reactions, normalized emoji identity, durable reaction/notice queues, transactional awards, multiple recipients, message shortcuts, reconciliation/audit, cooldown admin exemption, selected-role Excel reports, history checkpoints, reviewer onboarding, real health, bounded loop repair, independent owner pulse, backups, checked installer and rollback are implemented.

## Included in V3.1

Optional volunteer oversight, bounded random/rotating weekly allocation, private 1–10 evidence-based scores, friendly team inboxes/replies, notification opt-out, independent second looks, automatic private 14-day review analytics, on-demand eight-sheet Excel/CSV and a non-mutating setup/MC calculator are implemented. Configure roles explicitly and pilot with willing moderators. Discuss a common rubric, compare limited/full samples separately and treat suggested quotas as proposals, not automatic restrictions. These review-analysis schedules are distinct from the still-manual historical role scans described below.

## First deployment

Before update, retain a verified private backup and note the service/application path. Install the checked release and complete LIVE_ACCEPTANCE.md with test accounts. Publish the user panel guide and share the moderator reference. Start reports with a small specific role rather than the whole server.

During the first day, inspect reaction delay, permission errors, queue retries, role roster completeness and recovery logs. During the first week, compare a sample of Excel counts with Discord evidence, confirm daily backups, check disk use and ensure stopped workers are not repeatedly restarting. Confirm admins understand that a new manual award or snapshot is a new reward.

## Next operational improvements

These are future work, not hidden features in this release:

1. Add an owner-controlled retention/deletion policy for activity excerpts, old exports and upgrade backups after the community chooses a retention period.
2. Benchmark the actual guild's peak event volume and report size, then adjust worker batches, archive enumeration and memory ceilings from measured data.
3. Add explicit, audited MC reversal/adjustment approval with linked original transactions if the moderation policy requires it.
4. Add saved role-report presets and optional schedules only after desired roles, intervals and destinations are agreed. V3 has manual resumable reports.
5. Add durable rich showcase/role delivery jobs if these notifications require the same retry guarantees as credit logs. V3 already commits their MC independently.
6. Consider a separate infrastructure recovery channel or hosting-provider monitor for whole-host outages. A process on the same host cannot repair its own lost host.
7. Audit long-term weekly cycle boundaries and refresh member onboarding copy from real support questions. Keep reward-policy changes separate from maintenance releases.

## Maintaining the reference

Update COMMANDS.md when registered commands change. Update MODERATOR_MANUAL.md and USER_GUIDE.md whenever access, amounts, limits or workflow behavior changes. Regenerate the standalone manual from the same source. Preserve a release manifest and test report for every shipped version; never put production databases or tokens in the repository.
