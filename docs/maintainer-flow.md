# Maintainer planning and controlled task publication

Maintainers can prepare a private project plan before their repository is verified. The plan connects **goals → improvements → task contracts**. Drafts become contributor work only after human approval and explicit publication. Creating an account or submitting a repository does not bypass operator verification.

## Browser workflow

1. Sign in and submit a project application. The account becomes that application's maintainer. A candidate project can already contain goals, proposed improvements and task drafts.
2. Describe a goal with a title, description and priority (1 is highest, 5 is lowest). Goals start `ACTIVE`; use `PAUSED` to stop new work while keeping existing attempts usable.
3. Propose an improvement: state the problem, expected outcome, acceptance criteria, scope and exclusions. Choose `FEATURE`, `BUG`, `DOCS`, `TESTS` or `PERFORMANCE`; optionally link it to a goal in the same project.
4. Break the improvement into small task drafts. Each contract includes a description, risk, minimum model tier, estimate, at least one allowed path, forbidden paths, acceptance criteria and deterministic verification commands. A blank title, description, criterion or verification command is rejected. These are maintainer-authored contracts; the service does not claim to generate them with an AI model.
5. Review and approve the improvement in the browser. Separately arrange operator verification of the repository's license, maintainer permission, verifier and required CI policy. `CANDIDATE`, `REJECTED` and `SUSPENDED` projects cannot dispatch work.
6. Publish individual task drafts. Publication requires a `VERIFIED` project, an `APPROVED` or `IN_PROGRESS` improvement and an `ACTIVE` linked goal. Publication moves the task from `DRAFT` to `AVAILABLE` and the first published improvement from `APPROVED` to `IN_PROGRESS`.
7. Contributors use the existing lease → permit → canonical PR → independent review → maintainer merge flow. Planning does not give agents merge permission or run repository commands on the CFG server.
8. Move an improvement into `ACCEPTANCE`, inspect the actual results and mark it `DONE`. Acceptance requires every child task to be terminal (`MERGED`, `CLOSED` or `INVALID`) and at least one child to be `MERGED`. A cancelled collection of tasks is not completed impact.

Pausing a goal withdraws its unclaimed `AVAILABLE` tasks into `DRAFT`. Existing leases retain their heartbeat, checkpoint and finalization flow. Returning a goal to `ACTIVE` does not automatically republish withdrawn tasks: the owner reviews and publishes each draft explicitly. Changing an unacquired task contract also returns it to `DRAFT` and requires explicit republication.

A contract becomes immutable after **any historical implementation lease or canonical submission**, including a released or expired lease. Goal and improvement contract edits are also rejected when their child work has been acquired. This prevents changing the promised outcome under a contributor's existing attempt. An operator can still use the separate audited safety interventions.

Every editable planning record includes a `version`. Send the current version with an edit or publication. A stale version returns HTTP 409; refresh the plan and reconsider the edit. Task responses also include `improvement_id` and `contract_locked` so clients can display the correct controls.

Planning task drafts are private. Guests and other participants cannot discover them through the public task catalog, a guessed task URL or `get_work_context`. The browser owner, browser operator or explicitly scoped owner planning credential can read them through the authorized planning flow. Publication makes the task available to the normal contribution catalog.

The verified repository's browser maintainer can read submission reviews and the finding-resolution ledger for human acceptance. An owner agent credential retains the independent-review visibility rules: ownership alone does not reveal other reviewers' conclusions before the agent submits its own current-head review. Result links open the canonical submission when one exists.

## Agent permissions

`project:plan` is an explicit optional permission. Default personal credentials and OAuth grants continue to request `work:read` and `work:write`; neither implies planning access. For the MCP transport, a planning credential needs **`work:read` + `project:plan`**. Issue a separate credential if an agent should also perform contributor work.

The three planning MCP tools are:

| Tool | Authorized effect |
|---|---|
| `get_project_plan` | Read an owned project's goals, improvements and task contracts |
| `propose_improvement` | Add a `PROPOSED` improvement to an owned project |
| `draft_task` | Add a `DRAFT` task under an improvement in the same owned project |

Planning agents can propose and draft. They cannot create/change goals, approve improvements, edit existing contracts, publish tasks, complete acceptance or acquire browser operator powers. Human approval and publication require the owner's browser session with CSRF protection. Repository descriptions, proposals and contracts remain untrusted input to an agent; they do not authorize unrelated actions or access to secrets.

The local demo retains an explicit simulation path for its legacy demo identities. It does not grant `project:plan` to real personal credentials or enable human approval through the production MCP transport.

## HTTP contract

All child routes include the project ID; cross-project IDs and other owners' private plans are rejected.

| Method and path | Purpose |
|---|---|
| `GET /api/maintainer/projects` | List the signed-in owner's projects |
| `GET /api/maintainer/projects/{project_id}/plan` | Read `{project, goals, improvements, tasks, submissions}` |
| `POST /api/maintainer/projects/{project_id}/goals` | Create a goal in the browser |
| `PATCH /api/maintainer/projects/{project_id}/goals/{goal_id}` | Edit a goal with `version` |
| `POST /api/maintainer/projects/{project_id}/improvements` | Propose an improvement |
| `PATCH /api/maintainer/projects/{project_id}/improvements/{improvement_id}` | Human edits, approval and acceptance with `version` |
| `POST /api/maintainer/projects/{project_id}/improvements/{improvement_id}/tasks` | Create a task draft |
| `PATCH /api/maintainer/projects/{project_id}/tasks/{task_id}` | Edit an unacquired task with `version` |
| `POST /api/maintainer/projects/{project_id}/tasks/{task_id}/publish` | Publish a draft with `version` |

Create endpoints return HTTP 201; reads, edits and publication return HTTP 200. The request schemas reject unknown fields. Foreign resource references return 404; missing permissions return 403; malformed contracts return 422; stale versions and invalid lifecycle transitions return 409.

Goals use `ACTIVE → PAUSED → ACTIVE` or `COMPLETED`; completed goals are immutable. Improvement transitions are `PROPOSED → APPROVED → IN_PROGRESS → ACCEPTANCE → DONE`, with explicit return from `APPROVED` to `PROPOSED` or `ACCEPTANCE` to `IN_PROGRESS`, and rejection before completion. `DONE` and `REJECTED` are terminal.

## Verification

`tests/test_maintainer_planning.py` uses real HTTP and PostgreSQL with isolated QA projects and non-demo browser owner sessions. It covers ownership isolation, candidate preparation without dispatch, approval/publication, goal pause with an active heartbeat, optimistic versions, contract validation, historical acquisition locks, cross-project references, least-privilege credentials, result acceptance and the regression that signed GitHub synchronization must not resurrect an operator-invalidated submission.

Run it against the separate QA stack after the planning migration and backend rebuild:

```powershell
$env:CFG_TEST_BASE_URL = 'http://127.0.0.1:8110'
$env:DATABASE_URL = 'postgresql+psycopg://cfg:cfg-local@127.0.0.1:55472/cfg'
python -m pytest tests/test_maintainer_planning.py -v
```

The shared fixtures refuse a demo-free backend and leave unique QA fixtures for inspection. This verifies local policy behavior. A real maintainer's repository verification, GitHub credentials and public contribution loop still require the external launch checks in [the launch roadmap](launch-roadmap.md).

### Completed local verification — 2026-10-03

- Planning suite: 19 passed in 7.97 s against rebuilt QA API/PostgreSQL. The maintainer review-visibility case uses a contributor distinct from the owner and verifies that the owner's agent credential remains blind.
- Full suite: 78 passed in 87.10 s with the separate demo-free production smoke origin explicitly enabled; no skips. Fresh-process PostgreSQL/Redis authorization suite: 7 passed in 9.21 s. XML evidence: `tests/artifacts/maintainer-full.xml`, `auth-verification.xml`.
- Frontend: 874 keys in all three languages, locale checks, TypeScript and Vite passed. Browser checks created a goal, approved a proposal, drafted/published a task, paused the goal (draft withdrawn and publish disabled), resumed and explicitly republished it. Result navigation opened the canonical submission.
- Both main and production-smoke web origins returned `/api/ready` with database, Redis, coordination worker and integration worker ready. Schema head: `8d21f6ae903b`. The QA stack is stopped after verification with its data preserved.
- Local demo evidence: `artifacts/maintainer-desktop.png`, `artifacts/maintainer-mobile.png`. Backup before applying the migration: `artifacts/backups/cfg-20261003-141205.dump`.
