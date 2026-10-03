# ComputeForGood launch roadmap

The immediate goal is a working public beta: visitors understand the project, create an account, connect an MCP client, reserve eligible work, and submit/review a canonical PR with auditable results. GitHub activation is planned for tomorrow. The owner has selected the domain and host below. Local tests do not establish external availability.

The owner selected `compute-for-good.tech` and the shared former NextDish intl host `185.115.33.169`. Read-only reconnaissance on 2026-10-03 confirmed that VPN, Content Factory and NextDish are all still running there. The stock production edge conflicts with the existing 80/443 listener; a shared-host deployment variant and explicit SNI route are required. DNS currently returns NXDOMAIN. See [the server reconnaissance](server-recon-2026-10-03.md) for the actual routes, capacity and remaining checks.

## Tonight — implementation and verification

Status: the local deliverables below are implemented. The completed integration run passed 59 checks, with 7 additional authorization checks; backup restore and desktop/mobile browser verification passed. See [the launch audit](launch-audit.md) for evidence and limits. External activation remains pending.

Maintainer planning update, 2026-10-03: `/maintainer` now supports goals → improvement proposals → private task drafts → human approval/publication → results/acceptance. Three scoped MCP planning tools are available. The current full local run passed 78 integration tests and 7 authorization tests, with no skips. Existing launch checks below remain required; the outstanding defects in [the project audit](project-audit-2026-10-03.md) are tracked separately.

| Priority | Deliverable | Completion gate |
|---|---|---|
| P0 | Public landing and separate participant workspace | Desktop/mobile browser checks; working primary calls to action; honest demo labels and empty states |
| P0 | Registration, login, logout, CSRF and login throttling | Real PostgreSQL sessions; negative tests for credential abuse and privilege escalation |
| P0 | MCP personal credentials and OAuth connection | Initialize/list/call over the real transport; expiry/revocation/scopes; PKCE and consent flow |
| P0 | Review reservations, revisions and finding resolution | Race tests; stale SHA/expired lease rejected; author cannot resolve own blocking finding |
| P0 | Production deployment configuration | Separate demo-free database; no public database/Redis ports; readiness checks; fresh migrations |
| P0 | Recovery and operator diagnostics | Validated backup restore; isolated webhook retries and dead letter queue; Redis outage recovery |
| P1 | Project application and personal profile | Candidate applications require operator verification; real contribution counts |
| P1 | Maintainer roadmap and task preparation | Owner isolation, private drafts, human publication, pause controls, frozen acquired contracts and actual merge evidence |
| P1 | GitHub adapter ready for configuration | Signed webhook verification/dedup; current SHA CI policy; linked author identity; no synthetic verification |

## Tomorrow — external activation before advertising

1. Select the public DNS hostname and deployment host. Deploy `compose.production.yaml` using a private `.env.production`; configure DNS and obtain HTTPS through Caddy.
2. Bootstrap an operator using the CLI. Verify public registration, session cookies and CSRF through the deployed origin.
3. Configure GitHub OAuth with `/api/auth/github/callback`; configure the signed webhook `/api/webhooks/github` for pull requests, check runs, check suites and commit statuses. Store secrets privately on the host.
4. Submit and verify at least one real project. Confirm maintainer permission and license, set named required CI checks, and create a small LOW-risk task with explicit acceptance criteria and verification commands.
5. Connect a real external MCP client via OAuth or a scoped personal token. Exercise find → claim → heartbeat → context → prepare submission. Verify that wrong/expired/revoked tokens fail.
6. Finish a real PR → independent review → maintainer merge cycle. Confirm webhook delivery, current-SHA CI, review quorum and one impact credit. Test the advertised browser journey from a clean session on desktop and mobile.
7. Confirm off-host backup, restore procedure, operator access and readiness monitoring. Start advertising only after these checks pass on the public domain.

The public site can accept participants and project applications before GitHub activation. The complete real contribution loop is not verified until step 6. Demo PRs and local fixture counts must never be presented as public impact.

## After the first public beta

| Priority | Work | Rationale |
|---|---|---|
| P1 | Email verification and account recovery | Registration currently needs a deliberate recovery/support policy |
| P1 | Maintainer repository-ownership proof and GitHub App installations | Scale project verification and limit repository credentials |
| P1 | Abuse reports, moderation queues, identity linking safeguards | Protect public signup and project submissions as traffic grows |
| P1 | Accessibility audit with keyboard and screen readers | Verify more than visual appearance and responsive layout |
| P1 | Error telemetry and load baselines on the chosen host | Establish capacity, latency and alert thresholds from real measurements |
| P2 | Verified model attestation and sensitive-task dispatch | HIGH/CRITICAL real work stays disabled until the attestation policy is implemented |
| P2 | Project quality scoring and advanced impact reporting | Use observed outcomes rather than fixture data or invented metrics |
| P2 | GitHub issue/task synchronization and maintainer invitations | Reduce manual operator work after the core loop proves reliable |

Parallel ownership: backend agent owns identity, MCP authorization and schema migrations; interface agent owns the public site and workspace; verification agent owns the review workflow and tests; root owns deployment, operations, project applications, GitHub reconciliation and integration checks. Shared-file mutations are coordinated explicitly.
