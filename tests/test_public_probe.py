"""Monitoring must reject a misleading 200 and avoid following redirects or logging secrets."""
import importlib.util
from pathlib import Path

import httpx
import pytest

spec = importlib.util.spec_from_file_location('public_probe', Path(__file__).resolve().parents[1] / 'scripts/check-public.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.mark.parametrize('failure', ['worker', 'demo', 'draft', 'csp', 'redirect', 'malformed', 'transport', 'issuer', 'issuer_type', 'methods_type', 'issuer_slash', None])
def test_public_probe_rejects_bad_success_and_does_not_disclose_body(failure):
    observed = []
    secret = 'private-response-value'

    def respond(request):
        observed.append(str(request.url))
        assert not any(name in request.headers for name in ('authorization', 'cookie'))
        path = request.url.path
        if path == '/api/ready':
            if failure == 'transport':
                raise httpx.ReadTimeout(secret, request=request)
            if failure == 'redirect':
                return httpx.Response(302, headers={'Location': 'https://untrusted.invalid/' + secret})
            if failure == 'malformed':
                return httpx.Response(200, text=secret)
            return httpx.Response(200, json={'status': 'ready', 'database': True, 'redis': True,
                                            'worker': failure != 'worker', 'integration_worker': True, 'secret': secret})
        if path == '/':
            return httpx.Response(200, text=secret, headers={'Content-Security-Policy': '' if failure == 'csp' else "script-src 'self'; object-src 'none'; frame-ancestors 'none'",
                                                          'X-Content-Type-Options': 'nosniff', 'Strict-Transport-Security': 'max-age=31536000'})
        if path == '/api/health':
            return httpx.Response(200, json={'status': 'ok', 'demo_mode': failure == 'demo'})
        if path == '/.well-known/oauth-authorization-server':
            issuer = 'https://untrusted.invalid' if failure == 'issuer' else ('https://cfg.test/' if failure == 'issuer_slash' else 'https://cfg.test')
            return httpx.Response(200, json={'issuer': 42 if failure == 'issuer_type' else issuer,
                                           'code_challenge_methods_supported': 'S256' if failure == 'methods_type' else ['S256']})
        return httpx.Response(200, json=[{'status': 'DRAFT' if failure == 'draft' else 'AVAILABLE', 'is_demo': False}])

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        report = module.probe(client, 'https://cfg.test', samples=2, interval=.1, pause=lambda _: None)
    assert report['passed'] is (failure in (None, 'issuer_slash'))
    assert all(url.startswith('https://cfg.test/') for url in observed)
    assert secret not in str(report)
    assert all(row['requests'] == 2 for row in report['routes'].values())


@pytest.mark.parametrize('origin', ['https://user:secret@cfg.test', 'https://cfg.test/?token=secret', 'https://cfg.test/#secret', 'https://cfg.test/path', 'http://cfg.test', 'https://cfg.test:invalid'])
def test_probe_origin_rejects_credentials_and_unsafe_targets(origin):
    with pytest.raises(ValueError):
        module.origin_url(origin)
