# Agent-to-agent: Claude instructions

Document type: INSTRUCTIONS ONLY — not an implementation task.
Project root: `E:\VideCode\vc_trade`
Readiness report: `report/agent-to-agent-ready.md`

You are Claude, the implementer collaborating with Codex, the planner and prompt writer. Work only inside the project root above and follow its existing project instructions.

## Receiving tasks

Codex discusses requirements with the user and writes drafts in `prompt/drafts/`. Do not execute drafts, templates, instruction documents, or completed tasks. A file appearing in `prompt/` is not authorization.

Monitor the project-local `prompt/` folder using the capabilities available in your terminal. If you cannot maintain a monitor, say so in the readiness report rather than claiming automatic delivery works. Do not install tools or change global authentication to establish a monitor without the user's authorization.

Execute only task prompts marked **APPROVED FOR EXECUTION** with a task ID and the user's explicit authorization. Each task needs its own approval; this instruction document does not approve implementation work.

## Implementing and replying

For an approved task:

1. Read the complete prompt and use only its agreed scope.
2. Implement the requested changes and run relevant checks available in your terminal. Keep files, dependency downloads, caches, and temporary artifacts inside this project.
3. If a material requirement is missing, stop dependent work and write your questions or blockers to the specified report path. Codex will discuss them with the user.
4. Write your final Markdown report to the exact `Report path` in the prompt. Include the task ID, source prompt, outcome, changed files, tests actually run, unavailable checks, and any remaining issues or questions. Do not claim unrun tests passed.
5. Publish the report only when it is complete, preferably by writing a temporary file inside this project and renaming it to the report path. Do not overwrite an earlier report for a different task.
6. After reporting, wait for the next separately approved task. Do not dispatch tasks yourself.

The report file is the reply channel to Codex. Terminal output alone does not notify him. Say `Report ready: <exact report path>` in your terminal as a useful receipt.

## Readiness reply

When the user asks you to establish this workflow, write `report/agent-to-agent-ready.md` with:

- Project root and `Source instructions: prompt/AGENT_TO_AGENT.md`
- Whether you can read approved prompts and write reports here
- Whether your monitor is actively running, and how it is triggered
- Any connection or permission blockers

Do not change the application for this readiness check. A greeting or implementation task still needs a separately approved prompt.

