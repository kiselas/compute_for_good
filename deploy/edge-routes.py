"""Install only CFG routes into the existing VPN nginx config, or check drift.

Run on the host as root. Backup is private; no existing route is replaced.
The nginx reload is graceful; it does not recreate VPN containers.
"""
import argparse
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import re
import subprocess

PATH = Path('/opt/next_connect/deploy/edge/nginx.conf')
BACKUPS = Path('/opt/compute-for-good/backups')
MARKER = '# ComputeForGood domain routes'


def candidate(text):
    if MARKER in text:
        required = ('compute-for-good.tech', 'cfg-gateway:443', 'cfg-gateway:80', '127.0.0.1:8547')
        if not all(value in text for value in required):
            raise RuntimeError('Existing CFG route markers are incomplete; inspect drift manually')
        return text
    if 'cfg-gateway' in text or re.search(r'\b8547\b', text):
        raise RuntimeError('CFG upstream or chosen hop already exists without markers')
    text, count = re.subn(r'(map \$ssl_preread_server_name \$inner_hop \{)',
        r'\1\n        # ComputeForGood domain routes\n        compute-for-good.tech "127.0.0.1:8547";\n        www.compute-for-good.tech "127.0.0.1:8547";', text, count=1)
    if count != 1:
        raise RuntimeError('Expected SNI map was not found')
    anchor = '    server {\n        listen 443 reuseport;'
    if anchor not in text:
        raise RuntimeError('Expected stream listener anchor was not found')
    block = '''    # ComputeForGood domain routes: preserve the client IP to its TLS listener.
    map "" $cfg_upstream { default "cfg-gateway:443"; }
    server {
        listen 127.0.0.1:8547 proxy_protocol;
        set_real_ip_from 127.0.0.1;
        proxy_pass $cfg_upstream;
        proxy_protocol on;
        proxy_timeout 30m;
        proxy_connect_timeout 5s;
    }

'''
    text = text.replace(anchor, block + anchor, 1)
    anchor = '    server {\n        listen 80 default_server;'
    if anchor not in text:
        raise RuntimeError('Expected default HTTP server anchor was not found')
    block = '''    # ComputeForGood domain routes: HTTP redirect and automatic ACME challenges.
    server {
        listen 80;
        listen [::]:80;
        server_name compute-for-good.tech www.compute-for-good.tech;
        location / {
            set $cfg_http_upstream "cfg-gateway:80";
            proxy_pass http://$cfg_http_upstream;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $remote_addr;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }

'''
    return text.replace(anchor, block + anchor, 1)


def run(*args):
    subprocess.run(args, check=True)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    original = PATH.read_bytes()
    updated = candidate(original.decode('utf-8')).encode('utf-8')
    print('Existing edge SHA256:', hashlib.sha256(original).hexdigest())
    if not args.apply:
        print('CFG route patch is valid; apply required:', updated != original)
        return
    if updated == original:
        run('docker', 'exec', 'next_connect-edge-1', 'nginx', '-t')
        print('CFG routes already present; no change')
        return
    BACKUPS.mkdir(parents=True, exist_ok=True, mode=0o700)
    backup = BACKUPS / ('edge-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '.conf')
    with backup.open('xb') as file:
        file.write(original)
    backup.chmod(0o600)
    if PATH.read_bytes() != original:
        raise RuntimeError('Concurrent edge edit detected before write')
    # Keep the existing bind-mounted inode, otherwise nginx tests the old file.
    PATH.write_bytes(updated)
    try:
        run('docker', 'exec', 'next_connect-edge-1', 'nginx', '-t')
        run('docker', 'exec', 'next_connect-edge-1', 'nginx', '-s', 'reload')
    except Exception:
        if PATH.read_bytes() == updated:
            PATH.write_bytes(original)
            run('docker', 'exec', 'next_connect-edge-1', 'nginx', '-t')
            run('docker', 'exec', 'next_connect-edge-1', 'nginx', '-s', 'reload')
        raise
    print('CFG routes installed; rollback file:', backup)


if __name__ == '__main__':
    main()
