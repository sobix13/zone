# Live Discord acceptance after installation

These checks have not been performed by the release's local simulation. Use test members and an agreed small MC amount. Record before/after balances so intentional test credits are accounted for.

1. Confirm both systemd services and `/ready`. Open a fresh admin and user panel. Confirm guild slash commands and both message context actions are visible.
2. Verify old member balances, X handles, roles/channels and pending posts before new awards. Do not run setup_reset during an upgrade.
3. In a normal text channel, an authorized admin reacts to a test member message. Confirm one configured regular award and one ledger identity.
4. Repeat inside a new community task thread and an older accessible thread. Repeat after the thread leaves the cache or is archived and readable. Confirm no channel-lookup failure.
5. Two different admins react simultaneously to one member's message. Confirm two awards. Remove/re-add the same admin reaction and confirm zero additional credit.
6. Try a non-admin, bot-author message and reaction self-award. Confirm zero reaction MC.
7. Use `/give_mc` for two test members. Confirm equal entered amounts for both. Include a malformed/non-member ID and confirm nobody is paid from that rejected batch.
8. Repeat the quick 1-MC message context action as the same admin. Confirm it pays once. Verify a separate custom award is recorded as a new deliberate operation.
9. Create a task with a short member cooldown. Confirm a member's second message is removed and two rapid messages cannot both be accepted. Confirm the configured bot-admin-role member and bot messages are exempt.
10. In an old task thread with native slowmode, run `/doctor repair:true`. Confirm native delay zero and the application cooldown preserved.
11. Request a selected small-role report over 90 days. Verify the roster against Discord, current join timestamps, registered handles and three MC balances. Check all four sheets and real links.
12. Use a small message budget to force pause. Resume; confirm the saved cursor continues, no duplicated indexed IDs and coverage remains explicit. Verify a denied-history channel is skipped with a reason.
13. Give the reviewer role to a test member. Verify its one-time invitation or server-guide fallback, /onboard progress and My next steps.
14. Complete one assigned review and one test quiz. Confirm each result/reward is recorded once, roles/hierarchy behave as configured and showcase publication is visible when eligible.
15. Temporarily deny credit-log send permission for a test award. Confirm MC survives the failed notice. Restore permission and use safe repair. A repeated log after an interruption must not be treated as a new MC payment.
16. Set up the owner recovery control. During a controlled maintenance window, stop only the main unit. Click the owner's pulse and confirm the separate unit restarts it. Verify a non-owner pulse cannot trigger restart.
17. Create a backup, verify it with SQLite quick_check and review the private upgrade backup path. Rehearse code rollback on a staging copy before a production rollback is needed.

A denied gateway intent, wrong bot token, missing permissions or whole-host outage requires fixing that environment. Local tests cannot certify them.

## V3.1 support acceptance

Configure small reviewer, volunteer-moderator and optional content roles. Verify a complete roster, opt-in distribution, spare-capacity skip and full-capacity queue. Test a 1–10 score with checked samples and a blank-score no-evidence check-in. Check full feedback, private replies, DM opt-out/closed DMs and an independent second look. Remove a moderator role and confirm stale task buttons fail. Generate a 14-day XLSX/CSV, compare identities/source counts/MC, and change Calculator inputs without any Discord setting or balance changing. Confirm all three support loops in `/health`. Do not run a large allocation merely to manufacture production test traffic.

## Configuration approval acceptance

Use a small test role without Discord Administrator. The original primary admin selects it as Moderator panel role in `/admin_access`. Give it to a test moderator, and confirm admin-panel access, private XLSX/CSV download, free-form task creation/closure, per-task cooldown editing, rapid moderator posts, member cooldown reset, and MC tools. Native Administrator alone must still lack primary approval access.

Submit a small reward/rule change from the test moderator. Confirm pending status and unchanged active values. The primary admin inspects the complete before/after JSON and approves or rejects. Check the request history and exactly one audit decision. Submit another proposal, modify that same field as a primary admin, then try approval: it must become stale, not overwrite the current field. Remove the moderator or primary role while its panel is open; old forms/buttons must fail. Add/remove a named primary administrator and select/clear a primary role; the original primary administrator/server owner must retain access. Do not test destructive configuration reset on the production guild.

These live checks need the actual server permissions and a controlled test account. They have not been run by the offline release test suite.
