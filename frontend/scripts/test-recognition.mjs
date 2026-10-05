import { test } from 'node:test';
import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { fileURLToPath } from 'node:url';
import vm from 'node:vm';
import { build } from 'esbuild';
import React from 'react';
import { renderToStaticMarkup } from 'react-dom/server';

const require = createRequire(import.meta.url);
const { MemoryRouter } = require('react-router-dom');
const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');
async function load(file) {
  const bundle = await build({ entryPoints: [fileURLToPath(new URL(file, import.meta.url))], bundle: true,
    write: false, format: 'cjs', platform: 'node', packages: 'external', jsx: 'automatic' });
  const module = { exports: {} };
  vm.runInNewContext(bundle.outputFiles[0].text, { module, exports: module.exports, require, console,
    setTimeout, clearTimeout, setInterval, clearInterval, URL, URLSearchParams, AbortController });
  return module.exports.default;
}
const Rankings = await load('../src/LeaderboardPage.tsx');
const Recognition = await load('../src/RecognitionPanel.tsx');
const reputation = {
  metrics: { accepted_contributions: 1, accepted_reviews: 0, projects_helped: 1 },
  acceptance: { accepted: 1, decided: 1, rate: 100 }, is_demo: false,
  achievements: [
    { id: 'first_contribution', threshold: 1, progress: 1, earned: true },
    { id: 'five_contributions', threshold: 5, progress: 1, earned: false },
    { id: 'first_review', threshold: 1, progress: 0, earned: false },
  ],
};
const data = { total: 2, entries: [{ username: 'qa-contributor', rank: 1, metrics: reputation.metrics }],
  as_of: '2026-10-05T09:00:00Z', metric: 'contributions', period: 'all', offset: 0, limit: 25, is_demo: false };
function renderRankings(path, value, error = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false, retryOnMount: false } } });
  const url = new URL(path, 'http://localhost');
  const queryPath = `/leaderboard?metric=${url.searchParams.get('metric') ?? 'contributions'}&period=${url.searchParams.get('period') ?? 'all'}&limit=25&offset=${url.searchParams.get('offset') ?? '0'}&demo=${url.searchParams.get('demo') ?? 'false'}`;
  if (value) client.setQueryData([queryPath], value);
  if (error) client.getQueryCache().build(client, { queryKey: [queryPath] }).setState({ status: 'error', error: new Error('Controlled API failure'), fetchStatus: 'idle' });
  const result = renderToStaticMarkup(React.createElement(QueryClientProvider, { client },
    React.createElement(MemoryRouter, { initialEntries: [path] }, React.createElement(Rankings))));
  client.clear();
  return result;
}
function renderRecognition(value) {
  return renderToStaticMarkup(React.createElement(MemoryRouter, null, React.createElement(Recognition, { reputation: value })));
}

test('actual table links public evidence, exposes selected category and handles pagination', () => {
  const result = renderRankings('/leaderboard?metric=reviews&period=30d&offset=25', data);
  assert.match(result, /href="\/people\/qa-contributor"/);
  assert.match(result, /<caption>Reviews on accepted work/);
  assert.match(result, /Last 30 days/);
  assert.match(result, /aria-pressed="true"[^>]*>[\s\S]*?Reviews on accepted work/);
  assert.match(result, /<button[^>]*disabled=""[^>]*>Next/);
  assert.doesNotMatch(result, /<button[^>]*disabled=""[^>]*>Previous/);
  assert.doesNotMatch(result, /role="tab"/);
});
test('empty, loading and unavailable states never fabricate contributors', () => {
  assert.match(renderRankings('/leaderboard', { ...data, total: 0, entries: [] }), /The first places are waiting/);
  assert.match(renderRankings('/leaderboard', null), /aria-busy="true"/);
  const failed = renderRankings('/leaderboard', null, true);
  assert.match(failed, /Rankings are temporarily unavailable/);
  assert.match(failed, /Try again/);
  assert.doesNotMatch(failed, /qa-contributor/);
});
test('demo rankings and profiles explicitly disclose their separate realm', () => {
  const result = renderRankings('/leaderboard?demo=true', { ...data, is_demo: true });
  assert.match(result, /Demo recognition is separate/);
  assert.match(renderRecognition({ ...reputation, is_demo: true }), /href="\/leaderboard\?demo=true"/);
});
test('recognition renders earned and locked achievements with accessible progress', () => {
  const result = renderRecognition(reputation);
  assert.match(result, /achievement-card earned/);
  assert.match(result, /achievement-card locked/);
  assert.match(result, /<progress value="1" max="5" aria-label="Steady contributor"/);
  assert.match(result, /1 of 3 earned/);
  assert.match(result, /1 decided submissions/);
});
test('no history renders an unavailable acceptance rate rather than perfect or failed reliability', () => {
  const result = renderRecognition({ ...reputation, acceptance: { accepted: 0, decided: 0, rate: null } });
  assert.match(result, /<strong>—<\/strong><span>PR acceptance rate/);
  assert.doesNotMatch(result, /<strong>0%|<strong>100%/);
});
