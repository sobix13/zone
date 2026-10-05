# Moderator operations and configuration approval

This is an administrator reference, not part of the accepted member/moderator handbook. That HTML/Word handbook remains byte-for-byte unchanged.

## Primary-admin setup

After upgrade, the existing `admin_user_id` and the Discord server owner remain primary administrators. No configured admin role or native Discord Administrator is silently promoted to primary status.

Open `/admin_access`, or `/admin_panel` → Setup → Access management. Choose a **Moderator panel role** for daily tools, choose an optional **Primary admin role**, and add/remove named primary administrators. Role and named-person grants can coexist. Removing a named grant does not remove access inherited from ownership, the original primary ID or the primary role. Clearing a primary role cannot lock out the original primary administrator or server owner. Never choose @everyone. Access management is itself primary-only and audited; moderators cannot request self-promotion into primary access.

For first-time deployment without a named primary administrator, the server owner starts `/setup_start`. Another Discord Administrator cannot claim the bot by pressing a setup button. An upgrade never needs `/setup_reset`.

## Operational permissions

| Action | Moderator | Primary administrator |
|---|---|---|
| Open admin panel / read saved configuration | Immediate | Immediate |
| Create any community task, choose body/recurrence/cooldown, close it | Immediate | Immediate |
| Edit an individual task cooldown, reset a member cooldown | Immediate | Immediate |
| Bypass task cooldown when moderating | Automatic | Automatic |
| Give MC to one/multiple people, reaction awards, snapshots, MC audit | Immediate | Immediate |
| Review distribution, quiz content, raffle operations, onboarding | Existing operational tools retained | Existing operational tools retained |
| Download role/14-day XLSX and CSV reports, run what-if calculator | Immediate, private response | Immediate, private response |
| Volunteer availability/pause/skip, scoring and friendly team messages | Existing personal/support scope retained | Existing personal/support scope retained |
| Global rules/rates/role or channel mappings/texts/support configuration/reset | Submit proposal; no immediate mutation | Apply directly or approve a proposal |
| Set moderator/primary access roles, grant/revoke named primary admins | Denied | Immediate and audited |
| Raw production backup and independent restart pulse | Existing pinned recovery-owner restrictions retained | Still requires existing recovery-owner authorization |

Individual community-task cooldowns are deliberately outside the global configuration approval flow. `/task_cooldown cooldown:30m task_id:ID` edits a task; omitting the ID inside its task thread selects that task. `/task_reset_cooldown user:MEMBER` skips one member's cooldown in the current active task thread. Moderator posts always bypass the application cooldown. Bot-owned task threads use native Discord slowmode zero so the bot can implement that exemption. If Discord prevents clearing old native slowmode, grant Manage Threads and use `/doctor repair:true`; the command reports that native slowmode is still active.

## Sensitive changes

The shared configuration service guards new and legacy panels/modals and direct setup commands. It covers submission/review caps, required reviews, score thresholds, main/total deadlines, warning/reminder/rescue rules, feedback minimums, all MC and quiz reward rates, reaction emojis/rates, raffle mappings, global role/channel mappings, names/branding/automated texts, global support roles/capacity/sample size/enabled state, and configuration reset. Calculator recommendations never change configuration themselves.

Operational moderators can still have the legacy configured `admin_role_id` or a native Discord Administrator permission. These remain daily-operation permissions only. The newly selected `moderator_role_id` is sufficient without granting Discord Administrator. Volunteer oversight's moderator-role setting is a separate scope and does not implicitly grant bot-panel or primary access.

## Request workflow

Saving a moderator change returns a request ID and **pending** status. Current configuration, MC accounting and running task/review processes stay unchanged. The system log receives a best-effort notification if a log channel is configured; failed notification delivery does not discard the durable request.

Primary admins open Admin Panel → Change requests or `/config_requests`. Select a request to see its author, scope, reason and previous/proposed values; the attached JSON includes every untruncated value. Approve or Reject opens an optional decision-note form. `/config_request request_id:FULL_ID` opens a specific request. Decision history lets moderators see their own outcomes and primary admins inspect all server requests.

The original actor, before/after values, timestamps, decision author/note and audit transitions are stored in SQLite. Approval and configuration mutation are one transaction, including the support-settings table. Double clicks or concurrent decisions apply once, even through separate database connections. A process interruption cannot leave settings applied but a request pending.

Requests expire after seven days. If any submitted field changed in the meantime, approval returns **stale** without overwriting current settings; submit a refreshed request. Related timing invariants and numeric limits are revalidated. Changes to unrelated fields do not invalidate an otherwise valid request. Pending queues are bounded to ten requests/person and 200/server; list pages contain at most twenty requests. Queues/decisions survive restart. Role-based authorization is checked again on each action; removed roles and old buttons do not preserve write access. Named-admin list updates detect concurrent edits instead of losing another grant.

Configuration reset clears configuration/message pointers, but preserves users, posts, balances, transaction history, tasks and primary/moderator access anchors. It must not be used as an upgrade step.

## Recovery boundaries

These permissions govern bot behavior, not VPS root access, GitHub permissions or Discord permissions. The independent recovery daemon remains pinned to its owner and restart budget. No ordinary moderator receives raw database/.env downloads or permission to restart system services just because they can download XLSX/CSV reports. Missing gateway intents, a revoked token, channel permission denial or a whole-host outage still requires fixing the environment; no local mock test certifies a live gateway.
