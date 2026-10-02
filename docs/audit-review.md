# Review and submission readiness audit

This audit covers the implementation in this repository. A running local demo does not establish production deployment, real GitHub credentials, maintainer consent, or compatibility with two real MCP hosts.

## Findings and disposition

| Priority | Finding | Disposition |
| --- | --- | --- |
| P0 | Direct review submission had no independent lease, allowing duplicate reserved review effort. | Added risk-policy review slots and atomic reviewer leases in `review_workflow.py`. Production submissions require the matching lease token, reviewer and current SHA. Direct reviews remain confined to explicit demo submissions. Actual PostgreSQL checks passed for slot concurrency, ownership, expiry/recovery and head invalidation on the final rebuilt image. |
| P0 | A SHA change previously removed unresolved HIGH/CRITICAL findings from the quorum calculation. | Quorum now retains unresolved security findings across heads. Original reviewers or operators must provide evidence to resolve them. Authors cannot resolve their own findings. New heads still require fresh independent reviews. |
| P0 | A review could be attributed to a commit that the reviewer did not inspect. | `head_sha` is mandatory and compared under the canonical submission lock. Previous actual PostgreSQL/HTTP tests verified stale SHA rejection; the review lease also pins its head. |
| P0 | Claiming or registering with an expired/reassigned implementation lease could create duplicate canonical work. | The previous actual database suite verified atomic claims, stale lease/permit rejection, canonical registration after reassignment and consumed-permit rejection. These gates remain in the full integration suite. |
| P0 | Existing GitHub PRs could be relabeled after a lease to earn contribution credit. | Production validation now compares GitHub PR creation time against lease acquisition. Legitimate revision uses the existing canonical submission, without a new cutoff. Actual GitHub integration still requires configuration and external verification. |
| P0 | An unverified local username is insufficient proof of GitHub authorship. | Production validation requires a linked GitHub identity and compares GitHub author ID. Demo PR handling is explicitly separate. Actual external identity linking remains a launch check. |
| P1 | A permanently failing webhook could roll back an entire batch and starve unrelated deliveries. | Worker uses per-delivery savepoints/transactions, persisted attempts/errors, retry backoff and visible terminal failure/operator retry. The actual poisoned-delivery test verifies that an unrelated delivery completes. Failed jobs are not acknowledged as completed. |
| P1 | Review conclusions could leak through public status or quorum counters. | Blind status, masked counters and hidden conclusions are required until the user completes a current-head review. Resolution evidence has its own access check. Public events contain invalidation metadata rather than findings or verdicts. |
| P1 | Reviewers could remain reserved against a PR that has been closed or merged. | `close_review_work()` ends unfinished reservations and is integrated into close/merge transitions. |
| P1 | A work-scoped operator agent token could adjudicate another reviewer's security finding. | Original reviewers may resolve their findings through a scoped work credential. Operator adjudication requires browser authority; explicit demo operators retain the local compatibility path. Dedicated authority-boundary verification is included in the final suite. |
| P1 | Suspending a project discarded unfinished review reservations without making them recoverable after re-verification. | Pausing revokes reservations; re-verification reopens unfinished slots only for the current head and preserves completed reviews. A dedicated private-project regression checks suspension, candidate rejection and subsequent resume. |
| P0 | Cached authentication could survive a concurrent user suspension while waiting on a domain lock. | Eligibility refreshes the user under the domain locks before mutation. Finding adjudication refreshes identity as well. The deterministic PostgreSQL regression holds an account lock, observes the waiting HTTP claim and commits suspension before releasing it. |
| P0 | Resolving a finding on fixed commit B could accidentally approve a return to the original bad commit A. | Quorum treats the finding as unresolved when the PR returns to its original bad SHA and the resolution covered another SHA. The regression verifies that old approvals cannot enable a merge of A. |
| P1 | A burst of individual Socket.IO events disconnected polling clients with the standard Engine.IO decoder limit. | Direct diagnosis observed 39 packets in one polling response, the decoder's 16-packet limit and an abort/disconnect. The worker now emits one public metadata packet per batch of at most 100 changes. Final rebuilt-image tests passed with forty persisted events, the unchanged client decoder limit and WebSocket through the production Caddy/nginx proxy. |

## Review invariants

- Each canonical submission head receives exactly the configured LOW/NORMAL/HIGH/CRITICAL number of review slots.
- PostgreSQL constraints allow one active lease per slot and one active lease per reviewer/submission/head. Account row locking prevents concurrent claims by one reviewer from evading their concurrency limit.
- An author cannot claim or submit a review of their own work.
- Eligibility uses the account's stored tier and server risk policy. Caller-supplied model names cannot elevate eligibility.
- A completed reviewer cannot occupy a second slot for the same head. A new commit requires a new review attempt.
- Expired, released or stale reservations cannot authorize a review. Heartbeats are capped by the maximum lease lifetime.
- Implementation work stays attached to the same canonical PR during revision. Revision does not make the task AVAILABLE and cannot create a second submission or second impact credit.
- Finding resolutions are append-only records with evidence, covered head SHA, resolver identity and authority. They do not rewrite the original finding. A current-head BLOCK/REQUEST_CHANGES verdict remains a veto even if an individual finding is resolved.
- CRITICAL quorum still requires five eligible independent approvals and human maintainer approval. Resolving a finding does not itself supply an approval or merge authority.

## Verification

`tests/test_http_alpha.py` and `tests/test_transports.py` previously passed 22 actual integration checks on the local PostgreSQL/Redis stack, including Streamable HTTP MCP and Socket.IO. The expanded suite adds real review-slot concurrency, ownership, lease expiration/recovery, stale-head invalidation, finding adjudication, production lease enforcement and canonical revision.

The earlier expanded run passed 56 of 57 checks, with a Socket.IO polling failure. A readiness barrier did not eliminate it. Direct diagnosis confirmed that a burst exceeded the polling decoder's packet limit; this superseded the initial startup-race hypothesis. Worker metadata batching fixed the confirmed issue.

The final coherent-image run on 2026-10-03 passed **59 checks in 81.04 seconds**, exit code 0, with no skips or failures. JUnit evidence is `tests/artifacts/launch-final.xml`. The command was `python -m pytest tests -v --tb=short --junitxml=tests/artifacts/launch-final.xml`, using QA HTTP 8110, PostgreSQL 55472, Redis 56382 and the separate demo-free production proxy 5380. Actual protocol checks covered two Streamable HTTP MCP flows, production cookie/CSRF and scoped credential boundaries, OAuth PKCE with three client authentication methods, polling with forty committed events and WebSocket through Caddy/nginx. GitHub identity/time/SHA and CI policy checks used controlled upstream responses; they do not establish live GitHub configuration.

After the lead agent's dependency audit replaced the frontend nginx runtime with the official `nginx:1.30.5-alpine` digest-pinned image, the six dependent production HTTP/OAuth and proxy WebSocket checks passed again in **1.41 seconds**, with no skips or failures. JUnit evidence is `tests/artifacts/proxy-final.xml`. Backend source was unchanged. The lead agent reported zero known vulnerabilities from the npm production dependency audit and Python locked dependency audit; those results are separate from these protocol tests.

The lead subsequently made forwarding headers explicit in OAuth/MCP/Socket.IO locations and reran the same six dependent checks: **6 passed in 1.19 seconds**, zero failures/errors/skips. The final `proxy-final.xml` records this latter run.

Run this suite against the dedicated QA stack rather than the showcase catalog. Test data is isolated under a unique `qa-` project prefix. No existing user data is deleted.

## Remaining launch evidence

The local production profile with demo mode disabled, registration/session/CSRF boundaries, scoped/revocable MCP credentials and OAuth PKCE passed the checks above. Public HTTPS deployment and actual GitHub identity linking, repository checks and webhook installation still need external verification. HIGH/CRITICAL real work remains restricted until the platform can verify the required model attestation; demo tier fixtures do not establish such attestation.

The lead agent additionally restored the final backup into the separate `cfg_restore_launch_final` database and verified Alembic revision `5c4267c97e04`, two projects, five tasks and one submission. The integration suite exercised poison-delivery isolation and operator controls. Remaining external checks are actual GitHub configuration and repository consent, two real MCP host clients and operation of the publicly deployed service. They remain pending until exercised.
