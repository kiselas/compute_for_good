"""Verification profiles with timings, unique evidence and no cached passes."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys
import time
import uuid
import signal

ROOT = Path(__file__).resolve().parent.parent
ARTIFACTS = ROOT / 'artifacts'
IMAGE_OVERRIDE = 'deploy/verification-images.override.yaml'
TIMEOUTS = {'frontend': 120, 'offline': 60, 'images': 600,
            'qa-services': 270, 'production-services': 270, 'readiness': 250,
            'integration': 300, 'authentication': 180, 'proxy-dns': 150}


def stop_process_tree(process):
    if os.name == 'nt':
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'],
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=15)
    else:
        os.killpg(process.pid, signal.SIGKILL)
    process.wait(timeout=15)


@contextmanager
def verification_lock():
    """Serialize shared images, services and TypeScript output per checkout."""
    ARTIFACTS.mkdir(exist_ok=True)
    with (ARTIFACTS / 'verification.lock').open('a+b') as stream:
        if stream.seek(0, os.SEEK_END) == 0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            raise RuntimeError('Another verification is running in this checkout') from None
        try:
            yield
        finally:
            stream.seek(0)
            if os.name == 'nt':
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(stream, fcntl.LOCK_UN)


def validate_selection(mode, tests):
    if tests and mode != 'backend':
        raise ValueError('Focused selectors require --mode backend; full always runs every check')
    for selector in tests:
        path = (ROOT / selector.split('::', 1)[0]).resolve()
        if selector.startswith('-') or not path.is_relative_to(ROOT / 'tests') or not path.exists():
            raise ValueError('Selectors must refer to existing files or nodes under tests/')


def qa_environment():
    return {**os.environ, 'CFG_TEST_BASE_URL': 'http://127.0.0.1:8110',
            'DATABASE_URL': 'postgresql+psycopg://cfg:cfg-local@127.0.0.1:55472/cfg',
            'REDIS_URL': 'redis://127.0.0.1:56382/0', 'CFG_TEST_REDIS_URL': 'redis://127.0.0.1:56382/0',
            'DEMO_MODE': 'true', 'CFG_TEST_WEBHOOK_SECRET': 'local-demo-webhook-secret',
            'CFG_PRODUCTION_BASE_URL': 'http://127.0.0.1:5380'}


class Verification:
    def __init__(self, mode):
        self.mode = mode
        run_id = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ') + '-' + uuid.uuid4().hex[:6]
        self.directory = ARTIFACTS / ('verification-' + mode + '-' + run_id)
        self.directory.mkdir(parents=True)
        self.environment = qa_environment()
        self.stages = []

    def run(self, name, command, env=None, timeout=None):
        log = self.directory / (name + '.log')
        start = time.monotonic()
        print(f'[verify] {name} started', flush=True)
        with log.open('w', encoding='utf-8') as output:
            options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
            process = subprocess.Popen(command, cwd=ROOT, env=env or self.environment,
                                       stdout=output, stderr=subprocess.STDOUT, **options)
            try:
                code = process.wait(timeout=timeout if timeout is not None else TIMEOUTS.get(name, 30))
            except subprocess.TimeoutExpired:
                stop_process_tree(process)
                output.write('\nStage deadline exceeded; owned subprocesses stopped.\n')
                code = 124
            except KeyboardInterrupt:
                stop_process_tree(process)
                raise
        stage = {'name': name, 'seconds': round(time.monotonic() - start, 3),
                 'exit_code': code, 'log': str(log.relative_to(ROOT))}
        self.stages.append(stage)
        print(f"[verify] {name}: {'PASS' if code == 0 else 'FAIL'} ({stage['seconds']}s) - {stage['log']}", flush=True)
        if code:
            raise RuntimeError(f'{name} failed; inspect {log.relative_to(ROOT)}')

    def python(self, name, *args):
        self.run(name, [sys.executable, *args])

    def frontend(self, bundle=False):
        self.run('frontend', ['node', 'frontend/scripts/check.mjs', *(['--build'] if bundle else [])])

    def pytest(self, name, selectors, *options):
        evidence = self.directory / (name + '.xml')
        self.python(name, '-m', 'pytest', *selectors, '-q', '-x', '--durations=10', '--junitxml=' + str(evidence), *options)
        return evidence

    def storage(self, tests):
        self.run('docker-ready', ['docker', 'info', '--format', '{{.ServerVersion}}'], timeout=15)
        self.python('configuration', 'scripts/prepare-local-smoke.py')
        qa = ['docker', 'compose', '-p', 'cfg-qa', '-f', 'compose.yaml', '-f', 'deploy/qa.override.yaml', '-f', IMAGE_OVERRIDE]
        production = ['docker', 'compose', '-p', 'cfg-production-smoke', '--env-file', '.env.production-smoke',
                      '-f', 'compose.production.yaml', '-f', 'deploy/production-smoke.override.yaml', '-f', IMAGE_OVERRIDE]
        # Two images, built once, serve three backend roles and both realms.
        self.run('images', [*qa, 'build', 'backend', 'frontend'])
        self.run('qa-services', [*qa, 'up', '--no-build', '-d', '--wait', '--wait-timeout', '240'])
        self.run('production-services', [*production, 'up', '--no-build', '-d', '--wait', '--wait-timeout', '240'])
        self.python('readiness', 'scripts/wait-test-ready.py')
        evidence = self.pytest('integration', tests or ['tests'])
        self.python('integration-evidence', 'scripts/check-test-evidence.py', str(evidence), *(['--focused'] if tests else []))
        if not tests:
            auth = self.directory / 'authentication.xml'
            self.python('authentication', 'scripts/verify-auth.py', '--junitxml', str(auth))
            self.python('auth-evidence', 'scripts/check-test-evidence.py', str(auth), '--focused')
        if self.mode == 'full':
            self.python('proxy-dns', 'scripts/verify-proxy-dns.py', '--project', 'cfg-qa')

    def execute(self, tests):
        start = time.monotonic()
        passed = False
        try:
            if self.mode == 'quick':
                with ThreadPoolExecutor(max_workers=2) as executor:
                    web = executor.submit(self.frontend)
                    python = executor.submit(self.pytest, 'offline', ['tests'], '-m', 'not integration')
                    web.result()
                    evidence = python.result()
                self.python('offline-evidence', 'scripts/check-test-evidence.py', str(evidence), '--focused')
            elif self.mode == 'frontend':
                self.frontend(bundle=True)
            else:
                if self.mode == 'full':
                    self.frontend()
                self.storage(tests)
            passed = True
        finally:
            report = {'mode': self.mode, 'passed': passed, 'full_verification': passed and self.mode == 'full',
                      'seconds': round(time.monotonic() - start, 3), 'stages': self.stages, 'selectors': tests,
                      'revision': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()}
            content = json.dumps(report, indent=2)
            (self.directory / 'report.json').write_text(content, encoding='utf-8')
            (ARTIFACTS / ('verification-' + self.mode + '-latest.json')).write_text(content, encoding='utf-8')
            print(f"[verify] {self.mode}: {'PASS' if passed else 'FAIL'}, {report['seconds']}s; report: {self.directory.relative_to(ROOT)}/report.json", flush=True)
            if passed and self.mode != 'full':
                print('[verify] Partial profile. Release verification requires --mode full.', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode', choices=['quick', 'frontend', 'backend', 'full'], default='quick')
    parser.add_argument('--tests', nargs='+', default=[])
    args = parser.parse_args()
    try:
        validate_selection(args.mode, args.tests)
        with verification_lock():
            Verification(args.mode).execute(args.tests)
    except (ValueError, RuntimeError, OSError) as error:
        print(f'[verify] {error}', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
