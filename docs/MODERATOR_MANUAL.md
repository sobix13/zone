# Melee Zone moderator manual

Version 3.0.0 | Operating reference, training and member support

## Purpose and authority

Melee Zone organizes a community's X submissions, assigned reviews, MC rewards, showcase, quizzes, raffle access and community task threads. Discord roles and the guild's saved configuration decide access. Moderators operate the bot through `/admin_panel`; members use the persistent user panel, `/guide` and `/onboard`.

MC has three stored balances: regular, golden and assignment. Their sum is total MC. Credits are ledger-backed community rewards, not a verified measure of a person's overall contribution.

An authorized bot admin is a Discord administrator, the configured admin user or a member of the configured admin role. The reviewer role is the configured `pro_role_id`, usually Meleeionaires. Its displayed name alone does not authorize reviews. The recovery owner is separately pinned by server configuration/environment or the recovery control. Being a moderator does not automatically grant restart access.

## Before operating a shift

1. Open `/health`. Check gateway, database and background workers.
2. Open `/setup_view` to confirm current roles, channels, amounts, review timing and reaction emojis.
3. Check recent credit-log messages and `/stats` for outstanding work.
4. Use `/doctor` in the location where a problem was reported. Permission overwrites vary by channel and thread.
5. Keep the private recovery control and this manual available. Use member/message links and IDs when escalating an issue.

Existing configuration is authoritative. The update does not replace your custom amounts, roles, branding or user balances with examples in this manual.

## Panel map

The user panel provides Dashboard, Submission, Reviews, Quiz and guide access, according to role and configuration. Dashboard includes the member's saved X handle and MC balance. Reviews shows current assignments and Ready for More.

The unified admin panel groups setup, content/reviews, rewards and configuration. It also includes a role activity selector and health/recovery tools. Open a fresh `/admin_panel` after an update if an older ephemeral panel has expired. Persistent public user-panel buttons are registered again on startup.

Administrative views and modals recheck authorization when used. Changing a role after opening a panel can remove access. Never distribute the Discord bot token as a moderator credential.

## MC awards

### Admin reactions

Configure up to five emojis with `/setup_reactions`. Each emoji has one regular-MC amount. Zero disables that emoji's MC payout. Keep the raffle emoji different; it follows the raffle role path before MC processing.

React on the member's message with a configured emoji. This works in ordinary text channels and accessible task/review threads. A raw event enters the saved queue, so processing may take a few seconds. The bot fetches the message author, verifies the reacting admin and commits the reward. Reactions on bot messages and an admin's own message do not give reaction MC.

For each message, each admin and each configured emoji can award once. Two admins using the same emoji make two legitimate awards. One admin using two different configured emojis makes two awards. Repeated gateway delivery or removing/re-adding the same reaction does not pay again. Removing a reaction does not reverse a recorded award.

### Several recipients in one command

```text
/give_mc amount:2 reason:Helpful participation users:@Alice @Bob mc_type:regular
/give_mc amount:3 reason:Task completed users:111111111111111111 222222222222222222 mc_type:assignment
```

The amount applies to each recipient. Use up to 25 unique mentions or Discord IDs. Repeated IDs collapse into one recipient. The earlier `user` option still works and can be combined with `users`. The whole batch validates before any award: one missing member, malformed ID or bot recipient prevents the batch.

A successful command reports new awards and already-recorded recipients. Retrying the same interaction is idempotent. Submitting a new slash command is a new explicit award, even with identical text. Two admins can award independently at the same time.

The credit log is delivered through a separate saved outbox. A failed log delivery does not undo MC or create another award. After repeated failures, repair permissions and run `/doctor repair:true` to retry the failed notices.

### Message shortcuts

Use the message menu, **Apps > Award 1 MC**, for a quick regular award. Repeating that action as the same admin on the same message does not pay again. **Apps > Award MC** opens an amount/reason form; each newly submitted form is a new award.

### Snapshot

Run `/snapshot` in a channel or thread, choose regular/golden/assignment, enter hours, amount and reason, then inspect the preview before confirming. Each distinct non-bot poster in the scanned messages receives the amount once for that snapshot. Confirmation and all balance updates commit together.

Snapshot accepts up to 720 hours and examines at most 10,000 messages. It is an award tool with a bounded window. It does not scan every child thread when invoked in a parent channel. A separate new snapshot can reward the same person again. For large or historical role analysis, use role reports.

### Audit and missed reactions

`/mc_audit user:@member` shows the most recent 15 ledger entries, amount, type, reason and awarding actor. `/user_info` provides broader member details. Ask for the exact message URL and award time when investigating.

`/mc_reconcile hours:24` scans the current destination's last 200 messages within the selected 1-168 hours and queues eligible uncredited admin reactions. It is serialized, bounded to 90 seconds and has a 60-second per-location cooldown. It cannot find every reaction from a long offline period. Run it in the affected thread; the reaction ledger prevents paying already-recorded awards again.

Check the balance before manually compensating. A new `/give_mc` after a successful reaction is another award. This release has no general negative-MC or automatic reversal command. Escalate an incorrect credited amount to the owner with its ledger reference; avoid editing SQLite while the bot is running.

## Community task threads

Use `/setup_assignment_channel` once for the parent channel. Open the community task tools in the admin panel or use the registered assignment commands. Create a task with a clear title, instructions, cooldown and recurring flag. Cooldown inputs include `0`, `1h`, `24h` and `7d`, bounded to seven days.

Members post entries inside the task's thread. Member posts in the configured parent channel are removed if the bot has Manage Messages. A premature member post inside an active task thread is removed and a short cooldown notice is sent. The accepted-message timestamp and participant record commit together. Bots and authorized admins bypass this application rule.

If a member needs a one-off retry after a moderation correction, run `/task_reset_cooldown user:@member` inside that task thread. It clears that member cooldown only and leaves MC and participation history in place.

New task threads have native Discord slowmode zero. In an older bot-owned task thread, run `/doctor repair:true` to remove native slowmode while retaining the saved application cooldown. Missing Manage Threads requires a permission fix by a server administrator. A custom bot-admin role does not itself imply Discord's native bypass permissions in unrelated channels.

A recurring flag records the task's intended ongoing use; it does not schedule automatic recreation, automatic payouts or automatic closure. Moderators create/close tasks explicitly. Closing archives the task workflow; past MC remains. Participant count is distinct members, not a quality score or a message total.

## Submissions, assigned reviews and showcase

Members register their X handle before submitting/reviewing when registration is required. Submission accepts direct X/Twitter status URLs, including `/i/status/`. Tracking/query parameters normalize to the same status ID. A member cannot submit the same status again in another week. The registered handle helps a moderator check ownership; `/i/status/` does not identify the author. The bot does not verify X ownership or content through an X API.

Weekly slots come from saved configuration. Exhausting the member's weekly submission capacity grants the configured completion reward once per week. Manual `/manual_assign` fills available assignment slots without resetting everyone's weekly submission capacity. The scheduled Saturday cycle performs the periodic reset.

Reviewers open Reviews or `/my_reviews`, read the assigned post and submit a score from 1 to 10 plus written feedback. The default minimum feedback length is 30 characters, but current configuration can differ. An optional X comment link contributes to existing comment-bonus eligibility; it is a URL format check, not remote verification of the comment.

Only the assigned reviewer can complete a pending/warning assignment. Duplicate submissions of the same review are rejected transactionally. No self-review is assigned. Each post's required number of reviews is saved when it is submitted. Changing the minimum later does not silently rewrite old posts.

Default score rewards, unless customized:

| Average score | Regular MC | Result |
|---|---:|---|
| Below 4 | 0 | Rejected |
| 4 to below 6 | 1 | Rejected, lower-tier reward |
| 6 to below 8 | 3 | Approved |
| 8 through 10 | 5 | Approved |

The showcase threshold defaults to 8 and its golden reward defaults to 3. Review-goal and comment bonuses are separate settings. A post can earn regular score MC and golden showcase MC together. Result finalization and both balances commit together. Delivery of a showcase message can still fail independently; check the ledger before giving compensation.

### Warning and rescue procedure

The inherited timing defaults are a five-day primary period, twelve-hour warning grace, seven-day displayed total deadline and up to three rescue assignments per reviewer per week. The panel's actual deadline and saved settings take precedence. A background check runs every 15 minutes; it is not an exact-to-the-second scheduler.

After the primary period, outstanding work receives a warning. After the grace period, an eligible reviewer marked Ready for More can receive a rescue assignment. The original remains active if a valid replacement cannot be created. Replacement creation and original retirement happen together.

A rescue candidate must have no unfinished primary work in the current cycle, must be marked ready, must have remaining rescue capacity and cannot be the author/original reviewer or a previous reviewer of that post. Rescue assignments have a 24-hour due date. Ready for More remains active until the rescue cap is reached or the user changes it.

For inaccessible content, conflict of interest or language problems, a reviewer uses `/review_skip assignment_id:... reason:...`. This retires their active assignment, records the reason and attempts a replacement. It grants no review reward and does not guarantee an immediate replacement when reviewer capacity is unavailable.

## Leaderboard and legacy exports

`/leaderboard` shows the current top MC earners. The configured persistent leaderboard updates periodically and `/setup_leaderboard` posts or refreshes it in the chosen leaderboard channel. `/my_mc` is the member balance view; `/user_info` is the admin detail view.

`/export_data` retains the existing CSV exports for users or posts. CSV is a legacy export; selected-role activity analysis uses the separate formatted XLSX report. Treat all user exports as moderator data and verify the chosen export type before distributing them.

## Quiz and raffle

The Quiz section serves the currently active quiz loaded by an admin. Questions and options are shuffled. The quiz loader accepts the format documented in the UI; validate the JSON before loading. A member completes a particular quiz once. Result, session completion and MC commit together, so two simultaneous completions do not pay twice.

Default quiz MC: 40-69 percent gives 1, 70-79 gives 2, 80-89 gives 3, 90-100 gives 5; below the configured minimum gives zero. Passing at 70 percent can grant the configured quiz role. Quiz role delivery requires Manage Roles and a bot role above that role. A role-delivery failure does not erase a completed result or its MC. Admin quiz tools provide progress/history and exports.

Configure raffle access with `/setup_raffle_role`. `/give_raffle` supports multiple mentions. A configured raffle reaction also grants that role to the reacted message's author when an admin uses it. `/revoke_all_raffle` and bulk quiz-role revocation affect members' roles; inspect the target configuration before using them. These actions are not MC balance resets. Put all managed roles below the bot's top role.

## Role analysis and Excel

Open `/admin_panel`, select **Role report**, then select one specific role. This queues a 30-day, 20,000-message report. For a different range:

```text
/role_report role:@Meleeionaires days:90 max_messages:20000
/role_report role:@SpecialRole days:0 max_messages:20000
/role_report_status job_id:REPORT_ID
/role_report_resume job_id:REPORT_ID extra_messages:20000
/role_report_cancel job_id:REPORT_ID
```

`days:0` requests all accessible history. Explicit windows support 1-3650 days. The message budget counts every examined message, including messages by non-target members. It bounds API work; it does not mean 20,000 messages per selected member. At most three active/paused reports per guild are queued and one worker scans serially.

The roster is fetched fresh through Discord's full member inventory. It includes everyone currently holding that role, even members without a Melee Zone database record. Missing Members Intent or inventory failure stops the request instead of labeling a partial cache as a complete roster. It includes bot members for roster completeness, but bot messages are excluded from human activity counts.

The report's roster and history upper cutoff are captured at request time. Its MC balances and latest locally observed activities are read when the workbook is generated. Thus it is not a single atomic historical snapshot of all these values. Request a fresh report when membership has changed.

### Meaning of the fields

| Field | Meaning |
|---|---|
| Discord ID | Exact text value; Excel does not round the ID |
| Username / display name | Discord identity at roster collection |
| X handle | Handle already registered with Melee Zone; blank means unknown |
| Joined (UTC) | Start of the person's current server membership |
| Last activity | Latest indexed message, observed reaction or bot action |
| Last message | Latest indexed message timestamp, including an observed later deletion |
| Messages in window | Retained indexed messages within this report's cutoff and upper bound |
| Known messages | All messages indexed for this member so far, including observed deletions |
| Regular / golden / assignment MC | Current balances read during export |
| Total MC | Excel formula summing the three balances |
| History coverage | Requested accessible history exhausted, or partial |

Recent messages contains up to five retained excerpts, capped at 350 content characters plus attachment count, with source URLs. Recent activity contains up to five live-observed reactions or bot actions. These recent records can include observations outside the requested message-count window. All dates use UTC.

No observed activity means the bot has no evidence; it does not prove inactivity. Presence, reading, voice participation, historical reaction timestamps and deleted-before-observation messages are not measured. Discord IDs and handles are not automatically cross-verified with another service.

### Paused, skipped and complete

A report pauses on its message/time budget or a transient history API failure. `/role_report_resume` keeps the saved cursor and adds allowance. `/role_report_status` attaches the most recent workbook when one has been generated. Partial reports remain usable with their visible coverage rows. A restart requeues interrupted running jobs; deliberately paused jobs wait for an admin.

The scanner enumerates text channels, active threads and readable archived public/private threads. Default archived-thread enumeration is capped at 500; exceeding it is explicitly recorded. An inaccessible or deleted destination is skipped with a reason. Permissions or an enumeration cap require a new report after correction; resume continues pending destinations and does not rescan skipped ones automatically.

A complete scan means all discovered accessible destinations exhausted the requested window. It cannot certify deleted or permanently inaccessible history. Even an all-history scan is therefore an accessible-history count, not a guaranteed lifetime total.

Reviewer-role members are observed prospectively from V3 startup. Selecting another role adds it to observation. Exports are admin-only and ephemeral; keep the workbook in the moderator team. The bot stores the activity index locally and clears indexed message excerpts after observed deletion. Backups may retain prior data. No fixed message-index retention period or external sync is enabled in this release; the owner controls retention and backup handling.

## Onboarding Meleeionaires

Use `/onboard` with each new reviewer. It presents six short pages: start, submit, review, deadlines/rescue, MC/tasks and common questions. Progress persists; `/onboard` resumes while `/guide` starts from the first page.

**My next steps** shows registered handle, remaining submission capacity and pending reviews with the nearest deadline. The public panel also has **Guide and next steps**. Newly receiving the configured reviewer role triggers one DM invitation. Existing role holders can start directly, and closed DMs leave the server-based guide available. A role name change does not break access because configuration uses IDs.

For the first review, ask the member to explain the score in concrete terms. Examples: accuracy, useful detail, clarity and a suggested improvement. A short generic compliment does not give actionable feedback. The bot enforces length and score range; moderators enforce review quality.

## Troubleshooting a reported issue

| Symptom | First check | Action |
|---|---|---|
| Reaction gives no MC | Exact emoji, actor authorization, target author, history access | `/doctor`, then `/mc_reconcile` in that destination |
| MC changed but no log | `/mc_audit` and credit-log permissions | Repair permissions, retry notices; do not re-award |
| Admin message deleted for cooldown | Current bot admin role/user and old native slowmode | `/setup_view`, then `/doctor repair:true` inside task |
| Report omits old activity | Window, partial/paused state and Coverage sheet | Resume or create a new all-history report after permissions fix |
| Report says no activity | Whether tracking/history includes the person | Treat as unknown; inspect their source messages |
| Reviewer sees no work | Configured reviewer role, weekly cycle and current assignments | `/my_reviews`, `/manual_assign` if slots are available |
| Post stalls | Needed reviewers and available capacity | `/stats`, verify role membership and reviewer availability |
| Role was not granted | Bot role hierarchy and Manage Roles | Fix hierarchy; manually grant once if authorized |
| Slash command absent | Installation readiness and guild command sync | Check service logs and `/health`; owner investigates |
| Main bot is offline | Independent recovery control still available | Recovery owner clicks the reset reaction once |
| Recovery is rate limited | Three restarts per 15 minutes, two-minute spacing | Stop repeated pulses; inspect the cause via server logs |

For dangerous or uncertain state, use the server runbook in OPERATIONS.md. Recovery never clears balances, deletes the database, rewrites roles or rotates the token automatically.

## Member questions and suggested answers

**Why did two admin reactions give more MC?** Each authorized admin awards independently; each admin/emoji/message identity pays once.

**Can I react to reward myself?** Reaction self-awards are excluded. Ask a moderator to assess the contribution.

**The admin removed their reaction. Why is MC unchanged?** Recorded MC is a ledger entry. Removing a reaction does not reverse it.

**I posted twice in a task and one message disappeared.** The task's member cooldown permits one accepted entry per interval. Wait for the next interval.

**Do admins have the same cooldown?** Melee Zone admins bypass the application cooldown. Old native slowmode needs repair inside that task.

**Is MC immediate?** Manual awards commit before the successful response. Reaction awards wait for the saved worker and Discord message fetch. Network delays can extend that wait.

**Why are there three balances?** Regular covers ordinary rewards, golden covers showcase or explicitly golden awards, and assignment is used for explicitly assignment-type awards. Their sum is total MC.

**My submission scored 5 and was rejected but earned MC. Is that a bug?** Lower-tier MC begins at score 4; approval begins at 6. Check custom amounts in the current configuration.

**Can I submit the same post next week?** A status already submitted by you is rejected across weeks, including alternate URL forms.

**Who checks X ownership or comment quality?** The member supplies a handle/link; reviewers and moderators check content. Melee Zone does not use an X API to certify them.

**The assigned post is gone.** Use `/review_skip` with Cannot access post. Do not invent a review score.

**Ready for More did not immediately give a rescue.** A rescue must be available, your primary work must be finished and your weekly rescue limit must have space. The check runs periodically.

**Does Known messages mean every message I ever wrote?** It means messages Melee Zone has indexed. Deleted-before-observation and inaccessible history are unavailable.

**Is the join date my very first join?** It is your current membership's join date. A rejoin can replace the earlier date.

**Can the recovery control fix every outage?** It can recover the main process while the server, recovery service, token and Discord REST API remain available. A dead server or invalid token needs an owner fix.

## Escalation record

Record the member ID, guild/location, message/assignment/job ID, timestamp, expected outcome, `/health` or `/doctor` result and the relevant ledger transaction. Keep tokens and full `.env` files out of Discord tickets. This makes a problem reproducible and distinguishes a financial error from a delayed notification.
