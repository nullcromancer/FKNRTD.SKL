#!/usr/bin/env python3
"""odin toolkit - deterministic helpers for the odin repository-forensics protocol.

Stdlib only, Python 3.8+. Works the same under Claude Code, Codex, Aider, or a
bare shell. Every subcommand prints a JSON summary to stdout so an agent can
read the result without re-deriving it.

    python odin.py init --repo <REPO_ROOT> [--artifacts <ARTIFACT_ROOT>]
    python odin.py env
    python odin.py inventory
    python odin.py todos
    python odin.py secrets
    python odin.py docstub
    python odin.py coverage [--module] <target> [arguments ...]
    python odin.py log --phase P --action-id A --status S --tool T --command "..."
    python odin.py verify
    python odin.py validate
    python odin.py manifest
    python odin.py package
    python odin.py status

Run `python odin.py <command> --help` for per-command options.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import sys
import tempfile
from pathlib import Path

# The protocol forbids writing caches into REPO_ROOT. When the toolkit lives
# inside the repository under analysis — self-analysis, or any checkout that
# vendors this skill — importing odin_lib would otherwise drop __pycache__
# directories next to the source. Set before the odin_lib imports below, which
# are what would trigger bytecode writing.
sys.dont_write_bytecode = True

sys.path.insert(0, str(Path(__file__).resolve().parent))

from odin_lib import package as packaging  # noqa: E402
from odin_lib import scan, verify  # noqa: E402
from odin_lib.common import (  # noqa: E402
    DETERMINISM_ENV,
    PACKET_DIRS,
    REQUIRED_TOP_LEVEL_DOCS,
    odinError,
    State,
    jdumps,
    read_json,
    read_jsonl,
    sha256_file,
    state_path,
    write_json,
    write_text,
)
from odin_lib.inventory import run_inventory  # noqa: E402

# --------------------------------------------------------------------------
# init
# --------------------------------------------------------------------------

def default_artifact_root(repo_root: Path) -> Path:
    """A writable directory outside REPO_ROOT, stable for a given repository."""
    digest = hashlib.sha256(str(repo_root.resolve()).encode("utf-8")).hexdigest()[:12]
    return Path(tempfile.gettempdir()) / ("odin-" + repo_root.name + "-" + digest)


def cmd_init(args):
    repo_root = Path(args.repo).expanduser().resolve()
    if not repo_root.is_dir():
        raise odinError("REPO_ROOT is not a readable directory: " + str(repo_root))

    if args.artifacts:
        artifact_root = Path(args.artifacts).expanduser().resolve()
    else:
        artifact_root = default_artifact_root(repo_root)

    try:
        artifact_root.relative_to(repo_root)
        raise odinError(
            "ARTIFACT_ROOT must be physically outside REPO_ROOT; refusing to write "
            "generated output into the evidence tree: " + str(artifact_root)
        )
    except ValueError:
        pass

    artifact_root.mkdir(parents=True, exist_ok=True)
    packet = artifact_root / "findings"
    packet.mkdir(parents=True, exist_ok=True)
    for name in PACKET_DIRS:
        (packet / name).mkdir(parents=True, exist_ok=True)
    (artifact_root / "scratch").mkdir(parents=True, exist_ok=True)
    (artifact_root / "scratch" / "home").mkdir(parents=True, exist_ok=True)
    (artifact_root / "scratch" / "tmp").mkdir(parents=True, exist_ok=True)

    applied, unapplied = {}, {}
    for key, value in DETERMINISM_ENV.items():
        os.environ[key] = value
        applied[key] = value
    try:
        previous = os.umask(0o022)
        os.umask(0o022)
        applied["umask"] = "0o022"
        if previous != 0o022:
            applied["umask_previous"] = oct(previous)
    except (AttributeError, OSError) as exc:
        unapplied["umask"] = str(exc)

    state_data = {
        "schema": "odin.state/1",
        "repo_root": str(repo_root),
        "artifact_root": str(artifact_root),
        "packet_root": str(packet),
        "scratch_root": str(artifact_root / "scratch"),
        "final_zip": str(artifact_root / "findings.zip"),
        "seq": 0,
        "network_policy": args.network,
        "sandbox": args.sandbox,
        "determinism_env_applied": applied,
        "determinism_env_unapplied": unapplied,
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "machine": platform.machine(),
            "processor": platform.processor(),
            "python_version": platform.python_version(),
            "python_implementation": platform.python_implementation(),
            "filesystem_encoding": sys.getfilesystemencoding(),
            "case_sensitive_paths": _probe_case_sensitivity(artifact_root),
        },
    }
    write_json(state_path(artifact_root), state_data)

    manifest_path = packet / "ACTION_MANIFEST.json"
    if not manifest_path.is_file():
        write_json(manifest_path, {
            "schema": "odin.action-manifest/1",
            "repo_root_absolute": str(repo_root),
            "artifact_root_absolute": str(artifact_root),
            "network_policy": args.network,
            "sandbox": args.sandbox,
            "note": "Actions are identified by monotonically increasing sequence "
                    "numbers, never by wall-clock time. Failed, skipped, unavailable "
                    "and policy-blocked actions are recorded alongside successes.",
            "actions": [],
        })

    return {
        "repo_root": str(repo_root),
        "artifact_root": str(artifact_root),
        "packet_root": str(packet),
        "scratch_root": str(artifact_root / "scratch"),
        "final_zip": str(artifact_root / "findings.zip"),
        "state_file": str(state_path(artifact_root)),
        "artifact_root_outside_repo": True,
        "network_policy": args.network,
        "sandbox": args.sandbox,
        "determinism_env_applied": applied,
        "determinism_env_unapplied": unapplied,
        "packet_directories_created": PACKET_DIRS,
        "next": "python odin.py env, then python odin.py inventory",
    }


def _probe_case_sensitivity(root: Path):
    probe = root / ".odin-case-probe"
    try:
        probe.write_text("x", encoding="utf-8")
        result = not (root / ".odin-CASE-PROBE").exists()
        probe.unlink()
        return result
    except OSError:
        return None


# --------------------------------------------------------------------------
# env
# --------------------------------------------------------------------------

TOOL_PROBES = [
    ("git", ["git", "--version"]),
    ("python", [sys.executable, "--version"]),
    ("node", ["node", "--version"]),
    ("npm", ["npm", "--version"]),
    ("pnpm", ["pnpm", "--version"]),
    ("yarn", ["yarn", "--version"]),
    ("bun", ["bun", "--version"]),
    ("deno", ["deno", "--version"]),
    ("tsc", ["tsc", "--version"]),
    ("go", ["go", "version"]),
    ("cargo", ["cargo", "--version"]),
    ("rustc", ["rustc", "--version"]),
    ("java", ["java", "-version"]),
    ("mvn", ["mvn", "--version"]),
    ("gradle", ["gradle", "--version"]),
    ("dotnet", ["dotnet", "--version"]),
    ("ruby", ["ruby", "--version"]),
    ("php", ["php", "--version"]),
    ("perl", ["perl", "--version"]),
    ("gcc", ["gcc", "--version"]),
    ("clang", ["clang", "--version"]),
    ("cmake", ["cmake", "--version"]),
    ("make", ["make", "--version"]),
    ("bazel", ["bazel", "--version"]),
    ("docker", ["docker", "--version"]),
    ("podman", ["podman", "--version"]),
    ("pytest", [sys.executable, "-m", "pytest", "--version"]),
    ("mypy", [sys.executable, "-m", "mypy", "--version"]),
    ("ruff", ["ruff", "--version"]),
    ("pylint", [sys.executable, "-m", "pylint", "--version"]),
    ("eslint", ["eslint", "--version"]),
    ("semgrep", ["semgrep", "--version"]),
    ("bandit", ["bandit", "--version"]),
    ("gitleaks", ["gitleaks", "version"]),
    ("trufflehog", ["trufflehog", "--version"]),
    ("osv-scanner", ["osv-scanner", "--version"]),
    ("grype", ["grype", "version"]),
    ("syft", ["syft", "version"]),
    ("trivy", ["trivy", "--version"]),
    ("cyclonedx-py", ["cyclonedx-py", "--version"]),
    ("cdxgen", ["cdxgen", "--version"]),
    ("ctags", ["ctags", "--version"]),
    ("tree-sitter", ["tree-sitter", "--version"]),
    ("mmdc", ["mmdc", "--version"]),
    ("file", ["file", "--version"]),
    ("jq", ["jq", "--version"]),
]


# Environment-variable disclosure policy. The protocol permits values only for
# demonstrably non-sensitive variables, so the default is to record the name and
# withhold the value. A packet is meant to be shareable; the operator's identity,
# home directory and installed-software inventory are not part of the evidence.
SENSITIVE_ENV_MARKERS = (
    "TOKEN", "SECRET", "PASSWORD", "PASSWD", "PWD", "KEY", "CREDENTIAL",
    "AUTH", "SESSION", "COOKIE", "PRIVATE", "LICENSE", "API", "PROXY",
    "ACCOUNT", "USER", "LOGIN", "MAIL", "SIGNATURE", "CERT",
)

PATH_LIKE_ENV = frozenset({
    "PATH", "PYTHONPATH", "LD_LIBRARY_PATH", "DYLD_LIBRARY_PATH", "CLASSPATH",
    "GOPATH", "NODE_PATH", "PSMODULEPATH", "MANPATH", "PKG_CONFIG_PATH",
})

LOCATION_ENV = frozenset({
    "HOME", "USERPROFILE", "HOMEPATH", "HOMEDRIVE", "TEMP", "TMP", "TMPDIR",
    "APPDATA", "LOCALAPPDATA", "PROGRAMFILES", "PROGRAMDATA", "GOROOT",
    "JAVA_HOME", "CARGO_HOME", "RUSTUP_HOME", "VIRTUAL_ENV", "CONDA_PREFIX",
    "SHELL", "COMSPEC", "PWD", "OLDPWD", "XDG_CACHE_HOME", "XDG_CONFIG_HOME",
    "CODEX_HOME", "odin_home", "odin_artifact_root",
})

# Values that describe the build/runtime posture and identify nobody.
SAFE_VALUE_ENV = frozenset({
    "TZ", "LANG", "LC_ALL", "LC_CTYPE", "OS", "PROCESSOR_ARCHITECTURE",
    "NUMBER_OF_PROCESSORS", "CI", "SOURCE_DATE_EPOCH", "PYTHONHASHSEED",
    "PYTHONIOENCodinG", "PYTHONDONTWRITEBYTECODE", "UMASK", "NODE_ENV",
    "NODE_OPTIONS", "RUSTFLAGS", "CFLAGS", "CXXFLAGS", "MAKEFLAGS",
    "GOFLAGS", "GOPROXY", "GONOSUMDB", "GOARCH", "GOOS", "TERM",
})


def cmd_env(args):
    from odin_lib.common import run

    state = State.load(args.artifacts)
    available, unavailable = {}, {}
    for name, cmd in TOOL_PROBES:
        code, out, err = run(cmd, timeout=30)
        text = (out or err).strip().splitlines()
        if code == 0 and text:
            available[name] = text[0].strip()
        else:
            unavailable[name] = "exit {}".format(code) if code != 127 else "not installed"

    env_report = {}
    for key in sorted(os.environ):
        upper = key.upper()
        if any(marker in upper for marker in SENSITIVE_ENV_MARKERS):
            env_report[key] = "<REDACTED: name matches a sensitive pattern>"
        elif upper in PATH_LIKE_ENV:
            # Path lists identify the operator and enumerate installed software.
            # Keep the shape, which is analytically useful; drop the content.
            entries = [e for e in os.environ[key].split(os.pathsep) if e]
            env_report[key] = "<REDACTED: path list, {} entries>".format(len(entries))
        elif upper in LOCATION_ENV:
            env_report[key] = "<REDACTED: operator-identifying location>"
        elif upper in SAFE_VALUE_ENV:
            env_report[key] = os.environ[key]

    report = {
        "note": "Tool availability determines which analyses are possible. An "
                "unavailable tool is recorded as an unavailable capability, never "
                "silently substituted.",
        "platform": state.data.get("platform", {}),
        "sandbox": state.data.get("sandbox"),
        "network_policy": state.data.get("network_policy"),
        "determinism_env_applied": state.data.get("determinism_env_applied", {}),
        "determinism_env_unapplied": state.data.get("determinism_env_unapplied", {}),
        "tools_available": dict(sorted(available.items())),
        "tools_unavailable": dict(sorted(unavailable.items())),
        "environment_variables_sanitized": env_report,
        "environment_variable_policy": {
            "rule": "Names influencing the build are listed. Values appear only for "
                    "demonstrably non-sensitive variables; everything else is redacted.",
            "redaction_classes": {
                "sensitive-name": "name matches a credential-shaped pattern",
                "path-list": "value withheld; entry count retained because the shape "
                             "is analytically useful and the content identifies the "
                             "operator and their installed software",
                "operator-identifying location": "home, temp and toolchain directories "
                                                 "withheld; they contain the username",
            },
            "note": "Packets are meant to be shareable. No operator-identifying value "
                    "is written here.",
        },
    }
    write_json(state.packet_root / "inventory" / "environment.json", report)
    return {
        "tools_available": len(available),
        "tools_unavailable": len(unavailable),
        "available": sorted(available),
        "output": "inventory/environment.json",
    }


# --------------------------------------------------------------------------
# inventory / scans
# --------------------------------------------------------------------------

def cmd_inventory(args):
    state = State.load(args.artifacts)
    return run_inventory(state, tree_limit=args.tree_limit)


def cmd_todos(args):
    return scan.scan_todos(State.load(args.artifacts))


def cmd_secrets(args):
    return scan.scan_secrets(State.load(args.artifacts))


def cmd_coverage(args):
    from odin_lib import coverage as coverage_lib

    state = State.load(args.artifacts)
    result, action = coverage_lib.measure(
        state, module=args.module, target=args.target,
        target_args=args.target_args, timeout=args.timeout)
    _append_actions(state, [action])
    return result


# --------------------------------------------------------------------------
# docstub
# --------------------------------------------------------------------------

STUB_TEMPLATE = """# {path}

<!-- odin:pending -->
<!-- Mechanical fields below are filled from the inventory and are authoritative.
     Every analytic field marked PENDING must be completed, or replaced with an
     explicit, evidence-backed statement of why it cannot be determined.
     Remove the odin:pending marker once the record is complete. -->

## Identity

- **Path:** `{path}`
- **SHA-256:** `{sha256}`
- **Size:** {size} bytes{lines}
- **Filesystem type/mode:** {entry_type}, mode {mode}{nlink}
- **File format:** {fmt}
- **Language(s):** {language}
- **Content kind:** {content_kind}{encoding}
- **Role:** {role} ({role_evidence})
- **Module:** PENDING
- **Classification:** {origin} ({origin_evidence})
- **Sensitive-content handling:** {sensitivity}
- **Git state:** {git}

## Purpose / summary

PENDING

## Key symbols and types

PENDING

## Imports, exports, dependencies

PENDING

## Callers, callees, references

PENDING

## Runtime and control-flow behavior

PENDING

## Data flow and I/O

PENDING

## Configuration and environment usage

PENDING

## Security observations

PENDING

## Tests touching or referring to this file

PENDING

## Measured coverage

Not measured.

## TODO / unfinished work

PENDING

## Related files and modules

PENDING

## Evidence class and confidence

PENDING

## Parse and tool errors

None recorded.

## Limitations and unknowns

PENDING
"""


def cmd_docstub(args):
    state = State.load(args.artifacts)
    packet = state.packet_root
    rows = read_jsonl(packet / "inventory" / "files.jsonl")
    regular = [r for r in rows if r.get("entry_type") == "regular-file"]
    if not regular:
        raise odinError("no inventory records found; run `odin.py inventory` first")

    written, skipped = 0, 0
    for row in regular:
        target = packet / row["doc_path"]
        if target.is_file() and not args.overwrite:
            skipped += 1
            continue
        alternatives = row.get("classification_alternatives") or []
        language = row.get("classification_primary") or "unknown"
        if alternatives:
            language += " (alternatives: " + ", ".join(
                "{} [{}]".format(a["label"], a["evidence"]) for a in alternatives[:4]) + ")"
        git = row.get("git") or {}
        git_text = ", ".join(sorted("{}={}".format(k, v) for k, v in git.items())) or "no Git metadata"
        body = STUB_TEMPLATE.format(
            path=row["path"],
            sha256=row.get("sha256") or "unavailable",
            size=row.get("size_bytes"),
            lines=(", {} lines".format(row["line_count"]) if row.get("line_count") is not None else ""),
            entry_type=row.get("entry_type"),
            mode=row.get("mode_octal"),
            nlink=(", hardlink group {}".format(row["hardlink_group"]) if row.get("hardlink_group") else ""),
            fmt=row.get("magic_format") or row.get("classification_primary") or "unclassified",
            language=language,
            content_kind=row.get("content_kind") or "unknown",
            encoding=(", encoding {}".format(row["encoding"]) if row.get("encoding") else ""),
            role=row.get("role_hint"),
            role_evidence=row.get("role_evidence"),
            origin=row.get("origin_hint"),
            origin_evidence=row.get("origin_evidence"),
            sensitivity=(row.get("handling") or "normal; no special handling required"),
            git=git_text,
        )
        write_text(target, body)
        written += 1

    return {
        "stubs_written": written,
        "existing_documents_kept": skipped,
        "total_regular_files": len(regular),
        "reminder": "Stubs carry the marker <!-- odin:pending -->. `odin.py validate` "
                    "fails while any document still carries it.",
    }


# --------------------------------------------------------------------------
# action manifest
# --------------------------------------------------------------------------

def cmd_readme_scan(args):
    from odin_lib import readme as readme_lib

    state = State.load(args.artifacts)
    report = readme_lib.scan(state)
    return {
        "repository_shape": report["repository_shape"],
        "languages_ranked": [l["language"] for l in report["languages_ranked"][:8]],
        "ecosystems_detected": sorted(report["ecosystems_detected"]),
        "components_proposed": len(report["components_proposed"]),
        "entrypoints": sorted(report["entrypoints"]),
        "ci": sorted(report["ci"]),
        "containers_and_iac": sorted(report["containers_and_iac"]),
        "test_frameworks": report["tests"]["frameworks_detected"],
        "absences": {k: v for k, v in report["absences"].items() if v is True},
        "output": "readme/component-map.json",
    }


def cmd_readme_lint(args):
    from odin_lib import readme as readme_lib

    target = Path(args.path).expanduser()
    if not target.is_file():
        raise odinError("no README at " + str(target))
    report = readme_lib.lint(
        target.read_text(encoding="utf-8", errors="replace"),
        path_label=str(target),
        require_sections=not args.no_section_check)
    if args.artifacts is not None or not args.no_write:
        try:
            state = State.load(args.artifacts)
            write_json(state.packet_root / "readme" / "lint-report.json", report)
            report["output"] = "readme/lint-report.json"
        except odinError:
            pass
    report.pop("headings", None)
    return report


def cmd_render(args):
    """Render graphs/*.mmd with a trusted local Mermaid renderer, if one exists."""
    from odin_lib.common import run

    state = State.load(args.artifacts)
    graphs = state.packet_root / "graphs"
    rendered = graphs / "rendered"
    rendered.mkdir(parents=True, exist_ok=True)
    sources = sorted(graphs.glob("*.mmd"), key=lambda p: str(p).encode())

    renderer = args.renderer or "mmdc"
    code, out, err = run([renderer, "--version"], timeout=60)
    if code != 0:
        report = {
            "status": "unavailable",
            "renderer": renderer,
            "reason": "no trusted local Mermaid renderer found ({}). The .mmd sources "
                      "are the canonical representation and are retained; "
                      "graphs/rendered/ stays empty.".format(err.strip() or "exit %d" % code),
            "diagrams_found": len(sources),
            "rendered": [],
        }
        write_json(rendered / "RENDER_STATUS.json", report)
        return report

    version = (out or err).strip().splitlines()[0].strip()
    ok, failed = [], []
    for source in sources:
        target = rendered / (source.stem + "." + args.format)
        # Renderers may fetch remote fonts/themes; keep it local and deterministic.
        code, out, err = run(
            [renderer, "-i", str(source), "-o", str(target), "-b", args.background],
            timeout=args.timeout)
        if code == 0 and target.is_file():
            ok.append({"source": "graphs/" + source.name,
                       "output": "graphs/rendered/" + target.name,
                       "sha256": sha256_file(target)})
        else:
            failed.append({"source": "graphs/" + source.name,
                           "exit_code": code,
                           "error": (err or out).strip()[:500]})

    report = {
        "status": "rendered" if not failed else "partial",
        "renderer": renderer,
        "renderer_version": version,
        "format": args.format,
        "diagrams_found": len(sources),
        "rendered": ok,
        "failed": failed,
        "note": "Mermaid .mmd source remains canonical. A rendering failure is a "
                "recorded non-blocking error, never a reason to drop a diagram.",
    }
    write_json(rendered / "RENDER_STATUS.json", report)
    return report


def _append_actions(state, records, defaults=None):
    defaults = defaults or {}
    manifest_path = state.packet_root / "ACTION_MANIFEST.json"
    manifest = read_json(manifest_path) or {
        "schema": "odin.action-manifest/1", "actions": []}
    written = []
    for base in records:
        record = {
            "seq": state.next_seq(),
            "phase": base.get("phase", defaults.get("phase")),
            "action_id": base.get("action_id", defaults.get("action_id")),
            "status": base.get("status", defaults.get("status")),
            "tool": base.get("tool", defaults.get("tool")),
            "tool_version": base.get("tool_version", defaults.get("tool_version")),
            "runtime_version": base.get("runtime_version", defaults.get("runtime_version")),
            "working_directory": base.get("working_directory",
                                          defaults.get("working_directory")),
            "command": base.get("command", defaults.get("command")),
            "input_scope": base.get("input_scope", defaults.get("input_scope")),
            "output_paths": base.get("output_paths", defaults.get("output_paths", [])),
            "sandbox": base.get("sandbox", defaults.get(
                "sandbox", state.data.get("sandbox"))),
            "network": base.get("network", defaults.get(
                "network", state.data.get("network_policy"))),
            "repo_code_executed": base.get("repo_code_executed",
                                           defaults.get("repo_code_executed", False)),
            "exit_code": base.get("exit_code", defaults.get("exit_code")),
            "termination": base.get("termination", defaults.get("termination")),
            "log_path": base.get("log_path", defaults.get("log_path")),
            "reason": base.get("reason", defaults.get("reason")),
            "evidence": base.get("evidence", defaults.get("evidence", [])),
            "assumptions": base.get("assumptions", defaults.get("assumptions", [])),
        }
        if record["log_path"]:
            candidate = state.packet_root / record["log_path"]
            if not candidate.is_file():
                candidate = Path(record["log_path"])
            if candidate.is_file():
                record["log_sha256"] = sha256_file(candidate)
        record = {k: v for k, v in record.items() if v is not None}
        if not record.get("action_id") or not record.get("status"):
            raise odinError("each action needs at least --action-id and --status")
        manifest.setdefault("actions", []).append(record)
        written.append({"seq": record["seq"], "action_id": record["action_id"],
                        "status": record["status"]})

    write_json(manifest_path, manifest)
    return {"recorded": written, "actions_total": len(manifest["actions"])}


def cmd_log(args):
    state = State.load(args.artifacts)
    if args.from_json:
        payload = json.loads(Path(args.from_json).read_text(encoding="utf-8"))
        records = payload if isinstance(payload, list) else [payload]
    else:
        records = [{}]
    defaults = {
        "phase": args.phase,
        "action_id": args.action_id,
        "status": args.status,
        "tool": args.tool,
        "tool_version": args.tool_version,
        "runtime_version": args.runtime_version,
        "working_directory": args.cwd,
        "command": args.command,
        "input_scope": args.input_scope,
        "output_paths": args.output or [],
        "sandbox": args.sandbox or state.data.get("sandbox"),
        "network": args.network or state.data.get("network_policy"),
        "repo_code_executed": bool(args.repo_code_executed),
        "exit_code": args.exit_code,
        "termination": args.termination,
        "log_path": args.log_path,
        "reason": args.reason,
        "evidence": args.evidence or [],
        "assumptions": args.assumption or [],
    }
    return _append_actions(state, records, defaults)


# --------------------------------------------------------------------------
# verify / validate / package
# --------------------------------------------------------------------------

def cmd_verify(args):
    return verify.verify_integrity(State.load(args.artifacts))


def cmd_validate(args):
    report = verify.validate(State.load(args.artifacts))
    return {
        "status": report["status"],
        "blocking_problems": report["blocking_problems"],
        "per_file_documents": {
            k: v for k, v in report["per_file_documents"].items()
            if not isinstance(v, list)
        },
        "module_documents": {
            k: v for k, v in report["module_documents"].items()
            if not isinstance(v, list)
        },
        "detail": "VALIDATION.json",
    }


def cmd_manifest(args):
    state = State.load(args.artifacts)
    built = packaging.build_manifest(state)
    built["verification"] = packaging.verify_manifest(state)
    return built


def cmd_package(args):
    state = State.load(args.artifacts)
    if not args.skip_manifest:
        packaging.build_manifest(state)
    result = packaging.build_zip(state, compresslevel=args.compresslevel)
    if args.require_validation:
        report = read_json(state.packet_root / "VALIDATION.json")
        result["validation_status"] = (report or {}).get("status", "not-run")
    return result


def cmd_status(args):
    state = State.load(args.artifacts)
    packet = state.packet_root
    inventory_summary = read_json(packet / "inventory" / "inventory-summary.json") or {}
    manifest = read_json(packet / "ACTION_MANIFEST.json") or {}
    files_dir = packet / "files"
    modules_dir = packet / "modules"
    zip_path = Path(state.data["final_zip"])
    return {
        "repo_root": state.data["repo_root"],
        "artifact_root": state.data["artifact_root"],
        "packet_root": str(packet),
        "network_policy": state.data.get("network_policy"),
        "sandbox": state.data.get("sandbox"),
        "inventory": inventory_summary.get("counts", {}),
        "per_file_documents_written": sum(1 for _ in files_dir.rglob("*.md")) if files_dir.is_dir() else 0,
        "per_file_documents_required": inventory_summary.get("counts", {}).get("regular_files", 0),
        "module_documents_written": sum(1 for _ in modules_dir.glob("*.md")) if modules_dir.is_dir() else 0,
        "actions_logged": len(manifest.get("actions", [])),
        "top_level_documents_present": [name for name in REQUIRED_TOP_LEVEL_DOCS
                                        if (packet / name).is_file()],
        "top_level_documents_missing": [name for name in REQUIRED_TOP_LEVEL_DOCS
                                        if not (packet / name).is_file()],
        "findings_zip_exists": zip_path.is_file(),
        "findings_zip_sha256": sha256_file(zip_path) if zip_path.is_file() else None,
    }


# --------------------------------------------------------------------------
# argument parsing
# --------------------------------------------------------------------------

def build_parser():
    parser = argparse.ArgumentParser(
        prog="odin.py",
        description="Deterministic helpers for the odin repository-forensics protocol.")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_common(sp):
        sp.add_argument("--artifacts", help="ARTIFACT_ROOT or its .odin-state.json "
                                            "(defaults to $odin_artifact_root or an "
                                            "ancestor of the working directory)")

    p = sub.add_parser("init", help="resolve roots, create the packet skeleton, write state")
    p.add_argument("--repo", required=True, help="REPO_ROOT to analyze")
    p.add_argument("--artifacts", help="ARTIFACT_ROOT; must be outside REPO_ROOT")
    p.add_argument("--network", default="denied",
                   choices=["denied", "authorized-advisory-only", "authorized"],
                   help="network policy for this run (default: denied)")
    p.add_argument("--sandbox", default="none",
                   help="sandbox implementation available for dynamic analysis "
                        "(e.g. none, container, microvm, platform-sandbox)")
    p.set_defaults(func=cmd_init)

    p = sub.add_parser("env", help="probe tool/runtime versions and sanitized environment")
    add_common(p)
    p.set_defaults(func=cmd_env)

    p = sub.add_parser("inventory", help="exhaustive deterministic filesystem inventory")
    add_common(p)
    p.add_argument("--tree-limit", type=int, default=20000,
                   help="maximum entries rendered into tree.txt (default 20000)")
    p.set_defaults(func=cmd_inventory)

    p = sub.add_parser("todos", help="scan for TODO/FIXME and unfinished-work signals")
    add_common(p)
    p.set_defaults(func=cmd_todos)

    p = sub.add_parser("secrets", help="scan for redacted secret candidates")
    add_common(p)
    p.set_defaults(func=cmd_secrets)

    p = sub.add_parser("docstub", help="create per-file document skeletons from the inventory")
    add_common(p)
    p.add_argument("--overwrite", action="store_true",
                   help="replace existing per-file documents (default: keep them)")
    p.set_defaults(func=cmd_docstub)

    p = sub.add_parser(
        "coverage",
        help="measure Python line coverage with the stdlib trace module",
        description="Measure Python line coverage with the stdlib trace module in a "
                    "declared sandbox and disposable repository copy.")
    add_common(p)
    p.add_argument("--module", action="store_true",
                   help="run target as a Python module instead of a repository-relative script")
    p.add_argument("--timeout", type=int, default=300,
                   help="kill the coverage process tree after N seconds (default: 300)")
    p.add_argument("target", help="repository-relative Python script, or module with --module")
    p.add_argument("target_args", nargs=argparse.REMAINDER,
                   help="arguments passed to target; use -- before option-shaped arguments")
    p.set_defaults(func=cmd_coverage)

    p = sub.add_parser("readme-scan",
                       help="sweep the inventory for repository-README evidence")
    add_common(p)
    p.set_defaults(func=cmd_readme_scan)

    p = sub.add_parser("readme-lint",
                       help="enforce the README formatting constraints")
    add_common(p)
    p.add_argument("--path", default="README.md", help="README to check (default: ./README.md)")
    p.add_argument("--no-section-check", action="store_true",
                   help="check formatting only; skip the required-section check")
    p.add_argument("--no-write", action="store_true",
                   help="do not write readme/lint-report.json into the packet")
    p.set_defaults(func=cmd_readme_lint)

    p = sub.add_parser("render", help="render graphs/*.mmd with a local Mermaid renderer")
    add_common(p)
    p.add_argument("--renderer", help="renderer executable (default: mmdc)")
    p.add_argument("--format", default="svg", choices=["svg", "png", "pdf"])
    p.add_argument("--background", default="transparent",
                   help="background passed to the renderer (default: transparent)")
    p.add_argument("--timeout", type=int, default=120)
    p.set_defaults(func=cmd_render)

    p = sub.add_parser("log", help="append a record to ACTION_MANIFEST.json")
    add_common(p)
    p.add_argument("--phase")
    p.add_argument("--action-id")
    p.add_argument("--status", choices=["planned", "executed", "succeeded", "failed",
                                        "timeout", "skipped", "unavailable",
                                        "blocked_by_policy"])
    p.add_argument("--tool")
    p.add_argument("--tool-version")
    p.add_argument("--runtime-version")
    p.add_argument("--cwd")
    p.add_argument("--command", help="exact sanitized command or operation")
    p.add_argument("--input-scope")
    p.add_argument("--output", action="append")
    p.add_argument("--sandbox")
    p.add_argument("--network")
    p.add_argument("--repo-code-executed", action="store_true")
    p.add_argument("--exit-code", type=int)
    p.add_argument("--termination")
    p.add_argument("--log-path")
    p.add_argument("--reason")
    p.add_argument("--evidence", action="append")
    p.add_argument("--assumption", action="append")
    p.add_argument("--from-json", help="JSON file holding one action object or a list")
    p.set_defaults(func=cmd_log)

    p = sub.add_parser("verify", help="recompute repository hashes and compare to baseline")
    add_common(p)
    p.set_defaults(func=cmd_verify)

    p = sub.add_parser("validate", help="pre-packaging completeness and privacy validation")
    add_common(p)
    p.set_defaults(func=cmd_validate)

    p = sub.add_parser("manifest", help="generate and verify MANIFEST.sha256")
    add_common(p)
    p.set_defaults(func=cmd_manifest)

    p = sub.add_parser("package", help="build and verify findings.zip deterministically")
    add_common(p)
    p.add_argument("--skip-manifest", action="store_true",
                   help="do not regenerate MANIFEST.sha256 first")
    p.add_argument("--compresslevel", type=int, default=9)
    p.add_argument("--require-validation", action="store_true", default=True)
    p.set_defaults(func=cmd_package)

    p = sub.add_parser("status", help="show run progress")
    add_common(p)
    p.set_defaults(func=cmd_status)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        result = args.func(args)
    except odinError as exc:
        print(jdumps({"error": str(exc)}))
        return 2
    print(jdumps(result))
    if isinstance(result, dict) and result.get("status") == "FAIL":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
