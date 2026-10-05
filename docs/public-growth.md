# Sharing useful work

Public profiles provide a contribution calendar, accepted-result cards and README
badges. `/sprints` lists owner-curated campaigns with published task contracts.
The interface and portable cards support English, Russian and Simplified Chinese.

## Evidence and activity

The calendar uses `accepted-outcomes-v1`, the same eligibility as recognition.
Each green cell counts accepted contributions and independent final-head reviews
on accepted work. Filter implementation or review activity; review cells are blue.
Select a day to open its evidence. Years use UTC and the credit recording date,
not an inferred commit date or actual GitHub merge date. Claims, pending PRs,
self-reviews, stale-head reviews and reviews after acceptance do not earn cells.
Empty histories remain empty. There are no punitive streaks or login-based points.

Activity API: `/api/people/{username}/activity?year=2026` and
`/api/people/{username}/activity/day?day=2026-10-05`. Day evidence is limited to
100 outcomes. Rankings, calendars and badges exclude hidden projects and
suspended contributors. Demo data stays separate and is disabled in production.

## Accepted-result cards

The accepted-contribution list has a Share result disclosure. It supplies a
public evidence link, a suggested first-person post and downloads in 1200×630
and 1080×1350 PNG. Posting is always the contributor's choice. Clipboard failure
leaves selectable text available for manual copying.

`/share/{submission_id}?lang=ru` is server-rendered HTML with Open Graph and
Twitter metadata, so preview crawlers do not need JavaScript. The card links to
the actual PR and profile, displays the task title and final commit, and credits
eligible reviewers without publishing private findings or review content.

JSON evidence: `/api/shares/contributions/{submission_id}`. PNG endpoint:
`/api/shares/contributions/{submission_id}/card.png?lang=ru&shape=portrait`.
`download=true` sets an attachment disposition. Renderer concurrency and memory
cache are bounded; overloaded rendering returns 503 and Retry-After.

Eligibility is checked before rendering or serving a cached PNG. Revoked public
evidence returns 404 and responses request no caching. External social platforms
may retain downloaded images and previews independently; removing source
visibility cannot recall those copies.

## README badges

Profiles and verified projects provide a preview and copyable Markdown:

```markdown
[![ComputeForGood](https://compute-for-good.tech/api/badges/people/kiselas.svg?lang=en)](https://compute-for-good.tech/people/kiselas)
```

Contributor badges show lifetime accepted contributions. Project badges show
currently dispatchable LOW/NORMAL tasks and link to the task catalog. The SVG is
escaped, contains no script or external asset, and refreshes from current data.
GitHub's image proxy and other readers may cache it; it is not a live guarantee
of task availability.

## One prepared sprint

In the maintainer workspace, a browser owner selects published tasks, supplies
copy in all three languages, dates and a response target, then explicitly
publishes a draft. The project must be verified, the owner active, all members
available LOW/NORMAL work, and every contract complete and approved for dispatch.
Scoped agent credentials cannot publish a sprint.

Duration is positive and at most 31 days. There are at most 100 member tasks and
ten drafts per project. Membership and the accepted-task goal are frozen after
publication. Version checks reject stale operations. Published campaigns can be
paused; pausing the campaign does not cancel existing task reservations or
unpublish its task contracts. This version has no editing or resuming of sprints.

Progress counts eligible accepted outcomes recorded inside the sprint period.
Participants count the distinct accepted authors and eligible reviewers, not
visitors or registrations. The response target is an owner's aim, not an
automated service guarantee. Drafts are private; published and paused campaigns
disappear if the project or owner loses public eligibility.

The first campaign blueprint is [first-contribution.json](sprints/first-contribution.json).
It prepares three separate documentation tasks in ComputeForGood: a Russian
first-contribution guide, a Chinese counterpart and an independent-review guide.
These are real deliverables with distinct allowed paths, manual acceptance and
existing CI requirements. They do not establish capacity for a large launch.

Publish through the normal owner API, without direct database writes:

```powershell
uv run --with httpx python scripts/prepare-first-sprint.py --origin https://compute-for-good.tech --login-file C:/Users/kisel/.codex/private/computeforgood/first-user-login.json --apply
```

Without `--apply`, the script prints the public blueprint only. Applying checks
the credential's origin, reads current planning state, reuses matching items,
and refuses to overwrite changed contracts. It never prints credentials. A
partial attempt can be retried; acquired tasks and published sprints are retained.
