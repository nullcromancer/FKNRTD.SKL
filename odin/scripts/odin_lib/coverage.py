"""Measured Python line coverage using only the standard-library ``trace`` module.

The public ``measure`` function enforces odin's dynamic-execution gate, runs the
target from a disposable repository copy, and returns both the packet summary and
the action-manifest record.  This module also acts as the trusted child-process
runner so target failures and timeouts cannot terminate the odin CLI itself.
"""

from __future__ import annotations

import argparse
import json
import os
import platform
import re
import runpy
import shutil
import signal
import subprocess
import sys
import sysconfig
import trace
from pathlib import Path

try:
    from .common import DETERMINISM_ENV, odinError, is_inside, write_json, write_text
except ImportError:  # direct execution by the trusted coverage child runner
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from odin_lib.common import DETERMINISM_ENV, odinError, is_inside, write_json, write_text


SCHEMA = "odin.coverage-summary/1"
ACTION_ID = "DYN-COVERAGE"
SENSITIVE_OPTION = re.compile(r"(?i)(token|secret|pass(word|wd)?|key|credential|auth|cookie)")


def _percent(covered, total):
    return round((covered * 100.0 / total), 2) if total else 0.0


def _safe_rmtree(root, target):
    root_resolved = root.resolve()
    target_resolved = target.resolve()
    try:
        target_resolved.relative_to(root_resolved)
    except ValueError:
        raise odinError("refusing to remove coverage path outside scratch: " + str(target))
    if target_resolved == root_resolved:
        raise odinError("refusing to remove the scratch root")
    if target.exists() or target.is_symlink():
        shutil.rmtree(str(target))


def _sanitize_arguments(parts):
    """Render target arguments while redacting common credential option values."""
    rendered = []
    redact_next = False
    for part in parts:
        text = str(part)
        if redact_next:
            rendered.append("<REDACTED>")
            redact_next = False
            continue
        if text.startswith("-") and "=" in text:
            name, value = text.split("=", 1)
            rendered.append(name + "=<REDACTED>" if SENSITIVE_OPTION.search(name)
                            else name + "=" + value)
            continue
        rendered.append(text)
        if text.startswith("-") and SENSITIVE_OPTION.search(text):
            redact_next = True
    return rendered


def _display_command(module, target, target_args):
    pieces = ["python", "-m", "trace", "--count", "--missing", "--summary"]
    if module:
        pieces.append("--module")
    pieces.append(target)
    pieces.extend(_sanitize_arguments(target_args))
    return subprocess.list2cmdline(pieces)


def _sanitized_log(stdout, stderr, worktree, repo_root):
    text = "stdout:\n" + stdout + "\nstderr:\n" + stderr
    replacements = [
        (str(worktree.resolve()), "<sandbox>/worktree"),
        (str(repo_root.resolve()), "<repo>"),
    ]
    for value, replacement in replacements:
        text = text.replace(value, replacement)
        text = text.replace(value.replace("\\", "/"), replacement)
    return text


def _run_process(command, cwd, timeout, env):
    kwargs = {}
    if os.name == "posix":
        kwargs["start_new_session"] = True
    elif os.name == "nt":
        kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
    proc = subprocess.Popen(
        command,
        cwd=str(cwd),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
        **kwargs
    )
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        return proc.returncode, stdout.decode("utf-8", "replace"), \
            stderr.decode("utf-8", "replace"), False
    except subprocess.TimeoutExpired:
        if os.name == "posix":
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
        elif os.name == "nt":
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        else:  # pragma: no cover - only unusual Python platforms reach this
            proc.kill()
        stdout, stderr = proc.communicate()
        return 124, stdout.decode("utf-8", "replace"), \
            stderr.decode("utf-8", "replace"), True


def _blocked_summary(state):
    reason = ("coverage execution blocked by policy: sandbox is 'none'; measuring "
              "coverage would execute repository-controlled code")
    summary = {
        "schema": SCHEMA,
        "measured": False,
        "reason": reason,
        "sandbox": state.data.get("sandbox", "none"),
        "network_policy": state.data.get("network_policy", "denied"),
    }
    write_json(state.packet_root / "tests" / "coverage-summary.json", summary)
    action = {
        "phase": "dynamic",
        "action_id": ACTION_ID,
        "status": "blocked_by_policy",
        "tool": "Python stdlib trace",
        "tool_version": platform.python_version(),
        "runtime_version": "{} {}".format(platform.python_implementation(),
                                            platform.python_version()),
        "working_directory": "<sandbox>/worktree",
        "command": "coverage measurement not executed",
        "input_scope": "Python target in disposable repository copy",
        "output_paths": ["tests/coverage-summary.json"],
        "sandbox": state.data.get("sandbox", "none"),
        "network": state.data.get("network_policy", "denied"),
        "repo_code_executed": False,
        "termination": "policy gate",
        "reason": reason,
        "evidence": ["tests/coverage-summary.json"],
        "assumptions": [],
    }
    return summary, action


def measure(state, module, target, target_args, timeout):
    """Measure line coverage and return ``(CLI result, manifest action)``."""
    sandbox = str(state.data.get("sandbox") or "none").strip()
    if sandbox.lower() == "none":
        summary, action = _blocked_summary(state)
        result = dict(summary)
        result["status"] = "blocked_by_policy"
        result["output"] = "tests/coverage-summary.json"
        return result, action

    if timeout < 1:
        raise odinError("coverage --timeout must be at least 1 second")
    if not target:
        raise odinError("coverage needs a Python script target or --module MODULE")

    repo_root = state.repo_root.resolve()
    scratch = state.scratch.resolve()
    if is_inside(repo_root, scratch):
        raise odinError("coverage scratch must be physically outside REPO_ROOT")

    worktree = scratch / "coverage-worktree"
    runner_result = scratch / "coverage-run-result.json"
    native_scratch = scratch / "coverage-native"
    packet_native = state.packet_root / "tests" / "coverage"
    for path in (worktree, native_scratch, packet_native):
        root = scratch if path != packet_native else state.packet_root / "tests"
        _safe_rmtree(root, path)
    if runner_result.exists():
        runner_result.unlink()

    try:
        shutil.copytree(str(repo_root), str(worktree), symlinks=True)
    except OSError as exc:
        raise odinError("could not create disposable coverage worktree: {}".format(exc))
    native_scratch.mkdir(parents=True, exist_ok=True)

    if module:
        if not re.match(r"^[A-Za-z_]\w*(\.[A-Za-z_]\w*)*$", target):
            raise odinError("invalid Python module name: " + target)
    else:
        target_path = (worktree / target).resolve()
        if not is_inside(worktree, target_path):
            raise odinError("coverage script must be a repository-relative path")
        if not target_path.is_file():
            raise odinError("coverage script does not exist in disposable copy: " + target)

    runner = Path(__file__).resolve()
    command = [
        sys.executable,
        str(runner),
        "--worktree", str(worktree),
        "--coverdir", str(native_scratch),
        "--result", str(runner_result),
    ]
    if module:
        command.append("--module")
    command.append(target)
    if target_args:
        command.append("--")
        command.extend(target_args)

    env = dict(os.environ)
    env.update(DETERMINISM_ENV)
    env.update({
        "HOME": str(scratch / "home"),
        "USERPROFILE": str(scratch / "home"),
        "TMP": str(scratch / "tmp"),
        "TEMP": str(scratch / "tmp"),
        "TMPDIR": str(scratch / "tmp"),
        "PYTHONPYCACHEPREFIX": str(scratch / "pycache"),
        "PYTHONDONTWRITEBYTECODE": "1",
    })
    code, stdout, stderr, timed_out = _run_process(command, worktree, timeout, env)
    log_path = state.packet_root / "tool-output" / "coverage.log"
    if timed_out:
        stderr += "\ncoverage target timed out after {} seconds\n".format(timeout)
    write_text(log_path, _sanitized_log(stdout, stderr, worktree, repo_root))

    base_action = {
        "phase": "dynamic",
        "action_id": ACTION_ID,
        "tool": "Python stdlib trace",
        "tool_version": platform.python_version(),
        "runtime_version": "{} {}".format(platform.python_implementation(),
                                            platform.python_version()),
        "working_directory": "<sandbox>/worktree",
        "command": _display_command(module, target, target_args),
        "input_scope": "complete disposable copy of REPO_ROOT; traced Python files only",
        "sandbox": sandbox,
        "network": state.data.get("network_policy", "denied"),
        "repo_code_executed": True,
        "exit_code": code,
        "log_path": "tool-output/coverage.log",
        "assumptions": ["declared sandbox enforces its stated isolation and network policy"],
    }

    if timed_out or not runner_result.is_file():
        reason = ("coverage target timed out after {} seconds".format(timeout)
                  if timed_out else "coverage runner produced no result")
        summary = {
            "schema": SCHEMA,
            "measured": False,
            "reason": reason,
            "sandbox": sandbox,
            "network_policy": state.data.get("network_policy", "denied"),
        }
        write_json(state.packet_root / "tests" / "coverage-summary.json", summary)
        base_action.update({
            "status": "timeout" if timed_out else "failed",
            "termination": "timeout" if timed_out else "runner failure",
            "reason": reason,
            "output_paths": ["tests/coverage-summary.json", "tool-output/coverage.log"],
            "evidence": ["tests/coverage-summary.json", "tool-output/coverage.log"],
        })
        result = dict(summary)
        result["status"] = base_action["status"]
        result["output"] = "tests/coverage-summary.json"
        return result, base_action

    try:
        runner_data = json.loads(runner_result.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise odinError("coverage runner result is unreadable: {}".format(exc))

    shutil.copytree(str(native_scratch), str(packet_native), symlinks=True)
    native_artifacts = sorted(
        ["tests/coverage/" + p.relative_to(packet_native).as_posix()
         for p in packet_native.rglob("*") if p.is_file()],
        key=lambda value: value.encode("utf-8"),
    )
    files = runner_data.get("files", [])
    line_total = sum(item.get("line_total", 0) for item in files)
    line_covered = sum(item.get("line_covered", 0) for item in files)

    if line_total == 0:
        reason = "trace completed but recorded no executable Python lines inside REPO_ROOT"
        summary = {
            "schema": SCHEMA,
            "measured": False,
            "reason": reason,
            "sandbox": sandbox,
            "network_policy": state.data.get("network_policy", "denied"),
        }
        action_status = "failed"
    else:
        summary = {
            "schema": SCHEMA,
            "measured": True,
            "tool": "Python standard-library trace",
            "runtime_version": "{} {}".format(platform.python_implementation(),
                                                platform.python_version()),
            "scope": "Python files loaded from the disposable repository copy",
            "line_covered": line_covered,
            "line_total": line_total,
            "line_percent": _percent(line_covered, line_total),
            "branch_coverage": {
                "measured": False,
                "reason": "Python stdlib trace measures line execution, not branch coverage",
            },
            "files": files,
            "native_artifacts": native_artifacts,
            "target": {"kind": "module" if module else "script", "value": target},
            "target_exit_code": runner_data.get("target_exit_code", code),
            "execution_status": "succeeded" if code == 0 else "failed",
            "sandbox": sandbox,
            "network_policy": state.data.get("network_policy", "denied"),
        }
        action_status = "succeeded" if code == 0 else "failed"

    write_json(state.packet_root / "tests" / "coverage-summary.json", summary)
    evidence = ["tests/coverage-summary.json", "tool-output/coverage.log"] + native_artifacts
    base_action.update({
        "status": action_status,
        "termination": "target exited with status {}".format(code),
        "reason": None if line_total and code == 0 else
                  ("target exited nonzero; coverage evidence was still measured" if line_total
                   else summary.get("reason")),
        "output_paths": evidence,
        "evidence": evidence,
    })
    result = dict(summary)
    result["status"] = "measured" if line_total else "failed"
    result["output"] = "tests/coverage-summary.json"
    result["log"] = "tool-output/coverage.log"
    return result, base_action


def _inside(root, candidate):
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


def _child_main(argv=None):
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--worktree", required=True)
    parser.add_argument("--coverdir", required=True)
    parser.add_argument("--result", required=True)
    parser.add_argument("--module", action="store_true")
    parser.add_argument("target")
    parser.add_argument("target_args", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)
    if args.target_args and args.target_args[0] == "--":
        args.target_args = args.target_args[1:]

    sys.dont_write_bytecode = True
    worktree = Path(args.worktree).resolve()
    coverdir = Path(args.coverdir).resolve()
    result_path = Path(args.result).resolve()
    os.chdir(str(worktree))
    sys.path.insert(0, str(worktree))

    ignoredirs = set()
    candidates = [sysconfig.get_path("stdlib"), sysconfig.get_path("platstdlib"),
                  sys.prefix, sys.base_prefix, str(Path(__file__).resolve().parent)]
    for candidate in candidates:
        if candidate:
            path = Path(candidate).resolve()
            if not _inside(worktree, path):
                ignoredirs.add(str(path))

    tracer = trace.Trace(count=1, trace=0, ignoredirs=sorted(ignoredirs))
    sys.argv = [args.target] + list(args.target_args)
    target_exit_code = 0
    try:
        if args.module:
            tracer.runfunc(runpy.run_module, args.target, run_name="__main__", alter_sys=True)
        else:
            script = (worktree / args.target).resolve()
            tracer.runfunc(runpy.run_path, str(script), run_name="__main__")
    except SystemExit as exc:
        if exc.code is None:
            target_exit_code = 0
        elif isinstance(exc.code, int):
            target_exit_code = exc.code
        else:
            print(str(exc.code), file=sys.stderr)
            target_exit_code = 1
    except BaseException:  # target failures are evidence and must still yield coverage
        import traceback
        traceback.print_exc()
        target_exit_code = 1

    raw_counts = tracer.results().counts
    per_file = {}
    for (filename, lineno), count in raw_counts.items():
        path = Path(filename)
        if not path.is_absolute():
            path = (worktree / path).resolve()
        else:
            path = path.resolve()
        if _inside(worktree, path) and path.is_file() and path.suffix == ".py":
            per_file.setdefault(path, {})[lineno] = count

    rows = []
    filtered_counts = {}
    for path in sorted(per_file, key=lambda value: value.relative_to(worktree).as_posix().encode("utf-8")):
        counts = per_file[path]
        try:
            executable = trace._find_executable_linenos(str(path))
        except (OSError, SyntaxError, UnicodeError):
            executable = {}
        covered = sum(1 for lineno in executable if counts.get(lineno, 0) > 0)
        total = len(executable)
        rel = path.relative_to(worktree).as_posix()
        native_name = trace._fullmodname(str(path)) + ".cover"
        rows.append({
            "path": rel,
            "line_covered": covered,
            "line_total": total,
            "line_percent": _percent(covered, total),
            "native_artifact": "tests/coverage/" + native_name,
        })
        for lineno, count in counts.items():
            filtered_counts[(str(path), lineno)] = count

    if filtered_counts:
        results = trace.CoverageResults(counts=filtered_counts)
        results.write_results(show_missing=True, summary=False, coverdir=str(coverdir))

    result_path.parent.mkdir(parents=True, exist_ok=True)
    with open(result_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"files": rows, "target_exit_code": target_exit_code}, fh,
                  sort_keys=True, ensure_ascii=False, indent=2)
        fh.write("\n")
    return target_exit_code


if __name__ == "__main__":
    raise SystemExit(_child_main())
