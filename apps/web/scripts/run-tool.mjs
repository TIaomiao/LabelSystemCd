import { spawnSync } from 'node:child_process';
import { existsSync } from 'node:fs';
import { resolve } from 'node:path';

const [tool, ...args] = process.argv.slice(2);
if (!tool || !/^[a-z0-9_-]+$/i.test(tool)) throw new Error('A safe tool name is required.');

const projectRoot = resolve(import.meta.dirname, '../../..');
const executableName = process.platform === 'win32' ? `${tool}.cmd` : tool;
const candidates = [
  resolve(projectRoot, 'node_modules/.bin', executableName),
  resolve(projectRoot, 'frontend/node_modules/.bin', executableName)
];
const executable = candidates.find(existsSync);
if (!executable) {
  throw new Error(`Cannot find ${tool}. Run npm install at the repository root or in frontend/.`);
}

const result = spawnSync(executable, args, {
  cwd: resolve(import.meta.dirname, '..'),
  stdio: 'inherit',
  shell: process.platform === 'win32'
});
if (result.error) throw result.error;
process.exit(result.status ?? 1);
