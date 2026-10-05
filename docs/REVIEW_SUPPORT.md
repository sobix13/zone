# Review support, fortnightly analysis and calculator

Version 3.1.0. This is an optional layer over the existing review cycle. It neither replaces review assignments nor changes MC payouts, roles or main review settings. It is disabled until an admin selects its roles and enables it.

## راه‌اندازی سریع برای ادمین

در `/admin_panel` گزینه **Review support** را باز کنید. **Setup roles** را بزنید و سه انتخاب را مشخص کنید: رول ریویوکننده، رول مادریتور داوطلب و در صورت نیاز رول اعضایی که محتوایشان بررسی می‌شود. رول سوم اختیاری است. سپس **Save and enable** را بزنید.

نام واقعی رول‌ها را از انتخاب‌گر دیسکورد انتخاب کنید؛ `Meleeionaires` یا هر نام دیگری، بر اساس تنظیمات سرور شما است. رول مادریتور این بخش، دسترسی ادمین به MC یا خروجی همه اعضا نمی‌دهد. هر ماد باید خودش همکاری را فعال کند.

```text
/support panel
/support availability reviewers:10 members:0 available:true
/support status
/review_analytics days:14
/review_analytics_status job_id:REPORT_ID
/review_calculator days:14 max_reviews:7 max_submits:5 min_reviews:3
/team_messages
```

`REPORT_ID` را با شناسه‌ای که بات برمی‌گرداند جایگزین کنید. پارامترهای اختیاری را لازم نیست همیشه وارد کنید. برای بررسی اعضا علاوه بر ریویوکنندگان، ماد ظرفیت جداگانه اعلام می‌کند؛ مثلاً `members:5`. پیش‌فرض اعضا صفر است و به کسی کار اضافه تحمیل نمی‌شود.

ادمین برای توقف کل قابلیت، در همین پنل **Pause support** را می‌زند. پیام‌ها، گزارش‌ها و نمره‌های قبلی حذف نمی‌شوند و چرخه اصلی ریویو/MC دست‌نخورده می‌ماند. برای ادامه، دوباره تنظیمات این بخش را ذخیره و فعال کنید.

اگر ماد در یک هفته فرصت ندارد، **Pause my workload** یا دستور زیر را بزند:

```text
/support availability available:false reviewers:0 members:0
```

## Weekly distribution

The support week starts Saturday at 00:00 in Asia/Tehran. It inspects work recorded during the preceding week. The scheduler checks every 15 minutes; volunteers joining midweek can receive available tasks from that same cycle.

For 50 reviewers and five available moderators offering ten reviewer slots each, each moderator receives ten distinct people. Distribution uses a saved random seed, balanced current workload and a preference for a different moderator from the person's last completed support evaluation. People supported least recently have priority when capacity is short. Refresh/restart does not reroll the saved samples or duplicate tasks. It is a balanced randomized allocation, not a guarantee of independent uniform random sampling.

Reviewer and member/content capacities are separate opt-in commitments. Ten reviewer slots plus five member slots means up to fifteen tasks, not ten. Someone holding both target roles can have one task in each scope. No moderator evaluates themselves.

Skip has no MC deduction, negative score or disciplinary effect. A skipped task moves only to another eligible volunteer with spare capacity and never returns to a moderator who skipped that same task. If everyone else is full, it remains queued. Pausing redistributes unfinished work, not completed evaluations. Removed roles withdraw pending tasks at the next complete roster refresh. Expired/queued work does not become a zero score. At most 100 new tasks are prepared per scheduler pass to avoid long write-lock occupation.

The panel lists people, not every review as a separate job. Each task preserves up to three random source records by default, configurable from one to five. Source candidates are bounded to the latest 500 records for that person in the preceding week. The moderator sees source IDs, links, dates, stored content score and review text/status. Evidence is captured once for the cycle; later website or post changes are not silently substituted.

## Rating and friendly feedback

Open `/support panel`, choose a person, read the saved evidence and select **Score and feedback**. Enter an integer from 1 to 10, the full IDs actually checked and 30–1500 characters of helpful feedback. The supplied IDs are a checklist, not proof that a moderator opened a link; moderators must confirm honestly and remove unchecked IDs.

Use the same rubric across moderators. Judge the evidence, not personality, friendship, speed or raw message volume.

| Range | Reviewer evidence | Member/content evidence |
|---|---|---|
| 1–2 | Evidence is substantially inaccurate, unrelated or harmful; explain concrete examples | Content misses the intended purpose substantially; explain a concrete example |
| 3–4 | Mostly generic feedback with little usable explanation | An idea is present but clarity, relevance or supporting detail needs work |
| 5–6 | Usable review with some explanation and an identifiable next improvement | Useful relevant content with identifiable improvements |
| 7–8 | Specific, balanced, actionable feedback supported by the samples | Clear, useful, well-supported content |
| 9–10 | Consistently excellent sampled feedback, including precise helpful examples | Excellent sampled work with clear value and supporting examples |

Write one evidenced strength and one achievable suggestion. Do not demand more output merely to earn a high score. A peer-score difference or repeated phrase is a discussion prompt, not proof of dishonesty. Content scores given to posts and moderator scores of review quality are different metrics and are never substituted for each other.

Without any samples, leave the score blank and make a friendly check-in or skip. Blank means insufficient evidence, never zero. With fewer checked samples than the configured sample target, the score is marked limited evidence and reported separately from full-sample averages. The software checks ID ownership, rating range, active task ownership, deadline and duplicate submission, but cannot automate a human's quality judgment.

## Private team messages and second looks

**Team messages** exists in the main member panel and Reviews panel, with `/team_messages` as a shortcut. Each recipient sees only their own inbox. Moderators can reply to responses in their own inbox. Selecting a message shows its full text; each inbox page displays five excerpts. Responses are private, not a public thread or leaderboard.

Feedback is durably saved together with the evaluation before an optional DM is attempted. Closed DMs do not lose it. Members can use the panel-only button or:

```text
/team_messages dm_notifications:false
/team_messages dm_notifications:true
```

Replies are capped at five per person per hour per server. An interaction retry cannot duplicate the reply. Original feedback has no automatic effect on MC or roles. Private here means other regular users/moderators cannot read another user's inbox; server admins with report access and trusted host/database administrators can access evaluation data. Do not put credentials or sensitive personal material in feedback.

The recipient can request one second look per evaluation with a short explanation. An admin uses the support admin panel to list requests, inspects the evidence and resolves it. The evaluating moderator cannot resolve their own appeal. A different authorized admin can record an optional corrected 1–10 score:

```text
/support resolve request_id:REQUEST_ID resolution:EXPLANATION revised_score:8
```

The explanation is privately delivered. The original score and evidence remain unchanged in the audit record; the correction is stored separately. Reports use corrections only when recorded before the requested cutoff. A no-evidence check-in cannot be converted into a scored evaluation. Revisions never alter MC.

## Every 14 days and on-demand downloads

The first automatic report closes 14 days after the first support configuration. Subsequent windows are consecutive, saved UTC intervals, start inclusive/end exclusive. The bot prepares the files privately; it does not automatically post a member report in a channel or DM an admin. After downtime, it prepares the latest complete missed interval rather than a large backlog.

`/review_analytics` requests a rolling window ending now, default 14 days, permitted 1–90 days. `/review_analytics_status` downloads its XLSX and CSV when ready, using the returned job ID. Without an ID it shows the latest requested window, which may still be queued. Both commands and calculator/settings/report buttons require existing bot-admin authorization. Ordinary volunteer moderators cannot download everyone's records.

The workbook has eight distinct sheets:

| Sheet | Contents |
|---|---|
| Overview | Current/previous post and review totals, opportunities, capacity, ledger awards and proposed setup changes |
| Calculator | Editable proposed limits/rewards, current-rule comparison and user/week goal input records |
| Members | Discord ID, names, registered X handle, join date, posts, content score, participation, indexed activity, three current MC balances and quality feedback |
| Reviewers | Assignments, mature/completed opportunities, completion ratio, pending/reassigned work, review quality/context indicators and private moderator score |
| Moderators | Opted-in capacity, assigned/evaluated/skipped work and score context; skips are not penalties |
| Posts | Saved requirements, reviews/mean score before cutoff and traceable current/proposed reward formulas |
| Reviews | Submitted review records, source links, score and feedback |
| Oversight | Checked evidence IDs, moderator feedback, effective/original/revised scores and dates |

CSV combines person-level participation metrics, IDs, names, role context and MC balances into one UTF-8 file with a BOM. It does not flatten every individual post/review into the person table; those details are in the XLSX. User-controlled formula-like CSV text is escaped. When opening CSV in Excel, import Discord ID columns as **Text** to avoid Excel's numeric precision limit. The XLSX already stores exact IDs as text and sortable dates as numeric UTC dates. Use filtering and scrolling for wide tables; source text remains in the file even when a long cell needs its row expanded.

## Definitions and calculation logic

- Posts/reviews submitted count timestamped events in the half-open window. Previous-window comparison uses the same duration. Review opportunities use assignments received in the window, due before its end; removed/reassigned work is excluded. Future-due work is shown separately. Completions after the cutoff do not inflate completion.
- Current roles, names, join date and MC balances are capture-time values, not reconstructed historical membership/balances. Names/handles come from the Discord roster and existing registered bot profile. The analysis does not fetch X likes, impressions or proof of engagement.
- Indexed messages and observed actions/reactions count only records known to the bot within the window. They are not a complete Discord history or a substitute for review quality. Existing role-history reports remain a separate bounded/resumable tool. This analysis reads retained SQLite records, including records older than 720 hours; it does not invent inaccessible/deleted activity.
- Post outcomes are reconstructed from available review evidence before the cutoff rather than trusting today's final status. Current-rule reward estimates retain each post's saved requirement. Proposed reviews/post is explicitly hypothetical and can differ even if today's main setting matches an old post's setting. Historical reassignment/status transitions are not fully event-sourced; the report retains today's known exclusion state and is not an immutable replay of all past state.
- Post regular MC uses mean-score bands below 4 = 0; 4 to below 6 = low; 6 to below 8 = medium; 8–10 = high. Golden estimates use the configured showcase threshold/reward. Weekly reviewer-goal estimates count completed assignments by their stored cycle week. The comment bonus additionally requires valid recorded X comment links for every in-window review in that user/week group. Submission goals count posts by stored cycle week.
- A rolling window can cut through weeks or a post's review lifetime. Its what-if estimate describes those observed fragments under current/proposed rules; it does not audit missing payments or reconstruct historical rates. Actual positive/negative ledger flows and current balances are separate. Quiz, manual, reaction and community-assignment awards appear in the actual ledger totals; their future volume is not forecast by the review calculator. Use `/mc_audit` for ledger investigation.
- Theoretical review capacity is current reviewer count × weekly limit. Measured capacity is active current-role reviewer count × weekly limit × their mature opportunity completion rate. Demand is observed weekly post arrivals × required reviews/post. Missing denominators remain blank, not a healthy zero. These are approximate capacity models, not promised throughput.
- Workload recommendations require at least ten mature assignments among current reviewers, active reviewers and a nonzero observed completion rate. Suggested review-limit change is bounded to two and submission-limit change to one. Deadline suggestions require ten observed responses and never shorten the configured window. Prefer volunteers, realistic deadlines and context over restrictive quotas.

Amber Calculator cells are proposed inputs only. Formulas recalculate locally in Excel; the file has no macros, token or link that applies settings to the bot. Review-window input does not rewrite observed assignment due dates or rerun allocation. Review a proposal and apply any accepted values through the existing admin setup. There is no single universally optimal setup independent of traffic and voluntary availability.

## Faults, limits and recovery

The role inventory is fetched completely before roster replacement. Failure leaves the previous complete roster intact, and a role selection change invalidates it until refreshed. Invalid/unavailable moderator-role checks fail closed. Missing Members intent or inaccessible/deleted roles requires an admin fix, not an automatic permission bypass.

There is one report worker. Each server can have two queued/running reports. The complete snapshot has a combined 50,000-source-row budget; more data fails visibly and asks for a shorter window, never a silent partial report. Selected-role inventory is capped at 15,000 rows. Snapshot acquisition has a 45-second budget, roster acquisition 180 seconds. Reports reuse an inventory at most one minute old, otherwise refresh it; the Excel summary records its refresh time in saved report metadata. Analysis/XLSX work runs off the event loop. No REST or file generation occurs inside the short support/MC write transactions.

Failed report retry is explicit, at most three attempts per job:

```text
/review_analytics_status job_id:REPORT_ID retry:true
```

Correct the listed problem before retrying. After three attempts, fix the environment and request a new window. Saved files live privately under `REPORT_DIR/review-support` with restrictive permissions; outputs above the 8 MiB per-file attachment allowance need authorized host retrieval. There is no automatic deletion of reports or member records. Set a retention policy with the community before doing manual cleanup.

DM delivery processes at most five messages per 15-second tick with three bounded attempts for transient API failures. The panel is the durable fallback. A crash after Discord accepted a DM but before acknowledgment can duplicate a notification, not an evaluation or MC payment. Health monitors all three support loops and applies the existing bounded loop-restart policy. Host/token/permission faults still need an admin; the independent owner recovery pulse remains the deployment-level fallback.

## First live acceptance

After backup-first installation, configure small test roles, opt in two test moderators and inspect the roster/allocation. With spare capacity, skip one task and verify redistribution; with full capacity, verify a queue. Test a meaningful score, a no-sample check-in, closed DMs, panel-only notifications, a private reply and an independent second look. Revoke a test moderator role and confirm an old button no longer works. Generate a 14-day report, compare source counts/balances, change Calculator cells and confirm nothing in Discord changes. These live checks are intentionally separate from the delivered offline simulations.
