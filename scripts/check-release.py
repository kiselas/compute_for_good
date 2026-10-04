"""Read-only release gate: exact images, fresh worker ticks, and public HTTPS."""
import argparse
from datetime import datetime
import json
import re
import subprocess
import time
from urllib.request import HTTPRedirectHandler, build_opener

SERVICES = {"postgres", "redis", "backend", "worker", "integration_worker", "frontend", "cfg-gateway"}
IMAGE_ROOT = "ghcr.io/kiselas/compute-for-good-"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, request, file, code, message, headers, new_url):
        return None


def open_url(url, timeout=5):
    # A ready-looking page on another host must never qualify this origin.
    return build_opener(NoRedirect()).open(url, timeout=timeout)


def docker(*arguments):
    return subprocess.check_output(["docker", *arguments], text=True, timeout=15).strip()


def release_errors(containers, release, heartbeats, timestamp):
    roles = {}
    errors = []
    for row in containers:
        role = row["Config"]["Labels"].get("com.docker.compose.service")
        if role not in SERVICES:
            continue
        if role in roles:
            errors.append("Duplicate container for " + role)
        roles[role] = row
    for role in sorted(SERVICES):
        row = roles.get(role)
        if row is None:
            errors.append("Missing container for " + role)
            continue
        state = row["State"]
        if state.get("Status") != "running":
            errors.append(role + " is not running")
        if role != "cfg-gateway" and state.get("Health", {}).get("Status") != "healthy":
            errors.append(role + " is not healthy")
        if role in {"backend", "worker", "integration_worker", "frontend"}:
            component = "frontend" if role == "frontend" else "backend"
            if row["Config"]["Image"] != IMAGE_ROOT + component + ":" + release:
                errors.append(role + " is running a different release")
        if role in {"worker", "integration_worker"}:
            try:
                # Docker uses nanoseconds; Ubuntu's Python 3.10 accepts only
                # microseconds in fromisoformat, unlike newer CI runtimes.
                start_text = re.sub(r"(\.\d{6})\d+(?=Z|[+-]|$)", r"\1", state["StartedAt"])
                started = datetime.fromisoformat(start_text.replace("Z", "+00:00")).timestamp()
                heartbeat = float(heartbeats[role])
                age = timestamp - heartbeat
                max_age = 30 if role == "worker" else 180
                if not (started <= heartbeat and 0 <= age < max_age):
                    errors.append(role + " has no fresh heartbeat after container start")
            except (KeyError, ValueError, TypeError, OverflowError):
                errors.append(role + " has an invalid heartbeat")
    return errors


def probe(release, project, private_url, public_url):
    ids = docker("ps", "-aq", "--filter", "label=com.docker.compose.project=" + project).splitlines()
    if not ids:
        return ["Release containers are missing"]
    containers = json.loads(docker("inspect", *ids))
    redis = [row["Id"] for row in containers if row["Config"]["Labels"].get("com.docker.compose.service") == "redis"]
    if len(redis) != 1:
        return ["Exactly one release Redis container is required"]
    values = docker("exec", redis[0], "redis-cli", "--raw", "MGET", "cfg:worker:heartbeat", "cfg:integration-worker:heartbeat").splitlines()
    heartbeats = dict(zip(("worker", "integration_worker"), values))
    errors = release_errors(containers, release, heartbeats, time.time())
    for origin in (private_url, public_url):
        with open_url(origin.rstrip("/") + "/api/ready", timeout=5) as response:
            body = json.load(response)
            if response.status != 200 or body.get("status") != "ready" or any(body.get(key) is not True for key in ("database", "redis", "worker", "integration_worker")):
                errors.append("Readiness failed for " + origin)
    with open_url(public_url, timeout=5) as response:
        if response.status != 200:
            errors.append("Public frontend did not return HTTP 200")
        if not response.geturl().startswith(public_url.rstrip("/") + "/") and response.geturl() != public_url.rstrip("/"):
            errors.append("Unexpected public redirect")
        if response.headers.get("Strict-Transport-Security") != "max-age=31536000":
            errors.append("Public HSTS header missing")
        policy = response.headers.get("Content-Security-Policy", "")
        if "script-src 'self'" not in policy or "object-src 'none'" not in policy:
            errors.append("Public CSP header missing")
    return errors


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True)
    parser.add_argument("--project", default="compute-for-good")
    parser.add_argument("--private-url", default="http://127.0.0.1:5181")
    parser.add_argument("--public-url", default="https://compute-for-good.tech")
    parser.add_argument("--attempts", type=int, default=60)
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-f]{40}", args.release) or not args.public_url.startswith("https://") or not 1 <= args.attempts <= 60:
        parser.error("Exact SHA, HTTPS public origin, and one to sixty attempts required")
    errors = ["Release probe did not run"]
    deadline = time.monotonic() + 180
    for attempt in range(args.attempts):
        try:
            errors = probe(args.release, args.project, args.private_url, args.public_url)
        except Exception as error:
            # Do not print HTTP bodies, full inspect/environment, or credentials.
            errors = ["Release probe unavailable: " + type(error).__name__]
        if not errors:
            print("Exact release images, fresh worker ticks, private readiness and public HTTPS/security headers verified")
            return 0
        if time.monotonic() >= deadline:
            break
        if attempt + 1 < args.attempts:
            time.sleep(2)
    print("; ".join(errors))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
