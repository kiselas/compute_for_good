# Audit and priority implementation — 4 October 2026

This is the first audit release snapshot. See [round 2](project-audit-2026-10-04-round2.md) for the subsequent audit, fixes and repeated review.

Baseline: main 57b460f, deployed after the first real contribution. Static review, three parallel implementation/review agents, actual local PostgreSQL/Redis, HTTP/MCP tests and isolated Docker/backup experiments were used. CodeGraph remains disabled by owner choice. No production attack or mass traffic was generated.

## Findings fixed in this release

| Finding | Consequence | Implementation and meaningful verification |
|---|---|---|
| P1 Refresh replay did not revoke the live token family | A stolen refresh consumed first could retain access after the legitimate client retried | Grant-first locking; matching unexpired tombstone revokes grant and all live credentials. Revocation commits before SDK invalid_grant. 13 new real PostgreSQL/HTTP cases cover public/post/basic clients, two rotations, race, wrong client/secret/resource, expiry and isolation. |
| P1 Anonymous GitHub start grew states without a limit | Repeated GET could grow durable state and later callbacks cost provider requests | Redis rate limits before allocation/callback; untrusted Origin rejection; fail closed when limiter fails. Real state rows and Redis TTL tested. Async OAuth middleware sends blocking Redis work to a worker thread. |
| P2 Temporary auth records had no retention | Expired state verifiers/session/credential records grew indefinitely | Coordination worker every 5 minutes: up to 200 rows/class, SKIP LOCKED, separate transactions, bounded query/lock time. State 1 day, sessions 30 days, credentials 90 days. Refresh evidence remains while family lifetime survives. Six DB cases and six-index migration. OAuth client registrations remain persistent. |
| P2 Eligible work was hidden behind early LIMIT (A07) | Empty results despite available work; browser legacy review endpoint also suggested reserved heads | SQL cheap eligibility/dispatch filters precede LIMIT; review keyset chunks fill bounded results and retain canonical quorum/blind policy. REST /review-tasks, /review-work and MCP aligned. Five regressions with >100 ineligible/reserved/passed candidates and historic blocking findings. |
| P2 Browser storage errors lost a successful claim (A09) | Server lease acquired, UI throws or fails to render; user loses local token | User/lease/storage-scoped memory cache written before persistence; denied getter/quota failure handled. Two frontend regressions run in every build. Memory cannot survive a page reload when persistent storage is denied; server lease expiry/release still applies. |
| P2 nginx retained the previous backend IP (A12) | Static page works while API/MCP fail after a backend replacement | Shared upstream zone with Docker DNS resolver and resolve. Isolated Docker test forces a new IP, occupies the old address and verifies API/MCP/OAuth/socket routes without nginx restart. Actual WebSocket handshake remains covered by the separate transport smoke. |
| P2 Concurrent backup collision (A11) | Archives could be overwritten between dump and copy | Unique UUID paths; pg_restore --list and SHA-256 verification. Two simultaneous QA archives restored independently to scratch databases. |
| P2 Missing browser security policy / transport persistence | No CSP/HSTS on public responses | CSP permits self scripts, current inline styles and same-host ws/wss; blocks object/frame embedding. Shared HTTPS gateway HSTS max-age one year, without includeSubDomains or preload. Production smoke verifies CSP; public/browser checks follow deployment. |
| Operational gap: no checked off-host archive | Host loss would also lose same-host release backups | backup-remote.py fetches through existing verified SSH and encrypts locally using a separate private key. Actual production archive restored to an isolated QA database: 2 users, 1 impact credit, baseline schema 8d21f6ae903b. Plaintext stayed in memory. No scheduler created. |
| Local runner silently skipped production transports (A10 local remainder) | Developer verification could pass with six skipped checks | verify.ps1 prepares private local-only settings and independent production smoke; XML gate requires all six transport cases and zero skips; dynamic DNS probe is mandatory locally and in hosted CI. |

## Evidence and limits

The full integration run passed 98 tests, including all six actual production transports, with zero skips. The combined focused authorization run passed 25 tests; frontend build checked 879 RU/EN/zh-CN keys and two storage regressions. Evidence is in tests/artifacts/hardening-full-20261004.xml and auth-verification.xml; hosted release checks are available in GitHub Actions. An independent agent reviewed authorization/proxy/storage/backup changes; a second reviewed discovery and found the browser legacy endpoint omission before it was fixed.

OAuth replay revocation deliberately rejects a duplicate refresh even when it is a legitimate network retry; the client must reconnect. Invalid client/secret, expired/unknown/access token and wrong resource cannot revoke another live grant. Cleanup preserves the tombstones needed to recognize replay, and query failures prevent a fresh worker heartbeat.

The DNS test uses disposable HTTP servers to prove address/route recovery; it is not a WebSocket handshake or zero-downtime deployment guarantee. Existing production transport tests exercise real polling/WebSocket behavior. The real backup check does not establish recurring backup delivery or protection if the local key is lost. Keep the key in a separate secure recovery location; do not commit it.

## Still open

Repository API GITHUB_TOKEN is not configured; anonymous reads constrain scale. Email recovery/provider configuration, external alerts, load baseline, recurring off-host backups, measured accessibility and bundle splitting remain pending. Project score fields are still 0 and need an evidence-based scoring policy. Review discovery is correct but canonical quorum work can still be costly for large histories. See [the updated roadmap](launch-roadmap.md).

Prior A01–A06/A08 and hosted CI A10 were fixed before this release; the first real workflow is established separately by PR #1. Historical audit snapshots are preserved as historical evidence, not current launch status.

References: [OAuth refresh rotation and replay detection, RFC 9700 §4.14.2](https://datatracker.ietf.org/doc/html/rfc9700#section-4.14.2); [nginx dynamic upstream resolve](https://nginx.org/en/docs/http/ngx_http_upstream_module.html#resolve); [CSP connect-src and WebSocket considerations](https://developer.mozilla.org/en-US/docs/Web/HTTP/Reference/Headers/Content-Security-Policy/connect-src).
