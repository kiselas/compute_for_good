import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import ts from 'typescript';

const source = await readFile(new URL('../src/leaseStorage.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { readLeaseToken, writeLeaseToken } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);

test('denied storage getter preserves implementation and review tokens in memory', () => {
  for (const store of ['localStorage', 'sessionStorage']) {
    Object.defineProperty(globalThis, store, { configurable: true, get() { throw new Error('SecurityError'); } });
    assert.equal(readLeaseToken(store, 'user1:missing'), undefined);
    writeLeaseToken(store, 'user1:lease', 'first');
    assert.equal(readLeaseToken(store, 'user1:lease'), 'first');
    assert.equal(readLeaseToken(store, 'user2:lease'), undefined);
  }
});

test('quota failure preserves the latest claim and stored tokens survive module reload', async () => {
  const saved = new Map([['previous', 'persisted']]);
  Object.defineProperty(globalThis, 'localStorage', { configurable: true, value: {
    getItem: key => saved.get(key) ?? null,
    setItem() { throw new Error('QuotaExceededError'); },
  } });
  assert.equal(readLeaseToken('localStorage', 'previous'), 'persisted');
  writeLeaseToken('localStorage', 'user1:lease', 'replacement');
  assert.equal(readLeaseToken('localStorage', 'user1:lease'), 'replacement');
  const fresh = await import(`data:text/javascript;base64,${Buffer.from(compiled + '\n// fresh instance').toString('base64')}`);
  assert.equal(fresh.readLeaseToken('localStorage', 'previous'), 'persisted');
  assert.equal(fresh.readLeaseToken('localStorage', 'user1:lease'), undefined);
});
