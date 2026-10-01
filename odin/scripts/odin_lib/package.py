"""Deterministic MANIFEST.sha256 generation and findings.zip packaging."""

from __future__ import annotations

import zipfile
from pathlib import Path

from .common import (
    PACKET_DIRNAME,
    REQUIRED_TOP_LEVEL_DOCS,
    ZIP_NAME,
    sha256_bytes,
    sha256_file,
    sort_key,
    write_text,
)

# 1980-01-01T00:00:00Z - the earliest timestamp the ZIP format can represent.
FIXED_DOS_TIME = (1980, 1, 1, 0, 0, 0)
FILE_ATTR = (0o100644 << 16)
DIR_ATTR = (0o040755 << 16) | 0x10

EXCLUDED_FROM_MANIFEST = {"MANIFEST.sha256"}


def packet_files(packet: Path):
    """All regular files in the packet, in bytewise repository-relative order."""
    rows = []
    for path in packet.rglob("*"):
        if path.is_file() and not path.is_symlink():
            rows.append(path.relative_to(packet).as_posix())
    rows.sort(key=sort_key)
    return rows


def build_manifest(state):
    packet = state.packet_root
    lines = []
    count = 0
    for rel in packet_files(packet):
        if rel in EXCLUDED_FROM_MANIFEST:
            continue
        digest = sha256_file(packet / rel)
        lines.append(digest + "  " + rel)
        count += 1
    body = "\n".join(lines)
    write_text(packet / "MANIFEST.sha256", body)
    return {
        "entries": count,
        "manifest_path": PACKET_DIRNAME + "/MANIFEST.sha256",
        "manifest_sha256": sha256_file(packet / "MANIFEST.sha256"),
        "note": "MANIFEST.sha256 covers every packet file except itself, sorted by "
                "normalized path, with two spaces between digest and path.",
    }


def verify_manifest(state):
    packet = state.packet_root
    manifest = packet / "MANIFEST.sha256"
    if not manifest.is_file():
        return {"status": "missing", "note": "MANIFEST.sha256 has not been generated"}
    recorded = {}
    for line in manifest.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, _, rel = line.partition("  ")
        recorded[rel] = digest
    on_disk = {rel for rel in packet_files(packet) if rel not in EXCLUDED_FROM_MANIFEST}
    missing = sorted(set(recorded) - on_disk, key=sort_key)
    unlisted = sorted(on_disk - set(recorded), key=sort_key)
    mismatched = []
    for rel, digest in sorted(recorded.items(), key=lambda item: sort_key(item[0])):
        path = packet / rel
        if path.is_file() and sha256_file(path) != digest:
            mismatched.append(rel)
    ok = not (missing or unlisted or mismatched)
    return {
        "status": "PASS" if ok else "FAIL",
        "entries": len(recorded),
        "listed_but_absent": missing,
        "present_but_unlisted": unlisted,
        "digest_mismatch": mismatched,
    }


def build_zip(state, compresslevel: int = 9):
    """Write ARTIFACT_ROOT/findings.zip deterministically and verify it."""
    packet = state.packet_root
    artifact_root = state.artifact_root
    zip_path = artifact_root / ZIP_NAME

    if not packet.is_dir():
        raise FileNotFoundError("packet directory does not exist: " + str(packet))

    rels = packet_files(packet)
    if not rels:
        raise FileNotFoundError("packet directory is empty: " + str(packet))

    # Stable directory member list so the archive layout does not depend on
    # filesystem enumeration.
    dirs = set()
    for rel in rels:
        parts = rel.split("/")[:-1]
        for index in range(1, len(parts) + 1):
            dirs.add("/".join(parts[:index]))
    dir_members = sorted(dirs, key=sort_key)

    if zip_path.exists():
        zip_path.unlink()

    # One globally sorted member list, directories and files interleaved. A
    # directory entry is a bytewise prefix of its children, so sorting naturally
    # places each directory before its contents.
    members = sorted(
        [(rel + "/", True) for rel in dir_members] + [(rel, False) for rel in rels],
        key=lambda item: sort_key(item[0]))

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED,
                         compresslevel=compresslevel) as archive:
        for rel, is_dir in members:
            info = zipfile.ZipInfo(PACKET_DIRNAME + "/" + rel, date_time=FIXED_DOS_TIME)
            info.create_system = 3  # Unix, so permissions are interpreted consistently
            if is_dir:
                info.external_attr = DIR_ATTR
                archive.writestr(info, b"")
            else:
                info.external_attr = FILE_ATTR
                info.compress_type = zipfile.ZIP_DEFLATED
                archive.writestr(info, (packet / rel).read_bytes())

    result = {
        "zip_path": str(zip_path),
        "zip_sha256": sha256_file(zip_path),
        "zip_size_bytes": zip_path.stat().st_size,
        "member_files": len(rels),
        "member_directories": len(dir_members),
        "determinism": {
            "member_order": "sorted bytewise by normalized path",
            "timestamps": "fixed 1980-01-01T00:00:00Z for every member",
            "permissions": "0644 for files, 0755 for directories, Unix create_system",
            "compression": "deflate level {}".format(compresslevel),
        },
    }

    # -- reopen and verify -------------------------------------------------
    with zipfile.ZipFile(zip_path, "r") as archive:
        bad = archive.testzip()
        names = archive.namelist()
        result["reopen_ok"] = True
        result["corrupt_member"] = bad
        present = set(names)
        result["required_documents_present"] = {
            name: (PACKET_DIRNAME + "/" + name) in present
            for name in REQUIRED_TOP_LEVEL_DOCS
        }
        result["manifest_present"] = (PACKET_DIRNAME + "/MANIFEST.sha256") in present

        # Verify MANIFEST.sha256 against the archived bytes themselves.
        manifest_name = PACKET_DIRNAME + "/MANIFEST.sha256"
        mismatches = []
        checked = 0
        if result["manifest_present"]:
            manifest_text = archive.read(manifest_name).decode("utf-8")
            for line in manifest_text.splitlines():
                if not line.strip():
                    continue
                digest, _, rel = line.partition("  ")
                member = PACKET_DIRNAME + "/" + rel
                if member not in present:
                    mismatches.append({"member": rel, "problem": "listed in manifest but absent from archive"})
                    continue
                if sha256_bytes(archive.read(member)) != digest:
                    mismatches.append({"member": rel, "problem": "archived bytes do not match manifest digest"})
                checked += 1
        result["manifest_members_verified"] = checked
        result["manifest_mismatches"] = mismatches

    result["status"] = (
        "PASS"
        if result["reopen_ok"]
        and not result["corrupt_member"]
        and not result["manifest_mismatches"]
        and all(result["required_documents_present"].values())
        else "FAIL"
    )
    return result
