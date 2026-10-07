# Task panel (agent-to-agent AI Studio) for vc_trade

The helper is checked out at `tools/agent-to-agent/` (revision `cf2c267c8ff2f9f89af379fbef84f04ba800c257`). Its own panel scripts serve the helper folder's `prompt/` and `report/`. `tools/task-panel.mjs` makes the panel serve **this** project's `prompt/` and `report/` instead, without changing the helper's files.

## One-time setup (inside tools/agent-to-agent, using its local npm cache)

```powershell
cd E:\VideCode\vc_trade\tools\agent-to-agent
npm.cmd install --cache .npm-cache   # done on 2026-10-02 (83 packages)
npm.cmd run ui:typecheck
npm.cmd run ui:build                 # creates scripts/task-panel/dist/
npm.cmd run test:panel               # optional: the helper's own tests
```

## Start / stop (from E:\VideCode\vc_trade)

```powershell
node tools/task-panel.mjs start      # hidden background process; prints http://127.0.0.1:<port>/
node tools/task-panel.mjs status
node tools/task-panel.mjs stop
node tools/task-panel.mjs serve      # foreground alternative (Ctrl+C to stop)
```

- It listens on 127.0.0.1 only, on port 4317 by default. If that port is busy it tries the next ones. Use `--port N` or `TASK_PANEL_PORT` to choose a port.
- State and log files are in `.tmp/task-panel/`: `server.json` and `server.log`, plus the panel's own `approvals.jsonl` and `auto-send.jsonl`.
- **Send to Claude** publishes one approved prompt to `prompt/`. Claude's terminal monitor must be running in this project to pick it up.
- **Auto-send** is off by default and stays off unless you turn it on yourself.
