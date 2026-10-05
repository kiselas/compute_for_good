"""Recognition anti-farming and visibility regressions against real PostgreSQL."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import uuid

import pytest
from sqlalchemy import delete

from computeforgood.models import ImpactCredit, Project, Review, Submission, Task, User
from computeforgood.reputation import profile_reputation
from test_backend_boundaries import source_client


@pytest.fixture
def recognition(source_client):
    client, factory = source_client
    prefix = "qa-recognition-" + uuid.uuid4().hex[:10]
    now = datetime.now(timezone.utc)
    ids = {kind: [] for kind in (User, Project, Task, Submission, Review, ImpactCredit)}

    def add(db, row):
        db.add(row)
        db.flush()
        ids[type(row)].append(row.id)
        return row

    def user(demo=False, suspended=False):
        with factory.begin() as db:
            return add(db, User(username=prefix + "-" + uuid.uuid4().hex[:6],
                                token_hash=uuid.uuid4().hex * 2, role="contributor",
                                is_demo=demo, suspended=suspended))

    def project(demo=False, status="VERIFIED"):
        with factory.begin() as db:
            return add(db, Project(slug=prefix + "-" + uuid.uuid4().hex[:6], name="Isolated recognition QA",
                                   repository_url="https://github.com/cfg-alpha-test/" + uuid.uuid4().hex,
                                   status=status, is_demo=demo))

    def outcome(author, project, status="MERGED", credit=True, age=0, **changes):
        with factory.begin() as db:
            task = add(db, Task(project_id=project.id, title="Isolated recognition contract",
                                status=status, is_demo=author.is_demo))
            row = add(db, Submission(task_id=task.id, author_id=author.id, pr_url=project.repository_url + "/pull/" + str(len(ids[Submission]) + 1),
                                     head_sha="a" * 40, status=status, human_approved=status == "MERGED",
                                     checks_passed=True, is_demo=author.is_demo, **changes))
            if credit:
                add(db, ImpactCredit(submission_id=row.id, user_id=author.id, is_demo=author.is_demo,
                                     created_at=now - timedelta(days=age)))
            return row

    def review(reviewer, submission, sha=None, late=False):
        with factory.begin() as db:
            return add(db, Review(submission_id=submission.id, reviewer_id=reviewer.id,
                                  head_sha=sha or submission.head_sha, decision="APPROVE",
                                  summary="Isolated review summary must not leak into ranking responses",
                                  findings=[], model_tier="FRONTIER",
                                  created_at=now + timedelta(days=1) if late else now - timedelta(days=60)))

    yield type("RecognitionFixtures", (), dict(client=client, factory=factory, now=now,
                                               user=staticmethod(user), project=staticmethod(project),
                                               outcome=staticmethod(outcome), review=staticmethod(review)))()
    # Remove only fixtures made by this test, in foreign-key order.
    with factory.begin() as db:
        for model in reversed(list(ids)):
            if ids[model]:
                db.execute(delete(model).where(model.id.in_(ids[model])))


def profile(f, user):
    response = f.client.get("/api/people/" + user.username)
    assert response.status_code == 200, response.text
    return response.json()


def standings(f, **params):
    response = f.client.get("/api/leaderboard", params={"limit": 100, **params})
    assert response.status_code == 200, response.text
    return response.json()


def test_only_canonical_accepted_outcomes_earn_progress(recognition):
    f = recognition
    author, reviewer = f.user(), f.user()
    p = f.project()
    valid = f.outcome(author, p)
    f.review(reviewer, valid)
    f.review(reviewer, valid, sha="b" * 40)  # obsolete head
    f.review(author, valid)  # illicit self-review fixture earns nothing
    pending = f.outcome(author, p, status="REVIEWING", credit=False)
    f.review(reviewer, pending)
    f.outcome(author, p, status="CLOSED", credit=False)
    f.outcome(author, p, status="INVALID", credit=True)  # inconsistent credit
    f.outcome(author, p, credit=False)  # no authoritative credit
    f.outcome(author, f.project(status="CANDIDATE"))  # hidden project
    value = profile(f, author)
    assert value["reputation"]["metrics"] == {"accepted_contributions": 1, "accepted_reviews": 0, "projects_helped": 1}
    assert value["reputation"]["acceptance"] == {"accepted": 1, "decided": 3, "rate": 33.3}
    assert [row["id"] for row in value["contributions"]] == [valid.id]
    assert profile(f, reviewer)["reputation"]["metrics"]["accepted_reviews"] == 1
    assert profile(f, reviewer)["stats"]["reviews"] == 1
    data = standings(f, metric="reviews")
    assert not any(row["username"] == author.username for row in data["entries"])
    assert "summary" not in str(data) and reviewer.id not in str(data)


def test_demo_real_suspended_and_mismatched_credits_are_separate(recognition):
    f = recognition
    real, demo, suspended = f.user(), f.user(demo=True), f.user(suspended=True)
    real_pr = f.outcome(real, f.project())
    f.outcome(demo, f.project(demo=True))
    f.outcome(suspended, f.project())
    # A mixed-realm credit must not inflate real rankings or achievements.
    with f.factory.begin() as db:
        credit = db.query(ImpactCredit).filter_by(submission_id=real_pr.id).one()
        credit.is_demo = True
    real_names = {row["username"] for row in standings(f)["entries"]}
    assert not {real.username, demo.username, suspended.username} & real_names
    assert demo.username in {row["username"] for row in standings(f, demo=True)["entries"]}
    assert f.client.get("/api/people/" + suspended.username).status_code == 404
    assert profile(f, real)["reputation"]["metrics"]["accepted_contributions"] == 0


def test_period_uses_credit_date_and_ties_keep_stable_ranks(recognition):
    f = recognition
    first, second, reviewer = f.user(), f.user(), f.user()
    p = f.project()
    old = f.outcome(first, p, age=31)
    f.review(reviewer, old)
    recent = f.outcome(first, p, age=1)
    f.review(reviewer, recent)  # reviewed long ago, accepted recently
    f.review(f.user(), recent, late=True)  # after acceptance earns nothing
    f.outcome(second, p, age=1)
    all_rows = {r["username"]: r for r in standings(f)["entries"]}
    recent_rows = {r["username"]: r for r in standings(f, period="30d")["entries"]}
    assert all_rows[first.username]["metrics"]["accepted_contributions"] == 2
    assert recent_rows[first.username]["metrics"]["accepted_contributions"] == 1
    assert recent_rows[first.username]["rank"] == recent_rows[second.username]["rank"]
    assert next(r for r in standings(f, metric="reviews", period="30d")["entries"] if r["username"] == reviewer.username)["metrics"]["accepted_reviews"] == 1
    page = standings(f, limit=1)
    next_page = standings(f, limit=1, offset=1)
    assert page["total"] == next_page["total"] and len(page["entries"]) == len(next_page["entries"]) == 1
    assert page["entries"][0]["username"] != next_page["entries"][0]["username"]
    beyond = standings(f, offset=10000)
    assert beyond["entries"] == [] and beyond["total"] == page["total"]


def test_achievement_thresholds_backfill_and_follow_current_evidence(recognition):
    f = recognition
    author, reviewer = f.user(), f.user()
    projects = [f.project() for _ in range(3)]
    for n in range(10):
        row = f.outcome(author, projects[n % 3])
        f.review(reviewer, row)
    value = profile(f, author)["reputation"]
    earned = {a["id"] for a in value["achievements"] if a["earned"]}
    assert earned == {"first_contribution", "five_contributions", "ten_contributions", "cross_project"}
    assert {a["id"] for a in profile(f, reviewer)["reputation"]["achievements"] if a["earned"]} == {"first_review", "five_reviews"}
    with f.factory.begin() as db:
        db.get(Project, projects[0].id).status = "SUSPENDED"
    assert profile(f, author)["reputation"]["metrics"]["accepted_contributions"] == 6
    assert not next(a for a in profile(f, author)["reputation"]["achievements"] if a["id"] == "ten_contributions")["earned"]


def test_new_user_has_no_rank_or_invented_acceptance(recognition):
    f = recognition
    user = f.user()
    reputation = profile(f, user)["reputation"]
    assert reputation["acceptance"]["rate"] is None
    assert not any(a["earned"] for a in reputation["achievements"])
    assert user.username not in {r["username"] for r in standings(f)["entries"]}
    with f.factory() as db:
        assert profile_reputation(db, db.get(User, user.id))["metrics"] == reputation["metrics"]


def test_suspension_between_lookup_and_snapshot_fails_cleanly(recognition):
    from fastapi import HTTPException
    f = recognition
    user = f.user()
    with f.factory() as lookup:
        stale_user = lookup.get(User, user.id)
        assert stale_user.suspended is False
        with f.factory.begin() as moderation:
            moderation.get(User, user.id).suspended = True
        with pytest.raises(HTTPException) as error:
            profile_reputation(lookup, stale_user)
        assert error.value.status_code == 404


@pytest.mark.parametrize("params", [{"metric": "points"}, {"period": "year"}, {"limit": 101}, {"limit": 0}, {"offset": -1}, {"offset": 10001}])
def test_public_query_bounds(recognition, params):
    assert recognition.client.get("/api/leaderboard", params=params).status_code == 422


def test_production_refuses_demo_rankings_and_profiles(recognition, monkeypatch):
    from computeforgood import config
    monkeypatch.setattr(config, "settings", replace(config.settings, demo_mode=False))
    user = recognition.user(demo=True)
    assert recognition.client.get("/api/leaderboard?demo=true").status_code == 404
    assert recognition.client.get("/api/people/" + user.username).status_code == 404
