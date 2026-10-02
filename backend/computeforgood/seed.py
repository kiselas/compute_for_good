"""Idempotent, opt-in local fixtures. Never seed production identities."""
from sqlalchemy import select
from .config import settings
from .db import SessionLocal
from .models import Project, Task, User
from .services import event, hash_token


def seed():
    if not settings.demo_mode:
        print("DEMO_MODE is false; no demonstration data created.")
        return
    with SessionLocal.begin() as db:
        for username, role in [("alice", "contributor"), ("bob", "reviewer"), ("carol", "reviewer"), ("admin", "operator")]:
            if not db.scalar(select(User.id).where(User.username == username)):
                db.add(User(id=username, username=username, role=role, model_tier="FRONTIER", is_demo=True, token_hash=hash_token("cfg-demo-" + username)))
        db.flush()
        projects = [Project(id="cfg-demo", slug="compute-for-good", name="ComputeForGood", description="Coordination for useful open-source work. Local demonstration fixtures; maintainer consent and GitHub results are simulated.", repository_url="https://github.com/computeforgood/demo", language="Python", status="VERIFIED", impact_score=88, readiness_score=92, is_demo=True), Project(id="candidate-demo", slug="public-interest-tools", name="Public Interest Tools", description="A candidate awaiting explicit maintainer verification. Work cannot be dispatched yet.", repository_url="https://github.com/computeforgood/candidate-demo", language="Python", status="CANDIDATE", impact_score=76, readiness_score=61, is_demo=True)]
        for p in projects:
            if not db.get(Project, p.id):
                db.add(p)
        db.flush()
        titles = ["Document the first contribution workflow", "Add deterministic matching tests", "Make lease expiry safe under concurrency", "Review contributor authorization boundaries", "Improve accessible empty states"]
        for index, (title, risk) in enumerate(zip(titles, ["LOW", "NORMAL", "HIGH", "CRITICAL", "LOW"]), 1):
            task_id = f"CFG-{index:03}"
            if db.get(Task, task_id):
                continue
            tier = "BASIC" if risk == "LOW" else "STRONG" if risk == "NORMAL" else "FRONTIER"
            db.add(Task(id=task_id, project_id="cfg-demo", title=title, description="An illustrative task contract for the local alpha. Use the contribution workflow to explore claiming, checkpointing, permits and independent review.", difficulty="EASY" if risk == "LOW" else "MEDIUM", risk=risk, required_model_tier=tier, estimated_minutes=30 if risk == "LOW" else 90, status="AVAILABLE", acceptance_criteria=["Change addresses the stated objective", "Documented verification passes", "No unrelated changes"], allowed_paths=["docs/**"] if risk == "LOW" else ["backend/**", "tests/**"], forbidden_paths=[".env", "secrets/**"], verification_commands=["python -m pytest tests"], is_demo=True))
            event(db, "work.seeded", task_id, "Demonstration task ready for useful-work loop")
    print("Local demo seed ready: alice, bob, carol, admin; CFG-001 through CFG-005.")


if __name__ == "__main__":
    seed()
