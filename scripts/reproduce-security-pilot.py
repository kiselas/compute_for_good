"""Read-only component probes of the public Testence PR 32 source.

No real credentials, browser, network target, or production data are used.
These probes do not establish end-to-end export coverage.
"""
import ast
import importlib.util
import json
from pathlib import Path
import sys
import subprocess
from types import SimpleNamespace
import warnings

import pytest

root = Path(__file__).resolve().parents[1] / "artifacts/security-pilot-baseline"
root.mkdir(parents=True, exist_ok=True)
revision = "2fbd96e0100f4d5e027530a9c11453e084b8d811"
for remote, filename in [("src/testence/pytest_plugin.py", "pilot-testence-pytest_plugin.py"),
                         ("src/testence/evidence/sanitize.py", "pilot-testence-sanitize.py")]:
    result = subprocess.run(["gh", "api", f"repos/kiselas/testence/contents/{remote}?ref={revision}",
                             "-H", "Accept: application/vnd.github.raw+json"],
                            capture_output=True, text=True, encoding="utf-8", timeout=20)
    if result.returncode:
        raise SystemExit("Could not load pinned public Testence source")
    (root / filename).write_text(result.stdout, encoding="utf-8")
spec = importlib.util.spec_from_file_location("pilot_sanitize", root / "pilot-testence-sanitize.py")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
sys.modules["testence.evidence.sanitize"] = module

source = (root / "pilot-testence-pytest_plugin.py").read_text(encoding="utf-8-sig")
tree = ast.parse(source)
function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "_warn_about_allure_identity")
subset = ast.Module(body=[ast.ImportFrom(module="__future__", names=[ast.alias(name="annotations")], level=0), function], type_ignores=[])
ast.fix_missing_locations(subset)
namespace = {"pytest": pytest, "warnings": warnings, "_METADATA_KEY": object()}
exec(compile(subset, "public_pr32_warning_function", "exec"), namespace)

canary = "CFG_SYNTH_ONLY_q7n4v9"
nodeid = f"test_example.py::test_login[{canary}]"
item = SimpleNamespace(stash={}, callspec=SimpleNamespace(params={"password": canary}), nodeid=nodeid)
config = SimpleNamespace(pluginmanager=SimpleNamespace(hasplugin=lambda name: False))
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    namespace["_warn_about_allure_identity"](config, [item])
trace = f"test_example.py:12: in test_login\n    page.get_by_label('Password').fill('{canary}')\nE   AssertionError: synthetic failure"
results = {
    "schema": "cfg/security-pilot-component-probes/1",
    "source_sha": "2fbd96e0100f4d5e027530a9c11453e084b8d811",
    "scope": "Actual extracted warning function and full sanitizer module; no end-to-end pytest/export run",
    "synthetic_only": True,
    "warning_emitted": len(caught) == 1,
    "warning_contains_synthetic_password": any(canary in str(w.message) for w in caught),
    "unregistered_nodeid_survives_sanitizer": canary in module.sanitize_text(nodeid),
    "source_literal_survives_sanitizer": canary in module.sanitize({"error_trace": trace})["error_trace"],
    "registered_secret_is_removed": canary not in module.sanitize_text(trace, secrets=[canary]),
    "ordinary_control_preserved": module.sanitize_text("City: Lisbon") == "City: Lisbon",
}
(root / "security-pilot-component-probes.json").write_text(json.dumps(results, indent=2) + "\n", encoding="utf-8")
print(json.dumps(results, indent=2))

if not all(results[name] for name in ("warning_emitted", "warning_contains_synthetic_password", "unregistered_nodeid_survives_sanitizer", "source_literal_survives_sanitizer", "registered_secret_is_removed", "ordinary_control_preserved")):
    raise SystemExit("Baseline reproduction differs from the recorded contract")
print("Known baseline defects reproduced; this is not a security acceptance result.")
