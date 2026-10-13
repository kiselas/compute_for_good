import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import vm from 'node:vm';
import ts from 'typescript';

const source = await readFile(new URL('../src/submissionDraftStorage.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function storage() {
  const values = new Map();
  return { values, get length() { return values.size; }, key: index => [...values.keys()][index] ?? null,
    getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key) };
}
function load(store, blocked = false) {
  const module = { exports: {} };
  const context = { module, exports: module.exports };
  Object.defineProperty(context, 'sessionStorage', { get: () => { if (blocked) throw Error('Storage blocked'); return store; } });
  vm.runInNewContext(compiled, context);
  return module.exports;
}
const time = Date.parse('2026-10-13T12:00:00Z');
const scope = { userId: 'owner', taskId: 'task', leaseId: 'lease', expiresAt: new Date(time + 3600000).toISOString() };
const draft = { pr_url: 'https://github.com/owner/project/pull/12', head_sha: 'a'.repeat(40), summary: 'Verified tests\nОписание работы' };
const plain = value => JSON.parse(JSON.stringify(value));

test('same-tab reload restores only draft fields, never lease or permit credentials', () => {
  const store = storage();
  const first = load(store);
  assert.equal(first.writeSubmissionDraft(scope, { ...draft, permit_token: 'secret-permit', lease_token: 'secret-lease' }, time), 'persisted');
  const serialized = [...store.values.values()][0];
  assert.doesNotMatch(serialized, /secret-|permit_token|lease_token/);
  assert.deepEqual(plain(load(store).readSubmissionDraft(scope, time + 1)), draft);
});

test('account, task and lease changes cannot restore another draft', () => {
  const store = storage();
  load(store).writeSubmissionDraft(scope, draft, time);
  for (const changed of [{ userId: 'other' }, { taskId: 'other' }, { leaseId: 'other' }]) {
    assert.equal(load(store).hasSubmissionDraft(load(store).readSubmissionDraft({ ...scope, ...changed }, time)), false);
  }
  assert.equal(load(store).hasSubmissionDraft(load(store).readSubmissionDraft(null, time)), false);
});

test('lease expiry and 24-hour retention prevent stale recovery at the boundary', () => {
  const store = storage();
  load(store).writeSubmissionDraft(scope, draft, time);
  assert.equal(load(store).hasSubmissionDraft(load(store).readSubmissionDraft(scope, time + 3600000)), false);
  assert.equal(store.values.size, 0);
  const longLease = { ...scope, expiresAt: new Date(time + 3 * 86400000).toISOString() };
  load(store).writeSubmissionDraft(longLease, draft, time);
  assert.equal(load(store).hasSubmissionDraft(load(store).readSubmissionDraft(longLease, time + 86400000)), false);
});

test('denied storage and quota failure preserve drafts in memory and report no reload persistence', () => {
  const store = storage();
  for (const adapter of [load(store, true), load({ ...store, setItem: () => { throw Error('Quota'); } })]) {
    assert.equal(adapter.writeSubmissionDraft(scope, draft, time), 'memory');
    assert.deepEqual(plain(adapter.readSubmissionDraft(scope, time)), draft);
    adapter.removeSubmissionDraft(scope);
    assert.equal(adapter.hasSubmissionDraft(adapter.readSubmissionDraft(scope, time)), false);
  }
});

test('clear after registration and account changes removes only this feature data', () => {
  const store = storage();
  store.setItem('cfg-language', 'ru');
  const adapter = load(store);
  adapter.writeSubmissionDraft(scope, draft, time);
  adapter.removeSubmissionDraft(scope);
  assert.equal(load(store).hasSubmissionDraft(load(store).readSubmissionDraft(scope, time)), false);
  adapter.writeSubmissionDraft(scope, draft, time);
  adapter.writeSubmissionDraft({ ...scope, leaseId: 'second' }, draft, time);
  adapter.clearSubmissionDrafts();
  assert.equal(adapter.hasSubmissionDraft(adapter.readSubmissionDraft(scope, time)), false);
  assert.deepEqual([...store.values], [['cfg-language', 'ru']]);
});

test('malformed, foreign and oversized browser records fail closed', () => {
  const store = storage();
  load(store).writeSubmissionDraft(scope, draft, time);
  const key = [...store.values.keys()][0];
  const record = JSON.parse(store.getItem(key));
  for (const raw of ['bad json', 'null', JSON.stringify({ ...record, userId: 'other' }), JSON.stringify({ ...record, version: 2 }),
    JSON.stringify({ ...record, expiresAt: 'tomorrow' }), JSON.stringify({ ...record, draft: { ...draft, summary: 'x'.repeat(10001) } }), 'x'.repeat(80001)]) {
    store.setItem(key, raw);
    const adapter = load(store);
    assert.equal(adapter.hasSubmissionDraft(adapter.readSubmissionDraft(scope, time)), false);
  }
});

test('maximum-sized escaped text survives serialization and recovery without truncation', () => {
  const store = storage();
  const value = { ...draft, summary: '\u0001'.repeat(10000) };
  load(store).writeSubmissionDraft(scope, value, time);
  assert.deepEqual(plain(load(store).readSubmissionDraft(scope, time)), value);
});
