#!/usr/bin/env python3
"""Install or remove the inquisitor skill for Claude Code, Codex, Cline and Copilot CLI.

Resolves its source from its own location. Re-running replaces the installed copy, so
installed copies never drift from this folder. Python 3.8+, standard library only.

  python install.py                 install for all four, user scope
  python install.py --target claude
  python install.py --scope project --project path/to/repo
  python install.py --uninstall
  python install.py --dry-run
"""
from __future__ import annotations

import argparse
import os
import shutil
import stat
import sys
from pathlib import Path

NAME = "inquisitor"
SOURCE = Path(__file__).resolve().parent
TARGETS = ("claude", "codex", "cline", "copilot")
IGNORE = shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".DS_Store", "*.installing", "*.previous")


def force_remove(path: Path) -> None:
    def fix(func, target, _exc):
        try:
            os.chmod(target, stat.S_IWRITE)
            func(target)
        except OSError:
            pass
    if sys.version_info >= (3, 12):
        shutil.rmtree(path, onexc=fix)
    else:
        shutil.rmtree(path, onerror=fix)


def user_dest(target: str) -> Path:
    home = Path.home()
    if target == "claude":
        return Path(os.environ.get("CLAUDE_CONFIG_DIR") or home / ".claude") / "skills" / NAME
    if target == "codex":
        return home / ".agents" / "skills" / NAME
    if target == "cline":
        return home / ".cline" / "skills" / NAME
    return Path(os.environ.get("COPILOT_HOME") or home / ".copilot") / "skills" / NAME


def project_dest(target: str, project: Path) -> Path:
    sub = {"claude": ".claude/skills", "codex": ".agents/skills", "cline": ".cline/skills", "copilot": ".github/skills"}[target]
    return project / sub / NAME


def install(dest: Path, dry: bool) -> None:
    print("  install -> %s" % dest)
    if dry:
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    staging = dest.with_name(dest.name + ".installing")
    if staging.exists():
        force_remove(staging)
    shutil.copytree(SOURCE, staging, ignore=IGNORE)
    if dest.exists():
        backup = dest.with_name(dest.name + ".previous")
        if backup.exists():
            force_remove(backup)
        dest.rename(backup)
        try:
            staging.rename(dest)
        except Exception:
            backup.rename(dest)
            raise
        force_remove(backup)
    else:
        staging.rename(dest)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--target", choices=TARGETS + ("all",), default="all")
    p.add_argument("--scope", choices=("user", "project"), default="user")
    p.add_argument("--project", help="project root for --scope project (default: current directory)")
    p.add_argument("--uninstall", action="store_true")
    p.add_argument("--dry-run", action="store_true")
    a = p.parse_args(argv)
    if not (SOURCE / "SKILL.md").exists() or not (SOURCE / "assets" / "template.html").exists():
        print("  ! run install.py from an intact inquisitor skill folder", file=sys.stderr)
        return 1
    chosen = TARGETS if a.target == "all" else (a.target,)
    project = Path(a.project or Path.cwd()).resolve()
    dests = [(t, user_dest(t) if a.scope == "user" else project_dest(t, project)) for t in chosen]
    for _t, d in dests:
        if a.uninstall:
            print("  remove  -> %s" % d)
            if d.exists() and not a.dry_run:
                force_remove(d)
        else:
            install(d, a.dry_run)
    if not a.uninstall:
        print("\n  installed. Claude Code: /inquisitor   Codex: $inquisitor   Cline/Copilot: ask for the inquisitor skill")
    return 0


if __name__ == "__main__":
    sys.exit(main())
