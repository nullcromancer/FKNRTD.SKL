"""Repository integrity verification and pre-packaging validation."""

from __future__ import annotations

import json
import re
from pathlib import Path

from . import inventory as inv
from . import scan
from .common import (
    REQUIRED_TOP_LEVEL_DOCS,
    read_json,
    read_jsonl,
    sha256_file,
    sort_key,
    write_json,
)

REQUIRED_PACKET_ARTIFACTS = [
    "inventory/files.jsonl",
    "inventory/directories.jsonl",
    "inventory/languages.json",
    "inventory/file-types.json",
    "inventory/roles.json",
    "inventory/tree.txt",
    "inventory/source-hashes.sha256",
    "inventory/vcs-state.json",
    "graphs/architecture.mmd",
    "graphs/modules.mmd",
    "graphs/runtime.mmd",
    "graphs/data-flow.mmd",
    "graphs/build-test.mmd",
    "graphs/dependencies.mmd",
    "graphs/dependencies.json",
    "graphs/symbol-graph.json",
    "graphs/call-graph.json",
    "graphs/data-flow.json",
    "dependencies/dependency-graph.json",
    "dependencies/packages.json",
    "dependencies/cyclonedx.json",
    "dependencies/spdx.json",
    "dependencies/vulnerabilities.json",
    "dependencies/licenses.json",
    "tests/TEST_INVENTORY.md",
    "tests/results.json",
    "tests/failures.md",
    "tests/coverage-summary.json",
    "security/findings.sarif",
    "security/findings.json",
    "security/vulnerabilities.json",
    "security/secrets-redacted.json",
    "security/SECURITY_NOTES.md",
    "static-analysis/symbols.jsonl",
    "static-analysis/types.jsonl",
    "static-analysis/imports.jsonl",
    "static-analysis/diagnostics.jsonl",
    "sources/EXTERNAL_SOURCES.md",
    "sources/external-sources.json",
]

REQUIRED_FILE_DOC_FIELDS = [
    "Path", "SHA-256", "Size", "Filesystem type", "File format", "Role",
    "Module", "Purpose", "Evidence", "Limitations",
]

REQUIRED_MODULE_DOC_FIELDS = [
    "Purpose", "Boundaries", "Public API", "Internal dependencies",
    "External dependencies", "Entry points", "Configuration", "Tests",
    "Evidence",
]

MERMAID_KEYWORDS = (
    "graph", "flowchart", "sequenceDiagram", "classDiagram", "stateDiagram",
    "stateDiagram-v2", "erDiagram", "journey", "gantt", "pie", "mindmap",
    "timeline", "gitGraph", "C4Context", "C4Container", "C4Component",
    "quadrantChart", "requirementDiagram", "sankey-beta", "block-beta",
    "architecture-beta", "xychart-beta",
)

PENDING_MARKER = "<!-- odin:pending -->"
PERCENT_KEYS = re.compile(r"(?i)(percent|pct|coverage_rate|line_rate|branch_rate)")
MD_LINK = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")


# --------------------------------------------------------------------------
# integrity
# --------------------------------------------------------------------------

def verify_integrity(state):
    """Recompute repository hashes and VCS state; compare against the baseline."""
    repo_root = state.repo_root
    packet = state.packet_root
    baseline_rows = read_jsonl(packet / "inventory" / "files.jsonl")
    if not baseline_rows:
        result = {
            "status": "unverifiable",
            "reason": "inventory/files.jsonl is missing or empty; run `odin.py inventory` first",
        }
        write_json(packet / "inventory" / "integrity-verification.json", result)
        return result

    baseline = {}
    for row in baseline_rows:
        if row.get("entry_type") == "regular-file":
            baseline[row["path"]] = row

    errors = []
    current = {}
    for rel, abs_path, st, is_link in inv.walk(repo_root, errors):
        if is_link:
            continue
        try:
            import stat as _stat
            if not _stat.S_ISREG(st.st_mode):
                continue
        except Exception:  # pragma: no cover
            continue
        current[rel] = st

    added, removed, modified, size_changed, unreadable = [], [], [], [], []

    for rel in sorted(set(current) - set(baseline), key=sort_key):
        added.append(rel)
    for rel in sorted(set(baseline) - set(current), key=sort_key):
        removed.append(rel)

    for rel in sorted(set(baseline) & set(current), key=sort_key):
        row = baseline[rel]
        st = current[rel]
        if row.get("sha256") is None:
            continue
        if int(st.st_size) != int(row.get("size_bytes") or -1):
            size_changed.append(rel)
        try:
            digest = sha256_file(repo_root / rel)
        except OSError as exc:
            unreadable.append({"path": rel, "error": "{}: {}".format(type(exc).__name__, exc)})
            continue
        if digest != row["sha256"]:
            modified.append({
                "path": rel,
                "baseline_sha256": row["sha256"],
                "current_sha256": digest,
            })

    baseline_vcs = read_json(packet / "inventory" / "vcs-state.json", {}) or {}
    current_vcs = inv.collect_git_state(repo_root)
    vcs_diff = {}
    for key in ("vcs", "head_revision", "head_ref", "dirty", "porcelain_entry_count",
                "submodules", "stash_entries"):
        if baseline_vcs.get(key) != current_vcs.get(key):
            vcs_diff[key] = {"baseline": baseline_vcs.get(key), "current": current_vcs.get(key)}

    mutated = bool(added or removed or modified or size_changed or vcs_diff)
    result = {
        "status": "FAIL" if mutated else "PASS",
        "repository_unchanged": not mutated,
        "severity": "critical-process-failure" if mutated else "none",
        "counts": {
            "baseline_regular_files": len(baseline),
            "current_regular_files": len(current),
            "added": len(added),
            "removed": len(removed),
            "content_modified": len(modified),
            "size_changed": len(size_changed),
            "unreadable_now": len(unreadable),
            "traversal_errors": len(errors),
        },
        "added": added[:1000],
        "removed": removed[:1000],
        "content_modified": modified[:1000],
        "size_changed": size_changed[:1000],
        "unreadable_now": unreadable,
        "vcs_state_differences": vcs_diff,
        "interpretation": (
            "Any entry above is a deviation from the pre-analysis baseline. odin must "
            "not modify REPO_ROOT; report a non-empty result prominently in ERRORS.md "
            "and EXECUTIVE_SUMMARY.md, and identify whether odin or an external process "
            "caused it."
            if mutated else
            "Every baseline file is present with an identical SHA-256 and the VCS state "
            "is unchanged."
        ),
    }
    write_json(packet / "inventory" / "integrity-verification.json", result)
    return result


# --------------------------------------------------------------------------
# validation
# --------------------------------------------------------------------------

def _check_json_parses(packet: Path):
    problems = []
    checked = 0
    for path in sorted(packet.rglob("*"), key=lambda p: str(p)):
        if not path.is_file():
            continue
        suffix = path.suffix.lower()
        if suffix not in (".json", ".jsonl", ".sarif"):
            continue
        rel = path.relative_to(packet).as_posix()
        checked += 1
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append({"path": rel, "error": "unreadable: {}".format(exc)})
            continue
        try:
            if suffix == ".jsonl":
                for lineno, line in enumerate(text.splitlines(), start=1):
                    if line.strip():
                        json.loads(line)
            else:
                json.loads(text)
        except json.JSONDecodeError as exc:
            problems.append({"path": rel, "error": "invalid JSON: {}".format(exc)})
    return checked, problems


def _check_mermaid(packet: Path):
    problems = []
    checked = 0
    for path in sorted((packet / "graphs").rglob("*.mmd"), key=lambda p: str(p)):
        rel = path.relative_to(packet).as_posix()
        checked += 1
        try:
            text = path.read_text(encoding="utf-8")
        except OSError as exc:
            problems.append({"path": rel, "error": "unreadable: {}".format(exc)})
            continue
        body = [line for line in text.splitlines()
                if line.strip() and not line.strip().startswith("%%")]
        if not body:
            problems.append({"path": rel, "error": "diagram file has no content"})
            continue
        first = body[0].strip()
        if first.startswith("---"):
            body = body[1:]
            first = body[0].strip() if body else ""
        if not first.startswith(MERMAID_KEYWORDS):
            problems.append({"path": rel,
                             "error": "first directive is not a known Mermaid diagram type: "
                                      + first[:80]})
        opens = text.count("(") + text.count("[") + text.count("{")
        closes = text.count(")") + text.count("]") + text.count("}")
        if opens != closes:
            problems.append({"path": rel,
                             "error": "unbalanced brackets ({} opening vs {} closing)".format(opens, closes)})
    return checked, problems


def _check_markdown_links(packet: Path):
    problems = []
    checked = 0
    for path in sorted(packet.rglob("*.md"), key=lambda p: str(p)):
        rel = path.relative_to(packet).as_posix()
        checked += 1
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for target in MD_LINK.findall(text):
            if target.startswith(("http://", "https://", "mailto:", "#", "data:")):
                continue
            clean = target.split("#", 1)[0]
            if not clean:
                continue
            resolved = (path.parent / clean).resolve()
            if not resolved.exists():
                problems.append({"path": rel, "broken_link": target})
    return checked, problems


def _check_per_file_docs(packet: Path):
    rows = read_jsonl(packet / "inventory" / "files.jsonl")
    regular = [r for r in rows if r.get("entry_type") == "regular-file"]
    missing = []
    incomplete = []
    pending = []
    present = 0
    for row in regular:
        doc = packet / row["doc_path"]
        if not doc.is_file():
            missing.append({"path": row["path"], "expected_doc": row["doc_path"]})
            continue
        present += 1
        try:
            text = doc.read_text(encoding="utf-8", errors="replace")
        except OSError:
            incomplete.append({"doc": row["doc_path"], "missing_fields": ["<unreadable>"]})
            continue
        if PENDING_MARKER in text:
            pending.append(row["doc_path"])
        lowered = text.lower()
        gaps = [field for field in REQUIRED_FILE_DOC_FIELDS if field.lower() not in lowered]
        if gaps:
            incomplete.append({"doc": row["doc_path"], "missing_fields": gaps})

    docs_on_disk = set()
    files_dir = packet / "files"
    if files_dir.is_dir():
        for path in files_dir.rglob("*.md"):
            docs_on_disk.add(path.relative_to(packet).as_posix())
    expected = {row["doc_path"] for row in regular}
    orphans = sorted(docs_on_disk - expected)

    return {
        "regular_files": len(regular),
        "documents_present": present,
        "documents_missing": len(missing),
        "documents_incomplete": len(incomplete),
        "documents_still_stubbed": len(pending),
        "orphan_documents": len(orphans),
        "missing": missing[:500],
        "incomplete": incomplete[:500],
        "still_stubbed": pending[:500],
        "orphans": orphans[:500],
    }


def _check_module_docs(packet: Path):
    registry = read_json(packet / "inventory" / "modules.json")
    modules_dir = packet / "modules"
    docs = sorted(p.relative_to(packet).as_posix() for p in modules_dir.glob("*.md")) \
        if modules_dir.is_dir() else []
    if registry is None:
        return {
            "status": "no-registry",
            "note": "inventory/modules.json is absent; module coverage could not be "
                    "verified mechanically. Write the module registry during architecture "
                    "synthesis.",
            "module_documents_found": len(docs),
        }
    modules = registry.get("modules", registry if isinstance(registry, list) else [])
    missing = []
    incomplete = []
    for module in modules:
        module_id = module.get("id") if isinstance(module, dict) else str(module)
        doc_rel = "modules/" + str(module_id) + ".md"
        doc = packet / doc_rel
        if not doc.is_file():
            missing.append({"module_id": module_id, "expected_doc": doc_rel})
            continue
        text = doc.read_text(encoding="utf-8", errors="replace").lower()
        gaps = [field for field in REQUIRED_MODULE_DOC_FIELDS if field.lower() not in text]
        if gaps:
            incomplete.append({"module_id": module_id, "missing_fields": gaps})
    return {
        "status": "checked",
        "modules_registered": len(modules),
        "module_documents_found": len(docs),
        "documents_missing": len(missing),
        "documents_incomplete": len(incomplete),
        "missing": missing,
        "incomplete": incomplete,
    }


def _check_coverage_claims(packet: Path):
    path = packet / "tests" / "coverage-summary.json"
    data = read_json(path)
    if data is None:
        return {"status": "absent",
                "note": "tests/coverage-summary.json is missing; it must exist and state "
                        "explicitly whether coverage was measured."}
    if "measured" not in data or not isinstance(data.get("measured"), bool):
        return {"status": "invalid",
                "note": "coverage-summary.json must carry a boolean \"measured\" field so "
                        "'not measured' is never confused with zero percent."}
    if data.get("measured") is False:
        offenders = [key for key in _walk_keys(data) if PERCENT_KEYS.search(key)]
        if offenders:
            return {"status": "contradiction",
                    "note": "coverage is declared unmeasured but numeric coverage keys are present",
                    "offending_keys": sorted(set(offenders))}
        return {"status": "ok", "measured": False}
    figures = [(key, value) for key, value in _walk_items(data)
               if PERCENT_KEYS.search(key) and isinstance(value, (int, float))
               and not isinstance(value, bool)]
    if not figures:
        return {"status": "invalid",
                "note": "coverage is declared measured but no numeric coverage figure is present"}
    return {"status": "ok", "measured": True,
            "tool": data.get("tool"), "note": "numeric coverage is permitted because "
                                              "measurement is declared"}


def _walk_keys(obj, prefix=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            yield prefix + str(key)
            yield from _walk_keys(value, prefix + str(key) + ".")
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_keys(item, prefix)


def _walk_items(obj, prefix=""):
    if isinstance(obj, dict):
        for key, value in obj.items():
            path = prefix + str(key)
            yield path, value
            yield from _walk_items(value, path + ".")
    elif isinstance(obj, list):
        for item in obj:
            yield from _walk_items(item, prefix)


def _check_action_manifest(packet: Path):
    data = read_json(packet / "ACTION_MANIFEST.json")
    if data is None:
        return {"status": "missing", "note": "ACTION_MANIFEST.json is mandatory"}
    actions = data.get("actions", [])
    statuses = {}
    missing_fields = []
    required = ["seq", "phase", "action_id", "status", "tool", "command",
                "network", "repo_code_executed"]
    seqs = []
    for action in actions:
        statuses[action.get("status", "<none>")] = statuses.get(action.get("status", "<none>"), 0) + 1
        gaps = [field for field in required if field not in action]
        if gaps:
            missing_fields.append({"action_id": action.get("action_id"), "missing": gaps})
        if isinstance(action.get("seq"), int):
            seqs.append(action["seq"])
    monotonic = seqs == sorted(seqs) and len(set(seqs)) == len(seqs)
    non_success = sum(count for status, count in statuses.items()
                      if status not in ("succeeded", "executed"))
    return {
        "status": "checked",
        "action_count": len(actions),
        "by_status": dict(sorted(statuses.items())),
        "sequence_numbers_unique_and_monotonic": monotonic,
        "actions_missing_required_fields": missing_fields[:200],
        "non_success_actions_recorded": non_success,
        "note": "A manifest with no failed, skipped, unavailable or policy-blocked "
                "entries is suspicious unless the run genuinely had none."
        if non_success == 0 else "",
    }


def validate(state):
    packet = state.packet_root
    problems = []

    missing_docs = [name for name in REQUIRED_TOP_LEVEL_DOCS
                    if not (packet / name).is_file()]
    missing_artifacts = [name for name in REQUIRED_PACKET_ARTIFACTS
                         if not (packet / name).is_file()]

    json_checked, json_problems = _check_json_parses(packet)
    mermaid_checked, mermaid_problems = _check_mermaid(packet)
    links_checked, link_problems = _check_markdown_links(packet)
    file_docs = _check_per_file_docs(packet)
    module_docs = _check_module_docs(packet)
    coverage = _check_coverage_claims(packet)
    manifest = _check_action_manifest(packet)
    leaks = scan.audit_packet_for_leaks(state)
    integrity = read_json(packet / "inventory" / "integrity-verification.json")

    if missing_docs:
        problems.append("missing required top-level documents: " + ", ".join(missing_docs))
    if missing_artifacts:
        problems.append("missing required packet artifacts: " + ", ".join(missing_artifacts))
    if json_problems:
        problems.append("{} JSON/JSONL/SARIF files do not parse".format(len(json_problems)))
    if mermaid_problems:
        problems.append("{} Mermaid diagram problems".format(len(mermaid_problems)))
    if file_docs["documents_missing"]:
        problems.append("{} physical regular files have no per-file document".format(
            file_docs["documents_missing"]))
    if file_docs["documents_still_stubbed"]:
        problems.append("{} per-file documents are still unfilled stubs".format(
            file_docs["documents_still_stubbed"]))
    if module_docs.get("documents_missing"):
        problems.append("{} registered modules have no module document".format(
            module_docs["documents_missing"]))
    if module_docs.get("status") == "no-registry":
        problems.append("inventory/modules.json is absent; module coverage is unverified")
    if coverage["status"] in ("absent", "invalid", "contradiction"):
        problems.append("coverage claim problem: " + coverage["status"])
    if manifest["status"] == "missing":
        problems.append("ACTION_MANIFEST.json is missing")
    elif not manifest.get("sequence_numbers_unique_and_monotonic"):
        problems.append("action manifest sequence numbers are not unique and monotonic")
    if leaks:
        problems.append("{} potential unredacted secret values inside the packet".format(len(leaks)))
    if integrity is None:
        problems.append("repository integrity verification has not been run")
    elif integrity.get("status") != "PASS":
        problems.append("repository integrity verification did not pass: "
                        + str(integrity.get("status")))

    report = {
        "status": "PASS" if not problems else "FAIL",
        "blocking_problems": problems,
        "required_top_level_documents": {
            "expected": REQUIRED_TOP_LEVEL_DOCS,
            "missing": missing_docs,
        },
        "required_packet_artifacts": {
            "expected_count": len(REQUIRED_PACKET_ARTIFACTS),
            "missing": missing_artifacts,
            "note": "A required artifact may be omitted only with an explicit, documented "
                    "reason recorded in ERRORS.md and ASSUMPTIONS_AND_LIMITATIONS.md.",
        },
        "structure": {
            "json_files_checked": json_checked,
            "json_problems": json_problems,
            "mermaid_files_checked": mermaid_checked,
            "mermaid_problems": mermaid_problems,
            "markdown_files_checked": links_checked,
            "broken_internal_links": link_problems[:200],
            "broken_internal_link_count": len(link_problems),
        },
        "per_file_documents": file_docs,
        "module_documents": module_docs,
        "coverage_claims": coverage,
        "action_manifest": manifest,
        "privacy": {
            "packet_secret_scan_hits": len(leaks),
            "hits": leaks[:200],
            "note": "Each hit must be redacted before packaging; finding metadata may stay.",
        },
        "repository_integrity": integrity or {"status": "not-run"},
    }
    write_json(packet / "VALIDATION.json", report)
    return report
