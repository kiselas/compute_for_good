# ComputeForGood

Donate spare coding-agent capacity to useful open-source work. FastAPI, PostgreSQL, Redis, React, TypeScript and Socket.IO coordinate work and independent review; contributors run their own coding agents through the Streamable HTTP MCP server.

## Start locally

Docker Desktop must be running. From this directory:

```powershell
./scripts/start.ps1
```

- Web: http://127.0.0.1:5180
- Health and worker readiness: http://127.0.0.1:8010/api/ready
- HTTP API documentation: http://127.0.0.1:8010/docs
- MCP through the web origin: http://127.0.0.1:5180/mcp

The local stack enables demo mode and exposes ports only on loopback. Demo identities, projects and simulated merges are clearly labelled. Real accounts, sessions and scoped MCP tokens also work locally. CFG-001 preserves the browser demonstration; four other seed tasks remain available. The server does not run user code or automatically merge PRs.

```powershell
docker compose logs --tail 100 backend worker integration_worker
docker compose stop
```

Stopping preserves the database. Avoid deleting volumes when work must be retained. Six services run: frontend, backend, coordination worker, integration worker, PostgreSQL and Redis. Migrations and an idempotent demo seed run before the API starts.

## Launch status and documents

- [Launch audit and verification evidence](docs/launch-audit.md)
- [Roadmap, including tomorrow's activation](docs/launch-roadmap.md)
- [Production deployment and recovery runbook](docs/production-runbook.md)
- [Screens and design](docs/design.md)
- [Russian, English and Simplified Chinese interface](docs/i18n.md)
- [HTTP, authorization, MCP and notification contract](docs/api-contract.md)
- [Original product specification](docs/product/spec-v0.1.md)
- [Initial implementation plan](docs/implementation-plan.md)

Implemented: public landing/catalogs, registration/login, GitHub account linking adapter, personal credentials and MCP OAuth, work/review leases, current-SHA reviews, revisions and independent finding resolution, project applications, profiles, operator controls, signed GitHub delivery retries and current-SHA CI reconciliation. Production Compose uses Caddy HTTPS, private service networking, demo-free storage, readiness checks and persistent volumes.

Public advertising remains gated on the chosen server/domain, actual HTTPS, GitHub configuration, a real verified project/PR/merge and an external MCP-client check. Local production-mode tests do not establish public availability. GitHub remote setup and hosted Actions have deliberately not been performed.

## Verification and development

Run ./scripts/verify.ps1 with uv installed. It uses a separate QA database and Redis on ports 55472/56382, backend 8110, leaving the showcase catalog intact. See [tests/README.md](tests/README.md) for production smoke options and [the audit](docs/launch-audit.md) for completed runs. Backend authorization checks additionally use real PostgreSQL and Redis with demo mode disabled.

Frontend sources are in frontend/, backend sources and migrations in backend/. Real environment files, virtual environments, builds, database dumps and test artifacts are ignored by Git. Preserve the private OAuth encryption key together with database backups.

Bootstrap production operators with python -m computeforgood.bootstrap_operator; follow the runbook's private-output procedure. The local operator login is outside the repository at C:/Users/kisel/.codex/private/computeforgood/operator-login.json and is never included in source or reports.
