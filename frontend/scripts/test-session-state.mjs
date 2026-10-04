import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import ts from 'typescript';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';
const require = createRequire(import.meta.url);
// Match the bundled App's CommonJS entrypoints so provider contexts are shared.
const { MemoryRouter } = require('react-router-dom');
const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');

const source = await readFile(new URL('../src/sessionState.ts', import.meta.url), 'utf8');
const compiled = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const { sessionPhase } = await import(`data:text/javascript;base64,${Buffer.from(compiled).toString('base64')}`);
// Vite's existing esbuild dependency bundles the real App for server rendering.
// No DOM simulation or alternate UI implementation replaces its route gates.
const bundle = await build({ entryPoints: [fileURLToPath(new URL('../src/App.tsx', import.meta.url))],
  bundle: true, write: false, format: 'cjs', platform: 'node', packages: 'external', jsx: 'automatic' });
const module = { exports: {} };
vm.runInNewContext(bundle.outputFiles[0].text, { module, exports: module.exports, require, console,
  setTimeout, clearTimeout, setInterval, clearInterval, URL, URLSearchParams, AbortController });
const App = module.exports.default;

function render(path, state, user = null) {
  // The seeded error represents an already mounted request that failed. Avoid
  // a new observer converting it into an automatic mount retry during SSR.
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false } } });
  client.setQueryData(['health'], { demo_mode: false });
  if (state === 'known' || state === 'cached-error') client.setQueryData(['auth-session'], { user, csrf_token: 'qa-only' });
  if (state === 'error' || state === 'cached-error') {
    const query = client.getQueryCache().build(client, { queryKey: ['auth-session'] });
    query.setState({ status: 'error', error: new Error('Controlled session outage'), fetchStatus: 'idle' });
  }
  client.setQueryData(['/projects', 'public'], [{ id: 'qa-project', slug: 'qa-project', name: 'Public catalog still available',
    description: 'A public project', status: 'VERIFIED', is_demo: false, language: 'Python', readiness_score: 0, impact_score: 0 }]);
  client.setQueryData(['/tasks/qa-work', 'public'], { id: 'qa-work', title: 'Public task still available', description: 'A public task contract',
    status: 'AVAILABLE', project_id: 'qa-project', is_demo: false, risk: 'LOW', difficulty: 'EASY', required_model_tier: 'BASIC',
    estimated_minutes: 15, acceptance_criteria: [], allowed_paths: [], forbidden_paths: [], verification_commands: [] });
  const output = renderToStaticMarkup(React.createElement(QueryClientProvider, { client },
    React.createElement(MemoryRouter, { initialEntries: [path] }, React.createElement(App))));
  client.clear();
  return output;
}
const header = html => html.match(/<header[\s\S]*?<\/header>/)[0];

test('cold session progresses through loading/error/retry and only a known null user is guest', () => {
  assert.equal(sessionPhase({ hasData: false, hasUser: false, isError: false }), 'loading');
  assert.equal(sessionPhase({ hasData: false, hasUser: false, isError: true }), 'error');
  assert.equal(sessionPhase({ hasData: true, hasUser: false, isError: false }), 'guest');
  assert.equal(sessionPhase({ hasData: true, hasUser: true, isError: false }), 'authenticated');
});

test('real protected/auth/consent routes never render guest forms before session resolution', () => {
  for (const path of ['/account', '/activity', '/login', '/register', '/oauth/consent?id=qa-request', '/maintainer', '/maintainer/projects/qa-owner', '/moderation']) {
    for (const state of ['loading', 'error']) {
      const html = render(path, state);
      assert.match(html, state === 'loading' ? /Checking your session/ : /Unable to check your session/);
      assert.doesNotMatch(html, /Log in to start contributing|Sign in to manage projects|Operator access required|type="password"/);
      assert.doesNotMatch(header(html), /href="\/login"|href="\/register"/);
      if (state === 'error') assert.match(html, /type="button"[^>]*>Retry session check/);
    }
  }
});

test('known guest receives login actions and authenticated cached data survives a refetch failure', () => {
  const guest = render('/account', 'known');
  assert.match(guest, /Log in to start contributing/);
  assert.match(header(guest), /href="\/login"/);
  const user = { id: 'qa-user', username: 'qa-session-owner', role: 'contributor', github_connected: true };
  const cached = render('/account', 'cached-error', user);
  assert.match(header(cached), /qa-session-owner/);
  assert.doesNotMatch(cached, /Unable to check your session|Log in to start contributing/);
  assert.equal(sessionPhase({ hasData: true, hasUser: false, isError: true }), 'guest');
});

test('public catalog and landing remain rendered while cold authentication fails', () => {
  const catalog = render('/projects', 'error');
  assert.match(catalog, /Public catalog still available/);
  assert.match(catalog, /Retry session check/);
  assert.doesNotMatch(header(catalog), /href="\/login"/);
  const landing = render('/', 'error');
  assert.match(landing, /class="marketing-hero"/);
  assert.match(landing, /href="\/tasks"/);
});

test('shared guest prompts on public task/review/connect/onboarding surfaces wait for a known session', () => {
  for (const path of ['/tasks/qa-work', '/reviews', '/connect', '/onboarding']) {
    const html = render(path, 'error');
    assert.match(html, /Unable to check your session/);
    assert.doesNotMatch(html, /Log in to start contributing|Create an account or log in to submit a project you maintain|Sign up to get a revocable/);
    if (path === '/tasks/qa-work') assert.match(html, /Public task still available/);
  }
});
