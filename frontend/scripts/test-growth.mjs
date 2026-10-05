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
async function load(file, globals = {}) {
  const bundle = await build({ entryPoints: [fileURLToPath(new URL(file, import.meta.url))], bundle: true,
    write: false, format: 'cjs', platform: 'node', packages: 'external', jsx: 'automatic' });
  const module = { exports: {} };
  vm.runInNewContext(bundle.outputFiles[0].text, { module, exports: module.exports, require, console,
    setTimeout, clearTimeout, setInterval, clearInterval, URL, URLSearchParams, AbortController, ...globals });
  return module.exports;
}
const calendar = await load('../src/ActivityCalendar.tsx');
const share = await load('../src/ShareTools.tsx');
const sprint = await load('../src/SprintPage.tsx');
const activity = { username: 'participant', year: 2024, is_demo: false, as_of: '2024-01-03T12:00:00Z',
  days: [ { date: '2024-01-01', contributions: 0, reviews: 0 }, { date: '2024-01-02', contributions: 2, reviews: 1 }, { date: '2024-01-03', contributions: 0, reviews: 0 } ],
  active_days: 1, totals: { contributions: 2, reviews: 1 }, available_years: [2024] };
function render(element, entries = []) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  for (const [path, data] of entries) client.setQueryData([path], data);
  const result = renderToStaticMarkup(React.createElement(QueryClientProvider, { client }, React.createElement(MemoryRouter, null, element)));
  client.clear(); return result;
}
test('calendar renders real per-day counts, zero cells and exactly one keyboard entry point', () => {
  const result = render(React.createElement(calendar.default, { username: 'participant' }), [['/people/participant/activity', activity]]);
  assert.match(result, /data-date="2024-01-02"/);
  assert.match(result, /data-level="3"/);
  assert.match(result, /3 outcomes/);
  assert.match(result, /1 active days/);
  assert.match(result, /on the acceptance recording date in UTC/);
  assert.equal((result.match(/data-level="\d+"[^>]+tabindex="0"/g) ?? []).length, 1);
  assert.equal(calendar.calendarCells(activity).length, 3);
  assert.equal(calendar.calendarCells({ ...activity, year: 2023 }).length, 9);
});
test('calendar loading and demo states are explicit', () => {
  assert.match(render(React.createElement(calendar.default, { username: 'participant' })), /aria-busy="true"/);
  const result = render(React.createElement(calendar.default, { username: 'participant' }), [['/people/participant/activity', { ...activity, is_demo: true }]]);
  assert.match(result, /Demo recognition is separate/);
});
test('portable badges link to stable public evidence and project work', () => {
  const person = render(React.createElement(share.ReadmeBadge, { username: 'participant' }));
  assert.match(person, /\/api\/badges\/people\/participant.svg\?lang=en/);
  assert.match(person, /\/people\/participant/);
  assert.match(person, /may cache badges/);
  const project = render(React.createElement(share.ReadmeBadge, { projectId: 'project-id' }));
  assert.match(project, /\/tasks\?project_id=project-id/);
});
test('sharing supplies real PNG variants, escaped text and manual copy fallback', () => {
  const result = render(React.createElement(share.default, { id: 'submission-id', title: '<script>bad</script>' }));
  assert.match(result, /\/share\/submission-id\?lang=en/);
  assert.match(result, /card.png\?lang=en/);
  assert.match(result, /shape=portrait/);
  assert.match(result, /&lt;script&gt;bad&lt;\/script&gt;/);
  assert.doesNotMatch(result, /<script>/);
  assert.match(result, /readonly=""/i);
});
test('sprint card uses accepted outcomes and available task counts, without fake social activity', () => {
  const value = { project: { name: 'Project' }, state: 'active', slug: 'first-contribution', title: { en: 'First contribution' }, description: { en: 'Prepared work' }, accepted: 0, goal: 3, available: 3 };
  const result = render(React.createElement(sprint.SprintCard, { value }));
  assert.match(result, /href="\/sprints\/first-contribution"/);
  assert.match(result, /<progress value="0" max="3"/);
  assert.match(result, /0 of 3 tasks accepted/);
  assert.match(result, /3 available tasks/);
});

test('owner sprint mutations reach the real HTTP adapter as contracts, never RequestInit wrappers', async () => {
  const requests = [];
  const builder = await load('../src/SprintBuilder.tsx', { fetch: async (url, init) => {
    requests.push({ url, ...init });
    return { ok: true, status: 200, json: async () => ({ status: 'PUBLISHED' }) };
  } });
  const contract = { slug: 'first-contribution', title: { en: 'First', ru: 'Первый', 'zh-CN': '第一次' }, task_ids: ['task-1'] };
  await builder.saveSprint('/maintainer/projects/project-1/sprints', contract);
  await builder.saveSprint('/maintainer/projects/project-1/sprints/sprint-1/publish', { version: 1 });
  await builder.saveSprint('/maintainer/projects/project-1/sprints/sprint-1/pause', { version: 2 });
  assert.deepEqual(JSON.parse(requests[0].body), contract);
  assert.deepEqual(JSON.parse(requests[1].body), { version: 1 });
  assert.deepEqual(JSON.parse(requests[2].body), { version: 2 });
  assert.equal(requests[0].url, '/api/maintainer/projects/project-1/sprints');
  assert.ok(requests.every(r => r.method === 'POST' && r.credentials === 'include' && r.headers['Content-Type'] === 'application/json'));
});
