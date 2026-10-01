# Security analysis, findings and secrets

## Scope

**Source security:** injection; command/shell execution; SQL and NoSQL injection;
template injection; path traversal; unsafe archive extraction; SSRF; XSS; CSRF where
applicable; authentication weaknesses; authorization failures; insecure defaults;
unsafe deserialization; unsafe reflection and `eval`; cryptographic misuse; weak
randomness; credential handling; secret leakage; insecure temporary files; unsafe file
permissions; race-sensitive security behavior; memory-safety issues where detectable;
native/FFI boundaries; unvalidated inputs; sensitive logging; error-information
leakage.

**Supply chain:** see `dependencies-and-sbom.md`.

**Infrastructure and configuration:** excessive container privileges; root execution;
writable sensitive mounts; exposed services; weak TLS settings; overly broad cloud/IAM
permissions; dangerous Kubernetes and IaC configuration; CI token exposure; untrusted
pull-request execution with secrets; unsafe artifact handling.

## Finding record

SARIF is the preferred machine-readable format for static findings
(`security/findings.sarif`). Normalize everything else: manual analysis, dynamic
confirmation, non-SARIF tools: to the same conceptual fields in
`security/findings.json`.

| Field | Rule |
| --- | --- |
| `id` | stable across runs; derive it from rule + normalized location + a content anchor, never a run counter alone |
| `category` / `cwe` | CWE only when defensibly known |
| `rule_id` | the original scanner rule ID, unchanged |
| `severity_normalized` | `Critical` \| `High` \| `Medium` \| `Low` \| `Informational` \| `Unknown` |
| `severity_original` | the scanner's own severity, unchanged, in its own field |
| `confidence` | `Confirmed` \| `High` \| `Medium` \| `Low` |
| `locations` | repository-relative paths with line/column ranges |
| `dataflow` | source → sink evidence when you have it |
| `symbol` / `module` | the affected symbol and module |
| `exploit_conditions` | what must be true for this to matter |
| `reachability` | runtime reachability evidence, if any |
| `advisory_ids` | CVE/GHSA/OSV identifiers where relevant |
| `remediation` | safe recommendation; never an applied fix |
| `tool` / `tool_version` | the producing tool |
| `provenance` | `scanner-reported` \| `manually-derived` \| `dynamically-confirmed` |

**A pattern match is not a confirmed vulnerability.** Promote to `Confirmed` only with
evidence: a traced data flow, a reachable entry point, or dynamic confirmation in the
sandbox. Everything else stays a candidate with its confidence stated.

Never invoke automatic vulnerability remediation, in any ecosystem, under any flag.

## Secrets

`odin.py secrets` produces `security/secrets-redacted.json`. Its contract, which
applies to everything you add by hand:

- Identify the secret **category**.
- Give the repository-relative file and a safe line or range.
- State whether it looks active, is example/test-only, or is unknown: with the reason.
- Include a non-reversible fingerprint for deduplication when safe.
- **Redact the value.** `"<REDACTED>"`, plus length, charset shape and entropy if
  useful.
- **Never validate the credential against an external service.** Not once, not to
  "check whether it's real".

The helper is pattern- and entropy-based over text files within a size cap, and does
not read VCS history. Close those gaps with a dedicated local scanner (gitleaks,
trufflehog) when one is available, run it in a mode that does not transmit anything,
and log it as its own action. When no scanner is available, say so: an empty secrets
section with no stated method is indistinguishable from a scan that never ran.

`validate` re-scans the entire generated packet for unredacted secret values before
packaging. Treat a hit there as a blocking defect.

## Sensitive files that are not text

The inventory flags binary and non-text files with sensitive names:  keystores, key
material, credential stores. Document them by metadata (path, size, format,
provenance, what references them) without dumping their contents, and note them in
`SECURITY_NOTES.md`.

## Environment variables

Collect the names that influence the build. Include values only for demonstrably
non-sensitive variables; everything else is `<REDACTED>`. `odin.py env` already applies
this policy to `inventory/environment.json`: keep it when you write prose.

## What the security documents must not say

Do not write "secure", "no vulnerabilities", "fully hardened" or equivalent because no
tool reported anything. State what was analyzed, with which tool at which version,
what was not analyzed, and what that leaves unknown:

> Static analysis covered Python and TypeScript sources with Semgrep 1.x (registry
> rules unavailable offline; only the repository's own rule set ran) and manual review
> of the authentication and file-upload paths. No SAST tool was available for the Go
> module, so its findings are manual-review only. Dependency advisories were not
> checked: no offline database was present and network access was denied. Absence of a
> finding in these conditions is not evidence of absence.

## Cross-referencing

A finding usually belongs in more than one place. Put the analysis in one place and
reference it from the others:

- `SECURITY.md`: the narrative and the prioritized list
- `security/findings.sarif` / `findings.json`: the machine-readable record
- `security/SECURITY_NOTES.md`: method, coverage, tool versions, limitations
- the per-file document: the file-level observation
- the module document: the trust boundary it sits on
- `EXECUTIVE_SUMMARY.md`: only the findings that change a reader's decisions
