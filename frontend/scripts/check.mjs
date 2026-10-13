import { spawn } from 'node:child_process';
import { mkdir, writeFile } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import { performance } from 'node:perf_hooks';

const root = fileURLToPath(new URL('../', import.meta.url));
const output = new URL('../../artifacts/frontend-check-latest.json', import.meta.url);
const started = performance.now();
const stages = [];

async function run(name, args) {
  const start = performance.now();
  console.log(`[check] ${name} started`);
  const code = await new Promise(resolve => {
    const child = spawn(process.execPath, args, { cwd: root, stdio: 'inherit' });
    child.on('error', error => { console.error(error.message); resolve(1); });
    child.on('exit', code => resolve(code ?? 1));
  });
  const seconds = Number(((performance.now() - start) / 1000).toFixed(3));
  stages.push({ name, seconds, exit_code: code });
  console.log(`[check] ${name}: ${code === 0 ? 'PASS' : 'FAIL'} (${seconds}s)`);
  return code;
}

const codes = await Promise.all([
  run('i18n', ['scripts/check-i18n.mjs']),
  run('tests', ['scripts/run-tests.mjs']),
  run('types', ['node_modules/typescript/bin/tsc', '-b']),
]);
if (codes.every(code => code === 0) && process.argv.includes('--build')) {
  codes.push(await run('bundle', ['node_modules/vite/bin/vite.js', 'build']));
}
const passed = codes.every(code => code === 0);
await mkdir(new URL('./', output), { recursive: true });
await writeFile(output, JSON.stringify({ passed, stages, seconds: Number(((performance.now() - started) / 1000).toFixed(3)) }, null, 2));
process.exitCode = passed ? 0 : 1;
