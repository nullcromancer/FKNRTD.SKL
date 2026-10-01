"""Shared state, IO, hashing and process helpers for the odin toolkit.

Stdlib only. Deterministic by construction:
  * all JSON is written with sorted keys, fixed separators, LF endings, UTF-8
  * all path ordering is bytewise over the normalized POSIX relative path
  * no wall-clock time is written into packet content; actions are identified
    by a monotonically increasing sequence number held in the state file
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import unicodedata
from pathlib import Path, PurePosixPath

STATE_FILENAME = ".odin-state.json"
PACKET_DIRNAME = "findings"
ZIP_NAME = "findings.zip"

# Fixed environment odin tries to establish for every child process.
DETERMINISM_ENV = {
    "TZ": "UTC",
    "LC_ALL": "C.UTF-8",
    "LANG": "C.UTF-8",
    "PYTHONHASHSEED": "0",
    "PYTHONIOENCodinG": "utf-8",
    "SOURCE_DATE_EPOCH": "315532800",  # 1980-01-01T00:00:00Z
}

PACKET_DIRS = [
    "inventory",
    "modules",
    "files",
    "graphs",
    "graphs/rendered",
    "dependencies",
    "tests",
    "tests/coverage",
    "security",
    "static-analysis",
    "sources",
    "readme",
    "tool-output",
]

REQUIRED_TOP_LEVEL_DOCS = [
    "README.md",
    "EXECUTIVE_SUMMARY.md",
    "REPOSITORY_OVERVIEW.md",
    "ARCHITECTURE.md",
    "BUILD_AND_RUN.md",
    "DEPENDENCIES.md",
    "TESTS_AND_COVERAGE.md",
    "SECURITY.md",
    "TODOS_AND_UNFINISHED_WORK.md",
    "ASSUMPTIONS_AND_LIMITATIONS.md",
    "REPRODUCE.md",
    "ERRORS.md",
    "ACTION_MANIFEST.json",
]


class odinError(RuntimeError):
    pass


# --------------------------------------------------------------------------
# paths
# --------------------------------------------------------------------------

def norm_rel(root: Path, target: Path) -> str:
    """Normalized, POSIX-style, NFC-stable repository-relative path."""
    rel = os.path.relpath(str(target), str(root))
    rel = rel.replace(os.sep, "/")
    if rel.startswith("./"):
        rel = rel[2:]
    rel = str(PurePosixPath(rel))
    return unicodedata.normalize("NFC", rel)


WINDOWS_RESERVED = {
    "con", "prn", "aux", "nul",
    "com1", "com2", "com3", "com4", "com5", "com6", "com7", "com8", "com9",
    "lpt1", "lpt2", "lpt3", "lpt4", "lpt5", "lpt6", "lpt7", "lpt8", "lpt9",
}
UNSAFE_PATH_CHARS = '<>:"|?*\\'


def safe_doc_path(rel_path: str):
    """Map a repository-relative path to a per-file document path.

    Returns (doc_path, remapped_bool). The default is
    ``files/<repository-relative-path>.md``. A component that cannot exist on
    the host filesystem (Windows reserved device name, forbidden character,
    trailing dot or space) is escaped and the whole path is disambiguated with
    a short digest of the original, so the mapping stays injective and the
    original path is still recoverable from files/_PATH_MAP.json.
    """
    parts = rel_path.split("/")
    out = []
    remapped = False
    for part in parts:
        safe = part
        for char in UNSAFE_PATH_CHARS:
            if char in safe:
                safe = safe.replace(char, "%{:02X}".format(ord(char)))
                remapped = True
        safe = "".join(
            ch if ord(ch) >= 32 else "%{:02X}".format(ord(ch)) for ch in safe
        )
        if safe != part:
            remapped = True
        stem = safe.split(".", 1)[0].lower()
        if stem in WINDOWS_RESERVED:
            safe = "_" + safe
            remapped = True
        if safe.endswith(".") or safe.endswith(" "):
            safe = safe.rstrip(". ") + "_"
            remapped = True
        out.append(safe)
    doc = "files/" + "/".join(out) + ".md"
    if remapped:
        digest = hashlib.sha256(rel_path.encode("utf-8", "surrogatepass")).hexdigest()[:8]
        doc = doc[:-3] + ".." + digest + ".md"
    return (doc, remapped)


def sort_key(path_str: str) -> bytes:
    """Bytewise ordering key so traversal order never depends on the OS."""
    return path_str.encode("utf-8", "surrogatepass")


def is_inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.resolve().relative_to(root.resolve())
        return True
    except (ValueError, OSError):
        return False


# --------------------------------------------------------------------------
# state
# --------------------------------------------------------------------------

def state_path(artifact_root: Path) -> Path:
    return artifact_root / STATE_FILENAME


def find_state(explicit=None) -> Path:
    """Locate the odin state file for the current run."""
    if explicit:
        p = Path(explicit).expanduser()
        if p.is_dir():
            p = state_path(p)
        if p.is_file():
            return p
        raise odinError("no odin state file at " + str(p))
    env = os.environ.get("odin_artifact_root")
    if env:
        p = state_path(Path(env).expanduser())
        if p.is_file():
            return p
    cwd = Path.cwd()
    for candidate in [cwd] + list(cwd.parents):
        p = state_path(candidate)
        if p.is_file():
            return p
    raise odinError(
        "no odin state file found; run `odin.py init --repo <REPO_ROOT> "
        "--artifacts <ARTIFACT_ROOT>` first, or pass --artifacts"
    )


class State:
    def __init__(self, path: Path, data: dict):
        self.path = path
        self.data = data

    @classmethod
    def load(cls, explicit=None) -> "State":
        p = find_state(explicit)
        return cls(p, json.loads(p.read_text(encoding="utf-8")))

    def save(self) -> None:
        write_json(self.path, self.data)

    @property
    def repo_root(self) -> Path:
        return Path(self.data["repo_root"])

    @property
    def artifact_root(self) -> Path:
        return Path(self.data["artifact_root"])

    @property
    def packet_root(self) -> Path:
        return self.artifact_root / PACKET_DIRNAME

    @property
    def scratch(self) -> Path:
        return self.artifact_root / "scratch"

    def next_seq(self) -> int:
        seq = int(self.data.get("seq", 0)) + 1
        self.data["seq"] = seq
        self.save()
        return seq


# --------------------------------------------------------------------------
# deterministic IO
# --------------------------------------------------------------------------

def jdumps(obj) -> str:
    return json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if text and not text.endswith("\n"):
        text += "\n"
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)


def write_json(path: Path, obj) -> None:
    write_text(path, jdumps(obj))


def write_jsonl(path: Path, rows) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, ensure_ascii=False))
            fh.write("\n")


def read_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def read_jsonl(path: Path):
    if not path.is_file():
        return []
    rows = []
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


# --------------------------------------------------------------------------
# hashing
# --------------------------------------------------------------------------

def sha256_file(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            block = fh.read(chunk)
            if not block:
                break
            h.update(block)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def fingerprint(value: str, salt: str = "odin-secret-fingerprint") -> str:
    """Non-reversible, deduplication-safe fingerprint of a sensitive value."""
    return hashlib.sha256((salt + "\x00" + value).encode("utf-8")).hexdigest()[:16]


# --------------------------------------------------------------------------
# subprocess
# --------------------------------------------------------------------------

def child_env(extra=None) -> dict:
    env = dict(os.environ)
    env.update(DETERMINISM_ENV)
    if extra:
        env.update(extra)
    return env


def run(cmd, cwd=None, timeout: int = 120, env_extra=None):
    """Run a read-only helper command. Returns (exit_code, stdout, stderr)."""
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            timeout=timeout,
            env=child_env(env_extra),
        )
    except FileNotFoundError:
        return (127, "", "executable not found: " + str(cmd[0]))
    except subprocess.TimeoutExpired:
        return (124, "", "timeout after {}s: {}".format(timeout, " ".join(map(str, cmd))))
    except OSError as exc:  # pragma: no cover - platform dependent
        return (126, "", "{}: {}".format(type(exc).__name__, exc))
    out = proc.stdout.decode("utf-8", "replace")
    err = proc.stderr.decode("utf-8", "replace")
    return (proc.returncode, out, err)


def eprint(*args) -> None:
    print(*args, file=sys.stderr)
