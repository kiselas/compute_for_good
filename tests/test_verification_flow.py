"""Partial profiles cannot masquerade as release verification."""
import importlib.util
import json
import tempfile
import sys
import time
from pathlib import Path
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name.replace('-', '_'), ROOT / 'scripts' / (name + '.py'))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runner = load('verify')
evidence = load('check-test-evidence')


@pytest.fixture
def tmp_path():
    # Windows' shared pytest temp directory may belong to another executor.
    # Keep these disposable files inside this checkout's ignored artifacts.
    directory = ROOT / 'artifacts'
    directory.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='verification-test-', dir=directory) as temporary:
        yield Path(temporary)


@pytest.mark.parametrize('mode', ['quick', 'frontend', 'full'])
def test_focused_selectors_cannot_weaken_non_backend_profile(mode):
    with pytest.raises(ValueError, match='full always'):
        runner.validate_selection(mode, ['tests/test_transports.py'])


@pytest.mark.parametrize('selector', ['../backend/tests_auth.py', 'tests/../backend/tests_auth.py', '--ignore=tests/test_transports.py'])
def test_selectors_stay_inside_tests_and_cannot_inject_pytest_options(selector):
    with pytest.raises(ValueError):
        runner.validate_selection('backend', [selector])


@pytest.mark.parametrize('case', ['', '<testcase/>', '<testcase><skipped/></testcase>', '<testcase><failure/></testcase>', '<testcase><error/></testcase>'])
def test_full_evidence_rejects_empty_missing_transports_skips_and_failures(tmp_path, case):
    path = tmp_path / 'result.xml'
    path.write_text('<testsuite>' + case + '</testsuite>')
    with pytest.raises(ValueError):
        evidence.validate(path)
    if not case or '<skipped' in case or '<failure' in case or '<error' in case:
        with pytest.raises(ValueError):
            evidence.validate(path, focused=True)


def test_verification_lock_rejects_concurrent_mutation_and_releases_after_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ARTIFACTS', tmp_path)
    with pytest.raises(RuntimeError, match='controlled failure'):
        with runner.verification_lock():
            with pytest.raises(RuntimeError, match='Another verification'):
                with runner.verification_lock():
                    pytest.fail('Two verifiers acquired the same lock')
            raise RuntimeError('controlled failure')
    with runner.verification_lock():
        pass


@pytest.mark.parametrize('mode', ['quick', 'full'])
def test_profiles_execute_their_gates_and_label_evidence_honestly(tmp_path, monkeypatch, mode):
    monkeypatch.setattr(runner, 'ARTIFACTS', tmp_path)
    verification = runner.Verification(mode)
    commands = []
    monkeypatch.setattr(verification, 'run', lambda name, command, **kwargs: commands.append((name, command)))
    verification.execute([])
    report = json.loads((verification.directory / 'report.json').read_text())
    assert report['passed'] is True
    assert report['full_verification'] is (mode == 'full')
    names = {name for name, _ in commands}
    if mode == 'quick':
        assert not any(command[0] == 'docker' for _, command in commands)
        assert {'frontend', 'offline', 'offline-evidence'} <= names
        offline = next(command for name, command in commands if name == 'offline')
        assert offline[offline.index('-m', 3) + 1] == 'not integration'
    else:
        assert {'frontend', 'images', 'qa-services', 'production-services', 'readiness',
                'integration', 'integration-evidence', 'authentication', 'auth-evidence', 'proxy-dns'} <= names
        command = next(command for name, command in commands if name == 'integration')
        assert command[3] == 'tests' and '--focused' not in command
        gate = next(command for name, command in commands if name == 'integration-evidence')
        assert '--focused' not in gate
        assert sum(name == 'images' for name, _ in commands) == 1


def test_failed_stage_does_not_write_successful_full_evidence(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ARTIFACTS', tmp_path)
    verification = runner.Verification('full')
    def fail(*args, **kwargs):
        raise RuntimeError('controlled failure')
    monkeypatch.setattr(verification, 'frontend', fail)
    with pytest.raises(RuntimeError, match='controlled failure'):
        verification.execute([])
    report = json.loads((verification.directory / 'report.json').read_text())
    assert report['passed'] is False and report['full_verification'] is False


def test_hung_stage_stops_owned_processes_and_records_failure(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, 'ARTIFACTS', tmp_path)
    verification = runner.Verification('quick')
    start = time.monotonic()
    with pytest.raises(RuntimeError, match='deadline failed'):
        verification.run('deadline', [sys.executable, '-c', 'import time; time.sleep(30)'], timeout=0.2)
    assert time.monotonic() - start < 10
    assert verification.stages[-1]['exit_code'] == 124
