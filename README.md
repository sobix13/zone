The accepted moderator handbook is supplied unchanged as self-contained searchable HTML and Word under `docs/`. It contains only Discord usage and member support, not installation or repository instructions. `scripts/build_manual.py` generates a separate internal operations reference; it must not replace the approved handbook. Runtime XLSX templates are included in `assets/` and need no Excel dependency on the server.


Normal CI skips the private-backup test unless `LEGACY_TEST_DB` is provided. Tests use real SQLite and synthetic Discord interfaces; they do not log in to Discord or issue real awards.


## Review support and calculator


Open **Review support** in `/admin_panel`, select reviewer and volunteer-moderator roles, optionally select a content-member role, then save. Each moderator opts in and chooses their own capacity. Default: ten reviewers/week, zero content members. Fifty reviewers with five available moderators offering ten slots each are distributed evenly; skips redistribute only within spare capacity. Private scores/feedback never automatically change MC or roles.


```text
/support panel
/support availability reviewers:10 members:0
/support status
/review_analytics days:14
/review_analytics_status job_id:REPORT_ID
/review_calculator days:14 max_reviews:7 min_reviews:3
/team_messages
```


The bot privately prepares a report every 14 days after activation; admins request the download. Eight XLSX sheets include participation, MC balances, detailed source records, moderator evidence and a formula-driven **Calculator**. Amber inputs are what-if proposals, not an automatic setup change. CSV combines person-level metrics. Missing evidence is blank, not zero. **Team messages** in the member/Reviews panel supports private replies, DM opt-out and independent second looks.


Read the [complete support/calculation guide, including Persian setup instructions](docs/REVIEW_SUPPORT.md) for rubric, limits, fairness and metric definitions. The [mobile upgrade guide](docs/UPGRADE_V3_2_FA.md) explains backup-first installation in Termius. Runtime exports add no Python requirements; both authored XLSX templates are shipped in `assets/`.


## Moderator operations and primary-admin approval


`/admin_access` (or Setup → Access management) lets the existing named primary admin or server owner select an operational moderator role, select a primary-admin role and add/remove named primary admins. The original primary-admin ID and server ownership remain recovery anchors. A native Discord Administrator keeps operational access but is **not** automatically a primary approver.


Moderators keep every daily tool: free-form community-task creation and closure, direct task cooldown changes, automatic moderator cooldown bypass, member cooldown resets, MC awards/reactions/snapshots, review allocation and report downloads. Use Community Tasks → Change cooldown, or `/task_cooldown cooldown:30m task_id:ID`. These actions do not wait for configuration approval.


Sensitive global rules, reward rates, role/channel mappings, automated texts, support settings and configuration resets submit a durable request instead. Nothing changes until approval. Primary admins open Admin Panel → Change requests or `/config_requests`, inspect the author and complete before/after JSON, then approve/reject with a note. Moderator requests/history are visible only to their author and primary admins. Direct changes by primary admins are audited as applied. Expired/conflicting requests cannot silently overwrite current values. Access grants themselves are primary-admin-only, never self-promotion proposals. [Full access policy](docs/ADMIN_ACCESS.md).


For a new deployment, copy `.env.example` to `.env`, supply the bot token, install requirements in a venv and run `bot.py` once to initialize SQLite. Enable Server Members and Message Content intents in the Developer Portal. Stop that initial process, then use a separately extracted release with `install.sh` to install the two services. Configure roles/channels through `/setup_start`, `/setup_roles` and `/setup_channels`. Existing deployments use their preserved configuration.


## Documentation


- [Searchable moderator handbook](docs/Melee-Zone-Moderator-Manual.html)
- [Moderator handbook in Word](docs/Melee-Zone-Moderator-Handbook.docx)
- [Reviewer and member guide](docs/USER_GUIDE.md)
- [Weekly support, analysis and calculator](docs/REVIEW_SUPPORT.md)
- [V3.2 upgrade in Termius (فارسی)](docs/UPGRADE_V3_2_FA.md)
- [Access and configuration approvals](docs/ADMIN_ACCESS.md)
- [All registered commands](docs/COMMANDS.md)
- [Operations, recovery and rollback](docs/OPERATIONS.md)
- [Root causes](docs/ROOT_CAUSES.md)
- [Architecture and state](docs/ARCHITECTURE.md)
- [Live acceptance checks](docs/LIVE_ACCEPTANCE.md)
- [Rollout and roadmap](docs/ROADMAP.md)
- [Release notes](docs/RELEASE_NOTES.md)
- [Validation evidence](docs/TEST_REPORT.md)


Historical notes and earlier upgrade reports remain available as history. The current entry points are this README, the access policy and the V3.2 upgrade guide.

## Policies

- [Privacy Policy](PRIVACY.md)
- [Terms of Use](TERMS.md)
