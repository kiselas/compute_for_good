"""Create private local-only smoke settings without touching existing values."""
from pathlib import Path
import secrets
from cryptography.fernet import Fernet

root = Path(__file__).resolve().parent.parent
demo = root / '.env'
existing = demo.read_text() if demo.exists() else ''
if not any(line.startswith('OAUTH_SECRET_KEY=') and line.partition('=')[2].strip() for line in existing.splitlines()):
    with demo.open('a', encoding='utf-8') as stream:
        stream.write('\nOAUTH_SECRET_KEY=' + Fernet.generate_key().decode() + '\n')
    demo.chmod(0o600)
production = root / '.env.production-smoke'
if not production.exists():
    values = {
        'PUBLIC_HOST': 'http://127.0.0.1',
        'PUBLIC_URL': 'http://127.0.0.1:5380',
        'SECURE_COOKIES': 'false', 'REGISTRATION_ENABLED': 'true',
        'POSTGRES_PASSWORD': secrets.token_hex(32),
        'GITHUB_WEBHOOK_SECRET': secrets.token_hex(32),
        'OAUTH_SECRET_KEY': Fernet.generate_key().decode(),
    }
    production.write_text(''.join(f'{key}={value}\n' for key, value in values.items()), encoding='utf-8')
    production.chmod(0o600)
print('Local smoke settings ready; existing secrets preserved.')
