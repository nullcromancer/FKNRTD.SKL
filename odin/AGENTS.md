# odin

This directory is the **odin** skill: a deterministic repository-forensics protocol
that analyzes one repository read-only, builds one evidence model, and can produce `findings.zip`, a GitHub README, an interactive documentation site, a developer handoff, or all outputs.

## To run odin

1. Read `SKILL.md` - the operating procedure, phases 0-12.
2. Read `PROTOCOL.md` - normative and binding. Where anything else disagrees with it,
   it wins.
3. Load `reference/*.md` as each phase needs it.
4. Use `python scripts/odin.py` for the mechanical phases (`reference/toolkit.md`).

## To work *on* this skill

Files and their jobs:

| Path | Role |
| --- | --- |
| `SKILL.md` | entry point and phase plan; keep it short enough to read every run |
| `PROTOCOL.md` | the normative protocol, content-faithful to the source specification - **do not reword requirements here**; add operational guidance to `reference/` instead |
| `reference/` | per-phase operational detail, loaded on demand |
| `reference/output-profiles.md` | output selection, shared human voice, website and handoff contracts |
| `reference/readme-generation.md` | GitHub README modes, required sections, formatting constraints |
| `templates/` | packet skeletons plus developer-handoff and site-content templates |
| `scripts/odin.py` + `scripts/odin_lib/` | the stdlib-only toolkit |
| `tests/test_odin.py` | regression tests for the mechanical guarantees - run `python -m unittest discover -s tests` |
| `prompts/odin.md` | Codex / generic slash-prompt shim |
| `install/` | installers for Claude Code and Codex |

Constraints on the toolkit: Python 3.8+, **standard library only**, no network, never
writes into REPO_ROOT, never executes repository-controlled code, deterministic output
(sorted keys, bytewise path order, LF, no wall-clock time in packet content).

If you change what the packet must contain, update all four of: `PROTOCOL.md`'s
contract section, `reference/packet.md`, `REQUIRED_PACKET_ARTIFACTS` in
`scripts/odin_lib/verify.py`, and the templates.

**Run the tests before committing.** `python -m unittest discover -s tests` covers the
promises that are easy to break silently: repository non-modification, deterministic
ordering, byte-identical packaging, secret redaction, operator privacy, archive-member
safety, and validation honesty.
