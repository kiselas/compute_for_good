"""Isolated Docker regression: nginx follows backend DNS without a reload.

Uses existing locally built Compose images; creates only disposable containers
on a fresh network. Run after building the application, outside production.
"""
import json
import argparse
from pathlib import Path
import subprocess
import time
import uuid
import httpx

root = Path(__file__).resolve().parent.parent

def docker(*args):
    return subprocess.check_output(['docker', *args], cwd=root, text=True).strip()

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--project', help='Local Compose project providing built images')
args = parser.parse_args()
compose = ['compose'] + (['-p', args.project] if args.project else [])
def built_image(service):
    containers = docker(*compose, 'ps', '-q', service).splitlines()
    assert len(containers) == 1, f'One running local {service} container is required'
    # A running container can retain a removed OCI manifest ID after a cached
    # Compose rebuild. Its configured local tag points to the usable new image.
    image = json.loads(docker('inspect', containers[0]))[0]['Config']['Image']
    docker('image', 'inspect', image)
    return image

frontend_image = built_image('frontend')
backend_image = built_image('backend')
prefix = 'cfg-dns-' + uuid.uuid4().hex[:10]
network = prefix + '-net'
names = [prefix + suffix for suffix in ('-old', '-guard', '-new', '-proxy')]
old, guard, new, proxy = names
server = '''
import json, os
from http.server import BaseHTTPRequestHandler, HTTPServer
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200); self.end_headers()
        self.wfile.write(json.dumps({'marker':os.environ['MARKER'],'path':self.path}).encode())
    def log_message(self, *args): pass
HTTPServer(('0.0.0.0',8000),Handler).serve_forever()
'''

try:
    docker('network', 'create', network)
    # Reserve a daemon-selected free subnet, then make it user-configured.
    # Linux Docker requires explicit IPAM before accepting --ip for the guard;
    # Docker Desktop also accepts automatically allocated networks.
    subnet = json.loads(docker('network', 'inspect', network))[0]['IPAM']['Config'][0]['Subnet']
    docker('network', 'rm', network)
    docker('network', 'create', '--subnet', subnet, network)
    docker('run', '-d', '--name', old, '--network', network, '--network-alias', 'backend', '-e', 'MARKER=before', backend_image, 'python', '-u', '-c', server)
    old_ip = json.loads(docker('inspect', old))[0]['NetworkSettings']['Networks'][network]['IPAddress']
    docker('run', '-d', '--name', proxy, '--network', network, '-p', '127.0.0.1::80', '-v', str(root / 'frontend/nginx.conf') + ':/etc/nginx/conf.d/default.conf:ro', frontend_image)
    port = docker('port', proxy, '80/tcp').split(':')[-1]
    started = json.loads(docker('inspect', proxy))[0]['State']['StartedAt']
    with httpx.Client(base_url='http://127.0.0.1:' + port, timeout=2, trust_env=False) as client:
        def wait_marker(marker):
            deadline = time.monotonic() + 40
            while time.monotonic() < deadline:
                try:
                    response = client.get('/api/probe?preserve=query')
                    if response.status_code == 200 and response.json()['marker'] == marker:
                        assert response.json()['path'] == '/api/probe?preserve=query'
                        return
                except (httpx.HTTPError, ValueError):
                    pass
                time.sleep(.5)
            raise AssertionError('Proxy did not discover ' + marker + ' backend')

        wait_marker('before')
        docker('rm', '-f', old)
        docker('run', '-d', '--name', guard, '--network', network, '--ip', old_ip, backend_image, 'python', '-c', 'import time;time.sleep(300)')
        docker('run', '-d', '--name', new, '--network', network, '--network-alias', 'backend', '-e', 'MARKER=after', backend_image, 'python', '-u', '-c', server)
        new_ip = json.loads(docker('inspect', new))[0]['NetworkSettings']['Networks'][network]['IPAddress']
        assert new_ip != old_ip
        wait_marker('after')
        for path in ('/mcp/probe', '/.well-known/probe', '/socket.io/probe'):
            response = client.get(path)
            assert response.status_code == 200 and response.json() == {'marker': 'after', 'path': path}
        assert json.loads(docker('inspect', proxy))[0]['State']['StartedAt'] == started
        print(json.dumps({'backend_ip_changed': True, 'proxy_restart_required': False, 'api_mcp_oauth_socket_routes': 'passed'}))
finally:
    for name in names:
        subprocess.run(['docker', 'rm', '-f', name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    subprocess.run(['docker', 'network', 'rm', network], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
