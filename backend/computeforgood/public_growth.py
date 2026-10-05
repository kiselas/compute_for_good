"""Public evidence, portable cards/badges and an outcome activity calendar.

Every read rechecks visibility; no persistent or user-writable social points.
"""
from datetime import date, timedelta
from html import escape
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, Query
from fastapi.responses import HTMLResponse, Response
from sqlalchemy import func, literal, select, union_all

from . import services as s
from .config import settings
from .models import Project, Review, Submission, Task, User
from .reputation import accepted_outcomes, profile_reputation

Lang = Literal["en", "ru", "zh-CN"]
COPY = {
    "en": {"accepted": "A useful change. Accepted.", "review": "Final-commit reviewers", "recorded": "Acceptance recorded", "proof": "View pull request", "next": "Find your next contribution", "demo": "DEMO — simulated outcome", "badge": "accepted contributions", "work": "open tasks", "card": "Download PNG", "profile": "Contributor profile"},
    "ru": {"accepted": "Полезное изменение. Принято.", "review": "Ревьюеры итогового коммита", "recorded": "Принятие зафиксировано", "proof": "Посмотреть PR", "next": "Найти следующую задачу", "demo": "ДЕМО — результат симуляции", "badge": "принятых вкладов", "work": "открытых задач", "card": "Скачать PNG", "profile": "Профиль участника"},
    "zh-CN": {"accepted": "有用的改进。已接受。", "review": "最终提交的审查者", "recorded": "接受记录日期", "proof": "查看拉取请求", "next": "寻找下一项贡献", "demo": "演示 — 模拟结果", "badge": "已接受的贡献", "work": "开放任务", "card": "下载 PNG", "profile": "贡献者资料"},
}
PUBLIC_HEADERS = {"Cache-Control": "no-store", "X-Content-Type-Options": "nosniff"}


def public_user(db, username):
    user = db.scalar(select(User).where(func.lower(User.username) == username.lower(), User.suspended.is_(False)))
    if not user or user.is_demo and not settings.demo_mode:
        s.fail(404, "Contributor profile not found")
    return user


def accepted_reviews(outcomes, is_demo):
    # Same final-head, once-per-PR eligibility as contributor rankings.
    return (select(Review.reviewer_id.label("user_id"), outcomes.c.submission_id,
                   outcomes.c.project_id, outcomes.c.credited_at)
            .join(outcomes, (outcomes.c.submission_id == Review.submission_id) & (outcomes.c.head_sha == Review.head_sha))
            .join(User, User.id == Review.reviewer_id)
            .where(Review.reviewer_id != outcomes.c.user_id, Review.created_at <= outcomes.c.credited_at,
                   User.suspended.is_(False), User.is_demo == is_demo)
            .distinct())


def contribution(db, submission_id):
    now = s.now(db)
    # IDs are resolved only through the same eligible ledger as recognition.
    raw = db.get(Submission, submission_id)
    if not raw or raw.is_demo and not settings.demo_mode:
        s.fail(404, "Accepted contribution not found")
    outcomes = accepted_outcomes(raw.is_demo, as_of=now)
    row = db.execute(select(Submission, Task, Project, User, outcomes.c.credited_at)
                     .join(outcomes, outcomes.c.submission_id == Submission.id)
                     .join(Task, Task.id == Submission.task_id).join(Project, Project.id == Task.project_id)
                     .join(User, User.id == Submission.author_id).where(Submission.id == submission_id)).one_or_none()
    if not row:
        s.fail(404, "Accepted contribution not found")
    submission, task, project, user, recorded = row
    review_rows = accepted_reviews(outcomes, raw.is_demo).subquery()
    reviewers = db.scalars(select(User.username).join(review_rows, User.id == review_rows.c.user_id)
                           .where(review_rows.c.submission_id == submission_id).order_by(User.username).limit(50)).all()
    return {"id": submission.id, "title": task.title, "username": user.username,
            "project": {"id": project.id, "slug": project.slug, "name": project.name},
            "pr_url": submission.pr_url, "head_sha": submission.head_sha, "recorded_at": recorded,
            "reviewers": reviewers, "is_demo": raw.is_demo,
            "share_url": f"{settings.public_url}/share/{quote(submission.id, safe='')}",
            "profile_url": f"{settings.public_url}/people/{quote(user.username, safe='')}",
            "next_url": f"{settings.public_url}/tasks?project_id={quote(project.id, safe='')}"}


def activity(db, user, year):
    now = s.now(db)
    if year > now.year:
        s.fail(422, "Future activity years are unavailable")
    start = date(year, 1, 1)
    end = min(date(year, 12, 31), now.date())
    outcomes = accepted_outcomes(user.is_demo, as_of=now)
    reviews = accepted_reviews(outcomes, user.is_demo).subquery()
    evidence = union_all(
        select(outcomes.c.credited_at, outcomes.c.submission_id,
               literal(1).label("contributions"), literal(0).label("reviews"))
        .where(outcomes.c.user_id == user.id),
        select(reviews.c.credited_at, reviews.c.submission_id,
               literal(0), literal(1))
        .where(reviews.c.user_id == user.id)).subquery()
    day = func.date(func.timezone("UTC", evidence.c.credited_at))
    rows = db.execute(select(day.label("day"), func.sum(evidence.c.contributions).label("contributions"),
                             func.sum(evidence.c.reviews).label("reviews"))
                      .where(day >= start, day <= end).group_by(day).order_by(day)).mappings().all()
    lookup = {row["day"]: row for row in rows}
    days = []
    current = start
    while current <= end:
        row = lookup.get(current, {})
        days.append({"date": current.isoformat(), "contributions": int(row.get("contributions", 0)), "reviews": int(row.get("reviews", 0))})
        current += timedelta(days=1)
    return {"username": user.username, "is_demo": user.is_demo, "year": year, "as_of": now,
            "timezone": "UTC", "days": days, "active_days": len(rows),
            "totals": {key: sum(d[key] for d in days) for key in ("contributions", "reviews")},
            "available_years": list(range(now.year, max(user.created_at.year, 2000) - 1, -1))}


def activity_day(db, user, day):
    now = s.now(db)
    if day > now.date():
        s.fail(422, "Future activity days are unavailable")
    outcomes = accepted_outcomes(user.is_demo, as_of=now)
    reviews = accepted_reviews(outcomes, user.is_demo).subquery()
    records = union_all(
        select(outcomes.c.submission_id, outcomes.c.credited_at, literal("contribution").label("kind"))
        .where(outcomes.c.user_id == user.id),
        select(reviews.c.submission_id, reviews.c.credited_at, literal("review"))
        .where(reviews.c.user_id == user.id)).subquery()
    items = db.execute(select(records.c.submission_id, records.c.kind, Task.title, Project.name.label("project"))
                       .join(Submission, Submission.id == records.c.submission_id).join(Task, Task.id == Submission.task_id)
                       .join(Project, Project.id == Task.project_id)
                       .where(func.date(func.timezone("UTC", records.c.credited_at)) == day)
                       .order_by(records.c.kind, records.c.submission_id).limit(100)).mappings().all()
    return {"date": day, "is_demo": user.is_demo, "items": [dict(item) for item in items], "limit": 100}


def badge(label, value, demo=False):
    # All text is escaped and bounded. SVG contains no links, scripts or external assets.
    label = ("DEMO · " if demo else "") + label
    return f'<svg xmlns="http://www.w3.org/2000/svg" width="420" height="32" role="img" aria-label="{escape(label)}: {escape(value)}"><title>{escape(label)}: {escape(value)}</title><rect width="420" height="32" rx="6" fill="#102b28"/><rect x="270" width="150" height="32" rx="6" fill="#157450"/><g font-family="Verdana,Arial,sans-serif" font-size="12" fill="#fff" text-anchor="middle"><text x="135" y="21">{escape(label)}</text><text x="345" y="21">{escape(value)}</text></g></svg>'


def evidence_html(value, lang):
    c = COPY[lang]
    url = value["share_url"] + "?lang=" + lang
    png = f'{settings.public_url}/api/shares/contributions/{quote(value["id"], safe="")}/card.png?lang={lang}'
    title = f'@{value["username"]} · {value["project"]["name"]}'
    e = escape
    demo = f'<p class="demo">{e(c["demo"])}</p>' if value["is_demo"] else ""
    return f'''<!doctype html><html lang="{lang}"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>{e(title)} — ComputeForGood</title><meta name="description" content="{e(value['title'])}"><meta property="og:type" content="website"><meta property="og:title" content="{e(title)}"><meta property="og:description" content="{e(value['title'])}"><meta property="og:url" content="{e(url)}"><meta property="og:image" content="{e(png)}"><meta property="og:image:width" content="1200"><meta property="og:image:height" content="630"><meta name="twitter:card" content="summary_large_image"><link rel="canonical" href="{e(url)}"><style>body{{font:17px system-ui,sans-serif;background:#f5f8f6;color:#152f29;margin:0}}main{{max-width:900px;margin:40px auto;padding:24px}}img{{width:100%;border-radius:20px}}h1{{font-size:clamp(28px,5vw,46px)}}a{{color:#166a50}}nav{{display:flex;gap:20px;flex-wrap:wrap;margin:24px 0}}.demo{{background:#fff2ce;padding:12px}}footer{{margin-top:30px;font-size:14px}}code{{overflow-wrap:anywhere}}</style></head><body><main><a href="/">ComputeForGood</a>{demo}<h1>{e(c['accepted'])}</h1><img src="{e(png)}" alt="{e(title)}"><h2>{e(value['title'])}</h2><p><a href="{e(value['profile_url'])}">@{e(value['username'])}</a> · {e(value['project']['name'])}</p><p>{e(c['recorded'])}: {value['recorded_at'].date().isoformat()} UTC</p><p>{e(c['review'])}: {e(', '.join('@'+n for n in value['reviewers'])) or '—'}</p><p><code>{e(value['head_sha'])}</code></p><nav><a href="{e(value['pr_url'])}">{e(c['proof'])}</a><a href="{e(png)}&amp;download=true">{e(c['card'])}</a><a href="{e(value['next_url'])}">{e(c['next'])}</a></nav><footer><a href="?lang=en">English</a> · <a href="?lang=ru">Русский</a> · <a href="?lang=zh-CN">简体中文</a></footer></main></body></html>'''


def create_growth_router(database):
    router = APIRouter()
    dep = Depends(database, scope="function")

    @router.get("/api/people/{username}/activity")
    def calendar(username: str, year: int | None = Query(default=None, ge=2000, le=2100), db=dep):
        user = public_user(db, username)
        return activity(db, user, year or s.now(db).year)

    @router.get("/api/people/{username}/activity/day")
    def calendar_day(username: str, day: date, db=dep):
        return activity_day(db, public_user(db, username), day)

    @router.get("/api/shares/contributions/{submission_id}")
    def shared(submission_id: str, db=dep):
        return contribution(db, submission_id)

    @router.get("/share/{submission_id}", response_class=HTMLResponse)
    def shared_page(submission_id: str, lang: Lang = "en", db=dep):
        return HTMLResponse(evidence_html(contribution(db, submission_id), lang), headers=PUBLIC_HEADERS)

    @router.get("/api/shares/contributions/{submission_id}/card.png")
    def shared_image(submission_id: str, lang: Lang = "en", shape: Literal["wide", "portrait"] = "wide", download: bool = False, db=dep):
        value = contribution(db, submission_id)
        from .share_images import render_card
        headers = dict(PUBLIC_HEADERS)
        if download:
            headers["Content-Disposition"] = 'attachment; filename="computeforgood-contribution.png"'
        return Response(render_card(value, COPY[lang], shape, lang), media_type="image/png", headers=headers)

    @router.get("/api/badges/people/{username}.svg")
    def person_badge(username: str, lang: Lang = "en", db=dep):
        user = public_user(db, username)
        metrics = profile_reputation(db, user)["metrics"]
        return Response(badge("ComputeForGood", f'{metrics["accepted_contributions"]} · {COPY[lang]["badge"]}', user.is_demo), media_type="image/svg+xml", headers=PUBLIC_HEADERS)

    @router.get("/api/badges/projects/{project_id}.svg")
    def project_badge(project_id: str, lang: Lang = "en", db=dep):
        return _project_badge(db, project_id, lang)

    return router


def _project_badge(db, project_id, lang):
    from .maintainer_planning import check_dispatch
    p = db.scalar(select(Project).where((Project.id == project_id) | (Project.slug == project_id), Project.status == "VERIFIED"))
    if not p or p.is_demo and not settings.demo_mode:
        s.fail(404, "Project not found")
    tasks = db.scalars(select(Task).where(Task.project_id == p.id, Task.is_demo == p.is_demo, Task.status == "AVAILABLE", Task.risk.in_(["LOW", "NORMAL"]))).all()
    count = 0
    from fastapi import HTTPException
    for task in tasks:
        try:
            check_dispatch(db, task)
            count += 1
        except HTTPException:
            pass
    return Response(badge("ComputeForGood", f'{count} · {COPY[lang]["work"]}', p.is_demo), media_type="image/svg+xml", headers=PUBLIC_HEADERS)
