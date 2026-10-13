"""Validate current-run JUnit evidence; full runs must include six transports."""
import argparse
from pathlib import Path
import xml.etree.ElementTree as ET

def validate(path, focused=False):
    cases = ET.parse(Path(path)).getroot().findall('.//testcase')
    if not cases:
        raise ValueError('No tests executed')
    if any(case.find('skipped') is not None for case in cases):
        raise ValueError('Selected checks must execute without skips')
    if any(case.find('failure') is not None or case.find('error') is not None for case in cases):
        raise ValueError('Verification failures recorded')
    if not focused:
        smoke = [case for case in cases if 'test_production_smoke' in case.attrib.get('classname', '') or case.attrib.get('name') == 'test_actual_websocket_through_caddy_and_nginx_committed_public_change']
        if len(smoke) != 6:
            raise ValueError(f'Expected six production checks, got {len(smoke)}')
    return len(cases)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('path')
    parser.add_argument('--focused', action='store_true')
    args = parser.parse_args()
    try:
        count = validate(args.path, args.focused)
    except (ValueError, OSError, ET.ParseError) as error:
        raise SystemExit(str(error)) from None
    print(f'All {count} {"selected" if args.focused else "integration"} checks passed; zero skips.' +
          ('' if args.focused else ' Six production transports confirmed.'))
