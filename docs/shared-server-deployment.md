# Deployment on the shared server

ComputeForGood uses `185.115.33.169` alongside Content Factory and VPN services. Its dedicated Compose project is `compute-for-good`, installed below `/opt/compute-for-good`. The application uses the production origin `https://compute-for-good.tech`, secure cookies and no demo fixtures. PostgreSQL and Redis have no host ports. Each service has a memory limit, bounded logs and an automatic restart policy. Only `cfg-gateway` joins the existing `edge_net` network; the application frontend has no conflicting `frontend` alias on that network.

## DNS activation

| Type | Name | Value |
|---|---|---|
| A | `@` | `185.115.33.169` |
| CNAME | `www` | `compute-for-good.tech` |

Use the provider's default TTL. Remove conflicting A/AAAA records for these names; IPv6 deployment has not been verified. For initial certificate issuance, use direct DNS routing rather than a CDN proxy. DNS is managed by the owner. Caddy obtains and renews certificates after the records resolve to this server. Until then public HTTPS is pending, even when the application and workers are healthy.

The existing edge continues to own ports 80/443. `deploy/edge-routes.py --apply` adds only the two CFG domains, with a private backup, concurrent-edit check, `nginx -t` and graceful reload. Existing Reality, subscription and Content Factory branches remain intact. TLS traffic follows SNI → loopback port 8547 → `cfg-gateway:443`. Both stream hops carry PROXY protocol; Caddy accepts it only from the verified edge address `172.22.0.3/32`. If that container's address changes, inspect and update this trust setting before enabling the replacement. HTTP Host routing forwards redirects and ACME challenges to `cfg-gateway:80`.

## Release operation

GitHub publishes commit-tagged backend and frontend images only after successful CI for the current `main` SHA. The server's existing SSH policy admits only `root`, so deployment uses a dedicated forced-command key under that account. The administrator-owned dispatcher validates the exact deployment command. The key cannot open an interactive shell or forward ports; the general SSH policy is unchanged. Application secrets are generated directly into the private host environment file; CI receives no application or database secret.

The administrator installs `deploy/ci-dispatch.sh` and `deploy/deploy-release.sh` in `/opt/compute-for-good/bin`, owned by root and mode 0700. The dedicated key is authorized with `restrict,command="/opt/compute-for-good/bin/ci-dispatch"`; the dispatcher validates `SSH_ORIGINAL_COMMAND`. This installation is separate from normal application releases.

`deploy-release <full-sha>` serializes updates with `flock`, fetches and archives the exact source commit, pulls matching images using temporary job credentials, and validates Compose without printing its environment. Before updating an existing database it saves a private custom-format `pg_dump` and validates the archive index. It applies migrations, waits for individual service health including both worker heartbeats, then checks `/api/ready` and the existing Content Factory/subscription HTTPS endpoints. It advances `current-sha` only after these checks pass. A failed update retains its backup and does not mark the new release successful.

## Inspection before DNS

The host disables SSH TCP forwarding. An administrator can inspect the private production frontend using a command on the server:

```sh
ssh nextdish-intl 'curl -fsS http://127.0.0.1:5181/api/ready'
```

Port 5181 is bound only to the server's loopback interface. Public login requires the configured HTTPS origin and secure cookies. Browser inspection of the public site follows DNS activation; do not weaken the host's forwarding or authentication policy to create a temporary preview.

## Recovery and launch checks

Inspect `current-sha`, `previous-sha`, Compose health and the retained database archives in `/opt/compute-for-good/backups`. Do not downgrade a database migration automatically. A previous image is usable only when compatible with the current schema; otherwise restore the database backup during a coordinated maintenance window. Removing application volumes is not a rollback procedure.

After DNS resolves, verify the apex and `www` redirect with valid TLS, `/api/ready`, account registration/login, Socket.IO and authenticated MCP access. Configure the GitHub OAuth application and webhook separately and verify a real repository/PR lifecycle. CI's controlled GitHub tests do not prove that live integration. Keep launch decisions tied to observed checks and the remaining items in the project audit.
