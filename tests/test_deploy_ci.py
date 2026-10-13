"""Release authorization stays closed under stale, foreign and incomplete evidence."""
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location('deploy_ci', Path(__file__).resolve().parents[1] / 'scripts/check-deploy-ci.py')
guard = importlib.util.module_from_spec(spec)
spec.loader.exec_module(guard)
SHA = 'a' * 40
REPO = 'kiselas/compute_for_good'


def run(**changes):
    value = dict(id=42, head_sha=SHA, head_branch='main', event='push',
                 status='completed', conclusion='success', workflow_id=10,
                 head_repository={'full_name': REPO})
    value.update(changes)
    return value


def api_for(observations, heads=None):
    heads = iter(heads or [SHA, SHA])
    observations = iter(observations)

    def api(endpoint, fields=None):
        if endpoint.endswith('/branches/main'):
            return {'commit': {'sha': next(heads)}}
        if endpoint.endswith('/workflows/ci.yml'):
            return {'id': 10}
        if endpoint.endswith('/runs/42'):
            return next(observations)
        assert fields == dict(head_sha=SHA, branch='main', event='push', status='success', per_page='100')
        return {'workflow_runs': next(observations)}
    return api


def test_triggering_run_does_not_depend_on_list_index():
    assert guard.verify(REPO, SHA, api_for([run()]), run_id='42') == 42


def test_manual_dispatch_waits_for_index_without_weakening_evidence():
    waits = []
    assert guard.verify(REPO, SHA, api_for([[], [run()]]), sleep=waits.append) == 42
    assert waits == [5]


@pytest.mark.parametrize('change', [dict(head_sha='b' * 40), dict(head_branch='other'),
    dict(event='pull_request'), dict(conclusion='failure'), dict(status='in_progress'),
    dict(workflow_id=99), dict(head_repository={'full_name': 'other/fork'}), dict(head_repository=None)])
def test_foreign_failed_or_incomplete_trigger_is_rejected(change):
    with pytest.raises(guard.Rejected):
        guard.verify(REPO, SHA, api_for([run(**change)]), run_id='42')


def test_main_moving_during_observation_is_rejected():
    with pytest.raises(guard.Rejected, match='stale'):
        guard.verify(REPO, SHA, api_for([run()], [SHA, 'b' * 40]), run_id='42')


def test_missing_success_exhausts_bounded_observation():
    waits = []
    with pytest.raises(guard.Rejected, match='Successful'):
        guard.verify(REPO, SHA, api_for([[], [], []]), sleep=waits.append, attempts=3)
    assert waits == [5, 5]


@pytest.mark.parametrize('sha,run_id', [('main', '42'), (SHA.upper(), '42'), (SHA, '../42')])
def test_invalid_inputs_do_not_reach_github(sha, run_id):
    with pytest.raises(guard.Rejected):
        guard.verify(REPO, sha, lambda *args: pytest.fail('Unexpected API access'), run_id=run_id)
