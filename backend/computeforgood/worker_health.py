"""Container health probe: process existence alone does not mean work runs."""
import os
import time
from redis import Redis


def main():
    integration = os.getenv("WORKER_MODE") == "integrations"
    key = "cfg:integration-worker:heartbeat" if integration else "cfg:worker:heartbeat"
    max_age = 180 if integration else 30
    try:
        client = Redis.from_url(os.environ["REDIS_URL"], socket_timeout=2, socket_connect_timeout=2)
        value = client.get(key)
        age = time.time() - float(value) if value else float("inf")
        return 0 if 0 <= age < max_age else 1
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
