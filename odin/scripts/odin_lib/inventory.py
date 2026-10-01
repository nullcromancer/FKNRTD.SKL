"""Exhaustive, deterministic filesystem inventory of REPO_ROOT.

The *filesystem traversal*, not Git's ignore rules, defines the inventory.
Dotfiles, ignored files, vendored trees, build output, binaries and .git itself
are all inventoried. Git is consulted only as supplementary metadata.

Outputs (all under <packet>/inventory/):
    files.jsonl          one record per non-directory entry
    directories.jsonl    one record per directory entry
    tree.txt             stable textual tree
    source-hashes.sha256 baseline SHA-256 of every regular file
    languages.json       language histogram with evidence counts
    file-types.json      format histogram
    roles.json           role histogram
    inventory-summary.json
"""

from __future__ import annotations

import fnmatch
import os
import stat
from pathlib import Path

from . import archives, classify
from .common import (
    norm_rel,
    run,
    safe_doc_path,
    sha256_file,
    sort_key,
    write_json,
    write_jsonl,
    write_text,
)

HEAD_BYTES = 8192
TEXT_CONTROL = bytes(range(0, 9)) + bytes([11, 12]) + bytes(range(14, 32)) + bytes([127])

# Archive member tables collected during a traversal, written to
# inventory/archives.json once the walk completes.
ARCHIVE_REPORTS = []


# --------------------------------------------------------------------------
# text / encoding detection
# --------------------------------------------------------------------------

def sniff_text(head: bytes):
    """Return (kind, encoding, evidence). kind is text | binary | empty."""
    if not head:
        return ("empty", None, "file has zero bytes in the sampled head")
    if head.startswith(b"\xef\xbb\xbf"):
        return ("text", "utf-8-sig", "UTF-8 BOM present")
    if head.startswith(b"\xff\xfe\x00\x00"):
        return ("text", "utf-32-le", "UTF-32LE BOM present")
    if head.startswith(b"\x00\x00\xfe\xff"):
        return ("text", "utf-32-be", "UTF-32BE BOM present")
    if head.startswith(b"\xff\xfe"):
        return ("text", "utf-16-le", "UTF-16LE BOM present")
    if head.startswith(b"\xfe\xff"):
        return ("text", "utf-16-be", "UTF-16BE BOM present")
    if b"\x00" in head:
        return ("binary", None, "NUL byte in sampled head")
    control = sum(1 for byte in head if byte in TEXT_CONTROL)
    if control / max(len(head), 1) > 0.02:
        return ("binary", None, "more than 2% control bytes in sampled head")
    try:
        head.decode("utf-8")
        return ("text", "utf-8", "sampled head decodes as UTF-8")
    except UnicodeDecodeError:
        pass
    try:
        head.decode("utf-8", "strict")
    except UnicodeDecodeError:
        # A truncated multibyte sequence at the sample boundary is not proof of
        # binary content; retry ignoring the tail.
        try:
            head[:-4].decode("utf-8")
            return ("text", "utf-8", "sampled head decodes as UTF-8 (boundary-truncated)")
        except UnicodeDecodeError:
            pass
    try:
        head.decode("cp1252")
        return ("text", "unknown-8bit", "decodes as a single-byte encoding; exact encoding unconfirmed")
    except UnicodeDecodeError:
        return ("unknown", None, "no confident text or binary determination")


def count_lines(path: Path):
    """Stream a line count without loading the file into memory."""
    total = 0
    last_byte = b""
    try:
        with open(path, "rb") as fh:
            while True:
                block = fh.read(1 << 20)
                if not block:
                    break
                total += block.count(b"\n")
                last_byte = block[-1:]
    except OSError:
        return None
    if last_byte and last_byte != b"\n":
        total += 1
    return total


def detect_eol(head: bytes):
    crlf = head.count(b"\r\n")
    lf = head.count(b"\n") - crlf
    cr = head.count(b"\r") - crlf
    kinds = []
    if lf > 0:
        kinds.append("LF")
    if crlf > 0:
        kinds.append("CRLF")
    if cr > 0:
        kinds.append("CR")
    if not kinds:
        return "none"
    return "+".join(kinds)


# --------------------------------------------------------------------------
# .gitattributes (evidence rule E1)
# --------------------------------------------------------------------------

def load_gitattributes(repo_root: Path):
    rules = []
    for attr_path in sorted(repo_root.rglob(".gitattributes"), key=lambda p: str(p)):
        if not attr_path.is_file():
            continue
        base = norm_rel(repo_root, attr_path.parent)
        base = "" if base == "." else base + "/"
        try:
            text = attr_path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for raw in text.splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            parts = line.split()
            pattern = parts[0]
            attrs = {}
            for token in parts[1:]:
                if token.startswith("linguist-"):
                    if "=" in token:
                        key, value = token.split("=", 1)
                        attrs[key] = value
                    elif token.startswith("-"):
                        attrs[token[1:]] = False
                    else:
                        attrs[token] = True
            if attrs:
                rules.append((base, pattern, attrs, norm_rel(repo_root, attr_path)))
    return rules


def match_gitattributes(rules, rel_path: str):
    result = {}
    source = None
    for base, pattern, attrs, origin in rules:
        if base and not rel_path.startswith(base):
            continue
        subject = rel_path[len(base):] if base else rel_path
        candidates = [subject, subject.rsplit("/", 1)[-1]]
        if any(fnmatch.fnmatch(c, pattern) for c in candidates):
            result.update(attrs)
            source = origin
    return (result, source)


# --------------------------------------------------------------------------
# Git supplementary metadata
# --------------------------------------------------------------------------

def collect_git_state(repo_root: Path):
    state = {
        "vcs": "none",
        "git_available": False,
        "is_work_tree": False,
        "notes": [],
    }
    code, out, err = run(["git", "--version"], cwd=repo_root, timeout=30)
    if code != 0:
        state["notes"].append("git executable unavailable: " + err.strip())
        if (repo_root / ".git").exists():
            state["vcs"] = "git"
            state["notes"].append(".git exists but git could not be executed")
        for name, label in ((".hg", "mercurial"), (".svn", "subversion"), (".bzr", "bazaar")):
            if (repo_root / name).exists():
                state["vcs"] = label
        return state
    state["git_available"] = True
    state["git_version"] = out.strip()

    code, out, _ = run(["git", "rev-parse", "--is-inside-work-tree"], cwd=repo_root, timeout=30)
    if code != 0 or out.strip() != "true":
        for name, label in ((".hg", "mercurial"), (".svn", "subversion"), (".bzr", "bazaar")):
            if (repo_root / name).exists():
                state["vcs"] = label
        state["notes"].append("REPO_ROOT is not inside a Git work tree")
        return state

    state["vcs"] = "git"
    state["is_work_tree"] = True

    def git(args, timeout=180):
        return run(["git"] + args, cwd=repo_root, timeout=timeout)

    code, out, _ = git(["rev-parse", "--show-toplevel"])
    state["toplevel"] = out.strip() if code == 0 else None
    nested = False
    if state["toplevel"]:
        try:
            nested = Path(state["toplevel"]).resolve() != repo_root.resolve()
        except OSError:
            nested = False
    state["repo_root_is_git_toplevel"] = not nested
    if nested:
        state["notes"].append(
            "REPO_ROOT is a subdirectory of a larger Git work tree; Git metadata "
            "describes the enclosing repository"
        )

    code, out, _ = git(["rev-parse", "HEAD"])
    state["head_revision"] = out.strip() if code == 0 else None
    if code != 0:
        state["notes"].append("no HEAD revision (unborn branch or empty repository)")

    code, out, _ = git(["rev-parse", "--abbrev-ref", "HEAD"])
    state["head_ref"] = out.strip() if code == 0 else None

    code, out, _ = git(["status", "--porcelain=v1", "--untracked-files=all"])
    if code == 0:
        entries = [line for line in out.splitlines() if line.strip()]
        state["dirty"] = bool(entries)
        state["porcelain_entry_count"] = len(entries)
        state["porcelain_entries"] = sorted(entries)[:2000]
        if len(entries) > 2000:
            state["notes"].append("porcelain entry list truncated to 2000 entries")
    else:
        state["dirty"] = None
        state["notes"].append("git status failed")

    code, out, _ = git(["submodule", "status", "--recursive"])
    state["submodules"] = sorted(line.strip() for line in out.splitlines() if line.strip()) if code == 0 else []

    code, out, _ = git(["remote", "-v"])
    state["remotes"] = sorted(line.strip() for line in out.splitlines() if line.strip()) if code == 0 else []

    code, out, _ = git(["log", "-1", "--format=%H%n%cI%n%an"])
    if code == 0 and out.strip():
        lines = out.strip().split("\n")
        state["head_commit_evidence"] = {
            "revision": lines[0] if len(lines) > 0 else None,
            "committer_date_repository_evidence": lines[1] if len(lines) > 1 else None,
            "author_name_repository_evidence": lines[2] if len(lines) > 2 else None,
        }

    code, out, _ = git(["stash", "list"])
    state["stash_entries"] = len([line for line in out.splitlines() if line.strip()]) if code == 0 else None

    return state


def collect_git_file_status(repo_root: Path, git_state: dict):
    """Return {rel_path: status_dict} using read-only Git plumbing."""
    if not git_state.get("is_work_tree"):
        return {}
    status = {}

    code, out, _ = run(["git", "ls-files", "-z"], cwd=repo_root, timeout=300)
    if code == 0:
        for item in out.split("\0"):
            if item:
                status.setdefault(item, {})["tracked"] = True

    code, out, _ = run(
        ["git", "status", "--porcelain=v1", "-z", "--untracked-files=all", "--ignored=matching"],
        cwd=repo_root,
        timeout=300,
    )
    if code == 0:
        tokens = [tok for tok in out.split("\0") if tok]
        index = 0
        while index < len(tokens):
            token = tokens[index]
            if len(token) < 4:
                index += 1
                continue
            code_pair, path = token[:2], token[3:]
            record = status.setdefault(path, {})
            record["porcelain"] = code_pair
            if code_pair == "!!":
                record["ignored"] = True
            elif code_pair == "??":
                record["untracked"] = True
            else:
                record["modified_or_staged"] = True
            if code_pair.startswith("R") or code_pair.startswith("C"):
                index += 1  # rename/copy source follows
            index += 1

    for line in git_state.get("submodules", []):
        parts = line.split()
        if len(parts) >= 2:
            status.setdefault(parts[1], {})["submodule"] = True

    return status


# --------------------------------------------------------------------------
# traversal
# --------------------------------------------------------------------------

def entry_type(st) -> str:
    mode = st.st_mode
    if stat.S_ISDIR(mode):
        return "directory"
    if stat.S_ISREG(mode):
        return "regular-file"
    if stat.S_ISLNK(mode):
        return "symlink"
    if stat.S_ISFIFO(mode):
        return "fifo"
    if stat.S_ISSOCK(mode):
        return "socket"
    if stat.S_ISBLK(mode):
        return "block-device"
    if stat.S_ISCHR(mode):
        return "character-device"
    return "unknown"


def walk(repo_root: Path, errors: list):
    """Yield (rel_path, abs_path, lstat_result, is_symlink) in bytewise order.

    Directories are never traversed through a symlink, and no directory is
    traversed twice through an alias.
    """
    root_real = repo_root.resolve()
    seen_dirs = {str(root_real)}
    stack = [(repo_root, "")]
    while stack:
        current, rel = stack.pop()
        try:
            entries = list(os.scandir(current))
        except OSError as exc:
            errors.append({
                "path": rel or ".",
                "stage": "scandir",
                "error": "{}: {}".format(type(exc).__name__, exc),
            })
            continue
        items = []
        for entry in entries:
            child_rel = (rel + "/" + entry.name) if rel else entry.name
            items.append((child_rel, entry))
        items.sort(key=lambda pair: sort_key(pair[0]), reverse=True)
        for child_rel, entry in items:
            abs_path = Path(entry.path)
            try:
                st = entry.stat(follow_symlinks=False)
            except OSError as exc:
                errors.append({
                    "path": child_rel,
                    "stage": "lstat",
                    "error": "{}: {}".format(type(exc).__name__, exc),
                })
                continue
            is_link = stat.S_ISLNK(st.st_mode)
            yield (child_rel, abs_path, st, is_link)
            if stat.S_ISDIR(st.st_mode) and not is_link:
                try:
                    real = str(abs_path.resolve())
                except OSError:
                    real = str(abs_path)
                if real in seen_dirs:
                    errors.append({
                        "path": child_rel,
                        "stage": "traverse",
                        "error": "directory alias already traversed; not descending again",
                    })
                    continue
                seen_dirs.add(real)
                stack.append((abs_path, child_rel))


def build_record(repo_root: Path, rel: str, abs_path: Path, st, is_link: bool,
                 attr_rules, git_status, errors: list):
    name = rel.rsplit("/", 1)[-1]
    kind = entry_type(st)
    doc_path, remapped = safe_doc_path(rel)
    record = {
        "path": rel,
        "basename": name,
        "entry_type": kind,
        "size_bytes": int(st.st_size),
        "mode_octal": oct(stat.S_IMODE(st.st_mode)),
        "nlink": int(getattr(st, "st_nlink", 1)),
        "doc_path": doc_path,
    }
    if remapped:
        record["doc_path_remapped"] = True
        record["doc_path_remap_reason"] = (
            "the repository path contains a component the host filesystem cannot "
            "represent verbatim; see files/_PATH_MAP.json"
        )

    if getattr(st, "st_ino", 0) and record["nlink"] > 1:
        record["hardlink_group"] = "{}:{}".format(getattr(st, "st_dev", 0), st.st_ino)

    if is_link:
        try:
            target = os.readlink(str(abs_path))
        except OSError as exc:
            target = None
            errors.append({"path": rel, "stage": "readlink",
                           "error": "{}: {}".format(type(exc).__name__, exc)})
        record["symlink_target_raw"] = target
        try:
            resolved = abs_path.resolve()
            record["symlink_target_resolved"] = str(resolved)
            inside = False
            try:
                resolved.relative_to(repo_root.resolve())
                inside = True
            except ValueError:
                inside = False
            record["symlink_target_inside_repo"] = inside
            if inside:
                record["symlink_target_repo_relative"] = norm_rel(repo_root, resolved)
            else:
                record["content_analysis"] = "skipped: symlink target is outside REPO_ROOT"
            record["symlink_dangling"] = not resolved.exists()
        except OSError as exc:
            record["symlink_target_resolved"] = None
            errors.append({"path": rel, "stage": "resolve-symlink",
                           "error": "{}: {}".format(type(exc).__name__, exc)})

    attrs, attr_source = match_gitattributes(attr_rules, rel)
    if attrs:
        record["gitattributes"] = attrs
        record["gitattributes_source"] = attr_source

    if git_status:
        gs = git_status.get(rel)
        if gs:
            record["git"] = gs
        else:
            record["git"] = {"tracked": False, "untracked_or_unreported": True}

    ext, ext_lang = classify.classify_extension(name)
    record["extension"] = ext
    special = classify.SPECIAL_NAMES.get(name.lower())

    head = b""
    text_head = ""
    if kind == "regular-file":
        try:
            with open(abs_path, "rb") as fh:
                head = fh.read(HEAD_BYTES)
        except OSError as exc:
            record["read_error"] = "{}: {}".format(type(exc).__name__, exc)
            errors.append({"path": rel, "stage": "read-head",
                           "error": "{}: {}".format(type(exc).__name__, exc)})

        try:
            record["sha256"] = sha256_file(abs_path)
        except OSError as exc:
            record["sha256"] = None
            record["hash_error"] = "{}: {}".format(type(exc).__name__, exc)
            errors.append({"path": rel, "stage": "sha256",
                           "error": "{}: {}".format(type(exc).__name__, exc)})

        kind_text, encoding, text_evidence = sniff_text(head)
        record["content_kind"] = kind_text
        record["encoding"] = encoding
        record["content_kind_evidence"] = text_evidence
        if kind_text == "text":
            record["eol"] = detect_eol(head)
            record["line_count"] = count_lines(abs_path)
            try:
                text_head = head.decode(encoding or "utf-8", "replace")
            except (LookupError, UnicodeDecodeError):
                text_head = head.decode("utf-8", "replace")

        magic = classify.detect_magic(head)
        if magic:
            record["magic_format"] = magic[0]
            record["mime_guess"] = magic[1]
            record["magic_prefix_hex"] = magic[2]

    # -- language classification, strongest evidence first ------------------
    candidates = []
    linguist_lang = attrs.get("linguist-language") if attrs else None
    if linguist_lang:
        candidates.append((linguist_lang, "E1 .gitattributes linguist-language"))
    if special:
        candidates.append((special[0], "E2 special filename"))
    modeline = classify.detect_modeline(text_head[:2048]) if text_head else None
    if modeline:
        candidates.append((modeline, "E3 editor modeline"))
    shebang = classify.detect_shebang(head) if head else None
    if shebang:
        record["shebang"] = shebang[0]
        if shebang[1]:
            candidates.append((shebang[1], "E4 shebang interpreter"))
    if ext_lang:
        candidates.append((ext_lang, "E5 extension '." + ext + "'"))
    if record.get("magic_format"):
        candidates.append((record["magic_format"], "E6 magic number"))
    structured = classify.detect_structured_root(text_head) if text_head else None
    if structured:
        candidates.append((structured, "E7 structured-language header"))
    if not candidates and kind == "regular-file":
        if record.get("content_kind") == "text":
            candidates.append(("Plain text (unclassified)", "E10 content heuristic"))
        elif record.get("content_kind") == "binary":
            candidates.append(("Binary (unclassified)", "E10 content heuristic"))
        elif record.get("content_kind") == "empty":
            candidates.append(("Empty file", "E10 zero-length file"))

    if candidates:
        record["classification_primary"] = candidates[0][0]
        record["classification_evidence"] = candidates[0][1]
        alternatives = []
        for label, evidence in candidates[1:]:
            if label != record["classification_primary"]:
                alternatives.append({"label": label, "evidence": evidence})
        if alternatives:
            record["classification_alternatives"] = alternatives
            record["classification_conflict"] = True
        record["classification_confidence"] = (
            "high" if candidates[0][1].startswith(("E1", "E2", "E4", "E6"))
            else "medium" if candidates[0][1].startswith(("E3", "E5", "E7"))
            else "low"
        )

    # -- role ---------------------------------------------------------------
    roles = classify.role_hints(rel, name, ext)
    if roles[0][0] == "unknown" and classify.is_source_language(record.get("classification_primary")):
        roles.insert(0, ("first-party-source",
                         "classified as a source language with no test, vendor, "
                         "generated, build or asset path signal"))
    record["role_hint"] = roles[0][0]
    record["role_evidence"] = roles[0][1]
    if len(roles) > 1:
        record["role_alternatives"] = [{"role": r, "evidence": e} for r, e in roles[1:]]

    # -- origin -------------------------------------------------------------
    if attrs and attrs.get("linguist-vendored") is True:
        record["origin_hint"] = "vendored"
        record["origin_evidence"] = "E1 .gitattributes linguist-vendored"
    elif attrs and attrs.get("linguist-generated") is True:
        record["origin_hint"] = "generated"
        record["origin_evidence"] = "E1 .gitattributes linguist-generated"
    else:
        origin, evidence = classify.origin_hints(rel, name, text_head)
        record["origin_hint"] = origin
        record["origin_evidence"] = evidence

    # -- archive member table (ARCHIVE RULE) --------------------------------
    if kind == "regular-file" and record.get("content_kind") != "text":
        akind = archives.archive_kind(rel, record.get("magic_format"))
        if akind:
            record["archive_kind"] = akind
            try:
                report = archives.inspect(abs_path, akind, rel)
            except Exception as exc:  # a parser crash must not stop the inventory
                report = {"path": rel, "archive_kind": akind, "status": "parser-crash",
                          "error": "{}: {}".format(type(exc).__name__, exc),
                          "extracted": False}
                errors.append({"path": rel, "stage": "archive-inspect",
                               "error": report["error"]})
            record["archive"] = {
                "status": report.get("status"),
                "members": report.get("counts", {}).get("members"),
                "findings": [f["kind"] for f in report.get("findings", [])],
                "detail": "inventory/archives.json",
            }
            ARCHIVE_REPORTS.append(report)

    # -- sensitivity --------------------------------------------------------
    sensitive = any(p.search(rel) for p in classify.SENSITIVE_NAME_PATTERNS)
    record["sensitivity_hint"] = "secret-candidate" if sensitive else "normal"
    if sensitive:
        record["handling"] = "summarize and redact; never reproduce values in the packet"

    return record


# --------------------------------------------------------------------------
# aggregation
# --------------------------------------------------------------------------

def histogram(rows, key):
    counts = {}
    for row in rows:
        value = row.get(key) or "unclassified"
        bucket = counts.setdefault(value, {"files": 0, "bytes": 0, "lines": 0})
        bucket["files"] += 1
        bucket["bytes"] += int(row.get("size_bytes") or 0)
        bucket["lines"] += int(row.get("line_count") or 0)
    return dict(sorted(counts.items(), key=lambda item: (-item[1]["files"], item[0])))


def render_tree(dir_rows, file_rows, limit: int = 20000):
    lines = ["."]
    combined = []
    for row in dir_rows:
        combined.append((row["path"], True, row))
    for row in file_rows:
        combined.append((row["path"], False, row))
    combined.sort(key=lambda item: sort_key(item[0]))
    truncated = False
    for index, (path, is_dir, row) in enumerate(combined):
        if index >= limit:
            truncated = True
            break
        depth = path.count("/")
        name = path.rsplit("/", 1)[-1]
        prefix = "  " * (depth + 1)
        suffix = "/" if is_dir else ""
        if row.get("entry_type") == "symlink":
            suffix = " -> " + str(row.get("symlink_target_raw"))
        lines.append(prefix + name + suffix)
    if truncated:
        lines.append("... tree listing truncated at {} entries; ".format(limit)
                     + "inventory/files.jsonl and inventory/directories.jsonl are complete")
    return "\n".join(lines)


def run_inventory(state, tree_limit: int = 20000):
    repo_root = state.repo_root
    packet = state.packet_root
    inv_dir = packet / "inventory"
    errors = []

    del ARCHIVE_REPORTS[:]
    attr_rules = load_gitattributes(repo_root)
    git_state = collect_git_state(repo_root)
    git_status = collect_git_file_status(repo_root, git_state)

    dir_rows = []
    file_rows = []
    for rel, abs_path, st, is_link in walk(repo_root, errors):
        record = build_record(repo_root, rel, abs_path, st, is_link,
                              attr_rules, git_status, errors)
        if record["entry_type"] == "directory":
            record.pop("doc_path", None)
            dir_rows.append(record)
        else:
            file_rows.append(record)

    dir_rows.sort(key=lambda row: sort_key(row["path"]))
    file_rows.sort(key=lambda row: sort_key(row["path"]))

    write_jsonl(inv_dir / "files.jsonl", file_rows)
    write_jsonl(inv_dir / "directories.jsonl", dir_rows)
    write_text(inv_dir / "tree.txt", render_tree(dir_rows, file_rows, tree_limit))

    hash_lines = []
    for row in file_rows:
        if row.get("sha256"):
            hash_lines.append(row["sha256"] + "  " + row["path"])
    write_text(inv_dir / "source-hashes.sha256", "\n".join(hash_lines))

    regular = [row for row in file_rows if row["entry_type"] == "regular-file"]
    write_json(inv_dir / "languages.json", {
        "note": "First-pass classification hints. Evidence rules E1-E7/E10 only; "
                "native-parser confirmation happens in the static-analysis phase.",
        "by_primary_classification": histogram(regular, "classification_primary"),
    })
    write_json(inv_dir / "file-types.json", {
        "by_extension": histogram(regular, "extension"),
        "by_magic_format": histogram([r for r in regular if r.get("magic_format")], "magic_format"),
        "by_content_kind": histogram(regular, "content_kind"),
    })
    write_json(inv_dir / "roles.json", {
        "note": "Role hints from filename and path evidence; the agent confirms or "
                "overrides these during classification review.",
        "by_role": histogram(regular, "role_hint"),
        "by_origin": histogram(regular, "origin_hint"),
    })
    write_json(inv_dir / "vcs-state.json", git_state)

    reports = sorted(ARCHIVE_REPORTS, key=lambda r: sort_key(r["path"]))
    write_json(inv_dir / "archives.json", {
        "note": "Archive member tables read from archive metadata only. No member was "
                "extracted, decompressed to disk, or opened as a nested archive. "
                "Members are embedded artifacts of their containing archive; they are "
                "not repository files and receive no per-file document.",
        "archives_found": len(reports),
        "archives_with_findings": sum(1 for r in reports if r.get("findings")),
        "by_status": {s: sum(1 for r in reports if r.get("status") == s)
                      for s in sorted({r.get("status") for r in reports})} if reports else {},
        "archives": reports,
    })

    remapped = [{"repository_path": r["path"], "doc_path": r["doc_path"]}
                for r in file_rows if r.get("doc_path_remapped")]
    write_json(packet / "files" / "_PATH_MAP.json", {
        "note": "Per-file documents normally live at files/<repository-relative-path>.md. "
                "Entries listed here could not use that name verbatim on the host "
                "filesystem and were escaped; the mapping is injective.",
        "remapped_count": len(remapped),
        "remapped": sorted(remapped, key=lambda item: sort_key(item["repository_path"])),
    })

    write_json(inv_dir / "per-file-documents-required.json", {
        "note": "One document per physical regular file is mandatory. Validation "
                "compares this list against the files/ directory.",
        "count": len(regular),
        "documents": [{"path": r["path"], "doc_path": r["doc_path"],
                       "role_hint": r.get("role_hint"), "origin_hint": r.get("origin_hint")}
                      for r in regular],
    })

    by_type = {}
    for row in file_rows + dir_rows:
        by_type[row["entry_type"]] = by_type.get(row["entry_type"], 0) + 1

    summary = {
        "counts": {
            "entries_total": len(file_rows) + len(dir_rows),
            "directories": len(dir_rows),
            "non_directory_entries": len(file_rows),
            "regular_files": len(regular),
            "symlinks": sum(1 for r in file_rows if r["entry_type"] == "symlink"),
            "special_entries": sum(1 for r in file_rows
                                   if r["entry_type"] in ("fifo", "socket", "block-device",
                                                          "character-device", "unknown")),
            "hardlinked_files": sum(1 for r in regular if r.get("hardlink_group")),
            "total_bytes": sum(int(r.get("size_bytes") or 0) for r in regular),
            "total_text_lines": sum(int(r.get("line_count") or 0) for r in regular),
            "hashed_files": len(hash_lines),
            "traversal_errors": len(errors),
        },
        "origin_breakdown": {k: v["files"] for k, v in histogram(regular, "origin_hint").items()},
        "role_breakdown": {k: v["files"] for k, v in histogram(regular, "role_hint").items()},
        "entry_type_breakdown": dict(sorted(by_type.items())),
        "secret_candidates": sorted(r["path"] for r in regular
                                    if r.get("sensitivity_hint") == "secret-candidate"),
        "classification_conflicts": sum(1 for r in regular if r.get("classification_conflict")),
        "per_file_documents_required": len(regular),
        "traversal_rules": [
            "filesystem traversal defines the inventory; Git ignore rules do not",
            "directories are never traversed through a symlink",
            "no directory alias is traversed twice",
            "symlink targets outside REPO_ROOT are recorded but never read",
        ],
        "errors": errors,
    }
    write_json(inv_dir / "inventory-summary.json", summary)
    if errors:
        write_json(inv_dir / "traversal-errors.json", errors)

    return summary
