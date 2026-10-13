"""Require both workers and migrated storage before integration tests."""
import os
import time
import httpx

urls = [os.getenv('CFG_TEST_BASE_URL', 'http://127.0.0.1:8110'), os.getenv('CFG_PRODUCTION_BASE_URL', 'http://127.0.0.1:5380')]
with httpx.Client(timeout=5, trust_env=False, follow_redirects=False) as client:
    for url in urls:
        deadline = time.monotonic() + 120
        while True:
            try:
                response = client.get(url + '/api/ready')
                response.raise_for_status()
                data = response.json()
                if response.status_code == 200 and data.get('status') == 'ready' and all(data.get(key) is True for key in ('database', 'redis', 'worker', 'integration_worker')):
                    break
            except (httpx.HTTPError, ValueError):
                pass
            if time.monotonic() >= deadline:
                raise SystemExit('Test stack did not become ready within 120 seconds')
            time.sleep(1)
print('Both test stacks are ready, including their workers.')
