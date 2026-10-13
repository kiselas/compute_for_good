import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const bundle = await build({ entryPoints: [fileURLToPath(new URL('../src/api.ts', import.meta.url))],
  bundle: true, write: false, format: 'cjs', platform: 'node', packages: 'external' });

function load(fetch, locale = 'en') {
  const timers = new Map();
  let nextTimer = 0;
  const module = { exports: {} };
  vm.runInNewContext(bundle.outputFiles[0].text, { module, exports: module.exports, require, console,
    AbortController, fetch,
    setTimeout: (callback, delay) => { const id = ++nextTimer; timers.set(id, { callback, delay }); return id; },
    clearTimeout: id => timers.delete(id),
    window: { localStorage: { getItem: () => locale }, navigator: { languages: [locale] }, addEventListener: () => {} } });
  return { ...module.exports, timers, expire: () => {
    assert.equal(timers.size, 1);
    const timer = [...timers.values()][0];
    assert.equal(timer.delay, 30_000);
    timer.callback();
  } };
}
function untilAbort(signal) {
  return new Promise((resolve, reject) => {
    const cancel = () => reject(signal.reason);
    if (signal.aborted) cancel();
    else signal.addEventListener('abort', cancel, { once: true });
  });
}

for (const stage of ['headers', 'success body', 'error body']) {
  test(`deadline covers stalled ${stage} and never replays a mutation`, async () => {
    let requests = 0;
    let signal;
    let started;
    const reading = new Promise(resolve => { started = resolve; });
    const adapter = load(async (url, options) => {
      requests++;
      signal = options.signal;
      if (stage === 'headers') { started(); return untilAbort(signal); }
      return { ok: stage === 'success body', status: stage === 'success body' ? 200 : 503,
        json: () => { started(); return untilAbort(signal); } };
    }, 'ru');
    const pending = adapter.api('/tasks/task/claim', { tier: 'BASIC' });
    await reading;
    adapter.expire();
    await assert.rejects(pending, error => error instanceof adapter.ApiError && error.status === 0 && /время/i.test(error.message));
    assert.equal(signal.aborted, true);
    assert.equal(requests, 1);
    assert.equal(adapter.timers.size, 0);
  });
}

test('query cancellation reaches fetch and keeps the caller abort reason', async () => {
  let signal;
  const adapter = load(async (url, options) => { signal = options.signal; return untilAbort(signal); });
  const caller = new AbortController();
  const pending = adapter.api('/auth/session', undefined, undefined, { signal: caller.signal });
  const reason = new Error('identity changed');
  caller.abort(reason);
  await assert.rejects(pending, error => error === reason);
  assert.equal(signal.aborted, true);
  assert.equal(adapter.timers.size, 0);
});

test('already cancelled calls remain cancelled and completed requests detach abort listeners', async () => {
  let signal;
  const adapter = load(async (url, options) => {
    signal = options.signal;
    if (signal.aborted) return untilAbort(signal);
    return { ok: true, status: 204 };
  });
  const cancelled = new AbortController();
  cancelled.abort();
  await assert.rejects(adapter.api('/tasks', undefined, undefined, { signal: cancelled.signal }), error => error.name === 'AbortError');
  const caller = new AbortController();
  assert.equal(await adapter.api('/tasks', undefined, undefined, { signal: caller.signal }), null);
  caller.abort();
  assert.equal(signal.aborted, false);
  assert.equal(adapter.timers.size, 0);
});

test('JSON, cookies, locale, CSRF and scoped bearer contracts survive request cancellation support', async () => {
  const requests = [];
  const adapter = load(async (url, options) => {
    requests.push({ url, ...options });
    return { ok: true, status: 200, json: async () => ({ saved: true }) };
  }, 'zh-CN');
  adapter.setCsrfToken('browser-csrf');
  assert.deepEqual(await adapter.api('/tasks', { title: 'work' }, 'PATCH'), { saved: true });
  const patch = requests[0];
  assert.equal(patch.method, 'PATCH');
  assert.equal(patch.credentials, 'include');
  assert.equal(patch.headers['Accept-Language'], 'zh-CN');
  assert.equal(patch.headers['X-CSRF-Token'], 'browser-csrf');
  assert.equal(patch.body, JSON.stringify({ title: 'work' }));
  adapter.setToken('scoped-token');
  await adapter.api('/tasks', {});
  assert.equal(requests[1].headers.Authorization, 'Bearer scoped-token');
  assert.equal(requests[1].headers['X-CSRF-Token'], undefined);
  assert.equal(adapter.timers.size, 0);
});

test('HTML proxy errors include a localized actual status; API details remain intact', async () => {
  const adapter = load(async () => ({ ok: false, status: 502, json: async () => { throw new SyntaxError('HTML response'); } }), 'ru');
  await assert.rejects(adapter.api('/projects'), error => error.status === 502 && error.message === 'Ошибка запроса (502)');
  assert.equal(adapter.timers.size, 0);
  const conflict = load(async () => ({ ok: false, status: 409, json: async () => ({ detail: 'Submission permit expired' }) }));
  await assert.rejects(conflict.api('/submissions', {}), error => error.status === 409 && error.message === 'Submission permit expired');
  assert.equal(conflict.timers.size, 0);
});
