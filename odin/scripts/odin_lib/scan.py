"""Deterministic text scans: unfinished work and redacted secret candidates.

Both scans read only files already present in inventory/files.jsonl and
classified as text. Neither scan ever writes a secret value into the packet:
secret findings carry a category, a location, a length/charset shape and a
non-reversible fingerprint, and nothing else.
"""

from __future__ import annotations

import math
import re
from pathlib import Path

from .common import fingerprint, read_jsonl, write_json

MAX_SCAN_BYTES = 8 * 1024 * 1024
MAX_MATCHES_PER_FILE = 500
CONTEXT_CHARS = 200


# --------------------------------------------------------------------------
# unfinished work
# --------------------------------------------------------------------------

MARKER_RULES = [
    ("TODO", re.compile(r"\bTODO\b")),
    ("FIXME", re.compile(r"\bFIXME\b")),
    ("XXX", re.compile(r"\bXXX\b")),
    ("HACK", re.compile(r"\bHACK\b")),
    ("BUG", re.compile(r"\bBUG\b")),
    ("TEMP", re.compile(r"\b(TEMP|TEMPORARY)\b")),
    ("WIP", re.compile(r"\bWIP\b")),
    ("DEPRECATED", re.compile(r"\bDEPRECATED\b")),
    ("NOT_IMPLEMENTED", re.compile(
        r"\b(not\s+implemented|NotImplementedError|NotImplementedException|"
        r"UnsupportedOperationException|notImplemented)\b", re.I)),
    ("PANIC_STUB", re.compile(
        r"(\btodo!\s*\(|\bunimplemented!\s*\(|\bunreachable!\s*\(|"
        r"panic\(\s*[\"'](TODO|not implemented|unimplemented)|"
        r"raise\s+NotImplementedError|throw\s+new\s+NotImplementedError)", re.I)),
    ("SKIPPED_TEST", re.compile(
        r"(@pytest\.mark\.(skip|xfail)|@unittest\.skip|"
        r"\b(it|test|describe|context)\.(skip|todo)\s*\(|\bxit\s*\(|\bxdescribe\s*\(|"
        r"@Ignore\b|@Disabled\b|#\[ignore\]|t\.Skip\s*\(|\bpending\s*\(|"
        r"\.skip\s*\(\s*['\"]|SkipTest)")),
    ("PLACEHOLDER", re.compile(
        r"\b(CHANGE_?ME|REPLACE_?ME|FILL_?ME|YOUR_[A-Z_]{3,}|"
        r"placeholder|dummy value|lorem ipsum|foo\s*bar\s*baz|"
        r"insert[ _-]?your|<your-[a-z-]+>|xxxx+)\b", re.I)),
    ("STUB", re.compile(r"\b(stub|stubbed|mock implementation|fake implementation|no-?op placeholder)\b", re.I)),
    ("FEATURE_FLAG_INCOMPLETE", re.compile(
        r"\b(feature[_-]?flag|isEnabled|ENABLE_)[A-Za-z0-9_]*\s*[:=]\s*(false|False|0)\b")),
]

OWNER_PATTERN = re.compile(r"(?:TODO|FIXME|XXX|HACK|BUG)\s*[\(\[:]?\s*@?([A-Za-z0-9._-]{2,40})[\)\]]?")
ISSUE_PATTERN = re.compile(r"(?:#(\d{1,7})|([A-Z][A-Z0-9]{1,9}-\d{1,6}))")

TEST_FIXTURE_HINTS = ("fixture", "testdata", "test-data", "__mocks__", "snapshot", "golden")


def classify_marker(row, marker, line_text):
    """Return (category, confidence) for an unfinished-work hit."""
    origin = row.get("origin_hint")
    role = row.get("role_hint")
    path = row.get("path", "")
    if origin == "vcs-metadata":
        return ("vcs-metadata-occurrence", "low")
    if origin == "vendored":
        return ("vendored-occurrence", "low")
    if origin == "generated":
        return ("generated-occurrence", "low")
    if any(hint in path.lower() for hint in TEST_FIXTURE_HINTS):
        return ("test-fixture-occurrence", "low")
    if role == "documentation":
        return ("documentation-occurrence", "medium")
    if marker == "SKIPPED_TEST":
        return ("disabled-or-skipped-test", "high")
    if marker in ("NOT_IMPLEMENTED", "PANIC_STUB"):
        return ("unimplemented-code-path", "high")
    if marker in ("TODO", "FIXME", "BUG", "HACK", "XXX", "WIP", "TEMP"):
        stripped = line_text.strip()
        historical = re.match(r"^\s*(//|#|\*|/\*|<!--)?\s*(NOTE|HISTORY|WAS|PREVIOUSLY)\b", stripped, re.I)
        if historical:
            return ("explanatory-historical-comment", "medium")
        return ("actionable-unfinished-work", "high")
    if marker == "PLACEHOLDER":
        return ("placeholder-value", "medium")
    if marker == "STUB":
        return ("stub-or-mock-implementation", "medium")
    if marker == "DEPRECATED":
        return ("deprecation-notice", "medium")
    return ("unclassified", "low")


def scan_todos(state):
    repo_root = state.repo_root
    packet = state.packet_root
    rows = read_jsonl(packet / "inventory" / "files.jsonl")
    findings = []
    scanned = 0
    skipped = []

    for row in rows:
        if row.get("entry_type") != "regular-file":
            continue
        if row.get("content_kind") != "text":
            continue
        if int(row.get("size_bytes") or 0) > MAX_SCAN_BYTES:
            skipped.append({"path": row["path"], "reason": "text file larger than scan cap",
                            "size_bytes": row.get("size_bytes")})
            continue
        path = repo_root / row["path"]
        try:
            text = path.read_text(encoding=row.get("encoding") or "utf-8", errors="replace")
        except (OSError, LookupError) as exc:
            skipped.append({"path": row["path"], "reason": "{}: {}".format(type(exc).__name__, exc)})
            continue
        scanned += 1
        per_file = 0
        for lineno, line in enumerate(text.splitlines(), start=1):
            if per_file >= MAX_MATCHES_PER_FILE:
                skipped.append({"path": row["path"],
                                "reason": "per-file match cap reached",
                                "cap": MAX_MATCHES_PER_FILE})
                break
            for marker, pattern in MARKER_RULES:
                if not pattern.search(line):
                    continue
                category, confidence = classify_marker(row, marker, line)
                owner_match = OWNER_PATTERN.search(line)
                issue_match = ISSUE_PATTERN.search(line)
                finding = {
                    "id": "UNFIN-{:06d}".format(len(findings) + 1),
                    "marker": marker,
                    "path": row["path"],
                    "line": lineno,
                    "category": category,
                    "confidence": confidence,
                    "context": line.strip()[:CONTEXT_CHARS],
                    "file_role_hint": row.get("role_hint"),
                    "file_origin_hint": row.get("origin_hint"),
                    "language_hint": row.get("classification_primary"),
                }
                if owner_match and not owner_match.group(1).upper() in ("TODO", "FIXME"):
                    finding["owner_tag"] = owner_match.group(1)
                if issue_match:
                    finding["issue_reference"] = issue_match.group(0)
                findings.append(finding)
                per_file += 1
                break

    by_marker = {}
    by_category = {}
    for finding in findings:
        by_marker[finding["marker"]] = by_marker.get(finding["marker"], 0) + 1
        by_category[finding["category"]] = by_category.get(finding["category"], 0) + 1

    result = {
        "summary": {
            "files_scanned": scanned,
            "files_skipped": len(skipped),
            "findings_total": len(findings),
            "actionable": by_category.get("actionable-unfinished-work", 0)
            + by_category.get("unimplemented-code-path", 0)
            + by_category.get("disabled-or-skipped-test", 0),
            "by_marker": dict(sorted(by_marker.items())),
            "by_category": dict(sorted(by_category.items())),
        },
        "scan_limits": {
            "max_file_bytes": MAX_SCAN_BYTES,
            "max_matches_per_file": MAX_MATCHES_PER_FILE,
            "note": "One marker is recorded per line; a line matching several rules "
                    "reports the first rule in declaration order.",
        },
        "skipped": sorted(skipped, key=lambda item: item["path"]),
        "findings": findings,
    }
    write_json(packet / "static-analysis" / "unfinished-work.json", result)
    return result["summary"]


# --------------------------------------------------------------------------
# secret candidates
# --------------------------------------------------------------------------

SECRET_RULES = [
    ("aws-access-key-id", "AWS access key ID",
     re.compile(r"\b((?:AKIA|ASIA|ABIA|ACCA)[0-9A-Z]{16})\b")),
    ("aws-secret-access-key", "AWS secret access key",
     re.compile(r"(?i)aws[_-]?secret[_-]?access[_-]?key\W{0,3}([A-Za-z0-9/+=]{40})")),
    ("github-token", "GitHub token",
     re.compile(r"\b(gh[pousr]_[A-Za-z0-9]{36,255})\b")),
    ("github-app-jwt", "GitHub fine-grained token",
     re.compile(r"\b(github_pat_[A-Za-z0-9_]{60,255})\b")),
    ("gitlab-token", "GitLab token",
     re.compile(r"\b(glpat-[A-Za-z0-9_-]{20,})\b")),
    ("slack-token", "Slack token",
     re.compile(r"\b(xox[abposr]-[A-Za-z0-9-]{10,})\b")),
    ("slack-webhook", "Slack webhook URL",
     re.compile(r"(https://hooks\.slack\.com/services/[A-Za-z0-9/]{20,})")),
    ("google-api-key", "Google API key",
     re.compile(r"\b(AIza[0-9A-Za-z_-]{35})\b")),
    ("gcp-service-account", "GCP service account key material",
     re.compile(r"\"type\"\s*:\s*\"service_account\"")),
    ("stripe-key", "Stripe secret key",
     re.compile(r"\b((?:sk|rk)_(?:live|test)_[A-Za-z0-9]{16,})\b")),
    ("openai-key", "OpenAI-style API key",
     re.compile(r"\b(sk-[A-Za-z0-9_-]{20,})\b")),
    ("anthropic-key", "Anthropic API key",
     re.compile(r"\b(sk-ant-[A-Za-z0-9_-]{20,})\b")),
    ("npm-token", "npm token",
     re.compile(r"\b(npm_[A-Za-z0-9]{36})\b")),
    ("pypi-token", "PyPI token",
     re.compile(r"\b(pypi-[A-Za-z0-9_-]{16,})\b")),
    ("sendgrid-key", "SendGrid API key",
     re.compile(r"\b(SG\.[A-Za-z0-9_-]{16,}\.[A-Za-z0-9_-]{16,})\b")),
    ("twilio-key", "Twilio account SID",
     re.compile(r"\b(AC[0-9a-fA-F]{32})\b")),
    ("private-key-block", "Private key block",
     re.compile(r"-----BEGIN (?:RSA |DSA |EC |OPENSSH |PGP |ENCRYPTED )?PRIVATE KEY-----")),
    ("putty-private-key", "PuTTY private key",
     re.compile(r"PuTTY-User-Key-File-\d")),
    ("jwt", "JSON Web Token",
     re.compile(r"\b(eyJ[A-Za-z0-9_-]{8,}\.eyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,})\b")),
    ("basic-auth-url", "Credentials embedded in a URL",
     re.compile(r"\b[a-zA-Z][a-zA-Z0-9+.-]*://[^/\s:@]{1,64}:([^/\s:@]{3,64})@")),
    ("connection-string", "Database connection string with password",
     re.compile(r"(?i)\b(?:postgres|postgresql|mysql|mongodb(?:\+srv)?|redis|amqp|mssql)://"
                r"[^/\s:@]{1,64}:([^/\s:@]{3,64})@")),
    ("env-assignment", "Secret-shaped environment assignment",
     re.compile(r"(?im)^\s*(?:export\s+)?[A-Z0-9_]*"
                r"(?:API_?KEY|SECRET|PASSWORD|PASSWD|TOKEN|CREDENTIAL|PRIVATE_?KEY|"
                r"ACCESS_?KEY|AUTH|DSN|CONNECTION_?STRING)[A-Z0-9_]*"
                r"\s*=\s*(?!['\"]?\s*$)['\"]?([^'\"\s#]{6,})['\"]?\s*(?:#.*)?$")),
    ("generic-assignment", "Generic secret-shaped assignment",
     re.compile(r"(?i)\b(?:api[_-]?key|apikey|secret|password|passwd|pwd|token|"
                r"access[_-]?key|private[_-]?key|client[_-]?secret|auth[_-]?token)"
                r"\s*[:=]\s*[\"']([^\"'\s]{8,})[\"']")),
]

PLACEHOLDER_VALUES = re.compile(
    r"(?i)^(?:x{3,}|\.{3,}|\*{3,}|<[^>]+>|\$\{[^}]+\}|\$[A-Z_]+|%[A-Z_]+%|"
    r"changeme|change_me|placeholder|example|test|dummy|sample|redacted|"
    r"your[_-].*|my[_-]?secret|password|secret|token|none|null|true|false|"
    r"process\.env\..*|os\.environ.*|\{\{.*\}\})$")

EXAMPLE_PATH_HINTS = (
    ".example", ".sample", ".template", ".dist", "example", "sample", "template",
    "fixture", "testdata", "test-data", "mock", "__mocks__", "docs/", "doc/",
    "test/", "tests/", "spec/", "__tests__/",
)

B64ISH = re.compile(r"[A-Za-z0-9+/=_-]{24,}")


def shannon_entropy(value: str) -> float:
    if not value:
        return 0.0
    counts = {}
    for char in value:
        counts[char] = counts.get(char, 0) + 1
    length = len(value)
    return -sum((c / length) * math.log2(c / length) for c in counts.values())


def charset_shape(value: str) -> str:
    shape = []
    if any(c.islower() for c in value):
        shape.append("lower")
    if any(c.isupper() for c in value):
        shape.append("upper")
    if any(c.isdigit() for c in value):
        shape.append("digit")
    if any(not c.isalnum() for c in value):
        shape.append("symbol")
    return "+".join(shape) or "empty"


def assess_activity(row, value, path_lower):
    """Return (status, reason) — example/test-only, active-looking, or unknown."""
    if value and PLACEHOLDER_VALUES.match(value):
        return ("example-or-placeholder", "value matches a placeholder pattern")
    if any(hint in path_lower for hint in EXAMPLE_PATH_HINTS):
        return ("example-or-test-only", "path indicates an example, template or test artifact")
    if row.get("role_hint") in ("test", "example", "documentation"):
        return ("example-or-test-only", "file role is test, example or documentation")
    if row.get("origin_hint") in ("vendored", "generated"):
        return ("unknown", "value lives in vendored or generated content")
    if value and shannon_entropy(value) >= 3.5 and len(value) >= 20:
        return ("active-looking", "high-entropy value in non-example first-party content")
    return ("unknown", "no example or activity signal was decisive")


def scan_secrets(state):
    repo_root = state.repo_root
    packet = state.packet_root
    rows = read_jsonl(packet / "inventory" / "files.jsonl")
    findings = []
    scanned = 0
    skipped = []
    seen = set()

    for row in rows:
        if row.get("entry_type") != "regular-file":
            continue
        if row.get("content_kind") != "text":
            continue
        if int(row.get("size_bytes") or 0) > MAX_SCAN_BYTES:
            skipped.append({"path": row["path"], "reason": "text file larger than scan cap"})
            continue
        path = repo_root / row["path"]
        try:
            text = path.read_text(encoding=row.get("encoding") or "utf-8", errors="replace")
        except (OSError, LookupError) as exc:
            skipped.append({"path": row["path"], "reason": "{}: {}".format(type(exc).__name__, exc)})
            continue
        scanned += 1
        path_lower = row["path"].lower()
        per_file = 0

        for lineno, line in enumerate(text.splitlines(), start=1):
            if per_file >= MAX_MATCHES_PER_FILE:
                break
            if len(line) > 8000:
                line = line[:8000]
            for rule_id, label, pattern in SECRET_RULES:
                match = pattern.search(line)
                if not match:
                    continue
                value = match.group(1) if match.groups() else match.group(0)
                if rule_id in ("generic-assignment", "env-assignment") and value:
                    if PLACEHOLDER_VALUES.match(value):
                        continue
                    if shannon_entropy(value) < 2.6:
                        continue
                status, reason = assess_activity(row, value, path_lower)
                fp = fingerprint(value or (rule_id + ":" + row["path"]))
                dedupe = (rule_id, fp)
                finding = {
                    "id": "SECRET-{:05d}".format(len(findings) + 1),
                    "rule_id": rule_id,
                    "category": label,
                    "path": row["path"],
                    "line": lineno,
                    "value": "<REDACTED>",
                    "value_length": len(value) if value else None,
                    "value_charset_shape": charset_shape(value) if value else None,
                    "value_entropy_bits_per_char": round(shannon_entropy(value), 3) if value else None,
                    "fingerprint_sha256_16": fp,
                    "status": status,
                    "status_reason": reason,
                    "duplicate_of_earlier_finding": dedupe in seen,
                    "file_role_hint": row.get("role_hint"),
                    "file_origin_hint": row.get("origin_hint"),
                    "validation": "not validated; odin never tests credentials against any service",
                    "confidence": "High" if rule_id not in (
                        "generic-assignment", "env-assignment", "jwt") else "Medium",
                }
                seen.add(dedupe)
                findings.append(finding)
                per_file += 1
                break
            else:
                # No named rule matched; look for an unattributed high-entropy blob.
                for token in B64ISH.findall(line):
                    if len(token) < 32 or shannon_entropy(token) < 4.2:
                        continue
                    if PLACEHOLDER_VALUES.match(token):
                        continue
                    status, reason = assess_activity(row, token, path_lower)
                    fp = fingerprint(token)
                    findings.append({
                        "id": "SECRET-{:05d}".format(len(findings) + 1),
                        "rule_id": "high-entropy-string",
                        "category": "Unattributed high-entropy string",
                        "path": row["path"],
                        "line": lineno,
                        "value": "<REDACTED>",
                        "value_length": len(token),
                        "value_charset_shape": charset_shape(token),
                        "value_entropy_bits_per_char": round(shannon_entropy(token), 3),
                        "fingerprint_sha256_16": fp,
                        "status": status,
                        "status_reason": reason,
                        "duplicate_of_earlier_finding": ("high-entropy-string", fp) in seen,
                        "file_role_hint": row.get("role_hint"),
                        "file_origin_hint": row.get("origin_hint"),
                        "validation": "not validated; odin never tests credentials against any service",
                        "confidence": "Low",
                    })
                    seen.add(("high-entropy-string", fp))
                    per_file += 1
                    break

    binary_sensitive = [
        {"path": row["path"], "reason": "binary or non-text file with a sensitive name pattern",
         "sensitivity_hint": row.get("sensitivity_hint"), "size_bytes": row.get("size_bytes")}
        for row in rows
        if row.get("sensitivity_hint") == "secret-candidate" and row.get("content_kind") != "text"
    ]

    by_status = {}
    by_rule = {}
    for finding in findings:
        by_status[finding["status"]] = by_status.get(finding["status"], 0) + 1
        by_rule[finding["rule_id"]] = by_rule.get(finding["rule_id"], 0) + 1

    result = {
        "policy": [
            "no secret value is stored in this packet",
            "fingerprints are truncated salted SHA-256 and are not reversible",
            "no discovered credential was validated against any service",
        ],
        "summary": {
            "files_scanned": scanned,
            "files_skipped": len(skipped),
            "findings_total": len(findings),
            "distinct_fingerprints": len(seen),
            "by_status": dict(sorted(by_status.items())),
            "by_rule": dict(sorted(by_rule.items())),
            "binary_sensitive_files": len(binary_sensitive),
        },
        "binary_sensitive_files": sorted(binary_sensitive, key=lambda item: item["path"]),
        "skipped": sorted(skipped, key=lambda item: item["path"]),
        "findings": findings,
        "limitations": [
            "pattern and entropy based; unknown credential formats are missed",
            "a match is a candidate, not a confirmed live credential",
            "only text files within the scan size cap were inspected",
            "reachable VCS history was not scanned by this helper",
        ],
    }
    write_json(packet / "security" / "secrets-redacted.json", result)
    return result["summary"]


# --------------------------------------------------------------------------
# packet-wide leak check
# --------------------------------------------------------------------------

def audit_packet_for_leaks(state):
    """Re-run the secret rules against the generated packet itself."""
    packet = state.packet_root
    hits = []
    for path in sorted(packet.rglob("*"), key=lambda p: str(p)):
        if not path.is_file():
            continue
        rel = path.relative_to(packet).as_posix()
        if rel == "security/secrets-redacted.json":
            continue
        try:
            if path.stat().st_size > MAX_SCAN_BYTES:
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for rule_id, label, pattern in SECRET_RULES:
                if rule_id in ("generic-assignment", "env-assignment", "jwt"):
                    continue
                match = pattern.search(line)
                if match:
                    value = match.group(1) if match.groups() else match.group(0)
                    hits.append({
                        "packet_path": rel,
                        "line": lineno,
                        "rule_id": rule_id,
                        "category": label,
                        "fingerprint_sha256_16": fingerprint(value),
                        "action_required": "redact this value before packaging",
                    })
                    break
    return hits
