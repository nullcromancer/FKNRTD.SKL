---
description: Run odin repository forensics and produce a packet, README, website, handoff, or all outputs
argument-hint: [REPO_ROOT] [--output packet|readme|website|handoff|all] [--framework STACK] [--artifacts DIR] [--network denied|authorized] [--sandbox none|container|microvm]
---

Run the **odin** protocol: a deterministic, read-only forensic analysis of one
repository that builds a defensible evidence model and can render `findings.zip`, a GitHub README, an interactive documentation site, a developer handoff, or all outputs.

The skill lives at:

    {{odin_dir}}

(If that path was not substituted at install time, locate the skill directory - it
contains `SKILL.md`, `PROTOCOL.md`, `reference/` and `scripts/odin.py` - and use it.)

## Do this now

1. Read `{{odin_dir}}/SKILL.md` in full. It is the operating procedure.
2. Read `{{odin_dir}}/PROTOCOL.md` in full. It is normative and binding; where it and
   anything else disagree, it wins.
3. Resolve inputs from the arguments below, falling back to the protocol's defaults:
   REPO_ROOT defaults to the current working directory; ARTIFACT_ROOT defaults to a
   writable directory **outside** REPO_ROOT; network defaults to `denied`; sandbox
   defaults to `none` unless you can confirm real isolation.
4. Resolve `--output` from the arguments. If absent, default to `packet`. For `website`, honor `--framework` when supplied.
5. Execute Phases 0-12 from `SKILL.md`, loading `reference/*.md` as each phase needs it. Use `python {{odin_dir}}/scripts/odin.py` for the mechanical phases.
6. For README, website, handoff, or all-output requests, read `reference/output-profiles.md` before rendering.
7. Finish with the Phase 12 completion summary and the paths to every artifact actually produced.

## Non-negotiable

- REPO_ROOT is evidence: never modify it, never write generated output into it.
- Never execute repository-controlled code without an adequate sandbox; without one,
  do static analysis only and document the skip.
- Never invent a version, test result, coverage number, architecture edge, runtime
  behavior or vulnerability.
- Never print a secret value, and never validate a discovered credential anywhere.
- Fail soft: one failed phase does not end the run. Package a partial packet with
  explicit blocker documentation rather than abandoning the analysis.
- Do not ask the user questions. Resolve unknowns with the protocol's defaults and
  record every assumption.

Arguments: $ARGUMENTS
