import { readdir } from 'node:fs/promises';
import { spawn } from 'node:child_process';
import { fileURLToPath } from 'node:url';

const root = fileURLToPath(new URL('../', import.meta.url));
const selected = process.argv.slice(2);
const files = selected.length ? selected : (await readdir(new URL('./', import.meta.url)))
  .filter(name => /^test-.*\.mjs$/.test(name)).sort().map(name => `scripts/${name}`);
// Separate processes preserve each suite's module/global isolation. Bound CPU use.
const child = spawn(process.execPath, ['--test', '--test-concurrency=3', ...files], { cwd: root, stdio: 'inherit' });
child.on('error', error => { console.error(error.message); process.exitCode = 1; });
child.on('exit', code => { process.exitCode = code ?? 1; });
