# Template: `modules/<stable-module-id>.md`

One per entry in `inventory/modules.json`. `odin.py validate` checks for the headings
marked **required** below.

---

```markdown
# packages-api-server: `@acme/api-server`

**Stable ID:** `packages-api-server`
**Path:** `packages/api-server`
**Kind:** deployable service
**Boundary evidence:** DECLARED: `pnpm-workspace.yaml:3`, `packages/api-server/package.json`

## Purpose (required)

What this module is responsible for, and what it deliberately is not.

## Boundaries (required)

Directory and package boundaries; what belongs to it; nested modules; files that sit
in its tree but belong elsewhere (vendored, generated).

- 74 files, 61 first-party, 13 generated (`src/gen/**`, protobuf output)

## Public API (required)

The surface other modules and callers actually depend on.

| Export | Kind | Signature / route | Consumers |
| --- | --- | --- | --- |
| `createServer` | function | `(opts: Options) => Server` | `packages/worker` |
| `POST /v1/jobs` | HTTP route | `JobRequest → JobId` | `packages/web` (DERIVED) |

## Main types and symbols

The types a reader must understand to read this module.

## Internal dependencies (required)

Modules inside the repository this one depends on, with the evidence for each edge.

## External dependencies (required)

Third-party packages, services, and infrastructure, with resolved versions where
known. Cross-reference `dependencies/packages.json` rather than restating it.

## Initialization and lifecycle

Startup order, readiness, shutdown behavior, what happens on a failed dependency.

## Entry points (required)

Binaries, CLI commands, HTTP/RPC servers, workers, scheduled jobs, library entry
functions: with the evidence class for each.

## Configuration and environment (required)

Configuration sources in precedence order; required and optional environment
variables; feature flags; defaults; what happens when a required value is missing.

## State

Persistent state (databases, object stores, files) and transient state (caches,
in-memory queues), with ownership: does this module own the schema or consume it?

## Data inputs and outputs

Where data comes from, where it goes, and which trust boundaries it crosses.

## Service, API, database and message interactions

Concrete endpoints, tables, topics, queues, and the direction of each interaction.

## Concurrency model

Threads, async runtimes, worker pools, locks, transactional boundaries, and the
assumptions they rest on.

## Error handling

How failures propagate, what is retried, what is swallowed, what is logged, and
whether anything sensitive reaches the logs.

## Security and trust boundaries

Authentication and authorization boundaries this module enforces or assumes, input
validation, and its security-relevant findings (cross-referenced, not duplicated).

## Tests (required)

Test files, frameworks, what they cover, what they do not, disabled tests.

## Measured coverage

Only when actually measured; otherwise "Not measured" and why.

## TODO and unfinished work

The actionable items in this module, from `static-analysis/unfinished-work.json`.

## Known limitations

Of the module itself, and of odin's analysis of it.

## Architecture relationships

Where this module sits in `graphs/modules.mmd` and `graphs/runtime.mmd`.

## Evidence and confidence (required)

Per-section evidence classes and the confidence you hold in each conclusion.
```
