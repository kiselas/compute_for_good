"""Decrypt and restore an archive only to a new scratch DB on a local QA stack."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid
from cryptography.fernet import Fernet

LOCAL_PROJECTS = {"cfg-qa", "cfg-production-smoke", "computeforgood"}


def docker(*arguments, data=None, timeout=60):
    result = subprocess.run(["docker", *arguments], input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=timeout)
    if result.returncode:
        # PostgreSQL diagnostics can contain archive data. Keep them private.
        raise RuntimeError("Isolated PostgreSQL verification command failed")
    return result.stdout


def verify(archive, key, container, expected_schema=None):
    # Check the target before reading/decrypting private backup material.
    rows = json.loads(docker("inspect", container))
    if len(rows) != 1:
        raise ValueError("Exactly one local QA PostgreSQL container required")
    labels = rows[0]["Config"].get("Labels") or {}
    if labels.get("com.docker.compose.project") not in LOCAL_PROJECTS or labels.get("com.docker.compose.service") != "postgres":
        raise ValueError("Refusing a production or unrelated restore target")
    if rows[0]["State"]["Status"] != "running":
        raise ValueError("QA PostgreSQL is not running")
    manifest = json.loads(archive.with_suffix(".json").read_text())
    encrypted = archive.read_bytes()
    if manifest["filename"] != archive.name or hashlib.sha256(encrypted).hexdigest() != manifest["encrypted_sha256"]:
        raise ValueError("Encrypted archive checksum mismatch")
    plain = Fernet(key.read_bytes().strip()).decrypt(encrypted)
    if not plain.startswith(b"PGDMP") or len(plain) != manifest["plaintext_bytes"] or hashlib.sha256(plain).hexdigest() != manifest["archive_sha256"]:
        raise ValueError("Decrypted archive checksum mismatch")
    database = "cfg_restore_" + uuid.uuid4().hex
    created = False
    try:
        docker("exec", container, "createdb", "-U", "cfg", database)
        created = True
        docker("exec", "-i", container, "pg_restore", "--exit-on-error", "--no-owner", "--no-privileges", "-U", "cfg", "-d", database, data=plain, timeout=120)
        query = "SELECT json_build_object('users',(SELECT count(*) FROM users),'impact_credits',(SELECT count(*) FROM impact_credits),'schema',(SELECT version_num FROM alembic_version));"
        snapshot = json.loads(docker("exec", container, "psql", "-U", "cfg", "-d", database, "-At", "-c", query))
        if not snapshot["schema"] or expected_schema and snapshot["schema"] != expected_schema:
            raise ValueError("Restored migration revision differs from expected schema")
        return snapshot
    finally:
        if created:
            docker("exec", container, "dropdb", "--if-exists", "--force", "-U", "cfg", database)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--key", type=Path, required=True)
    parser.add_argument("--container", required=True)
    parser.add_argument("--expected-schema")
    args = parser.parse_args()
    try:
        result = verify(args.archive, args.key, args.container, args.expected_schema)
    except Exception as error:
        raise SystemExit("Backup restore verification failed: " + type(error).__name__) from None
    print(json.dumps({"restored": True, "scratch_database_removed": True, **result}))


if __name__ == "__main__":
    main()
