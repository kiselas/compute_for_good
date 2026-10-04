"""Fetch a PostgreSQL archive over existing SSH and encrypt it off-host.

The encryption key is a separate private file. Keep a second secure copy of it;
losing the key makes these archives unrecoverable. No credentials are logged.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from cryptography.fernet import Fernet

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--host', required=True, help='An existing verified SSH alias')
parser.add_argument('--container', required=True, help='The existing PostgreSQL container')
parser.add_argument('--directory', type=Path, required=True, help='Private off-host backup directory')
parser.add_argument('--key', type=Path, required=True, help='Private Fernet key file (created once if absent)')
args = parser.parse_args()
assert re.fullmatch(r'[A-Za-z0-9_.-]+', args.host) and re.fullmatch(r'[A-Za-z0-9_.-]+', args.container), 'Use simple existing alias/container names'
args.directory.mkdir(parents=True, exist_ok=True)
args.key.parent.mkdir(parents=True, exist_ok=True)
def private_write(path, value):
    with os.fdopen(os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600), 'wb') as stream:
        stream.write(value)

if not args.key.exists():
    private_write(args.key, Fernet.generate_key())
cipher = Fernet(args.key.read_bytes().strip())
result = subprocess.run(['ssh', '-o', 'BatchMode=yes', '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=20', args.host,
                         'docker', 'exec', args.container, 'pg_dump', '-U', 'cfg', '-d', 'cfg', '-Fc'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=120)
if result.returncode != 0:
    raise SystemExit('Remote backup failed; no archive saved. Inspect the SSH/backup service privately.')
assert result.stdout.startswith(b'PGDMP'), 'Remote response is not a PostgreSQL custom archive'
filename = 'cfg-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex + '.dump.fernet'
destination = args.directory / filename
encrypted = cipher.encrypt(result.stdout)
private_write(destination, encrypted)
assert hashlib.sha256(cipher.decrypt(destination.read_bytes())).digest() == hashlib.sha256(result.stdout).digest(), 'Off-host encryption verification failed'
manifest = {'filename': filename, 'created_at': datetime.now(timezone.utc).isoformat(), 'plaintext_bytes': len(result.stdout),
            'archive_sha256': hashlib.sha256(result.stdout).hexdigest(), 'encrypted_sha256': hashlib.sha256(encrypted).hexdigest()}
manifest_path = destination.with_suffix('.json')
private_write(manifest_path, json.dumps(manifest, indent=2).encode('utf-8'))
print('Encrypted off-host archive verified and saved: ' + str(destination))
