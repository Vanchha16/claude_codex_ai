# Claude report: Install and launch the agent-to-agent website panel here

Task ID: 20261002-105259-resume-task-panel
Source prompt: `prompt/20261002-105259-resume-task-panel.md`
Status: partially completed (blocked at build/launch)
Reported at: 2026-10-02

## Outcome

The prompt passed the approval gate:
- It is in `prompt/`, not drafts.
- It says `Delivery status: APPROVED FOR EXECUTION`.
- It has a Task ID, Source prompt and Report path.
- Its `User authorization:` line records "send it" plus "tell claude clone done."
- No report existed for it.

The user also told Claude directly in the terminal that the clone was done.

**Done:**
1. **Checked the clone.** `tools/agent-to-agent` is at revision `cf2c267c8ff2f9f89af379fbef84f04ba800c257` ("Add opt-in future-only Auto-send to the task panel", 2026-10-02 10:31 +0700), with a clean working tree. This matches the remote HEAD Codex reported. I did not clone again.
2. **Read the helper's instructions:** README.md, AGENTS.md, CLAUDE.md, package.json, .npmrc, and the panel's `server.mjs`, `start.mjs`, `stop.mjs`, `health.mjs` and `core.mjs`.
3. **Installed dependencies locally.** `npm.cmd install --cache .npm-cache` in `tools/agent-to-agent` added 83 packages to `tools/agent-to-agent/node_modules/`. The cache is `tools/agent-to-agent/.npm-cache/`. Nothing was installed globally.
4. **Root selection.** The stock `server.mjs --root` can't serve vc_trade. `withinProject()` only accepts folders inside the helper checkout, and vc_trade is its parent. Also, `start.mjs` waits for `.tmp/task-panel/server.json`, which `server.mjs` writes only for its default root, so a background start with `--root` would time out. As step 4 of the prompt allows, I added a small project-local launcher, `tools/task-panel.mjs`. It calls the helper's exported `startPanelServer({ root })` with root `E:\VideCode\vc_trade` and records state and logs in `E:\VideCode\vc_trade\.tmp\task-panel\`. The helper's own files were not modified.

**Blocked:** Claude Code's permission review denied running the helper's downloaded code ("Code from External"). That stopped `npm.cmd run ui:typecheck`, `ui:build` and `test:panel`. Launching the panel runs the same downloaded code (`server.mjs`), so I did not try to start it or work around the denial. No panel server is running, and there is no URL or PID.

## Files changed

- `tools/agent-to-agent/node_modules/` and `tools/agent-to-agent/.npm-cache/`: local dependencies only.
- `tools/agent-to-agent/package-lock.json`: rewritten by `npm install`. `git status` shows it as modified. It can be reverted with `git -C tools/agent-to-agent checkout package-lock.json` if wanted.
- `tools/task-panel.mjs` (new): project-local launcher with `start`, `stop`, `status` and `serve`. It runs the panel on 127.0.0.1 (default port 4317, or the next free port) against vc_trade's own `prompt/` and `report/`. The background start is a hidden, detached process that logs to `.tmp/task-panel/server.log`.
- `tools/TASK_PANEL.md` (new): setup, start/stop and restart instructions.
- `report/20261002-105259-resume-task-panel-report.md`: this report.
- No changes to `prompt/`, `prompt/drafts/`, earlier reports, `prompt/AGENT_TO_AGENT.md`, or the helper's source files. Auto-send was not enabled, and no task was dispatched.

## Validation performed

- `git rev-parse HEAD` and `git status --short` in `tools/agent-to-agent`: revision cf2c267, clean.
- `npm.cmd install --cache .npm-cache`: "added 83 packages in 18s".
- Read the code to confirm root handling, the health endpoint (`/health` returns `{ app: 'claude-task-panel', pid }`) and the state-file behaviour that the launcher relies on.
- Read the code to confirm vc_trade's report naming (`report/<task-id>-report.md`) matches what the panel expects. `prompt/AGENT_TO_AGENT.md` is in the panel's list of instruction files, so it is not shown as a task.

## Checks not performed

- `npm.cmd run ui:typecheck`, `npm.cmd run ui:build`, `npm.cmd run test:panel`: denied by permission review.
- Panel launch, HTTP smoke check, effective-root check, process-survival check, browser check: not attempted because of the same denial. No server is running.
- `tools/task-panel.mjs` has not been run, so it is untested.

## Questions, missing requirements, or blockers

1. **Blocker: permission to run the helper's code.** The user can do one of these:
   - **(a)** Run these from the Claude terminal with the `!` prefix:
     - `! cd E:\VideCode\vc_trade\tools\agent-to-agent && npm.cmd run ui:build`
     - `! cd E:\VideCode\vc_trade && node tools/task-panel.mjs start`
   - **(b)** Add a Claude Code permission rule allowing `npm.cmd run ui:*`, `npm.cmd run test:panel` and `node tools/task-panel.mjs *` in this project. Codex then sends an approved follow-up to finish the build, launch and verification.
2. Codex: please confirm the user accepts the project-local launcher approach for serving vc_trade's root, since the stock `--root` cannot do it.

## Suggested next step

The user picks (a) or (b). If they choose (b), Codex sends an approved follow-up limited to: build the UI, run `test:panel`, start the panel with `node tools/task-panel.mjs start`, smoke-check `/health` and the task list against vc_trade's `prompt/` and `report/`, and report the URL, PID, logs and stop command.
