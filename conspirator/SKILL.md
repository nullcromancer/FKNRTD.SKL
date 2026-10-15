---
name: conspirator
description: Token-efficient multi-agent conspirator pairing for Claude Code, Codex CLI, Cline, and GitHub Copilot CLI. Claude is the default independent auditor/orchestrator; Codex, Cline, or Copilot can implement in isolated worktrees. Uses CAVEMAN/1 compact packets, Git-ref queueing, deterministic verification, bounded repair rounds, recovery, audit gates, safe landing, rollback, profiles, and machine-readable history. Use when the user asks to pair agents, delegate implementation, audit implementation work, or manage the pairing runtime.
---

# Conspirator

Default topology:

- **Claude** = auditing/orchestrating seat.
- **Codex, Cline, or GitHub Copilot CLI** = implementing seat.
- The implementing seat is selected by config, profile, `--implementer`, or `auto` routing.
- Do not collapse implementation and independent audit into the same seat when an independent auditor is available.

The deterministic runtime is `scripts/pairctl.py`, resolved relative to this file. Prefer it for state, worktrees, queue transitions, verification, merge/rollback, recovery, and adapter dispatch rather than recreating those mechanics in prose.

## Prime directive: efficient, not expensive

The default wire protocol is **CAVEMAN/1 (`CVM1`)**. It exists to avoid paying multiple models to repeatedly restate the same context.

Use these rules:

- Send **references, deltas, acceptance criteria, commands, hashes, commits, and failures**, not essays.
- Do not paste source code an implementing CLI can read from the repository.
- Do not repeat stable pairing rules in each dispatch. The installed skill supplies stable policy; `show --wire` supplies only the active brief and latest delta context.
- Do not resend full history during repair. Send the latest report plus the latest failing verification/audit packet.
- Keep detailed command and agent output in local log files; put only command, exit status, digest, and actionable failure on the wire.
- Human-facing explanations may be normal prose. Seat-to-seat traffic should be compact.

CAVEMAN/1 brief keys:

```text
G goal        S scope        C constraint    A acceptance
F file/ref    T test/gate    X exclude       U unknown
```

Report/audit additions:

```text
D delta       M commit       E evidence      B blocker/finding
Q uncertainty
```

Read `references/caveman.md` only when the packet format itself needs clarification.

## Normal user experience

For a nontrivial requested change, the user should normally need only something like:

```text
Pair on this.
```

The user can optionally name the implementer:

```text
Pair on this using Codex.
Pair on this using Cline.
Pair on this using Copilot.
```

Do not make the user manually operate `brief`, `claim`, `report`, or worktrees unless they are debugging or explicitly ask for low-level control.

## 1. Check runtime

Run:

```text
python <skill-dir>/scripts/pairctl.py status
```

For environment problems:

```text
python <skill-dir>/scripts/pairctl.py doctor
```

If pairing is OFF and the user did not explicitly request pairing, do the work normally without ceremony. If pairing was explicitly requested, explain the disabled state or enable/configure it if the user asked you to.

## 2. Choose the implementing seat

Supported adapters:

```text
codex
cline
copilot
lmstudio
strata
auto
```

Default selection comes from config:

```text
python <skill-dir>/scripts/pairctl.py config implementer
```

A user request naming an implementer overrides config for that run. Otherwise use the active profile/config. `auto` selects the first installed supported CLI according to `implementer_priority`; it does not guess at live provider pricing.

Adapter details live in `references/adapters.md`.

### Strata as co-programmer

When the user wants **Strata** as the co-programmer (or "pair on this using Strata"), use `--implementer strata`.

- Run `python <skill-dir>/scripts/pairctl.py strata` first. It reads the configuration from the Strata install every time (launcher, model, engine args, what `/health` reports), so it is always current. Never quote Strata settings from memory or from older notes; quote this output.
- Fix any `PROBLEM` line before dispatching; dispatch refuses while one exists.
- Strata is standalone: never apply LM Studio, `lmstudio` seat, shim, `lms` or bionic settings or lessons to it.
- Change Strata only through its own install (its `strata-*.json`, `run-*.bat`, `strata-up.ps1`); conspirator follows automatically. Only `strata_home` is stored in conspirator config.

Details and the current snapshot: `references/strata.md`.

## 3. Decide whether pairing is worth its cost

Pair when the change is self-contained, commit-worthy, and independently verifiable: features, bug fixes, bounded refactors, migrations, and behavior changes.

Skip pairing for trivial edits, simple questions, read-only investigation, or work where coordination costs more tokens/time than the implementation.

## 4. Build a compact, high-quality brief

The auditor/orchestrator inspects relevant repository instructions/code/tests first. Then create a temporary JSON spec **outside the repository**:

```json
{
  "goal": "one precise outcome",
  "scope": ["bounded responsibilities"],
  "constraints": ["non-negotiable rules"],
  "acceptance": ["mechanically checkable outcomes"],
  "files": ["path:symbol or path:line reference"],
  "tests": ["known verification commands or expectations"],
  "exclude": ["adjacent work not requested"],
  "unknowns": ["only unresolved facts that matter"]
}
```

Avoid prose repetition. A path/symbol reference is cheaper and usually better than copying source.

The runtime quality-gates new `pair` briefs: goal, acceptance criteria, and scope/file references are required.

## 5. Run the implementation loop

Preferred command:

```text
python <skill-dir>/scripts/pairctl.py pair "short title" --spec <brief.json> --repo <repo> --profile standard --implementer <agent>
```

Omit `--implementer` to use configured routing.

`pair` performs the deterministic orchestration:

1. initialize the Git-ref queue if needed;
2. quality-check and encode the brief as CAVEMAN/1;
3. create an isolated implementing-seat worktree/branch;
4. atomically claim the brief;
5. dispatch the selected CLI with a minimal prompt;
6. discover/run repository verification;
7. if verification fails, send only the failure delta and allow a bounded repair round;
8. stop at **AUDIT-READY** rather than pretending deterministic tests replace independent semantic audit.

Profiles control repair rounds and execution policy. Use `fast` for cheap/simple changes, `standard` by default, `deep` for difficult work, and `release` for release-sensitive work.

## 6. Implementing-seat contract

This contract applies when the current agent is Codex, Cline, or Copilot and it was dispatched as the implementing seat.

1. Run the exact `show <id> --wire` command supplied by the dispatcher.
2. Read applicable repository instructions (`AGENTS.md`, `CLAUDE.md`, `.github` instructions, Cline rules, etc.) that the current CLI normally honors.
3. Work only in the supplied worktree and within brief scope.
4. Read referenced files directly; do not ask the auditor to resend them.
5. Add/update tests for testable acceptance criteria.
6. Run relevant tests.
7. **Commit the implementation to the current implementation branch before reporting.** Never merge the main/default branch.
8. Create a compact report JSON outside the repository:

```json
{
  "delta": ["implemented X", "added Y test"],
  "commit": "<commit sha>",
  "tests": ["dotnet test => 0"],
  "blockers": [],
  "uncertainties": [],
  "evidence": ["path:symbol"]
}
```

9. Report once:

```text
python <skill-dir>/scripts/pairctl.py report <id> --verdict pass --spec <report.json> --repo <main-repo> --seat <codex|cline|copilot>
```

Use `fail` for attempted work that does not meet acceptance criteria. Use `blocked` when the brief cannot responsibly be implemented as written. Do not invent adjacent work.

## 7. Claude independent audit

After `pair` says AUDIT-READY, Claude independently:

- inspects the actual branch/worktree diff;
- reads changed code in context;
- runs relevant verification itself (`pairctl verify <id>` when appropriate);
- checks every acceptance criterion and constraint;
- checks scope expansion, regression risk, missing edge cases, and repository-rule violations;
- treats the implementing seat's report as a claim, not evidence.

Create compact audit JSON:

```json
{
  "evidence": ["what Claude independently checked"],
  "tests": ["commands/results Claude independently observed"],
  "findings": [],
  "uncertainties": []
}
```

Pass:

```text
python <skill-dir>/scripts/pairctl.py audit <id> --verdict pass --spec <audit.json> --repo <repo> --seat claude
```

Fail + bounded repair:

```text
python <skill-dir>/scripts/pairctl.py audit <id> --verdict fail --spec <audit.json> --redispatch --repo <repo> --seat claude
```

The runtime preserves the original implementer across repair rounds unless explicitly overridden.

Block an invalid/unrecoverable brief:

```text
python <skill-dir>/scripts/pairctl.py audit <id> --verdict block --spec <audit.json> --repo <repo> --seat claude
```

## 8. Land only after audit

After audit pass:

```text
python <skill-dir>/scripts/pairctl.py land <id> --repo <repo> --seat claude
```

`land` requires `audit-passed`, creates a backup ref, merges with `--no-ff`, records the merge commit, and cleans the worktree/branch when configured. It does not push remote branches by itself.

Undo a landed merge without rewriting history:

```text
python <skill-dir>/scripts/pairctl.py rollback <id> --repo <repo> --seat claude
```

## Swarm

When the user says **swarm** (or "swarm this"), Claude, Codex and whatever model LM Studio has loaded attack one project together:

1. Claude reads the repo and splits the goal into **disjoint slices**, one brief per seat (`codex`, `lmstudio`), each with `files` (required; overlapping paths are rejected), `acceptance`, `scope`, `tests`. Give the riskier slice to Codex. Write the spec outside the repo:

```json
{"goal": "...", "briefs": [
  {"seat": "codex", "title": "...", "goal": "...", "scope": ["..."], "files": ["src/a"], "acceptance": ["..."], "tests": ["..."]},
  {"seat": "lmstudio", "title": "...", "goal": "...", "scope": ["..."], "files": ["src/b"], "acceptance": ["..."]}]}
```

2. `python <skill-dir>/scripts/pairctl.py swarm "title" --spec swarm.json --repo <repo>` creates every brief, auto-detects the loaded LM Studio model (`lms ps`, then `/v1/models`) reloads LM Studio at the model's maximum context if it is lower (mandatory for every LM Studio run), and runs all seats in parallel worktrees with verification and bounded repair. Each slice ends `reported` (AUDIT-READY). A slice may also use `"seat": "strata"`; its live configuration is checked first (see "Strata as co-programmer").
3. Claude independently audits **every** slice exactly as in section 7 (`pairctl verify <id>`, read the diff, `audit --seat claude`). Seats cannot audit, land, rollback or swarm: dispatch sets `PAIRCTL_IMPLEMENTER_SEAT`.
4. `pairctl swarm --land <swarm-id> --repo <repo>` lands the audit-passed slices in order, stops on a merge conflict, then runs verification on main. `swarm --status <swarm-id>` lists the slices. The swarm id is the first brief's id.

**Takeover.** If a slice ends `blocked` (its seat kept failing), Claude becomes its implementer:
`swarm --takeover <brief-id>` reassigns it to `claude` on the failed seat's branch and worktree. Claude fixes and commits there, `report --seat claude`, then `verify <id>`, then `swarm --review <id> [--reviewer codex|lmstudio|strata]` (a different seat reviews read-only and must end with `REVIEW: PASS`). `audit --verdict pass` on a taken-over slice is refused until both verification and review have passed after the takeover (`--force` overrides). Tell the user which slices were self-implemented.

## 9. Recovery

Inspect an interrupted round:

```text
python <skill-dir>/scripts/pairctl.py resume <id> --repo <repo>
```

The queue records seat, claim lease, process ID, host, worktree, branch, round, and phase. Never blindly redispatch a process that still appears live.

For a stale/dead claim:

```text
python <skill-dir>/scripts/pairctl.py resume <id> --requeue --repo <repo>
python <skill-dir>/scripts/pairctl.py resume <id> --redispatch --repo <repo>
```

Inspect the worktree before forcing recovery if uncommitted implementation may exist.

## 10. Visibility and history

```text
python <skill-dir>/scripts/pairctl.py queue --repo <repo>
python <skill-dir>/scripts/pairctl.py status <id> --repo <repo>
python <skill-dir>/scripts/pairctl.py show <id> --json --repo <repo>
python <skill-dir>/scripts/pairctl.py events <id> --ndjson --repo <repo>
```

Every important transition is represented in queue state/events; queue history itself is a Git commit chain on `refs/pairing/queue`.

## 11. Profiles and repository configuration

Global profiles:

```text
python <skill-dir>/scripts/pairctl.py profile list
python <skill-dir>/scripts/pairctl.py profile use standard
python <skill-dir>/scripts/pairctl.py profile show deep
```

A repository may contain dependency-free `.pairing.toml`:

```toml
[pairing]
profile = "standard"
implementer = "auto"

[verification]
commands = ["dotnet build", "dotnet test"]

[profile.fast]
max_rounds = 1
verification_timeout = 600
implementer = "cline"
```

`.pairing.json` is also supported. Repository settings override global defaults for that repository.

## 12. Adapter safety

- **Codex** defaults to `workspace-write` rather than broad host access.
- **Cline** runs headlessly in the isolated worktree; auto-approval is configurable.
- **Copilot** runs programmatically in the isolated worktree. `copilot_yolo` is OFF by default because `--yolo` grants broad permissions beyond the worktree boundary.
- Worktree isolation prevents edit collisions; it is not a security sandbox for arbitrary shell commands.
