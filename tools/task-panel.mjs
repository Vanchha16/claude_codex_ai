// Project-local launcher for the agent-to-agent task panel, serving THIS project's prompt/ and report/.
//
// The helper's own `--root` option only accepts folders inside tools/agent-to-agent, and its start script
// only records server state for its default root, so this launcher calls the helper's exported
// startPanelServer({ root }) with the vc_trade project root instead. The helper's files are not modified.
//
// Usage (from the project root):
//   node tools/task-panel.mjs start [--port N]   start in the background (hidden) and print the URL
//   node tools/task-panel.mjs stop               stop the recorded panel
//   node tools/task-panel.mjs status             show whether the recorded panel is alive
//   node tools/task-panel.mjs serve [--port N]   run in the foreground (Ctrl+C to stop)
import { spawn } from 'node:child_process'
import { mkdir, open, rename, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const ROOT = path.resolve(fileURLToPath(new URL('..', import.meta.url)))
const HELPER = path.join(ROOT, 'tools', 'agent-to-agent', 'scripts', 'task-panel')
const STATE_DIR = path.join(ROOT, '.tmp', 'task-panel')
const STATE = path.join(STATE_DIR, 'server.json')
const LOG = path.join(STATE_DIR, 'server.log')

const { recordedPanel } = await import(pathToFileURL(path.join(HELPER, 'health.mjs')).href)

function argument(name) {
  const index = process.argv.indexOf(name)
  return index === -1 ? undefined : process.argv[index + 1]
}

async function serve() {
  const { startPanelServer, DEFAULT_PORT } = await import(pathToFileURL(path.join(HELPER, 'server.mjs')).href)
  const port = Number(argument('--port') ?? process.env.TASK_PANEL_PORT ?? DEFAULT_PORT)
  const log = message => console.log(`[${new Date().toISOString()}] ${message}`)
  const running = await startPanelServer({ root: ROOT, port, log })
  await mkdir(STATE_DIR, { recursive: true })
  const temporary = `${STATE}.${process.pid}.tmp`
  await writeFile(temporary, JSON.stringify({ url: running.url, pid: process.pid, root: ROOT, startedAt: new Date().toISOString() }, null, 2))
  await rename(temporary, STATE)
  log(`Claude task panel running at ${running.url} for project ${ROOT}`)
  const stop = () => running.close().then(() => process.exit(0))
  process.on('SIGINT', stop)
  process.on('SIGTERM', stop)
}

async function start() {
  const existing = await recordedPanel(STATE)
  if (existing.alive) {
    console.log(`Claude task panel is already running: ${existing.state.url} (PID ${existing.state.pid})`)
    return 0
  }
  await mkdir(STATE_DIR, { recursive: true })
  const output = await open(LOG, 'a')
  const child = spawn(process.execPath, [fileURLToPath(import.meta.url), 'serve', ...process.argv.slice(3)], {
    cwd: ROOT,
    detached: true,
    windowsHide: true,
    stdio: ['ignore', output.fd, output.fd],
  })
  child.unref()
  try {
    for (let waited = 0; waited < 10000; waited += 250) {
      await new Promise(resolve => setTimeout(resolve, 250))
      const panel = await recordedPanel(STATE)
      if (panel.alive && panel.state.pid === child.pid) {
        console.log(`Claude task panel running in the background: ${panel.state.url} (PID ${child.pid})`)
        console.log('Stop it with: node tools/task-panel.mjs stop')
        return 0
      }
    }
  } finally {
    await output.close()
  }
  console.error(`The panel did not start within 10 seconds. See ${path.relative(ROOT, LOG)}.`)
  return 1
}

async function stop() {
  const { state, alive } = await recordedPanel(STATE)
  if (!state) return console.log('No running panel is recorded.'), 0
  if (!alive) return console.log(`The recorded panel (${state.url}) is not responding as the task panel; nothing was stopped.`), 0
  process.kill(state.pid)
  console.log(`Stopped the Claude task panel at ${state.url} (PID ${state.pid}).`)
  return 0
}

async function status() {
  const { state, alive } = await recordedPanel(STATE)
  console.log(state ? `${alive ? 'Running' : 'Not responding'}: ${state.url} (PID ${state.pid})` : 'No running panel is recorded.')
  return alive ? 0 : 1
}

const command = process.argv[2]
if (command === 'serve') {
  serve().catch(error => { console.error(error.message); process.exit(1) })
} else {
  const actions = { start, stop, status }
  if (!actions[command]) {
    console.error('Usage: node tools/task-panel.mjs start|stop|status|serve [--port N]')
    process.exitCode = 2
  } else {
    process.exitCode = await actions[command]()
  }
}
