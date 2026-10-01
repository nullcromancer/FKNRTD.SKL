# Evidence, confidence, conflicts and fallbacks

Every non-trivial claim in the packet carries an evidence label. The label is what
separates a finding from a guess, and it is the first thing a reader of the packet
checks.

## Evidence labels

| Label | Means | Typical source |
| --- | --- | --- |
| `OBSERVED` | directly observed in an authorized sandbox execution | test output, build output, a running process, measured coverage |
| `DECLARED` | explicitly stated by executable or declarative project configuration | manifests, lockfiles, build systems, CI, schemas, toolchain files |
| `DERIVED` | computed from source-level semantic relationships | import graph, call graph, type resolution, route extraction |
| `DOCUMENTED` | stated only in prose, comments or documentation | README, docstrings, design notes, ADRs |
| `INFERRED` | heuristic conclusion not established by stronger evidence | ecosystem convention, naming pattern, structural similarity |

Strength runs `OBSERVED` > `DECLARED` > `DERIVED` > `DOCUMENTED` > `INFERRED`.

Write the label next to the claim, not in a footnote:

> The service listens on port 8080 (`DECLARED`: `docker-compose.yml:12`,
> `k8s/deployment.yaml:31`), and the README says 3000 (`DOCUMENTED`: `README.md:44`).
> The two disagree; the compose and manifest evidence is stronger and consistent with
> `src/server.ts:18` (`DERIVED`).

## Confidence

Confidence is about *how sure you are*, evidence class is about *where it came from*.
A `DERIVED` conclusion from a lexical fallback is weaker than a `DERIVED` conclusion
from a compiler frontend, even though both are `DERIVED`. Security findings use the
protocol's fixed scale: `Confirmed` | `High` | `Medium` | `Low`.

## Conflicts

When evidence conflicts:

1. Report the conflict explicitly: in the file or module record and, if it matters to
   the reader's decisions, in `EXECUTIVE_SUMMARY.md`.
2. Cite all of the conflicting evidence with locations.
3. Choose the conclusion the strongest applicable evidence supports.
4. **Never delete the weaker evidence.** "The README is out of date" is itself a
   finding about the repository.

The inventory already preserves classification conflicts this way:
`classification_primary` plus `classification_alternatives`, each with the evidence
rule that produced it.

## Classification evidence rules

The deterministic order used for file format and language, strongest first:

| Rule | Signal |
| --- | --- |
| E1 | repository metadata declaring language or role (`.gitattributes` linguist attributes) |
| E2 | standard or special filename |
| E3 | editor modeline |
| E4 | shebang / interpreter declaration |
| E5 | unambiguous extension |
| E6 | magic number or formal file header |
| E7 | XML/HTML/structured-language root or header |
| E8 | successful native parser or compiler-frontend recognition |
| E9 | successful Tree-sitter or equivalent parser recognition |
| E10 | deterministic content heuristic |

`odin.py inventory` applies E1-E7 and E10. E8 and E9 are yours, during static analysis
- and they are the only rules that let you *upgrade* a classification's confidence
from structural to semantic.

## Fallback ladders

Take the next rung only when the current one fails, record the failure with tool,
version and error, and lower confidence accordingly. Never substitute an unrelated
tool silently.

**Semantic analysis:** pinned compiler/frontend/LSP → installed compiler/frontend →
Tree-sitter → Universal Ctags → lexical/text analysis.

**Dependency resolution:** locked/resolved repository metadata → offline
package-manager graph from existing lockfiles/cache → vendored package metadata →
manifest exact version → manifest constraint (recorded *as a constraint*) → image
digest → image tag → undeclared source import.

**Build/run commands:** successful CI workflow or pinned wrapper invocation →
build-system configuration → package-manager scripts → repository documentation →
conventional command for the detected ecosystem (always `UNVERIFIED` unless executed).

**Machine-readable outputs:** preferred generator → a normalized equivalent you build
from collected evidence, when that is technically valid → an explicit placeholder or
error record explaining why a valid artifact could not be produced. Never fabricate
schema-valid-looking data with invented findings.

**Dynamic analysis:** sandboxed execution → static-only, with dynamic evidence
reported as unavailable.

## Things that are never claims

- A version you did not find in repository evidence.
- A test result from a test you did not run.
- A coverage percentage you did not measure. `"measured": false` is the honest answer,
  and it is not the same as zero percent.
- An architecture edge you did not trace to evidence.
- A runtime behavior you did not observe or derive.
- A vulnerability you matched by pattern and did not analyze.
- Byte-identical reproducibility you did not demonstrate.

## Nondeterminism

If two runs could legitimately differ: a nondeterministic test, a timestamp-embedding
generator, a randomized algorithm, parallel execution, a network-dependent resolution
step: do not hide it. Document the source, capture the result you observed, record
known seeds and options, and classify the reproduction accordingly in `REPRODUCE.md`.
