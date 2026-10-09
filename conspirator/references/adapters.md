# Implementer adapters

The orchestration runtime has three implementing-seat adapters. All use the same queue, CAVEMAN/1 packets, worktree isolation, reporting contract, verification gate, and audit lifecycle.

## Codex CLI

Skill invocation hint: `$conspirator`.

Runtime shape:

```text
codex exec --sandbox <sandbox> -C <worktree> <compact prompt>
```

Configuration keys:

```text
implementer=codex
codex_command=codex
codex_sandbox=workspace-write
codex_extra_args=[]
```

## Cline CLI

Cline discovers the skill from its skills directory and can activate it when asked to use `conspirator`.

Runtime shape:

```text
cline --cwd <worktree> --thinking <level> --json --auto-approve true <compact prompt>
```

Configuration keys:

```text
implementer=cline
cline_command=cline
cline_thinking=medium
cline_auto_approve=true
cline_extra_args=[]
```

Cline Skills may be feature-gated depending on the installed Cline version/configuration.

## GitHub Copilot CLI

Skill invocation hint: `/conspirator`.

Runtime shape:

```text
copilot -C <worktree> -p <compact prompt> --mode autopilot --no-ask-user --output-format=json --model auto
```

Configuration keys:

```text
implementer=copilot
copilot_command=copilot
copilot_model=auto
copilot_mode=autopilot
copilot_yolo=false
copilot_extra_args=[]
```

`copilot_yolo` is intentionally false by default. Programmatic Copilot can instead use permissions already configured by the user. Turning `copilot_yolo` on appends `--yolo`, which grants broad permissions for that CLI run; worktree isolation does not make arbitrary shell access harmless.

## Auto-routing

```text
implementer=auto
implementer_priority=["codex","cline","copilot"]
```

`auto` selects the first configured CLI found on `PATH`. It does not pretend to know provider billing or live model prices. Cost optimization should be expressed through profiles and each CLI's model/reasoning configuration.

## Shared behavior

Whichever implementer is selected:

- it receives only a tiny dispatch prompt plus a command to read the current CAVEMAN packet;
- it edits only its isolated worktree;
- it commits before reporting;
- it reports via `pairctl report --seat <agent>`;
- deterministic verification runs before the independent semantic audit;
- audit failures re-use the same branch/worktree and send only the latest failure delta.

## LM Studio (Claude Code, local model)

`--implementer lmstudio` runs `claude -p` with `ANTHROPIC_BASE_URL` pointed at LM Studio's
Anthropic-compatible `/v1/messages` endpoint. No Cline. Dispatch runs with cwd = the worktree and
sets `PAIRCTL_IMPLEMENTER_SEAT`, which makes `audit`, `land` and `rollback` refuse to run
(the local model otherwise audits and lands its own work).

```text
implementer=lmstudio
lmstudio_command=claude
lmstudio_url=http://127.0.0.1:1234
lmstudio_model=qwen3-coder-next     # must match the identifier in `lms ps`
lmstudio_extra_args=[]
```

Load the model first: `lms load qwen/qwen3-coder-next -c 262144 --identifier qwen3-coder-next --parallel 1 -y`
(262144 is the model's maximum; Claude Code's prompt alone is ~18k tokens). Not in the default `auto` priority.

**Maximum context is mandatory.** Before every LM Studio dispatch, review and swarm, `ensure_lmstudio_max_context` checks the loaded model (`lms ps --json`), and if its context is below the model's `maxContextLength` it reloads at the maximum, stepping down x0.75 only when the machine cannot hold that. Skipped when `lms` is absent or `lmstudio_use_lms=false`.
