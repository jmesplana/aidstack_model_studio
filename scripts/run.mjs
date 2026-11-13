import {spawn, spawnSync} from 'node:child_process';
import {existsSync, readFileSync, writeFileSync} from 'node:fs';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import {join} from 'node:path';

const root = fileURLToPath(new URL('..', import.meta.url));
const mode = process.argv[2] || 'dev';
const pythonFlag = process.argv.indexOf('--python');
const bin = process.platform === 'win32' ? 'Scripts' : 'bin';
const executable = process.platform === 'win32' ? 'python.exe' : 'python';
function run(cmd, args) {
  const result = spawnSync(cmd, args, {cwd: root, stdio: 'inherit'});
  if (result.error || result.status !== 0) {
    console.error(result.error?.message || 'Setup failed. Check Python 3.10+ and your internet connection, then retry.');
    process.exit(result.status || 1);
  }
}
function setup(directory, requirements) {
  const python = join(root, directory, bin, executable);
  if (!existsSync(python)) run(process.env.STUDIO_PYTHON || (process.platform === 'win32' ? 'python' : 'python3'), ['-m', 'venv', join(root, directory)]);
  const fingerprint = createHash('sha256').update(readFileSync(join(root, requirements))).update(readFileSync(join(root, 'requirements.txt'))).digest('hex');
  const stamp = join(root, directory, '.requirements-sha256');
  if (!existsSync(stamp) || readFileSync(stamp, 'utf8') !== fingerprint) {
    run(python, ['-m', 'pip', 'install', '-r', requirements]);
    writeFileSync(stamp, fingerprint);
  }
  return python;
}
if (mode === 'setup-model') {
  const id = process.argv[3];
  if (!id || !/^[a-z][a-z0-9_]*$/.test(id) || !existsSync(join(root, 'studio', 'models', id, 'manifest.json'))) {
    console.error('Usage: npm run setup:model -- <module-id> (for example: laya)');
    process.exit(1);
  }
  setup('.venv', 'requirements.txt');
  setup(`.venv-${id}`, `studio/models/${id}/requirements.txt`);
  console.log(`Model module ${id} is ready. Checkpoints download on the first training run if not cached.`);
} else {
  const python = (pythonFlag !== -1 ? process.argv[pythonFlag + 1] : process.env.STUDIO_APP_PYTHON) || setup('.venv', 'requirements.txt');
  if (mode === 'setup') process.exit(0);
  if (mode === 'test') {
    run(python, ['-m', 'unittest', 'discover', '-s', 'tests', '-v']);
    run(process.execPath, ['--test', 'tests/ui.test.mjs']);
    process.exit(0);
  }
  const args = ['-m', mode === 'serve' ? 'studio.serve' : 'studio.app'];
  const child = spawn(python, args, {cwd: root, stdio: 'inherit', env: {...process.env, PYTHONUNBUFFERED: '1'}});
  for (const signal of ['SIGINT', 'SIGTERM']) process.on(signal, () => child.kill(signal));
  child.on('error', error => {console.error(error.message); process.exitCode = 1;});
  child.on('exit', code => {process.exitCode = code || 0;});
}
