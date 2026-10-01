# The output packet

Everything lives under `ARTIFACT_ROOT/findings/` and is packaged into
`ARTIFACT_ROOT/findings.zip`. Additional files may be added; required artifacts may be
omitted only with an explicit documented reason in `ERRORS.md` and
`ASSUMPTIONS_AND_LIMITATIONS.md`.

```
findings/
  README.md                      packet guide: what this is, how it was produced, how to read it
  EXECUTIVE_SUMMARY.md
  REPOSITORY_OVERVIEW.md
  ARCHITECTURE.md
  BUILD_AND_RUN.md
  DEPENDENCIES.md
  TESTS_AND_COVERAGE.md
  SECURITY.md
  TODOS_AND_UNFINISHED_WORK.md
  ASSUMPTIONS_AND_LIMITATIONS.md
  REPRODUCE.md
  ERRORS.md
  ACTION_MANIFEST.json
  MANIFEST.sha256
  VALIDATION.json                (odin addition: the pre-packaging validation report)

  inventory/
    files.jsonl  directories.jsonl  languages.json  file-types.json  roles.json
    tree.txt  source-hashes.sha256  vcs-state.json
    environment.json  inventory-summary.json  integrity-verification.json
    modules.json  per-file-documents-required.json  archives.json

  modules/    <one document per module>.md
  files/      <one document per physical regular file>.md   (+ _PATH_MAP.json)

  graphs/
    architecture.mmd  modules.mmd  runtime.mmd  data-flow.mmd  build-test.mmd
    sequence-*.mmd  dependencies.mmd
    dependencies.json  symbol-graph.json  call-graph.json  data-flow.json
    rendered/   <SVG/PNG when a trusted local renderer is available>
                RENDER_STATUS.json  (what was rendered, or why nothing was)

  dependencies/
    dependency-graph.json  packages.json  cyclonedx.json  spdx.json
    vulnerabilities.json  licenses.json

  tests/
    TEST_INVENTORY.md  results.json  failures.md  coverage-summary.json
    coverage/   <native coverage artifacts when generated>

  security/
    findings.sarif  findings.json  vulnerabilities.json
    secrets-redacted.json  SECURITY_NOTES.md

  static-analysis/
    symbols.jsonl  types.jsonl  imports.jsonl  diagnostics.jsonl
    unfinished-work.json

  sources/
    EXTERNAL_SOURCES.md  external-sources.json

  readme/
    component-map.json   (technology discovery for repository-README generation)
    lint-report.json     (README formatting enforcement result)

  tool-output/
    <sanitized raw and normalized logs>
```

## Per-file documents

`files/<repository-relative-path>.md`: every physical regular file, including binary,
generated, vendored, cache and VCS-internal ones. For those, describe metadata,
format, provenance, references and role; do not invent source-level semantics.
Secret-sensitive files are summarized and redacted.

Required fields (`odin.py docstub` seeds them; `odin.py validate` checks them):

Path · SHA-256 · Size · Filesystem type/mode · File format · Language(s) · Role ·
Module · First-party/generated/vendor classification · Sensitive-content handling
status · Purpose/summary · Key symbols/types · Imports/exports/dependencies ·
Callers/callees/references · Runtime/control-flow behavior · Data-flow and I/O ·
Configuration/environment usage · Security observations · Tests touching the file ·
Measured coverage when attributable and available · TODO/unfinished-work findings ·
Related files/modules · Evidence class and confidence · Parse/tool errors ·
Limitations/unknowns

Where a field genuinely does not apply: "key symbols" for a PNG: say so explicitly.
"Not applicable: binary image asset with no source-level symbols" is a complete answer.
A blank is not.

Rare paths get an escaped document name recorded in `files/_PATH_MAP.json`; the
inventory's `doc_path` is always authoritative.

## Module documents

`modules/<stable-module-id>.md`, one per entry in `inventory/modules.json`. Field list
in `architecture.md`; template in `templates/module-record.md`.

## Executive summary

`EXECUTIVE_SUMMARY.md` must concretely state: what the repository appears to do;
repository size and inventory counts; primary languages; the applications, services,
libraries and modules found; architectural style; principal entry points; how it is
built; how it is run; dependency ecosystems; test status and measured coverage; the
most important security findings; the most important correctness/quality findings; the
most important unfinished work; dynamic analysis performed versus skipped; major
contradictions and unknowns; reproducibility status; and whether the original
repository remained unchanged.

Concise but concrete. "Several modules" is not a summary; "eleven modules, of which
four are deployable services" is.

Never claim "secure", "fully tested" or "complete" because no tool found a problem.

## Action manifest

`ACTION_MANIFEST.json` is mandatory and records every material attempted **or
intentionally skipped** action: sequence number; phase; action ID; status
(`planned` | `executed` | `succeeded` | `failed` | `timeout` | `skipped` |
`unavailable` | `blocked_by_policy`); tool; tool version; runtime version; working
directory; exact sanitized command; input scope; output paths; sandbox type/profile;
network mode; whether repository-controlled code could execute; exit code; termination
reason; sanitized log path; SHA-256 of logs/results; skip/block/failure reason;
evidence generated; assumptions used.

Failed commands are never omitted. Sequence numbers are monotonic and never wall-clock
times. Redact the sensitive portion of a command string and say that you did.

## Integrity

`MANIFEST.sha256` covers every packet file except itself, sorted by normalized path.
`odin.py manifest` generates and verifies it; `odin.py package` re-verifies it against
the archived bytes after building the ZIP.

## Packaging rules

Sorted member order; normalized member paths; stable generated-file timestamps
(1980-01-01T00:00:00Z); stable permissions; fixed compression. The ZIP contains the
`findings/` directory and nothing else: **not** the repository source, dependency
caches, build trees, secret values, private credentials or sandbox state.

After creation: compute the SHA-256, verify the archive opens, verify the required
top-level documents are present, and verify `MANIFEST.sha256` against the members.

## Validation checklist

`odin.py validate` mechanizes most of this; the judgment items are yours.

1. **Inventory completeness**: one inventory record per physical regular file, one
   document per physical regular file, one document per module. *(mechanized)*
2. **Source integrity**: recomputed hashes match the baseline; VCS state unchanged;
   any discrepancy reported prominently. *(mechanized via `odin.py verify`)*
3. **Privacy**: no unredacted secret anywhere in the packet; finding metadata
   preserved; no credentials copied in unnecessarily. *(mechanized)*
4. **Structure**: JSON/JSONL parses; SARIF validated where a validator exists;
   CycloneDX/SPDX validated where validators exist; Mermaid syntax-checked or
   rendered; internal Markdown links resolve. *(partly mechanized: run real SARIF and
   SBOM validators when available)*
5. **Evidence**: every high-impact conclusion cites repository or tool evidence;
   inferred claims are labeled; dynamic claims distinguish observed behavior from
   unexecuted inference. *(judgment)*
6. **Tests/coverage**: no numeric coverage that was not measured; "not measured"
   clearly distinguished from zero percent. *(mechanized)*
7. **Manifest**: succeeded, failed, skipped, unavailable and policy-blocked actions
   all present; tool versions and exact sanitized commands included. *(mechanized)*
8. **Integrity**: `MANIFEST.sha256` generated over all packet files except itself and
   verified once before packaging. *(mechanized)*

## Partial packets

If analyses failed, still package. A partial packet with honest blocker documentation
is the required outcome; abandoning the run is not. Set the final status to `partial`,
list unresolved blockers in `ERRORS.md`, and say in `EXECUTIVE_SUMMARY.md` what was
not covered and what that leaves unknown.
