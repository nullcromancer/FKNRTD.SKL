"""Archive member-table inspection (the protocol's ARCHIVE RULE).

Implements the required behaviour: inventory archive files normally, inspect their
member tables where a safe parser exists, and *never extract*. Nothing here writes
to the filesystem, so path-traversal and symlink-escape classes cannot be realised
by this module — but a traversing or escaping member is still a finding about the
archive, so it is detected and reported.

Protections required by the protocol and implemented here:
  * path traversal           - absolute paths, drive letters, and ".." components
  * symlink escape           - tar link targets that leave the archive root
  * decompression bombs      - total uncompressed size and per-member ratio caps
  * excessive expansion      - member-count cap
  * nested-archive explosion - members that are themselves archives are flagged,
                               never opened
  * malformed archives       - every parser call is guarded
  * parser crashes           - broad exception capture, recorded as an error

Archive members do not become repository files. They are documented as embedded
artifacts of the archive that contains them.
"""

from __future__ import annotations

import posixpath
import tarfile
import zipfile

MAX_MEMBERS = 10000
MAX_TOTAL_UNCOMPRESSED = 2 * 1024 ** 3      # 2 GiB
MAX_MEMBER_RATIO = 200                       # uncompressed / compressed
MAX_TOTAL_RATIO = 100
MAX_LISTED_MEMBERS = 500                     # recorded in full; the rest summarised

ZIP_EXTENSIONS = {
    "zip", "jar", "war", "ear", "whl", "egg", "apk", "aar", "nupkg", "vsix",
    "docx", "xlsx", "pptx", "odt", "ods", "odp", "epub", "crx", "xpi", "ipa",
}
TAR_EXTENSIONS = {"tar", "tgz", "tbz", "tbz2", "txz", "tzst"}
COMPOUND_TAR_SUFFIXES = ("tar.gz", "tar.bz2", "tar.xz", "tar.zst", "tar.lz")
NESTED_ARCHIVE_EXTENSIONS = (
    ZIP_EXTENSIONS | TAR_EXTENSIONS | {"gz", "bz2", "xz", "zst", "7z", "rar", "lz", "lzma"}
)


def archive_kind(rel_path: str, magic_format):
    """Return 'zip', 'tar', or None. Magic wins over extension."""
    lower = rel_path.lower()
    name = lower.rsplit("/", 1)[-1]
    if magic_format:
        if magic_format.startswith("ZIP container"):
            return "zip"
        if magic_format.startswith("tar archive"):
            return "tar"
        # gzip/bzip2/xz may wrap a tar; tarfile detects transparently by suffix.
        if any(name.endswith("." + s) for s in COMPOUND_TAR_SUFFIXES):
            return "tar"
        if magic_format.startswith(("gzip", "bzip2", "xz", "zstandard")):
            return None  # a bare compressed stream has no member table
    if any(name.endswith("." + s) for s in COMPOUND_TAR_SUFFIXES):
        return "tar"
    ext = name.rsplit(".", 1)[-1] if "." in name else ""
    if ext in ZIP_EXTENSIONS:
        return "zip"
    if ext in TAR_EXTENSIONS:
        return "tar"
    return None


def _is_traversing(name: str) -> bool:
    """True when a member name would escape the extraction root."""
    if not name:
        return False
    normalized = name.replace("\\", "/")
    if normalized.startswith("/"):
        return True
    if len(normalized) > 1 and normalized[1] == ":":      # drive-letter absolute
        return True
    parts = normalized.split("/")
    depth = 0
    for part in parts:
        if part in ("", "."):
            continue
        if part == "..":
            depth -= 1
            if depth < 0:
                return True
        else:
            depth += 1
    return False


def _link_escapes(member_name: str, target: str) -> bool:
    """True when a tar link target resolves outside the archive root."""
    if not target:
        return False
    normalized = target.replace("\\", "/")
    if normalized.startswith("/") or (len(normalized) > 1 and normalized[1] == ":"):
        return True
    base = posixpath.dirname(member_name.replace("\\", "/"))
    resolved = posixpath.normpath(posixpath.join(base, normalized))
    return resolved.startswith("../") or resolved == ".."


def _nested(name: str) -> bool:
    lower = name.lower()
    if any(lower.endswith("." + s) for s in COMPOUND_TAR_SUFFIXES):
        return True
    ext = lower.rsplit(".", 1)[-1] if "." in lower else ""
    return ext in NESTED_ARCHIVE_EXTENSIONS


def _finalise(result, members, compressed_total, uncompressed_total):
    result["counts"] = {
        "members": len(members),
        "listed": min(len(members), MAX_LISTED_MEMBERS),
        "directories": sum(1 for m in members if m.get("is_dir")),
        "symlinks": sum(1 for m in members if m.get("link_type")),
        "nested_archives": sum(1 for m in members if m.get("nested_archive")),
        "traversing_paths": sum(1 for m in members if m.get("path_traversal")),
        "escaping_links": sum(1 for m in members if m.get("link_escape")),
    }
    result["sizes"] = {
        "compressed_bytes": compressed_total,
        "uncompressed_bytes": uncompressed_total,
        "overall_ratio": round(uncompressed_total / compressed_total, 2)
        if compressed_total else None,
    }
    result["members"] = members[:MAX_LISTED_MEMBERS]
    if len(members) > MAX_LISTED_MEMBERS:
        result["members_truncated"] = {
            "listed": MAX_LISTED_MEMBERS, "total": len(members),
            "reason": "member listing cap; counts above cover every member"}

    findings = []
    if result["counts"]["traversing_paths"]:
        findings.append({
            "kind": "path-traversal", "severity": "High",
            "detail": "{} member name(s) would escape the extraction root".format(
                result["counts"]["traversing_paths"])})
    if result["counts"]["escaping_links"]:
        findings.append({
            "kind": "symlink-escape", "severity": "High",
            "detail": "{} link target(s) resolve outside the archive root".format(
                result["counts"]["escaping_links"])})
    ratio = result["sizes"]["overall_ratio"]
    if ratio and ratio > MAX_TOTAL_RATIO:
        findings.append({
            "kind": "decompression-bomb-candidate", "severity": "Medium",
            "detail": "overall expansion ratio {} exceeds the {}x threshold".format(
                ratio, MAX_TOTAL_RATIO)})
    bombs = [m for m in members if m.get("ratio_exceeded")]
    if bombs:
        findings.append({
            "kind": "decompression-bomb-candidate", "severity": "Medium",
            "detail": "{} member(s) exceed the {}x per-member expansion threshold".format(
                len(bombs), MAX_MEMBER_RATIO)})
    if result["counts"]["nested_archives"]:
        findings.append({
            "kind": "nested-archive", "severity": "Informational",
            "detail": "{} member(s) are themselves archives; they were flagged and "
                      "not opened".format(result["counts"]["nested_archives"])})
    result["findings"] = findings
    return result


def inspect(path, kind: str, rel_path: str):
    """Read an archive's member table. Never extracts, never writes."""
    result = {
        "path": rel_path,
        "archive_kind": kind,
        "parser": "zipfile" if kind == "zip" else "tarfile",
        "extracted": False,
        "policy": "member table read from archive metadata only; no member was "
                  "extracted, decompressed to disk, or opened as a nested archive",
        "caps": {"max_members": MAX_MEMBERS,
                 "max_total_uncompressed_bytes": MAX_TOTAL_UNCOMPRESSED,
                 "max_member_ratio": MAX_MEMBER_RATIO,
                 "max_listed_members": MAX_LISTED_MEMBERS},
    }
    members = []
    compressed_total = 0
    uncompressed_total = 0

    try:
        if kind == "zip":
            if not zipfile.is_zipfile(str(path)):
                result["status"] = "not-an-archive"
                result["error"] = "no ZIP central directory found despite matching signature"
                return result
            with zipfile.ZipFile(str(path)) as archive:
                for info in archive.infolist():
                    if len(members) >= MAX_MEMBERS:
                        result["cap_hit"] = "member count cap reached at {}".format(MAX_MEMBERS)
                        break
                    size = int(info.file_size)
                    csize = int(info.compress_size)
                    uncompressed_total += size
                    compressed_total += csize
                    ratio = (size / csize) if csize else None
                    members.append({
                        "name": info.filename,
                        "size": size,
                        "compressed_size": csize,
                        "is_dir": info.is_dir(),
                        "compress_type": info.compress_type,
                        "crc": format(info.CRC, "08x"),
                        "external_mode": oct((info.external_attr >> 16) & 0o7777),
                        "path_traversal": _is_traversing(info.filename),
                        "nested_archive": _nested(info.filename),
                        "ratio": round(ratio, 1) if ratio else None,
                        "ratio_exceeded": bool(ratio and ratio > MAX_MEMBER_RATIO),
                    })
                    if uncompressed_total > MAX_TOTAL_UNCOMPRESSED:
                        result["cap_hit"] = "total uncompressed size cap exceeded"
                        break
        else:
            with tarfile.open(str(path), "r:*") as archive:
                for info in archive:
                    if len(members) >= MAX_MEMBERS:
                        result["cap_hit"] = "member count cap reached at {}".format(MAX_MEMBERS)
                        break
                    size = int(info.size)
                    uncompressed_total += size
                    link_type = ("symlink" if info.issym() else
                                 "hardlink" if info.islnk() else None)
                    members.append({
                        "name": info.name,
                        "size": size,
                        "is_dir": info.isdir(),
                        "mode": oct(info.mode),
                        "link_type": link_type,
                        "link_target": info.linkname or None,
                        "device": info.isdev(),
                        "path_traversal": _is_traversing(info.name),
                        "link_escape": bool(link_type and _link_escapes(info.name, info.linkname)),
                        "nested_archive": _nested(info.name),
                    })
                    if uncompressed_total > MAX_TOTAL_UNCOMPRESSED:
                        result["cap_hit"] = "total uncompressed size cap exceeded"
                        break
            compressed_total = int(path.stat().st_size)
    except (zipfile.BadZipFile, tarfile.TarError, EOFError, ValueError) as exc:
        result["status"] = "malformed"
        result["error"] = "{}: {}".format(type(exc).__name__, exc)
        result["partial_members_read"] = len(members)
        return _finalise(result, members, compressed_total, uncompressed_total)
    except (OSError, MemoryError, RecursionError) as exc:
        result["status"] = "parser-error"
        result["error"] = "{}: {}".format(type(exc).__name__, exc)
        result["partial_members_read"] = len(members)
        return _finalise(result, members, compressed_total, uncompressed_total)

    result["status"] = "inspected"
    return _finalise(result, members, compressed_total, uncompressed_total)
