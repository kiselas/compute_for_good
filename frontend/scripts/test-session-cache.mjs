import { test } from 'node:test';
import assert from 'node:assert/strict';
import { build } from 'esbuild';
import vm from 'node:vm';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
const require = createRequire(import.meta.url);
const { QueryClient } = require('@tanstack/react-query');
const bundle = await build({ entryPoints: [fileURLToPath(new URL('../src/sessionCache.ts', import.meta.url))],
  bundle: true, write: false, format: 'cjs', platform: 'node', packages: 'external' });
const module = { exports: {} };
vm.runInNewContext(bundle.outputFiles[0].text, { module, exports: module.exports, require, console });
const { replaceAuthSession } = module.exports;
const guest = { user: null, csrf_token: null };
const member = id => ({ user: { id, username: id, role: 'contributor' }, csrf_token: id + '-csrf' });

for (const [action, before, after] of [['login', guest, member('new-user')], ['logout', member('old-user'), guest]]) {
  test(`late session lookup cannot undo ${action}`, async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    client.setQueryData(['auth-session'], before);
    let finish;
    let signal;
    const pending = client.fetchQuery({ queryKey: ['auth-session'], queryFn: context => {
      signal = context.signal;
      return new Promise(resolve => { finish = resolve; });
    } }).catch(() => {});
    try {
      await replaceAuthSession(client, after);
      finish(before);
      await pending;
      assert.deepEqual(client.getQueryData(['auth-session']), after);
      assert.equal(signal.aborted, true);
    } finally { finish(before); client.clear(); }
  });
}

test('logout purges private caches and cancels outstanding work before guest state is installed', async () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['health'], { demo_mode: false });
  client.setQueryData(['auth-session'], member('old-user'));
  for (const key of [['/me/profile', 'old-user'], ['maintainer', 'project', 'old-user'], ['/maintainer/projects/project/sprints']]) {
    client.setQueryData(key, { private: true });
  }
  let finish;
  let signal;
  const pending = client.fetchQuery({ queryKey: ['/me/credentials', 'old-user'], queryFn: context => {
    signal = context.signal;
    return new Promise(resolve => { finish = resolve; });
  } }).catch(() => {});
  try {
    await replaceAuthSession(client, guest);
    finish({ private: true });
    await pending;
    assert.equal(signal.aborted, true);
    assert.equal(client.getQueryCache().getAll().length, 2);
    assert.deepEqual(client.getQueryData(['health']), { demo_mode: false });
    assert.deepEqual(client.getQueryData(['auth-session']), guest);
  } finally { finish(null); client.clear(); }
});
