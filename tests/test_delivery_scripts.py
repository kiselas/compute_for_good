"""Safety gates reject stale release state and unsafe restore destinations."""
from copy import deepcopy
from datetime import datetime, timezone
import importlib.util
import json
import hashlib
from pathlib import Path
import tempfile
import subprocess
import sys
import os
import shutil
import shlex
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from threading import Thread
from urllib.error import HTTPError
import pytest
from cryptography.fernet import Fernet
from sqlalchemy import text

ROOT = Path(__file__).resolve().parent.parent


def module(name):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), ROOT / "scripts" / (name + ".py"))
    loaded = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(loaded)
    return loaded


release = module("check-release")
backup = module("verify-backup")
SHA = "a" * 40
TIMESTAMP = 1_800_000_000.0


@pytest.fixture
def backup_directory():
    root = (ROOT / "artifacts").resolve()
    root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="backup-verification-", dir=root) as directory:
        target = Path(directory).resolve()
        assert target.parent == root
        yield target


def snapshot():
    rows = []
    for role in release.SERVICES:
        component = "frontend" if role == "frontend" else "backend"
        rows.append({"Config": {"Labels": {"com.docker.compose.service": role}, "Image": release.IMAGE_ROOT + component + ":" + SHA},
                     "State": {"Status": "running", "Health": {"Status": "healthy"},
                               "StartedAt": datetime.fromtimestamp(TIMESTAMP - 10, timezone.utc).isoformat()}})
    return rows, {"worker": TIMESTAMP - 1, "integration_worker": TIMESTAMP - 1}


def test_release_accepts_exact_images_with_new_worker_ticks():
    rows, heartbeats = snapshot()
    for row in rows:
        row["State"]["StartedAt"] = row["State"]["StartedAt"].replace("+00:00", ".123456789Z")
    assert release.release_errors(rows, SHA, heartbeats, TIMESTAMP) == []


@pytest.mark.parametrize("heartbeat", [TIMESTAMP - 11, TIMESTAMP + 1, TIMESTAMP - 180, "nan", "inf", None])
def test_release_rejects_old_pre_restart_future_and_invalid_heartbeats(heartbeat):
    rows, heartbeats = snapshot()
    heartbeats["integration_worker"] = heartbeat
    assert release.release_errors(rows, SHA, heartbeats, TIMESTAMP)


@pytest.mark.parametrize("case", ["wrong-image", "missing", "duplicate", "unhealthy", "stopped"])
def test_ready_endpoint_cannot_hide_incomplete_or_mixed_release(case):
    rows, heartbeats = snapshot()
    backend = next(row for row in rows if row["Config"]["Labels"]["com.docker.compose.service"] == "backend")
    if case == "wrong-image":
        backend["Config"]["Image"] = release.IMAGE_ROOT + "backend:" + "b" * 40
    elif case == "missing":
        rows.remove(backend)
    elif case == "duplicate":
        rows.append(deepcopy(backend))
    elif case == "unhealthy":
        backend["State"]["Health"]["Status"] = "unhealthy"
    else:
        backend["State"]["Status"] = "exited"
    assert release.release_errors(rows, SHA, heartbeats, TIMESTAMP)


def test_restore_rejects_production_before_reading_private_archive(monkeypatch):
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        return json.dumps([{"Config": {"Labels": {"com.docker.compose.project": "compute-for-good", "com.docker.compose.service": "postgres"}}, "State": {"Status": "running"}}]).encode()
    monkeypatch.setattr(backup, "docker", docker)
    with pytest.raises(ValueError, match="production"):
        backup.verify(Path("missing-private-archive"), Path("missing-private-key"), "production-postgres")
    assert calls == [("inspect", "production-postgres")]


def test_restore_encrypted_real_postgres_dump_and_remove_only_scratch(database, backup_directory):
    # Select the QA database by its bound port, not by a guessed container name.
    ids = backup.docker("ps", "-q", "--filter", "label=com.docker.compose.service=postgres").decode().splitlines()
    containers = json.loads(backup.docker("inspect", *ids))
    target = next(row for row in containers if any(int(binding["HostPort"]) == database.engine.url.port for binding in row["NetworkSettings"]["Ports"].get("5432/tcp") or []))
    container = target["Id"]
    plain = backup.docker("exec", container, "pg_dump", "-U", "cfg", "-d", "cfg", "-Fc")
    key = Fernet.generate_key()
    encrypted = Fernet(key).encrypt(plain)
    archive = backup_directory / "isolated.dump.fernet"
    key_path = backup_directory / "isolated.key"
    archive.write_bytes(encrypted)
    key_path.write_bytes(key)
    archive.with_suffix(".json").write_text(json.dumps({
        "filename": archive.name, "plaintext_bytes": len(plain),
        "archive_sha256": hashlib.sha256(plain).hexdigest(),
        "encrypted_sha256": hashlib.sha256(encrypted).hexdigest(),
    }))
    with database.engine.connect() as connection:
        schema = connection.scalar(text("SELECT version_num FROM alembic_version"))
        existing = set(connection.scalars(text("SELECT datname FROM pg_database WHERE datname LIKE 'cfg_restore_%'")))
    result = backup.verify(archive, key_path, container, schema)
    assert result["schema"] == schema and result["users"] >= 1 and result["impact_credits"] >= 0
    with database.engine.connect() as connection:
        assert set(connection.scalars(text("SELECT datname FROM pg_database WHERE datname LIKE 'cfg_restore_%'"))) == existing


def test_restore_rejects_tampered_ciphertext_without_creating_database(monkeypatch, backup_directory):
    calls = []
    def docker(*args, **kwargs):
        calls.append(args)
        return json.dumps([{"Config": {"Labels": {"com.docker.compose.project": "cfg-qa", "com.docker.compose.service": "postgres"}}, "State": {"Status": "running"}}]).encode()
    monkeypatch.setattr(backup, "docker", docker)
    archive = backup_directory / "tampered.dump.fernet"
    archive.write_bytes(b"Changed ciphertext")
    archive.with_suffix(".json").write_text(json.dumps({"filename": archive.name, "encrypted_sha256": hashlib.sha256(b"Original ciphertext").hexdigest()}))
    with pytest.raises(ValueError, match="checksum"):
        backup.verify(archive, backup_directory / "unread-private-key", "qa-postgres")
    assert calls == [("inspect", "qa-postgres")]


@pytest.mark.parametrize("host,container", [("host;echo injected", "postgres"), ("-V", "postgres"), ("verified-host", "-i")])
def test_backup_cli_rejects_remote_shell_and_option_injection_even_with_python_optimization(backup_directory, host, container):
    directory = backup_directory / "must-not-be-created"
    result = subprocess.run([
        sys.executable, "-O", str(ROOT / "scripts" / "backup-remote.py"),
        "--host=" + host, "--container=" + container,
        "--directory", str(directory), "--key", str(directory / "key"),
    ], stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    assert result.returncode == 2
    assert not directory.exists()


def test_release_probe_refuses_redirect_to_a_ready_response():
    visited = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            visited.append(self.path)
            if self.path == "/api/ready":
                self.send_response(302)
                self.send_header("Location", "/foreign-ready")
            else:
                self.send_response(200)
            self.end_headers()
            self.wfile.write(b'{"status":"ready","database":true,"redis":true,"worker":true,"integration_worker":true}')
        def log_message(self, *args):
            pass
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        with pytest.raises(HTTPError) as error:
            release.open_url("http://127.0.0.1:" + str(server.server_port) + "/api/ready")
        assert error.value.code == 302
        assert visited == ["/api/ready"]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def test_ready_api_and_headers_cannot_hide_an_empty_frontend(monkeypatch):
    from io import BytesIO
    import time
    rows, heartbeats = snapshot()
    offset = time.time() - TIMESTAMP
    for index, row in enumerate(rows):
        row['Id'] = 'test-' + str(index)
        row['State']['StartedAt'] = datetime.fromtimestamp(TIMESTAMP - 10 + offset, timezone.utc).isoformat()
    def docker(*args):
        if args[0] == 'ps':
            return '\n'.join(row['Id'] for row in rows)
        if args[0] == 'inspect':
            return json.dumps(rows)
        return '\n'.join(str(value + offset) for value in heartbeats.values())
    monkeypatch.setattr(release, 'docker', docker)
    class Response(BytesIO):
        def __init__(self, url):
            ready = url.endswith('/api/ready')
            super().__init__(b'{"status":"ready","database":true,"redis":true,"worker":true,"integration_worker":true}' if ready else b'')
            self.status = 200 if ready else 204
            self.headers = {'Strict-Transport-Security': 'max-age=31536000', 'Content-Security-Policy': "script-src 'self'; object-src 'none'"}
            self.url = url
        def geturl(self):
            return self.url
    monkeypatch.setattr(release, 'open_url', lambda url, timeout: Response(url))
    assert release.probe(SHA, 'isolated-test', 'http://127.0.0.1:5181', 'https://cfg.test') == ['Public frontend did not return HTTP 200']


def test_rollback_rechecks_schema_after_deployment_lock_acquired(backup_directory):
    bash = "C:/Program Files/Git/bin/bash.exe" if os.name == "nt" else shutil.which("bash")
    assert bash, "Bash is required for deployment regression"
    def posix(path):
        if os.name != "nt":
            return str(path)
        return subprocess.check_output([bash, "-c", 'cygpath -u "$1"', "--", str(path)], text=True).strip()
    base = backup_directory / "base"
    commands = backup_directory / "bin"
    base.mkdir()
    commands.mkdir()
    (base / ".env.production").write_text("")
    log = backup_directory / "calls"
    schema = backup_directory / "schema"
    schema.write_text("old_schema")
    flock = commands / "flock"
    flock.write_text("#!/usr/bin/env bash\nprintf 'lock-acquired\\n' >> " + shlex.quote(posix(log)) + "\nprintf new_schema > " + shlex.quote(posix(schema)) + "\n")
    docker = commands / "docker"
    docker.write_text("""#!/usr/bin/env bash
case "$1" in
 image) exit 0 ;;
 ps) printf 'isolated-pg\\n' ;;
 exec) printf 'schema-read\\n' >> LOG_PATH; cat SCHEMA_PATH ;;
 run) printf 'old_schema (head)\\n' ;;
 *) echo 'Unexpected Docker mutation' >&2; exit 90 ;;
esac
""".replace("LOG_PATH", shlex.quote(posix(log))).replace("SCHEMA_PATH", shlex.quote(posix(schema))))
    flock.chmod(0o700)
    docker.chmod(0o700)
    script = backup_directory / "deploy-under-test.sh"
    script.write_text((ROOT / "deploy" / "deploy-release.sh").read_text().replace("BASE=/opt/compute-for-good", "BASE=" + shlex.quote(posix(base))))
    command = "export PATH=" + shlex.quote(posix(commands)) + ':"$PATH"; export CFG_REQUIRE_COMPATIBLE_SCHEMA=1; exec bash ' + shlex.quote(posix(script)) + " " + SHA
    result = subprocess.run([bash, "-c", command], stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=15)
    assert result.returncode == 1
    assert b"Rollback refused" in result.stderr
    assert log.read_text().splitlines() == ["lock-acquired", "schema-read"]
