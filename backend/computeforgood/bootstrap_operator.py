"""Provision an operator; generated password is written to a private local file."""
import argparse
import json
import os
from pathlib import Path
import secrets
from sqlalchemy import select
from .auth import password_hash
from .db import SessionLocal
from .models import User
from .services import hash_token


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--username", default="cfg_operator")
    parser.add_argument("--output", default=str(Path.home() / ".codex" / "private" / "computeforgood" / "operator-login.json"))
    args = parser.parse_args()
    output = Path(args.output).resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    # Exclusive creation avoids replacing an existing credential during reruns.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    password = secrets.token_urlsafe(32)
    try:
        with SessionLocal.begin() as db:
            if db.scalar(select(User.id).where(User.username == args.username)):
                raise ValueError("Username already exists; choose another operator username")
            db.add(User(username=args.username, role="operator", password_hash=password_hash(password), token_hash=hash_token(secrets.token_urlsafe(48)), model_tier="STRONG", is_demo=False))
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump({"username": args.username, "password": password}, handle)
                handle.write("\n")
    except Exception:
        output.unlink(missing_ok=True)
        raise
    print("Operator created. Credentials saved to " + str(output))


if __name__ == "__main__":
    main()
