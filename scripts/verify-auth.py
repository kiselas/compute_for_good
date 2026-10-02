"""Run real DB/Redis auth tests in a fresh process with an ephemeral test key."""
import os
from pathlib import Path
import subprocess
import sys
from cryptography.fernet import Fernet
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parent.parent
environment = os.environ.copy()
url = make_url(environment.get('DATABASE_URL', 'postgresql+psycopg://cfg:cfg-local@127.0.0.1:55472/cfg'))
if url.host not in {'127.0.0.1', 'localhost'} or url.port not in {55471, 55472} or url.database != 'cfg':
    raise SystemExit('Authentication QA is restricted to the local demo/QA database')
environment['DATABASE_URL'] = str(url.render_as_string(hide_password=False))
environment['DEMO_MODE'] = 'false'
environment['PUBLIC_URL'] = 'http://localhost:8010'
environment['FRONTEND_URL'] = 'http://localhost:8010'
environment['SECURE_COOKIES'] = 'false'
environment['OAUTH_SECRET_KEY'] = Fernet.generate_key().decode()
raise SystemExit(subprocess.call([sys.executable, '-m', 'pytest', 'backend/tests_auth.py', '-q', '--junitxml=tests/artifacts/auth-verification.xml'], cwd=root, env=environment))
