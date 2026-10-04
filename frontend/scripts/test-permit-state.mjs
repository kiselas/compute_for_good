import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/permitState.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { initialPermitState, permitReducer, permitIsValid, submissionPayload } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
const time = Date.parse('2026-10-04T12:00:00Z');
const permit = (token, expires) => ({ token, expires_at: new Date(expires).toISOString() });
const lease = { status: 'ACTIVE', token: 'own-lease-token', expires_at: new Date(time + 3600000).toISOString() };

function enterDraft(state) {
  for (const [field, value] of Object.entries({ pr_url: 'https://github.com/cfg-alpha-test/test/pull/1', head_sha: 'a'.repeat(40), summary: 'Verified implementation and tests' })) {
    state = permitReducer(state, { type: 'edit', field, value });
  }
  return state;
}

test('expiry disables registration at the exact boundary and live submit rejects a stale render', () => {
  const state = enterDraft(permitReducer(initialPermitState(), { type: 'issued', permit: permit('first', time + 600000) }));
  assert.equal(permitIsValid(state.permit, time + 599999), true);
  assert.equal(submissionPayload(state, time + 599999, lease).permit_token, 'first');
  assert.equal(permitIsValid(state.permit, time + 600000), false);
  // The UI might still reflect the pre-expiry render while a background timer
  // is throttled. Submission must use the current clock and refuse the token.
  assert.equal(submissionPayload(state, time + 600001, lease), null);
  assert.equal(state.draft.pr_url, 'https://github.com/cfg-alpha-test/test/pull/1');
});

test('renewal preserves all PR fields and includes edits made while the request was pending', () => {
  let state = enterDraft(permitReducer(initialPermitState(), { type: 'issued', permit: permit('expired', time) }));
  // Failed renewal does not produce an issued event and cannot destroy a draft.
  assert.equal(submissionPayload(state, time + 1, lease), null);
  const saved = { ...state.draft };
  state = permitReducer(state, { type: 'edit', field: 'summary', value: 'New verification while renewing' });
  state = permitReducer(state, { type: 'issued', permit: permit('replacement', time + 1200000) });
  const payload = submissionPayload(state, time + 600001, lease);
  assert.equal(payload.permit_token, 'replacement');
  assert.equal(payload.pr_url, saved.pr_url);
  assert.equal(payload.head_sha, saved.head_sha);
  assert.equal(payload.summary, 'New verification while renewing');
});

test('a valid permit cannot authorize an expired, released or unavailable lease', () => {
  const state = enterDraft(permitReducer(initialPermitState(), { type: 'issued', permit: permit('valid', time + 1200000) }));
  for (const invalid of [
    { ...lease, expires_at: new Date(time).toISOString() },
    { ...lease, status: 'RELEASED' },
    { ...lease, token: undefined },
    { ...lease, expires_at: 'invalid date' },
  ]) assert.equal(submissionPayload(state, time, invalid), null);
});

test('missing or malformed permits fail closed and new account/task state starts empty', () => {
  assert.equal(submissionPayload(initialPermitState(), time, lease), null);
  for (const invalid of [null, { token: '', expires_at: lease.expires_at }, { token: 'bad-date', expires_at: 'invalid' }]) {
    assert.equal(permitIsValid(invalid, time), false);
  }
  assert.equal(permitIsValid(permit('valid', time + 1000), NaN), false);
  assert.deepEqual(initialPermitState(), { permit: null, draft: { pr_url: '', head_sha: '', summary: '' }, invalidated: false });
});

test('server expiry wins over a slow client clock and only a new permit restores submission', () => {
  let state = enterDraft(permitReducer(initialPermitState(), { type: 'issued', permit: permit('server-expired', time + 1200000) }));
  assert.notEqual(submissionPayload(state, time, lease), null);
  // The server rejects the token even though the client's clock says valid.
  state = permitReducer(state, { type: 'invalidated' });
  const saved = { ...state.draft };
  assert.equal(submissionPayload(state, time, lease), null);
  state = permitReducer(state, { type: 'edit', field: 'summary', value: 'Preserved while retrying' });
  assert.equal(submissionPayload(state, time, lease), null);
  state = permitReducer(state, { type: 'issued', permit: permit('renewed', time + 1200000) });
  assert.equal(submissionPayload(state, time, lease).permit_token, 'renewed');
  assert.equal(state.draft.pr_url, saved.pr_url);
  assert.equal(state.draft.head_sha, saved.head_sha);
});
