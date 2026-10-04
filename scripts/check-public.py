"""Read-only public release checks and a small, sequential latency baseline.

No account is created, no credential is sent and no redirect is followed.
This command is a diagnostic snapshot, not a stress test or scheduled monitor.
"""
import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
import time
from urllib.parse import urlsplit

import httpx


BASELINE_PATHS = ('/', '/api/ready', '/api/projects', '/api/tasks')


def origin_url(value):
    if not isinstance(value, str):
        raise ValueError('Origin must be a URL string')
    parsed = urlsplit(value)
    if (parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or not parsed.hostname):
        raise ValueError('Use an origin without credentials, path, query or fragment')
    if parsed.scheme != 'https' and not (parsed.scheme == 'http' and parsed.hostname in ('localhost', '127.0.0.1', '::1')):
        raise ValueError('HTTPS is required except for explicit local smoke targets')
    # Validate the port before any request is issued.
    parsed.port
    return value.rstrip('/')


def response_checks(response, path, origin):
    checks = {'http_200': response.status_code == 200}
    if response.status_code != 200:
        return checks
    if path == '/':
        policy = response.headers.get('content-security-policy', '')
        checks['csp'] = all(part in policy for part in ("script-src 'self'", "object-src 'none'", "frame-ancestors 'none'"))
        checks['nosniff'] = response.headers.get('x-content-type-options') == 'nosniff'
        if origin.startswith('https://'):
            checks['hsts'] = 'max-age=31536000' in response.headers.get('strict-transport-security', '')
        return checks
    try:
        data = response.json()
    except ValueError:
        return {**checks, 'valid_json': False}
    if path == '/api/ready':
        checks['ready'] = isinstance(data, dict) and data.get('status') == 'ready' and all(
            data.get(key) is True for key in ('database', 'redis', 'worker', 'integration_worker'))
    elif path == '/api/health':
        checks['production_mode'] = isinstance(data, dict) and data.get('status') == 'ok' and data.get('demo_mode') is False
    elif path in ('/api/projects', '/api/tasks'):
        checks['real_catalog'] = isinstance(data, list) and all(
            isinstance(row, dict) and not row.get('is_demo') and row.get('status') != 'DRAFT' for row in data)
    elif path == '/.well-known/oauth-authorization-server':
        # The SDK serializes the root issuer with a trailing slash. Both forms
        # denote this configured root; reject a different authority or path.
        try:
            matching_issuer = isinstance(data, dict) and origin_url(data.get('issuer', '')) == origin
        except ValueError:
            matching_issuer = False
        methods = data.get('code_challenge_methods_supported') if isinstance(data, dict) else None
        checks['oauth_discovery'] = matching_issuer and isinstance(methods, list) and 'S256' in methods
    return checks


def percentile(values, fraction):
    ordered = sorted(values)
    return round(ordered[max(0, math.ceil(len(ordered) * fraction) - 1)], 2) if ordered else None


def probe(client, origin, samples=5, interval=.25, pause=time.sleep):
    if not 1 <= samples <= 50 or not .1 <= interval <= 10:
        raise ValueError('Use 1..50 samples and 0.1..10 seconds between sequential requests')
    routes = {path: {'requests': 0, 'failed': 0, 'latency_ms': [], 'checks': {}} for path in BASELINE_PATHS}
    report = {'origin': origin, 'checked_at': datetime.now(timezone.utc).isoformat(), 'concurrency': 1,
              'interval_seconds': interval, 'samples_per_route': samples, 'routes': routes, 'additional_checks': {}}
    sequence = [path for _ in range(samples) for path in BASELINE_PATHS]
    sequence += ['/api/health', '/.well-known/oauth-authorization-server']
    for index, path in enumerate(sequence):
        started = time.perf_counter()
        try:
            response = client.get(origin + path, follow_redirects=False)
            checks = response_checks(response, path, origin)
        except httpx.HTTPError:
            # Exception text and response bodies may contain sensitive data.
            checks = {'transport_success': False}
        latency = (time.perf_counter() - started) * 1000
        if path in routes:
            route = routes[path]
            route['requests'] += 1
            route['failed'] += int(not all(checks.values()))
            route['latency_ms'].append(latency)
            for key, passed in checks.items():
                route['checks'][key] = route['checks'].get(key, True) and passed
        else:
            report['additional_checks'][path] = checks
        if index + 1 < len(sequence):
            pause(interval)
    for route in routes.values():
        latencies = route.pop('latency_ms')
        route.update(p50_ms=percentile(latencies, .5), p95_ms=percentile(latencies, .95), max_ms=round(max(latencies), 2))
    report['passed'] = all(route['failed'] == 0 for route in routes.values()) and all(
        all(checks.values()) for checks in report['additional_checks'].values())
    report['scope'] = 'Sequential read-only snapshot. Does not establish peak traffic capacity, alert delivery or contribution write-path availability.'
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--origin', required=True)
    parser.add_argument('--samples', type=int, default=5)
    parser.add_argument('--interval', type=float, default=.25)
    parser.add_argument('--timeout', type=float, default=10)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    origin = origin_url(args.origin)
    if not 1 <= args.timeout <= 30:
        parser.error('Timeout must be 1..30 seconds')
    with httpx.Client(timeout=args.timeout, trust_env=False, headers={'User-Agent': 'ComputeForGood-readonly-probe/1.0'}) as client:
        report = probe(client, origin, args.samples, args.interval)
    result = json.dumps(report, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result, encoding='utf-8')
    print(result)
    return 0 if report['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
