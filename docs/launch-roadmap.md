# ComputeForGood: roadmap after the first public contribution

Updated 2026-10-04 (Europe/Moscow). The public site is https://compute-for-good.tech on the shared host 185.115.33.169. DNS, TLS, GitHub OAuth, signed webhooks and CI/CD are active. The first normal contributor is kiselas; PR #1 completed MCP reservation, independent review, maintainer merge, exactly one impact credit and automatic deployment. This validates one real workflow; it does not establish advertising capacity.

## Current release: repeated audit fixes

The first audit release covers refresh replay family revocation, throttling/retention, work discovery, browser storage fallback, dynamic proxy DNS, security headers and checked encrypted backups. The repeated audit adds scoped operator-token isolation, bounded database/pool waiting, concurrent credential quotas, authoritative PR-state recovery, permit expiry/renewal/reload recovery, honest uncomputed score display, lazy maintainer loading and stronger release/rollback/restore gates. A bounded read-only diagnostic command measures public readiness and latency; no external alert service or scheduler is configured by it.

See [the repeated audit](project-audit-2026-10-04-round2.md) for evidence and remaining limits. Release deployment is accepted only after hosted CI, exact running image revision, worker ticks after restart and public readiness/header/browser checks pass.

## Next priorities

| Priority | Improvement | Acceptance evidence / dependency |
|---|---|---|
| P1 | Least-privilege GitHub repository API credential / App installation | Owner configures a scoped read credential privately; verify PR/check reconciliation and remaining rate budget. Current anonymous API access proves functionality but has a low request budget. |
| P1 | Recovery for password accounts | Select email provider and verified-email policy, then implement short-lived single-use reset tokens, request throttling, neutral responses and revocation of existing sessions; currently recovery needs support. |
| P1 | External monitoring and load assessment | Bounded sequential catalog/readiness samples and resource snapshots are implemented; choose external alert delivery and measure realistic registration/MCP/write concurrency while preserving neighbor resources. No advertising-capacity claim from sequential samples. |
| P1 | Recurring encrypted off-host backups | One real archive has been saved/restored manually; choose backup destination, retention and secure second copy of the encryption key before scheduling. The current task creates no scheduler. |
| P1 | Publish useful LOW-risk work for new visitors | Maintainers provide goals and concrete acceptance criteria; operators verify repository/license/CI; frozen contracts and real review/merge evidence remain mandatory. The first task is already completed. |
| P2 | Further code splitting and full keyboard/mobile accessibility | Maintainer workspace is a lazy chunk; initial JS decreased 700418→684228 bytes but remains large. App and locale catalogs need deeper splitting plus measured keyboard/mobile coverage. |
| P2 | Project readiness and impact scoring | Uncomputed real scores are now explicitly unavailable; qualification status is visible. Define an evidence-based scoring contract and computation metadata before displaying numerical rankings. |
| P2 | Recovery when all GitHub triggers are missed | Queued/CI/manual reconciliation recovers current PR head/state and terminal credit, including missed synchronize references. A terminal event lost after the initial job still needs a later trigger or operator refresh; periodic recovery requires a suitable GitHub API budget. |
| P2 | Query optimization for large review history | Correctness now scans finite keyset chunks; authoritative per-head quorum can still be expensive for a large history. Benchmark before denormalizing. |
| P2 | GitHub issue synchronization and invitations | Implement after onboarding, recovery and operations are stable. |
| Deferred | Sensitive-task dispatch and model attestation | Real HIGH/CRITICAL work remains disabled until verifiable attestation/policy is implemented. |

## Launch gates

A verified project should have discoverable eligible work, a clear maintainer response policy and real named CI checks. Public beta has a working contribution loop. Advertising volume should follow a measured host capacity baseline, repository API credential, recovery policy and monitoring. These dependencies remain separate from successful regression tests.
