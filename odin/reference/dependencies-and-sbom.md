# Dependencies, versions and SBOMs

## What counts as a dependency source

Manifests; lockfiles; workspace files; vendored dependency trees; source imports;
generated dependency metadata; container base images; Git submodules; Git/VCS
dependencies; local and path dependencies; plugin dependencies; build-only
dependencies; dev/test dependencies; optional and feature-gated dependencies;
peer/provided dependencies; runtime dependencies; declared OS packages.

`inventory/roles.json` already separates `package-manifest` and `lockfile` files for
you, across every ecosystem the classifier knows.

## Version resolution priority

1. Exact locked/resolved repository metadata
2. The package manager's offline resolved graph, using existing lockfiles and cache
3. Vendored package metadata
4. Manifest exact version
5. Manifest version range or constraint: recorded **as a constraint**
6. Image digest
7. Image tag, only when no digest is available
8. Source import or reference with no declared version

**Never convert a range into an invented exact version.** `^1.3.0` resolves to `^1.3.0`
unless a lockfile, an offline resolution or vendored metadata says otherwise.

Prefer native package-manager graph commands in locked, offline, no-write modes:

| Ecosystem | Offline graph command |
| --- | --- |
| npm | `npm ls --all --json` against an existing `node_modules`, or parse the lockfile |
| pnpm / Yarn | `pnpm list --depth Infinity --json`, `yarn info --json`, or the lockfile |
| Python | parse `poetry.lock` / `uv.lock` / `pdm.lock` / `Pipfile.lock` / `requirements.txt`; `pip list --format=json` only for an already materialized environment |
| Cargo | `cargo metadata --locked --offline --format-version 1` |
| Go | `go list -m -json all` with `GOFLAGS=-mod=mod GOPROXY=off` |
| Maven | `mvn -o dependency:tree` via `./mvnw` when present |
| Gradle | `./gradlew --offline dependencies` |
| .NET | `packages.lock.json`, else the project files |
| Composer / Bundler / Mix / Pub / SwiftPM | the lockfile is authoritative |

If the network is denied, do **not** fetch missing submodules, Git LFS objects,
packages or remote metadata. Record them as unresolved external artifacts, with what
they are and why they could not be resolved.

## Per-dependency record

Every entry in `dependencies/packages.json` carries:

ecosystem; package/component name; resolved version if known; declared constraint;
direct or transitive; scope (runtime / dev / build / test / optional / peer); source
registry or repository when known; path/local/VCS source; integrity hash when present;
license evidence when available; the manifest or lockfile it came from; the modules
that import it; known vulnerability results; confidence.

```json
{
  "ecosystem": "npm",
  "name": "left-pad",
  "resolved_version": "1.3.0",
  "declared_constraint": "^1.3.0",
  "relationship": "direct",
  "scope": "runtime",
  "registry": "https://registry.npmjs.org",
  "integrity": "sha512-...",
  "license_evidence": {"value": "MIT", "source": "node_modules/left-pad/package.json"},
  "provenance": ["package.json", "package-lock.json"],
  "imported_by": ["src/format.js"],
  "vulnerabilities": [],
  "evidence_class": "DECLARED",
  "confidence": "High"
}
```

## Required outputs

| Artifact | Contents |
| --- | --- |
| `dependencies/dependency-graph.json` | normalized nodes and edges, including unresolved nodes |
| `dependencies/packages.json` | the flat per-dependency records above |
| `dependencies/cyclonedx.json` | CycloneDX SBOM |
| `dependencies/spdx.json` | SPDX SBOM |
| `dependencies/vulnerabilities.json` | advisory results per component |
| `dependencies/licenses.json` | license evidence and any conflicts or unknowns |
| `graphs/dependencies.mmd` | Mermaid dependency graph(s) |
| `DEPENDENCIES.md` | the human-readable report |

## SBOM rules

Use the highest schema version the installed or pinned generator emits **and that you
can validate locally**. Record the exact schema/specification version in the document
and in the manifest action. Do not relabel an older generator's output as a newer
schema.

If no SBOM generator is available, build a minimally valid SBOM from the dependency
evidence you actually collected, state in `DEPENDENCIES.md` and `ERRORS.md` that it
was generated from odin's normalized data rather than by a certified tool, and record
which fields are absent as a result. Do not emit a schema-shaped file containing
invented components.

Split SBOMs per ecosystem or per workspace component when one repository contains
several: and say which scheme you used.

## Vulnerability lookup

Use offline or local vulnerability databases first. If the caller authorized network
advisory lookup, query **package identifier and version only**: never transmit
repository source, snippets, private identifiers or discovered secrets. Record the
destination category and the reason. Do not contact application production endpoints.

Never invoke automatic remediation: no `npm audit fix`, no `osv-scanner fix`, no
`cargo fix`, no dependency-bumping bot behavior.

## Supply-chain observations to capture

Unpinned or overly broad constraints; unpinned CI actions and plugins; dependency
confusion and namespace risks; unverified downloads; `curl | sh` patterns; remote code
fetched during builds; omitted integrity checks; suspicious install hooks; package
lifecycle scripts; vendored binaries with no provenance; runtime versions declared past
end of support (when you can establish that from evidence).

These belong in `SECURITY.md` and `security/findings.sarif` as well as
`DEPENDENCIES.md`: cross-reference rather than duplicating the analysis.
