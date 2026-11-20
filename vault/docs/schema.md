# Vault SQLite schema

Database: `Catalog/Vault.sqlite`. Schema migrations `001.sql` through `016.sql` are applied in order; `schema_migrations` stores SHA-256 checksums and `PRAGMA user_version` is 16.

## Records

- `photos`: intake occurrence, SHA-256 and persisted 64-bit difference hash, dimensions/frame count, claim token, workflow state, source and archive destination. Difference-hash matches are review hints only; exact SHA-256 remains byte-identity evidence and neither hash establishes physical item identity.
- `scan_runs`: host-agent/model session records with active/complete/interrupted state. Photos may reference the run that committed their inventory transaction; recovery can be inspected independently from the agent conversation.
- `archives`, `archive_members`: ZIP source and member occurrence identities/dispositions. The member index allows duplicate filenames.
- `products`: exact normalized product identity. Multiple physical `items` can refer to one product.
- `items`: physical inventory identities, classification, confidence, condition, metadata, crop, active/review/research state.
- `taxonomy_nodes`, `taxonomy_aliases`, `item_taxonomy`: stable UUID category/type/subtype hierarchy, parent-scoped normalized aliases, and item-to-taxonomy links. Existing catalog labels are backfilled on migration/open; new labels are added dynamically and alias resolution prevents normalized synonym duplication.
- `observations`: one crop, frame and box per item/photo pair. `association` and `duplicate_confidence` record deduplication decisions.
- `evidence`: URL-backed identity or valuation statements, optionally associated with an observation.
- `valuations`: append-only history with supported and speculative USD cents, source basis, confidence, methodology, rationale and timestamp.
- `valuation_comparables`: individual observed listing/sale records; stores original decimal amount/currency, quantity, date, FX evidence/rate, normalized and adjusted USD unit cents.
- `catalog_assets`: relative path, byte count and SHA-256 for crop and detail assets.
- `detail_assets`: versioned close-up crops linked to an observation, with normalized frame/box, label, hash and byte count.
- `audit`, `field_locks`, `item_aliases`, `merge_members`: manual operations, protected corrections, soft deletion/reversible merges and split/undo history.
- `research_queue`, `research_cache`, `research_runs`: offline retry state, TTL research results and private query/page activity. Cache contents are hints and not automatically trusted as current valuation evidence.
- `item_origins`, `import_entity_origins`, `import_audit_origins`, `import_comparable_origins`: deterministic independent catalog provenance and conflict remaps.
- `asset_journal`: primary and detail files staged for a photo transaction and recovered after interruption.

## Consumer views

`current_inventory`, `v_inventory`, `v_current_valuations`, `v_item_sources`, `v_review_queue`, and `v_catalog_totals` are read-only reporting surfaces. Current valuation means latest recorded observation, not a promise that a source remains available or a price is current. Keep original photographs in sibling `Scanned`; the portable `Catalog` contains the database and cropped assets.

## Data rules

UUIDs identify physical items and durable entities. Money is integer USD cents in headline valuations; comparable inputs retain exact decimal strings and currency. Evidence URLs must be HTTP(S); the runtime validates structure and linkage, not remote truth. Inactive merged/deleted records remain for audit and reversal. `Catalog_assets` checks detect missing, changed, or redirected crops.
