"""Require complete integration evidence, including real production transports."""
from pathlib import Path
import sys
import xml.etree.ElementTree as ET

cases = ET.parse(Path(sys.argv[1])).getroot().findall('.//testcase')
assert cases, 'No integration cases executed'
assert not any(case.find('skipped') is not None for case in cases), 'Every production smoke test must execute'
smoke = [case for case in cases if 'test_production_smoke' in case.attrib['classname'] or case.attrib['name'] == 'test_actual_websocket_through_caddy_and_nginx_committed_public_change']
assert len(smoke) == 6, f'Expected six production checks, got {len(smoke)}'
assert not any(case.find('failure') is not None or case.find('error') is not None for case in cases), 'Verification failures recorded'
print(f'All {len(cases)} integration checks passed, including six production transports; zero skips.')
