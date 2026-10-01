# Dynamic execution: boundary and playbooks

Static inspection is always permitted. Everything below concerns running
repository-controlled code: project code, tests, package hooks, build scripts,
generators, compiler plugins, configuration evaluators and repository executables.

## The gate

Answer all three before any execution:

1. **Have I statically inspected what I am about to run?** Read the package scripts,
   the build file, the test configuration, `conftest.py`, the lifecycle hooks. A
   `postinstall` that curls a script is something you report, not something you run.
2. **Do I know this command's side effects?** Executable, full arguments, working
   directory, what it can write, expected network use, expected child processes,
   whether repository-controlled hooks will execute, credentials required, timeout,
   and the reason for running it.
3. **Does an adequate isolation boundary exist?** In preference order: a disposable
   microVM or equivalent strong sandbox; a disposable hardened container with
   appropriate kernel/security controls; another platform sandbox providing equivalent
   constraints.

**No adequate sandbox → do not execute project-controlled code.** Continue with static
analysis and document the skip. That is a complete, correct odin run, not a degraded
one.

## Isolation checklist

- Original repository exposed read-only, or a complete disposable copy: including the
  hidden and untracked files the project needs.
- All output, caches and dependencies under disposable scratch storage.
- Non-root/unprivileged user where supported.
- No privileged mode. No host PID namespace. No host IPC namespace.
- No host devices, unless one specific test genuinely requires it and it can be safely
  virtualized.
- **Never** mount a Docker/Podman/container-engine control socket.
- **Never** forward an SSH or GPG agent.
- **Never** expose cloud credentials, package-publishing tokens, browser profiles,
  home-directory secrets or host credential stores.
- Clean `HOME` in scratch. Unrelated host environment variables removed.
- Outbound network denied by default; sandbox-local loopback permitted where local
  tests require it.
- Platform-appropriate resource limits.
- Timeout kills the **entire process tree**, and records `TIMEOUT`.

Never weaken a control to make a test pass. If required dependencies are unavailable
under the policy, that is a documented blocker, not a reason to open the sandbox.

## Redirect writable state

`HOME`, `TMP`/`TEMP`/`TMPDIR`, every language and package cache, compiler output,
coverage output, Python bytecode (`PYTHONPYCACHEPREFIX`), the Rust target directory,
.NET artifacts, CMake build directories, test temp directories: all into scratch.
`odin.py init` creates `scratch/`, `scratch/home/` and `scratch/tmp/` for this.

## Dependency installation

Prefer an already materialized dependency tree. Otherwise prefer locked,
offline/cache-only installation with lifecycle and install hooks initially disabled.
Never provide private registry credentials unless the caller provisioned them for this
sandbox, and **never** use credentials discovered in the repository. If project hooks
turn out to be necessary for meaningful analysis: inspect them statically first, run
them only inside the sandbox, keep network denied unless preauthorized, and log the
decision with its evidence.

## Order of operations

A preference order, not a permission to run something unsafe:

1. Parser/syntax/compiler-frontend checks that do not execute project code
2. Static type checking
3. Non-fixing lint and static quality checks
4. Test discovery/collection
5. Unit tests
6. Integration tests needing only sandbox-local services
7. Build/compile
8. Measured coverage
9. Other repository-specific checks from CI, when demonstrably safe

Detect what the repository actually uses before reaching for any of the commands
below. Prefer pinned wrappers and the repository's own CI invocations over generic
ones. Do not install a global tool merely because this document names it: use an
existing trusted or pinned tool, or record the capability as unavailable.

## Per-ecosystem safe patterns

**Python**: redirect `PYTHONPYCACHEPREFIX`; `python -m compileall` against the
disposable copy; the repository's configured type checker (mypy/pyright); the
repository's configured linter in non-fixing mode (`ruff check` without `--fix`,
`pylint`); `pytest --collect-only`; `pytest`; the coverage tool the project already
declares.

**JavaScript/TypeScript**: use the package manager the lockfile implies; use
repo-local/pinned binaries rather than implicit `npx` downloads; install from
lockfile/cache with install scripts disabled first (`npm ci --ignore-scripts`);
`tsc --noEmit` when compatible with the repository's config; ESLint in non-fixing
mode; the repository test script only after reading the package scripts.

**Go**: resolve and list modules offline first (`GOFLAGS=-mod=mod GOPROXY=off go list
./...`); `go vet ./...` where compatible; `go test ./...`; `go test -coverprofile=...`
into scratch.

**Rust**: `cargo metadata --locked --offline`; `cargo check --locked --offline`;
`cargo clippy --locked --offline` with no `--fix`; `cargo test --locked --offline`;
`CARGO_TARGET_DIR` in scratch.

**JVM**: prefer `./mvnw` or `./gradlew` when supplied; offline mode when dependencies
are local (`-o`, `--offline`); run the relevant test/check tasks; never deploy or
publish.

**.NET**: use the declared SDK/toolchain (`global.json`); avoid implicit remote
restore when network is denied; artifacts to scratch; `dotnet build`/`dotnet test`
with `--no-restore` once dependencies are present.

**C/C++**: out-of-tree build directories in scratch; the repository's actual build
system; export and consume compile commands when supported; compiler diagnostics and
the analyzers the project declares; run tests from the scratch build output.

**Other ecosystems**: identify the official package/build/test tooling and apply the
same shape: locked, offline, no-fix, scratch output.

## Test execution rules

- Preserve the project's original test semantics unless doing so is unsafe.
- **Never rewrite a failing test to make it pass.**
- Record discovered / selected / passed / failed / skipped / xfailed counts.
- Preserve sanitized failure diagnostics.
- Distinguish test-**collection** failure from test failure.
- Distinguish missing-dependency and environment failure from product failure.
- Identify flaky or nondeterministic behavior when you observe it.
- Report coverage only when measured; never infer a percentage from reading source.

Obey any timeout, quota or job limit the platform supplies, and record it. Without
one, apply a conservative deterministic per-process timeout and record that policy. On
timeout: kill the process tree, record `TIMEOUT`, continue with independent analysis.

## Logging a dynamic action

Every execution gets a manifest entry with the sandbox type and profile, the network
mode, whether repository-controlled code could execute, the exact sanitized command,
exit code, termination reason, the sanitized log path and its SHA-256.

```
odin.py log --phase dynamic --action-id DYN-004 --status succeeded \
  --tool pytest --tool-version "8.2.0" --runtime-version "CPython 3.12.3" \
  --cwd "<sandbox>/worktree" --command "python -m pytest -q" \
  --sandbox "disposable container, non-root, no network" --network denied \
  --repo-code-executed --exit-code 0 --log-path tool-output/pytest.log \
  --evidence "tests/results.json"
```
