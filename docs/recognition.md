# Contributor recognition — accepted-outcomes-v1

Implemented 5 October 2026. The system describes recorded participation. It does not claim to measure security severity, code quality, downstream adoption, financial rewards or social impact.

## Public tables and profiles

`/leaderboard` is available without login. Three rankings: accepted contributions, reviews on accepted work, and different projects receiving the participant's accepted contributions. Each has lifetime and rolling 30-day views, shared ranks for equal totals, stable username ordering within ties, and pages of 25. Zero-outcome accounts are absent from rankings and retain an empty public profile.

`GET /api/leaderboard?metric=contributions&period=all&limit=25&offset=0` returns version, snapshot time, realm, metric, period, pagination, total and entries. Supported metrics: `contributions`, `reviews`, `projects`; periods: `all`, `30d`; limit 1–100; offset 0–10000. Each entry exposes only username, rank and the three outcome counts. One SQL statement computes totals and the requested page, including an empty page beyond the end.

`GET /api/people/{username}`, `GET /api/me/profile` and MCP `get_my_profile` include the same `reputation` object: version, snapshot time, realm, metrics, lifetime PR acceptance ratio and achievement progress. Private operational profile counters remain raw activity counts and are not ranking inputs. Public `stats.reviews` now counts reviews on accepted work rather than every historical review.

## Evidence and visibility

An accepted contribution requires a unique canonical `ImpactCredit` owned by the submission author, a `MERGED` submission with observed human approval, a merged task, and a verified project. User, project, task, submission and credit must all belong to the same real/demo realm. Suspended authors and non-verified projects are omitted. A ledger entry alone cannot turn pending, invalid or inconsistent work into public recognition.

An accepted review is counted once per reviewer/canonical PR. It must cover the final accepted head SHA, precede the acceptance record, and come from someone other than the author. Reviews of old heads, pending/closed/invalid PRs, post-acceptance reviews and self-reviews do not count. Reviewer decision and finding text are never exposed through the ranking response. This metric describes completed review participation; it does not establish that a particular finding was confirmed or prevented a vulnerability.

The rolling window uses the credit's recording timestamp for both implementation and review. The schema does not store an authoritative merge timestamp suitable for historical duration calculations; the interface explicitly explains the recording date. No durability/survival award is inferred from elapsed wall time.

Lifetime PR acceptance is accepted canonical submissions divided by accepted + closed + invalid canonical submissions within visible projects. Pending submissions are excluded. With no decided submissions the rate is `null`, displayed as unavailable. The sample size is visible; one accepted PR is not a measured reliability guarantee. Acceptance rate does not sort the rankings.

Real tables are the default even in local demo mode. `demo=true` selects a separate explicitly labelled table and is rejected outside demo mode. Public demo profiles are likewise unavailable in production.

## Six achievements

| ID | Evidence threshold |
|---|---|
| `first_contribution` | 1 accepted contribution |
| `five_contributions` | 5 accepted contributions |
| `ten_contributions` | 10 accepted contributions |
| `cross_project` | Accepted contributions to 3 different projects |
| `first_review` | Final-head review on 1 accepted contribution |
| `five_reviews` | Final-head reviews on 5 accepted contributions |

Progress is capped at the threshold for display. Awards are derived when read, so existing legitimate records gain recognition immediately without a backfill job, and excluded evidence cannot retain a permanent badge. There is no user-writable award/points endpoint and no extra award transaction to race duplicate webhook delivery. Existing unique credit and review constraints remain authoritative.

English, Russian and Simplified Chinese cover the table, explanations, loading/error/empty states, sample-size caveat and all award descriptions. Semantic tables, labelled native controls, focus styles and labelled progress bars support keyboard use. Tables scroll within their container on narrow screens.

## Follow-up product work

Useful work and timely maintainer decisions precede further gamification. Confirmed-finding awards, maintainer ratings, retained-after-30-days awards, skills/category attribution and a project impact score need additional evidence fields and anti-abuse rules before implementation. A more polished README/profile badge can link to the public evidence page; registration counts, raw PR volume and security keywords must not manufacture impact.

This release does not prevent multi-account collusion or prove independence between people. Owned-project dogfooding remains an accepted recorded outcome, not external adoption. Large contests, financial prizes and a combined social-credit score are outside this version.
