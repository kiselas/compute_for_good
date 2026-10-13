"""Require successful push CI for the current main commit before publishing images."""
import json
import os
import re
import subprocess
import time


class Rejected(ValueError):
    pass


def matching(run, repository, sha, workflow_id):
    return (run.get('head_sha') == sha and run.get('head_branch') == 'main'
            and run.get('event') == 'push' and run.get('status') == 'completed'
            and run.get('conclusion') == 'success' and run.get('workflow_id') == workflow_id
            and (run.get('head_repository') or {}).get('full_name') == repository)


def verify(repository, sha, api, run_id=None, sleep=time.sleep, attempts=6):
    if not re.fullmatch(r'[a-z0-9_.-]+/[a-z0-9_.-]+', repository, re.I):
        raise Rejected('Invalid repository')
    if not re.fullmatch(r'[0-9a-f]{40}', sha):
        raise Rejected('A full lowercase commit SHA is required')
    if run_id and not re.fullmatch(r'[0-9]+', str(run_id)):
        raise Rejected('Invalid triggering CI run ID')
    prefix = f'repos/{repository}'

    def current_main():
        if api(prefix + '/branches/main')['commit']['sha'] != sha:
            raise Rejected('Refusing stale or non-main deployment')

    current_main()
    workflow_id = api(prefix + '/actions/workflows/ci.yml')['id']
    for attempt in range(attempts):
        if run_id:
            # The completed event identifies the run directly. List indexing can lag.
            run = api(prefix + f'/actions/runs/{run_id}')
            if not matching(run, repository, sha, workflow_id):
                raise Rejected('Triggering run is not successful exact-main push CI')
            accepted = run
        else:
            response = api(prefix + '/actions/workflows/ci.yml/runs', {
                'head_sha': sha, 'branch': 'main', 'event': 'push',
                'status': 'success', 'per_page': '100',
            })
            accepted = next((run for run in response['workflow_runs']
                             if matching(run, repository, sha, workflow_id)), None)
        if accepted is not None:
            current_main()
            return accepted['id']
        if attempt + 1 < attempts:
            sleep(5)
    raise Rejected('Successful main push CI for this exact commit is required')


def main():
    deadline = time.monotonic() + 60

    def api(endpoint, fields=None):
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise Rejected('CI observation deadline exceeded')
        command = ['gh', 'api', '-X', 'GET', endpoint]
        for key, value in (fields or {}).items():
            command.extend(['-f', f'{key}={value}'])
        result = subprocess.run(command, capture_output=True, text=True,
                                timeout=min(10, remaining))
        if result.returncode:
            raise Rejected('GitHub CI observation failed')
        return json.loads(result.stdout)

    try:
        run = verify(os.environ['REPOSITORY'], os.environ['CANDIDATE_SHA'], api,
                     os.environ.get('TRIGGER_RUN_ID'))
    except (Rejected, KeyError, TypeError, json.JSONDecodeError, subprocess.TimeoutExpired) as error:
        raise SystemExit(f'Deployment rejected: {error}') from None
    print(f'Verified successful main push CI run {run}')


if __name__ == '__main__':
    main()
