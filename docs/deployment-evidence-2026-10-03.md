# Initial server deployment evidence

The public source repository is [kiselas/compute_for_good](https://github.com/kiselas/compute_for_good). Initial release `88b8727759fc75430a259f453a01a85aa6d03ec5` passed [hosted CI](https://github.com/kiselas/compute_for_good/actions/runs/37122699347) and was installed by the [production workflow](https://github.com/kiselas/compute_for_good/actions/runs/37122897605), both successful. Hosted XML evidence confirms 87 integration/production checks and 7 authentication checks, zero failures, errors or skips.

Post-deployment server checks confirmed:

- The exact release SHA, six healthy application/storage/worker containers, and running Caddy gateway.
- `/api/ready`: database, Redis, coordination worker and integration worker ready.
- Empty production project catalog; no demo fixture projects.
- MCP discovery using the configured HTTPS issuer and S256 PKCE; anonymous tool requests return 401.
- Both domain Host routes return 301 to `https://compute-for-good.tech/` after graceful nginx reload.
- Existing Content Factory and VPN subscription endpoints return 200 with valid TLS. This is not a VPN tunnel exercise.
- A private initial database archive was restored successfully to a separate scratch database. Migration revision and account/project counts match; the scratch database was then removed. The archive remains on the host.
- A generated operator login was saved in private server and local storage outside Git. No credential value was printed or committed.

The shared host retains approximately 1.6 GiB available RAM and 11 GiB free disk after installation. Only the two CFG domain routes were added to the existing edge; its prior configuration was backed up before the change. The CI key rejects shell access, invalid commit identifiers and command injection. The existing SSH admission and forwarding policies were preserved.

At verification time both domains resolve to the registrar's parking address `95.163.244.138`. The owner must replace the apex A record with `185.115.33.169` and set `www` to a CNAME for the apex, as described in [the deployment runbook](shared-server-deployment.md). Caddy retries certificate issuance automatically. Public domain TLS, real browser login, an external MCP client and a live GitHub repository/PR lifecycle remain unverified pending DNS and GitHub OAuth/webhook configuration. A successful server deployment does not by itself close these launch checks or the remaining audit findings.
