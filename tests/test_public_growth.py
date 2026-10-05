"""Public growth surfaces obey the canonical ledger and browser-owner boundary."""
from dataclasses import replace
from datetime import timedelta
from io import BytesIO
import uuid

from PIL import Image
import pytest
from sqlalchemy import delete

from computeforgood.models import BrowserSession, Event, PlanningAction, Sprint, SprintTask, Task
from computeforgood import auth
from computeforgood.services import hash_token
from test_backend_boundaries import source_client, operator_pat
from test_reputation import recognition


def test_calendar_matches_recognition_and_uses_recorded_acceptance_date(recognition):
    f = recognition
    author, reviewer = f.user(), f.user()
    row = f.outcome(author, f.project(), age=1)
    f.review(reviewer, row)
    f.review(author, row)
    f.review(reviewer, row, sha="b" * 40)
    day = (f.now - timedelta(days=1)).date().isoformat()
    def read(user):
        response = f.client.get(f"/api/people/{user.username}/activity")
        assert response.status_code == 200, response.text
        return response.json()
    author_year, reviewer_year = read(author), read(reviewer)
    assert author_year["totals"] == {"contributions": 1, "reviews": 0}
    assert reviewer_year["totals"] == {"contributions": 0, "reviews": 1}
    assert author_year["active_days"] == reviewer_year["active_days"] == 1
    assert next(d for d in reviewer_year["days"] if d["date"] == day)["reviews"] == 1
    items = f.client.get(f"/api/people/{reviewer.username}/activity/day?day={day}").json()["items"]
    assert len(items) == 1 and items[0]["kind"] == "review" and items[0]["submission_id"] == row.id
    assert "summary" not in str(items) and "findings" not in str(items)
    assert f.client.get(f"/api/people/{author.username}/activity?year={f.now.year+1}").status_code == 422
    assert f.client.get(f"/api/people/{author.username}/activity/day?day=garbage").status_code == 422


def test_calendar_zero_year_leap_day_and_visibility_revocation(recognition):
    f = recognition
    author = f.user()
    p = f.project()
    f.outcome(author, p)
    assert f.client.get(f"/api/people/{author.username}/activity?year=2024").json()["days"][59]["date"] == "2024-02-29"
    with f.factory.begin() as db:
        db.get(type(p), p.id).status = "SUSPENDED"
    assert f.client.get(f"/api/people/{author.username}/activity").json()["totals"]["contributions"] == 0
    with f.factory.begin() as db:
        db.get(type(author), author.id).suspended = True
    assert f.client.get(f"/api/people/{author.username}/activity").status_code == 404


def test_shares_need_accepted_evidence_and_never_expose_blind_review_text(recognition):
    f = recognition
    author, reviewer = f.user(), f.user()
    p = f.project()
    valid = f.outcome(author, p)
    f.review(reviewer, valid)
    pending = f.outcome(author, p, status="REVIEWING", credit=False)
    for path in (f"/api/shares/contributions/{pending.id}", f"/share/{pending.id}", f"/api/shares/contributions/{pending.id}/card.png"):
        assert f.client.get(path).status_code == 404
    response = f.client.get(f"/api/shares/contributions/{valid.id}")
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["reviewers"] == [reviewer.username]
    assert "summary" not in response.text and "findings" not in response.text
    assert f"project_id={p.id}" in result["next_url"]
    with f.factory.begin() as db:
        db.get(type(p), p.id).status = "SUSPENDED"
    assert f.client.get(f"/api/shares/contributions/{valid.id}").status_code == 404


@pytest.mark.parametrize("lang", ["en", "ru", "zh-CN"])
def test_share_html_is_crawler_readable_escaped_and_png_is_real(recognition, lang):
    f = recognition
    row = f.outcome(f.user(), f.project())
    with f.factory.begin() as db:
        db.get(Task, row.task_id).title = '<script>alert("x")</script> 中文 тест'
    page = f.client.get(f"/share/{row.id}?lang={lang}")
    assert page.status_code == 200 and f'lang="{lang}"' in page.text
    assert 'property="og:image"' in page.text and 'name="twitter:card"' in page.text
    assert "<script>" not in page.text and "&lt;script&gt;" in page.text
    assert page.headers["cache-control"] == "no-store"
    for shape, size in (("wide", (1200, 630)), ("portrait", (1080, 1350))):
        response = f.client.get(f"/api/shares/contributions/{row.id}/card.png?lang={lang}&shape={shape}&download=true")
        assert response.status_code == 200, response.text[:100]
        assert response.headers["content-type"] == "image/png"
        assert Image.open(BytesIO(response.content)).size == size
        assert "attachment" in response.headers["content-disposition"]
    assert f.client.get(f"/api/shares/contributions/{row.id}/card.png?lang=bogus").status_code == 422


def test_badges_are_escaped_live_and_cached_cards_cannot_bypass_suspension(recognition):
    f = recognition
    author, p = f.user(), f.project()
    row = f.outcome(author, p)
    result = f.client.get(f"/api/badges/people/{author.username}.svg?lang=ru")
    assert result.status_code == 200 and "1 ·" in result.text and "<script" not in result.text
    assert f.client.get(f"/api/shares/contributions/{row.id}/card.png").status_code == 200
    with f.factory.begin() as db:
        db.get(type(author), author.id).suspended = True
    assert f.client.get(f"/api/badges/people/{author.username}.svg").status_code == 404
    assert f.client.get(f"/api/shares/contributions/{row.id}/card.png").status_code == 404


def test_demo_growth_never_escapes_production(recognition, monkeypatch):
    f = recognition
    author = f.user(demo=True)
    row = f.outcome(author, f.project(demo=True))
    import computeforgood.public_growth as growth
    monkeypatch.setattr(growth, "settings", replace(growth.settings, demo_mode=False))
    for path in (f"/share/{row.id}", f"/api/shares/contributions/{row.id}/card.png", f"/api/people/{author.username}/activity", f"/api/badges/people/{author.username}.svg"):
        assert f.client.get(path).status_code == 404


@pytest.fixture
def sprint_case(recognition):
    f = recognition
    owner = f.user()
    project = f.project()
    raw = "qa-sprint-browser-" + uuid.uuid4().hex
    with f.factory.begin() as db:
        db.get(type(project), project.id).maintainer_id = owner.id
        session = BrowserSession(user_id=owner.id, token_hash=hash_token(raw), expires_at=f.now + timedelta(hours=1))
        db.add(session)
        task = Task(project_id=project.id, title="Public sprint task", description="An isolated full task contract",
                    acceptance_criteria=["A verifiable outcome"], allowed_paths=["docs/"], forbidden_paths=["backend/"],
                    verification_commands=["git diff --check"], status="AVAILABLE", is_demo=False)
        db.add(task)
        db.flush()
        ids = session.id, task.id
    f.client.cookies.set("cfg_session", raw)
    headers = {"X-CSRF-Token": auth.csrf_token(raw), "Origin": auth.settings.frontend_url}
    body = {"slug": "qa-sprint-" + uuid.uuid4().hex[:12], "title": {"en": "Public sprint", "ru": "Спринт", "zh-CN": "冲刺"},
            "description": {"en": "A prepared task", "ru": "Подготовленная задача", "zh-CN": "准备好的任务"},
            "starts_at": (f.now - timedelta(hours=1)).isoformat(), "ends_at": (f.now + timedelta(days=7)).isoformat(),
            "response_hours": 72, "task_ids": [task.id]}
    created = []
    base = f"/api/maintainer/projects/{project.id}/sprints"
    def create(changes=None, expected=201):
        response = f.client.post(base, headers=headers, json={**body, **(changes or {})})
        assert response.status_code == expected, response.text
        if expected == 201:
            created.append(response.json()["id"])
        return response.json()
    yield f, owner, project, task, headers, body, base, create
    f.client.cookies.clear()
    with f.factory.begin() as db:
        db.execute(delete(SprintTask).where(SprintTask.sprint_id.in_(created)))
        db.execute(delete(Sprint).where(Sprint.id.in_(created)))
        db.execute(delete(PlanningAction).where(PlanningAction.project_id == project.id))
        db.execute(delete(Event).where(Event.entity_id.in_(created)))
        db.execute(delete(BrowserSession).where(BrowserSession.id == ids[0]))
        db.execute(delete(Task).where(Task.id == ids[1]))


def test_owner_sprint_draft_publish_pause_and_version(sprint_case):
    f, owner, p, task, headers, body, base, create = sprint_case
    draft = create()
    assert f.client.get("/api/sprints/" + draft["slug"]).status_code == 404
    path = f'{base}/{draft["id"]}/publish'
    assert f.client.post(path, headers=headers, json={"version": 99}).status_code == 409
    published = f.client.post(path, headers=headers, json={"version": draft["version"]})
    assert published.status_code == 200, published.text
    public = f.client.get("/api/sprints/" + draft["slug"]).json()
    assert public["available"] == public["goal"] == 1 and public["accepted"] == 0
    assert public["owner"] == owner.username and public["state"] == "active"
    paused = f.client.post(f'{base}/{draft["id"]}/pause', headers=headers, json={"version": public["version"]})
    assert paused.status_code == 200
    assert f.client.get("/api/sprints/" + draft["slug"]).json()["available"] == 0


def test_sprint_rejects_mixed_tasks_missing_contract_and_agent_publish(sprint_case, database):
    f, owner, p, task, headers, body, base, create = sprint_case
    other = f.outcome(f.user(), f.project())
    create({"task_ids": [other.task_id]}, expected=422)
    create({"task_ids": [task.id, task.id]}, expected=422)
    create({"title": {"en": "English only"}}, expected=422)
    draft = create()
    with f.factory.begin() as db:
        db.get(Task, task.id).allowed_paths = []
    assert f.client.post(f'{base}/{draft["id"]}/publish', headers=headers, json={"version": 1}).status_code == 422
    agent = operator_pat(database, owner)
    assert f.client.post(base, headers=agent, json=body).status_code == 403
    # Remove only the temporary access credential made above before user cleanup.
    from computeforgood.models import ApiCredential
    with f.factory.begin() as db:
        db.execute(delete(ApiCredential).where(ApiCredential.user_id == owner.id))


def test_sprint_progress_is_period_bounded_and_hides_private_states(sprint_case):
    f, owner, p, task, headers, body, base, create = sprint_case
    row = f.outcome(owner, p)
    reviewer = f.user()
    f.review(reviewer, row)
    draft = create()
    assert f.client.post(f'{base}/{draft["id"]}/publish', headers=headers, json={"version": 1}).status_code == 200
    with f.factory.begin() as db:
        db.add(SprintTask(sprint_id=draft["id"], task_id=row.task_id))
        db.get(Task, task.id).status = "AWAITING_MAINTAINER"
    result = f.client.get("/api/sprints/" + draft["slug"]).json()
    assert result["accepted"] == 1 and result["participants"] == 2 and result["accepted_reviews"] == 1
    assert next(t for t in result["tasks"] if t["id"] == task.id)["status"] == "REVIEWING"
    assert "reviewer_id" not in str(result) and "findings" not in str(result)
    with f.factory.begin() as db:
        db.get(Sprint, draft["id"]).starts_at = f.now + timedelta(minutes=1)
    assert f.client.get("/api/sprints/" + draft["slug"]).json()["accepted"] == 0
    with f.factory.begin() as db:
        db.get(type(p), p.id).status = "SUSPENDED"
    assert f.client.get("/api/sprints/" + draft["slug"]).status_code == 404
