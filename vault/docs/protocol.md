# Vault runtime and agent contract

`SKILL.md` is the operational specification for compatible host agents. It defines the scan loop, schemas, validation rules, public-source research policy, private data boundary, recovery, error handling, and CLI calls. The Python runtime does not claim to perform general visual identification or internet research.

## Runtime guarantees

- SQLite is the catalog authority. Schema version 16 and SQL checksums are recorded in `schema_migrations`; host sessions can be recorded in `scan_runs`, with committed photos linked to their run. Stable taxonomy UUIDs, parent-scoped normalized labels and aliases link every item to category/type/subtype nodes. Perceptual difference hashes suggest similar archived photographs for review but never establish physical identity. SHA-256 and byte length are verified for each primary and detail crop asset. Valuation comparables preserve source amounts, currency, quantity, sale date, FX provenance, normalized unit value, and adjustment notes; valuations retain methodology and rationale.
- Inputs are claimed by identity/hash; the runtime validates agent-supplied boxes/quadrilaterals, frames, structured evidence and price fields before committing.
- `preview-crops PHOTO_ID --claim-token TOKEN --regions REGIONS.json --output-dir TEMP_PATH` verifies the active claim and source hash, renders item regions for host inspection outside the workspace, and leaves the catalog and source lifecycle unchanged. The host inspects previews before identity research and commit.
- Optional per-item `research_activity` stores up to eight actual query records (`query`, optional `source`) and twelve opened-page records (`url`, `source`, optional `query`, boolean `cache_hit`). URLs are validated as public HTTP(S), and the normalized activity is persisted in `research_runs` within the same commit as the item/evidence records.
- Crops are stored beneath `Catalog/Images`; original photographs move to sibling `Scanned` only after commit. Recovery resumes pending moves. ZIP members have independent durable state; the source archive remains until member dispositions are terminal.
- User corrections are audited and field-locked. Private correction history and research caches use `VAULT_DATA_HOME` (default `%USERPROFILE%/.local/share/vault` on Windows); they are excluded from this distributable source.
- `backup` uses SQLite's online backup API. `restore --from` accepts a verified database backup at the current schema version, verifies all referenced local assets first, creates a fresh safety backup of the current catalog, then atomically swaps the DB file. Restore assumes matching `Catalog/Images` assets are present. Original photographs remain in sibling `Scanned` and should be preserved separately. If the archived originals were moved to a separate location, `rebind --scanned-root PATH` hash-matches and copies them back into the workspace's sibling `Scanned` tree; it never deletes source files, and reports unmatched records.
- XLS uses BIFF, XLSX is OOXML, CSV is formula-safe, JSON has a schema version, and HTML embeds crop bytes as data URLs. Spreadsheet export splits sheets at format row limits.

## Research contract

The agent searches public Google/eBay sources first and category specialists as needed, follows source pages rather than relying on search snippets, records actual URLs, and distinguishes sold, dealer, asking and retail bases. The runtime validates URL structure and valuation consistency, but does not validate the truth of the remote page. Weak or absent comparables yield a NULL supported valuation. Private cache contents are candidates that the agent must re-check for relevance.

## Limits

OpenCV proposals are optional geometry hints and are not a general object detector. The host agent determines production item boundaries and identities. HEIF/HEIC decoding uses pillow-heif; supported camera RAW formats use rawpy/LibRaw, with device-specific decoder support dependent on rawpy/LibRaw. Codex/Claude visual and web abilities depend on each host's installed tools. Migration checksums detect unexpected migration-file changes. Never publish a user Catalog, Scanned, VAULT_DATA_HOME, virtual environments, or private test fixtures.

Read-only `filter` accepts only allowlisted category/type/name, review/research state, confidence bounds, supported valuation cents bounds/basis, ISO creation-date bounds, image presence and row limit. Use the host agent to translate natural language into these structured options; the runtime binds values and never executes model-generated SQL.
