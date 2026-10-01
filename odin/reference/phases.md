# Phase plan: entry and exit criteria

One table row per phase. A phase is done when its exit criteria hold, not when it
stops producing output. Phases 1-8 are independent enough that a failure in one does
not block the others; run what you can and record the rest.

## Phase 0: Establish the run

**Entry:** REPO_ROOT is readable.

**Do:**
- `odin.py init --repo <REPO_ROOT> [--artifacts <DIR>] --network <policy> --sandbox <kind>`
- `odin.py env`
- `odin.py inventory`
- Read `PROTOCOL.md` end to end.

**Exit:**
- ARTIFACT_ROOT exists and is provably outside REPO_ROOT.
- `inventory/environment.json`, `files.jsonl`, `directories.jsonl`, `tree.txt`,
  `source-hashes.sha256`, `vcs-state.json` exist.
- The baseline hash count matches the regular-file count.
- `inventory/inventory-summary.json` has no unexplained traversal errors.

**Trap:** an inventory that looks too small. Check `traversal-errors.json` and whether
a permission boundary, a junction, or a mount stopped the walk. Do not proceed on a
truncated inventory without recording it as a limitation.

## Phase 1: Classification review

**Entry:** inventory exists.

**Do:** review `classification_conflicts`, confirm role and origin hints, detect
embedded and polyglot content, decide what is first-party versus vendored versus
generated on evidence rather than convention alone.

**Exit:** every regular file has a primary classification you are willing to defend,
with alternatives preserved wherever signals disagreed.

## Phase 2: Static semantic analysis

**Entry:** classification review done for the languages you are about to parse.

**Do:** choose the richest available parser per language, extract the symbol/type/
import/export/relationship data the protocol lists, build the cross-file graphs.

**Exit:** `static-analysis/*.jsonl` and `graphs/*.json` written; the analysis backend
and version recorded per language; unresolved and dynamic edges labeled as such; every
parse failure recorded with parser, version and error.

**Trap:** claiming resolved types from a lexical pass. If Tree-sitter or Ctags produced
the data, the confidence is structural, not semantic.

## Phase 3: Unfinished work

**Entry:** inventory exists.

**Do:** `odin.py todos`, then triage. Add what pattern matching cannot see: suspicious
empty bodies, no-op placeholders, mock implementations shipped on production paths,
migration placeholders, feature flags that gate incomplete functionality.

**Exit:** `static-analysis/unfinished-work.json` reviewed and
`TODOS_AND_UNFINISHED_WORK.md` written, with actionable work separated from historical
comments, generated/vendored occurrences and deliberate fixtures.

## Phase 4: Build, configuration and runtime inference

**Entry:** inventory and classification.

**Do:** read every build and declarative artifact; infer the project's purpose,
boundaries, build order, commands, entry points, runtime surface, state, configuration
and deployment.

**Exit:** `BUILD_AND_RUN.md` and `REPOSITORY_OVERVIEW.md` written; every command
carries an evidence label; unexecuted commands marked `UNVERIFIED`; conflicts between
README, CI and build configuration reported rather than silently resolved.

## Phase 5: Dependencies and SBOM

**Entry:** manifests and lockfiles located.

**Exit:** all six `dependencies/*.json` artifacts plus `graphs/dependencies.mmd` and
`DEPENDENCIES.md`; every dependency carries ecosystem, name, resolved version or an
explicit statement that it is unresolved, constraint, scope, direct/transitive status,
provenance and confidence; unresolvable external artifacts (unfetched submodules, LFS
objects, missing packages) recorded as unresolved, never guessed.

## Phase 6: Security

**Entry:** inventory; static analysis where available.

**Do:** `odin.py secrets`, then source, supply-chain and infrastructure analysis.

**Exit:** `security/findings.sarif`, `findings.json`, `vulnerabilities.json`,
`secrets-redacted.json`, `SECURITY_NOTES.md` and `SECURITY.md`; no secret value
anywhere in the packet; every finding carries normalized severity, the scanner's
original severity, confidence and provenance.

## Phase 7: Dynamic analysis

**Entry:** an adequate sandbox exists **and** you have statically inspected the
commands you intend to run.

**Exit: with a sandbox:** `tests/results.json`, `TEST_INVENTORY.md`, `failures.md`,
`coverage-summary.json` (with `"measured": true|false`), coverage artifacts if
measured, and manifest entries describing sandbox type, network mode and whether
repository-controlled code could execute.

**Exit: without a sandbox:** the same documents exist and state plainly that dynamic
evidence is unavailable and why; `coverage-summary.json` carries `"measured": false`
and no numeric percentage; every skipped command is a `blocked_by_policy` or
`unavailable` manifest entry.

## Phase 8: Architecture and diagrams

**Entry:** Phases 2 and 4.

**Exit:** `inventory/modules.json` registry written; `ARCHITECTURE.md`; the required
Mermaid diagrams plus at least one sequence diagram; documented-versus-inferred
architecture compared.

## Phase 9: Documentation

**Entry:** everything you intend to document has been analyzed.

**Do:** `odin.py docstub`, then complete every record; write module documents and the
top-level documents.

**Exit:** one complete document per physical regular file, one per registered module,
every required top-level document present, and no `<!-- odin:pending -->` marker left
in the packet.

**Trap:** large repositories. Document in deterministic path order, in batches, and
check progress with `odin.py status`. Vendored and generated trees get short,
metadata-level records: short is fine, absent is not.

## Phase 10: Validate

**Do:** `odin.py verify`, then `odin.py validate`; fix and repeat.

**Exit:** integrity `PASS`; validation `PASS`, or every remaining gap explicitly
documented in `ERRORS.md` and `ASSUMPTIONS_AND_LIMITATIONS.md` with a reason.

## Phase 11: Package

**Do:** `odin.py manifest`, then `odin.py package`.

**Exit:** `findings.zip` exists at ARTIFACT_ROOT, reopens cleanly, contains every
required top-level document, and its archived bytes match `MANIFEST.sha256`.

## Phase 12: Respond

**Exit:** the completion summary from `SKILL.md` Phase 12, and nothing else. The
message is not a substitute for the packet.
