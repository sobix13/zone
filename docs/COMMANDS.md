# Registered command reference

Generated from the V3.2 offline command tree. All commands are server-only. Current saved configuration determines exact roles, amounts and timing.

57 root application commands: 55 slash roots and 2 message context actions. Groups and their executable subcommands are listed below.

## /admin_access

Primary-admin-only access management

**Access:** Primary administrator (server owner/original named admin/approved role or named people).

## /admin_guide

Open the moderator reference

**Access:** Admin.

## /admin_panel

Open the admin panel (admin only)

**Access:** Member or panel-specific role.

## Message action: Award 1 MC

Message context action

**Access:** Admin.

## Message action: Award MC

Message context action

**Access:** Admin.

## /backup

Create a consistent database backup (recovery owner)

**Access:** Recovery owner and admin.

## /config_request

Open a configuration request by its full ID

**Access:** Moderator (own requests); primary admin (all requests and approval).

| Option | Required | Default | Details |
|---|---|---|---|
| request_id | Yes |  | … |

## /config_requests

Review pending settings requests or view your request history

**Access:** Moderator (own requests); primary admin (all requests and approval).

## /doctor

Diagnose permissions, reactions, tasks and runtime (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| repair | No | False | … |

## /export_data

Export data as CSV (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| data_type | No | posts | … Choices: posts, users, reviews |

## /give_mc

Manually award MC (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| amount | Yes |  | Amount per member Range: 0.1 to 1000.0. |
| reason | Yes |  | Reason |
| user | No | None | One member |
| users | No | None | Multiple member mentions or IDs, up to 25 |
| mc_type | No | regular | Credit type Choices: regular, golden, assignment |

## /give_raffle

Give raffle role to one or more users (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| users | Yes |  | Mention users separated by spaces |

## /guide

Open the user guide and answers

**Access:** Member or panel-specific role.

## /health

Open bot health and recovery tools (admin)

**Access:** Admin.

## /leaderboard

Top MC earners

**Access:** Member or panel-specific role.

## /manual_assign

Trigger assignment cycle now (admin)

**Access:** Admin.

## /mc_audit

View recent MC transactions for a member (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| user | Yes |  | … |

## /mc_reconcile

Recover uncredited admin reactions in this channel or thread (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| hours | No | 24 | … Range: 1 to 168. |

## /my_mc

Check your Melee Credit balance

**Access:** Member or panel-specific role.

## /my_reviews

View posts assigned to you for review

**Access:** Reviewer role.

## /my_submits

View your submissions this week

**Access:** Member or panel-specific role.

## /onboard

Continue your Melee Zone introduction

**Access:** Member or panel-specific role.

## /panel

Post the user panel in this channel

**Access:** Member or panel-specific role.

## /quick_start

Open the first steps for your role

**Access:** Member or panel-specific role.

## /recovery_setup

Create an owner-only recovery pulse in a private control channel

**Access:** Recovery owner and admin.

| Option | Required | Default | Details |
|---|---|---|---|
| channel | Yes |  | … |

## /register_twitter

Register or update your X/Twitter handle

**Access:** Member or panel-specific role.

| Option | Required | Default | Details |
|---|---|---|---|
| twitter_username | Yes |  | Your X/Twitter username (without @) |

## /review

Submit your review for an assigned post

**Access:** Reviewer role.

| Option | Required | Default | Details |
|---|---|---|---|
| assignment_id | Yes |  | First 8 chars of assignment ID |
| score | Yes |  | Score 1-10 Range: 1 to 10. |
| summary | Yes |  | Written feedback |
| comment | No | None | Your X comment URL (optional) |

## /review_analytics

Prepare participation, moderator and setup reports as Excel and CSV (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| days | No | 14 | … Range: 1 to 90. |

## /review_analytics_status

Download a private saved Excel and CSV participation report (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| job_id | No | None | … |
| retry | No | False | … |

## /review_calculator

Preview workload and MC assumptions without applying changes (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| days | No | 14 | … Range: 1 to 90. |
| max_reviews | No | None | … Range: 1 to 20. |
| max_submits | No | None | … Range: 1 to 20. |
| min_reviews | No | None | … Range: 1 to 10. |
| review_reward | No | None | … Range: 0.0 to 1000.0. |

## /review_skip

Return an assigned post you cannot review

**Access:** Reviewer role.

| Option | Required | Default | Details |
|---|---|---|---|
| assignment_id | Yes |  | … |
| reason | Yes |  | … Choices: Cannot access post, Conflict of interest, Language issue, Other |

## /revoke_all_raffle

Remove raffle role from ALL users (admin)

**Access:** Admin.

## /role_report

Export role members, activity and MC to Excel (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| role | Yes |  | … |
| days | No | 30 | 0 scans all accessible history. Default: 30 days. Range: 0 to 3650. |
| max_messages | No | 20000 | Total messages scanned across channels. Resume adds another budget. Range: 100 to 200000. |

## /role_report_cancel

Stop a report and retain the collected history (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| job_id | Yes |  | … |

## /role_report_resume

Continue a paused report from its saved cursor (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| job_id | Yes |  | … |
| extra_messages | No | 20000 | … Range: 100 to 200000. |

## /role_report_status

Get report progress and its current Excel file (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| job_id | Yes |  | … |

## /setup

Open the unified setup center

**Access:** Admin.

## /setup_assignment_channel

Set the assignments channel where threads are posted (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| channel | Yes |  | The assignments channel |

## /setup_channels

Configure all channels

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| bot_content_channel | Yes |  | Main bot channel |
| showcase_channel | Yes |  | Featured posts channel |
| mention_role | Yes |  | Role pinged for showcase |
| leaderboard_channel | Yes |  | Leaderboard channel (auto-updates) |
| log_channel | No | None | System log (optional) |
| credit_log_channel | No | None | Credit log (optional) |
| review_channel | No | None | Review notifications fallback (optional) |

## /setup_leaderboard

Post or refresh leaderboard (admin)

**Access:** Admin.

## /setup_quiz_role

Set the quiz pass role - given to users who score 70%+ (admin only)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| role | Yes |  | Role assigned to users who score 70%+ |

## /setup_raffle_reaction

Set the emoji that grants the raffle role

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| emoji | Yes |  | Emoji that grants raffle role when admin reacts |

## /setup_raffle_role

Set the raffle access role (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| role | Yes |  | Role granted for raffle access |

## /setup_reactions

Set MC reaction emojis (up to 5)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| emoji_1 | Yes |  | Emoji 1 |
| mc_1 | Yes |  | MC for emoji 1 |
| emoji_2 | Yes |  | Emoji 2 |
| mc_2 | Yes |  | MC for emoji 2 |
| emoji_3 | Yes |  | Emoji 3 |
| mc_3 | Yes |  | MC for emoji 3 |
| emoji_4 | No | None | Emoji 4 (optional) |
| mc_4 | No | None | MC for emoji 4 |
| emoji_5 | No | None | Emoji 5 (optional) |
| mc_5 | No | None | MC for emoji 5 |

## /setup_reset

Reset all configuration (keeps user data)

**Access:** Admin.

## /setup_roles

Configure roles

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| pro_role | Yes |  | Reviewer role |
| basic_role | No | None | Basic role (optional) |
| admin_role | No | None | Admin role (optional) |

## /setup_settings

Tune all numeric parameters

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| max_submits | No | None | Max posts/user/week Range: 1 to 20. |
| max_reviews | No | None | Max reviews/reviewer/week Range: 1 to 20. |
| review_window_days | No | None | Days to complete a review Range: 1 to 14. |
| reminder_hours | No | None | Hours before reminder Range: 12 to 168. |
| min_reviews | No | None | Min reviews needed per post Range: 1 to 10. |
| showcase_threshold | No | None | Min avg score for showcase Range: 5.0 to 10.0. |
| require_twitter_id | No | None | Require X handle |

## /setup_start

Start configuration wizard

**Access:** Primary administrator (server owner/original named admin/approved role or named people).

## /setup_view

View current configuration

**Access:** Admin.

## /snapshot

Award MC to everyone who posted in a channel/thread within a time window (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| channel | No | None | Channel or thread to scan (default: current) |

## /stats

Weekly statistics (admin)

**Access:** Admin.

## /submit

Submit a post for review

**Access:** Member or panel-specific role.

| Option | Required | Default | Details |
|---|---|---|---|
| link | Yes |  | Twitter/X post URL |

## /support

Private weekly review support and volunteer moderation

**Access:** Member or panel-specific role.

## /support availability

Choose your own weekly capacities or pause without penalty

**Access:** Selected volunteer moderator role.

| Option | Required | Default | Details |
|---|---|---|---|
| available | No | True | … |
| reviewers | No | 10 | … Range: 0 to 50. |
| members | No | 0 | … Range: 0 to 50. |

## /support panel

Open your volunteer moderator workload

**Access:** Selected volunteer moderator role.

## /support resolve

Record and privately deliver a second-look resolution (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| request_id | Yes |  | … |
| resolution | Yes |  | … |
| revised_score | No | None | … Range: 1 to 10. |

## /support setup

Configure roles and automatic private review support (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| moderator_role | Yes |  | … |
| reviewer_role | No | None | … |
| member_role | No | None | … |
| weekly_cap | No | 10 | … Range: 1 to 50. |
| samples | No | 3 | … Range: 1 to 5. |
| enabled | No | True | … |

## /support status

Weekly workload and second-look overview (admin)

**Access:** Admin.

## /task_cooldown

Change a community task cooldown immediately (moderator)

**Access:** Moderator; immediate operation, no configuration approval.

| Option | Required | Default | Details |
|---|---|---|---|
| cooldown | Yes |  | … |
| task_id | No | None | … |

## /task_reset_cooldown

Reset one member cooldown in the current community task (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| user | Yes |  | … |

## /team_messages

Read private team feedback, reply or change DM notifications

**Access:** Member or panel-specific role.

| Option | Required | Default | Details |
|---|---|---|---|
| dm_notifications | No | None | … |

## /user_info

View user details (admin)

**Access:** Admin.

| Option | Required | Default | Details |
|---|---|---|---|
| user | Yes |  | User to inspect |

