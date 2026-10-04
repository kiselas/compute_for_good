# ComputeForGood: roadmap after the first public contribution

Updated 2026-10-04 (Europe/Moscow). The public site is https://compute-for-good.tech on the shared host 185.115.33.169. DNS, TLS, GitHub OAuth, signed webhooks and CI/CD are active. The first normal contributor is kiselas; PR #1 completed MCP reservation, independent review, maintainer merge, exactly one impact credit and automatic deployment. This validates one real workflow; it does not establish advertising capacity.

## Current release: audit fixes

The audit implementation covers refresh replay family revocation; GitHub OAuth state throttling and bounded retention; complete eligible task/review discovery; browser storage fallback; dynamic nginx upstream DNS; CSP and shared-host HSTS; unique validated concurrent backups and encrypted off-host backup tooling. A six-index Alembic migration supports retention. Mandatory local and hosted verification includes all six production transport checks, new PostgreSQL regressions and a forced backend-IP replacement probe.

See [the current audit](project-audit-2026-10-04.md) for evidence and explicit remaining limits. Release deployment is accepted only after hosted CI, exact server revision and public readiness/header/browser checks pass.

## Next priorities

| Priority | Improvement | Acceptance evidence / dependency |
|---|---|---|
| P1 | Least-privilege GitHub repository API credential / App installation | Owner configures a scoped read credential privately; verify PR/check reconciliation and remaining rate budget. Current anonymous API access proves functionality but has a low request budget. |
| P1 | Recovery for password accounts | Select email provider and verified-email policy, then implement short-lived single-use reset tokens, request throttling, neutral responses and revocation of existing sessions; currently recovery needs support. |
| P1 | Readiness/error monitoring and load baseline | Measure registration, catalog, MCP and worker latency on the shared host; alerts on ready failures/integration backlog; preserve VPN and Content Factory resources. No capacity claim until measured. |
| P1 | Recurring encrypted off-host backups | One real archive has been saved/restored manually; choose backup destination, retention and secure second copy of the encryption key before scheduling. The current task creates no scheduler. |
| P1 | Publish useful LOW-risk work for new visitors | Maintainers provide goals and concrete acceptance criteria; operators verify repository/license/CI; frozen contracts and real review/merge evidence remain mandatory. The first task is already completed. |
| P2 | Route-level code splitting and full keyboard/mobile accessibility | Frontend still ships about 700 kB before compression; extract pages and measure bundles/interaction/keyboard navigation. |
| P2 | Project readiness and impact scoring | Scores remain 0 for the first verified project; define evidence-based metrics or replace scores with explicit qualification status. No invented impact. |
| P2 | Query optimization for large review history | Correctness now scans finite keyset chunks; authoritative per-head quorum can still be expensive for a large history. Benchmark before denormalizing. |
| P2 | GitHub issue synchronization and invitations | Implement after onboarding, recovery and operations are stable. |
| Deferred | Sensitive-task dispatch and model attestation | Real HIGH/CRITICAL work remains disabled until verifiable attestation/policy is implemented. |

## Launch gates

A verified project should have discoverable eligible work, a clear maintainer response policy and real named CI checks. Public beta has a working contribution loop. Advertising volume should follow a measured host capacity baseline, repository API credential, recovery policy and monitoring. These dependencies remain separate from successful regression tests.
