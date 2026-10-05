"""Publish the reviewed first-sprint blueprint through browser-owner REST APIs.

No database writes, credential output, contract replacement or automatic merges.
An interrupted application can be retried; current state is read before changes.
"""
import argparse
from datetime import datetime, timedelta, timezone
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import httpx


def unique(rows, title):
    matches = [row for row in rows if row["title"] == title]
    if len(matches) > 1:
        raise ValueError(f"Duplicate planning title; reconcile manually: {title}")
    return matches[0] if matches else None


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", default="https://compute-for-good.tech")
    parser.add_argument("--login-file", type=Path)
    parser.add_argument("--blueprint", type=Path, default=Path(__file__).resolve().parents[1] / "docs/sprints/first-contribution.json")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    blueprint = json.loads(args.blueprint.read_text(encoding="utf-8-sig"))
    if not args.apply:
        print(json.dumps(blueprint, ensure_ascii=False, indent=2))
        return
    origin = args.origin.rstrip("/")
    target = urlparse(origin)
    if target.path or target.query or target.fragment or target.username or target.scheme != "https" and target.hostname not in {"localhost", "127.0.0.1"}:
        raise ValueError("Use an HTTPS origin, or an explicitly selected local QA origin")
    if not args.login_file:
        raise ValueError("--login-file required for application")
    credentials = json.loads(args.login_file.read_text(encoding="utf-8-sig"))
    if credentials.get("origin", "").rstrip("/") != origin:
        raise ValueError("The private login origin must exactly match --origin")
    with httpx.Client(base_url=origin, headers={"Origin": origin}, timeout=30, follow_redirects=False) as client:
        def request(method, path, body=None):
            response = client.request(method, path, json=body) if body is not None else client.request(method, path)
            # Do not include a response/request body in errors: it may contain credentials.
            if not response.is_success:
                raise RuntimeError(f"{method} {path} returned {response.status_code}; inspect current state before retrying")
            return response.json()

        login = request("POST", "/api/auth/login", {key: credentials[key] for key in ("username", "password")})
        client.headers["X-CSRF-Token"] = login["csrf_token"]
        try:
            projects = request("GET", "/api/maintainer/projects")
            matches = [p for p in projects if p["repository_url"].rstrip("/").removesuffix(".git") == blueprint["repository_url"]]
            if len(matches) != 1 or matches[0]["status"] != "VERIFIED" or matches[0]["is_demo"]:
                raise ValueError("Exactly one real, owned, verified repository is required")
            project = matches[0]
            base = "/api/maintainer/projects/" + project["id"]
            existing_sprints = request("GET", base + "/sprints")
            sprint = next((r for r in existing_sprints if r["slug"] == blueprint["slug"]), None)
            plan = request("GET", base + "/plan")
            goal_body = blueprint["goal"]
            goal = unique(plan["goals"], goal_body["title"])
            if goal:
                if any(goal[k] != v for k, v in goal_body.items()) or goal["status"] != "ACTIVE":
                    raise ValueError("Existing goal changed; do not overwrite it")
            else:
                goal = request("POST", base + "/goals", goal_body)
            task_ids = []
            for item in blueprint["tasks"]:
                proposal = {"goal_id": goal["id"], "title": item["title"], "problem": "First-time users need an accurate, standalone workflow guide.", "outcome": item["description"], "acceptance_criteria": item["acceptance_criteria"], "in_scope": ", ".join(item["allowed_paths"]), "out_of_scope": "Application code, infrastructure, credentials, GitHub settings and the other sprint guides.", "kind": "DOCS", "priority": 1}
                # Re-read each time: publishing can change the improvement version/status.
                plan = request("GET", base + "/plan")
                improvement = unique(plan["improvements"], item["title"])
                if improvement and any(improvement[k] != v for k, v in proposal.items()):
                    raise ValueError("Existing improvement changed; do not overwrite it")
                if not improvement:
                    improvement = request("POST", base + "/improvements", proposal)
                if improvement["status"] == "PROPOSED":
                    improvement = request("PATCH", base + "/improvements/" + improvement["id"], {"version": improvement["version"], "status": "APPROVED"})
                if improvement["status"] not in {"APPROVED", "IN_PROGRESS", "ACCEPTANCE", "DONE"}:
                    raise ValueError("Improvement no longer approves this work")
                contract = {**item, "difficulty": "EASY", "risk": "LOW", "required_model_tier": "BASIC", "forbidden_paths": ["backend/", "frontend/", "deploy/", "scripts/", ".github/", ".env*"], "verification_commands": ["git diff --check"]}
                task = unique(plan["tasks"], item["title"])
                if task and (task["improvement_id"] != improvement["id"] or any(task[k] != v for k, v in contract.items())):
                    raise ValueError("Existing task contract changed; do not overwrite it")
                if not task:
                    task = request("POST", base + "/improvements/" + improvement["id"] + "/tasks", contract)
                if task["status"] == "DRAFT":
                    task = request("POST", base + "/tasks/" + task["id"] + "/publish", {"version": task["version"]})
                if not sprint and task["status"] != "AVAILABLE":
                    raise ValueError("Work was acquired before sprint publication; reconcile manually")
                task_ids.append(task["id"])
            if sprint:
                if {t["id"] for t in sprint["tasks"]} != set(task_ids) or any(sprint[k] != blueprint[k] for k in ("title", "description", "response_hours")):
                    raise ValueError("Existing sprint differs; do not overwrite it")
            else:
                now = datetime.now(timezone.utc)
                body = {k: blueprint[k] for k in ("slug", "title", "description", "response_hours")}
                body.update(starts_at=now.isoformat(), ends_at=(now + timedelta(days=7)).isoformat(), task_ids=task_ids)
                sprint = request("POST", base + "/sprints", body)
            if sprint["status"] == "DRAFT":
                sprint = request("POST", base + "/sprints/" + sprint["id"] + "/publish", {"version": sprint["version"]})
            print(json.dumps({"url": origin + "/sprints/" + sprint["slug"], "status": sprint["status"], "available": sprint["available"], "goal": sprint["goal"], "tasks": [{"id": t["id"], "title": t["title"], "status": t["status"]} for t in sprint["tasks"]]}, ensure_ascii=False, indent=2))
        finally:
            request("POST", "/api/auth/logout")


if __name__ == "__main__":
    main()
