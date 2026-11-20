---
name: vault
description: Scan intentionally photographed objects into a durable SQLite visual inventory. Use for image intake, identification, public research, valuation, catalog queries, and exports.
metadata:
  version: 2.0.0-dev13
---
# Vault 2.0 operating protocol

When the user asks to scan Staging, operate the scan yourself with the visual and web tools available in this agent session. Do not ask the user to draw boxes, create JSON, run Python, or research items. Python is the deterministic queue, crop, persistence, and recovery engine; it is not an identity model. Never say an item was visually checked or researched unless you actually did so.

## Start and capability checks

Resolve `<skill>` to this installed directory and `<workspace>` to the user's stated/current workspace. Keep temporary manifests in the system temp directory, never in Staging. Use the skill's isolated Python on Windows: `<skill>\.venv\Scripts\python.exe`; other platforms use `<skill>/.venv/bin/python`. Run:

```text
python <skill>/scripts/vault.py --root <workspace> doctor
python <skill>/scripts/vault.py --root <workspace> dry-run
python <skill>/scripts/vault.py --root <workspace> run list
python <skill>/scripts/vault.py --root <workspace> run start --agent Codex [--model MODEL]
```

Keep the returned `run_id` in the session state and include it as `scan_run_id` in each commit manifest. If context resumes, inspect `run list` and preserve any active run ID when continuing that same session. After final `summary` and `check`, close it with `run finish --id RUN_ID`. On deliberate interruption, close with `run finish --id RUN_ID --interrupted`; abrupt termination leaves an auditable active run for later recovery.

Actually open each claimed image with the host image tool. If no visual tool can inspect it, leave it claimed for later and report that limitation; never commit filename-only guesses. Use public web search when available. Google and eBay are the default first queries; escalate to relevant specialist catalogs/marketplaces. No paid APIs, authenticated research, access-control bypass, or invented prices. If public search is unavailable, keep identification from visible evidence, set `pending_research: true`, and leave supported price fields null.

## Processing loop

1. Run `resume`, then `claim`. Recovery work does not consume the user's new-photo limit. A job includes `id`, `claim_token`, `source`, normalized `width`/`height`, `frame_count`, and reserved destination. `near_duplicate_suggestions` are difference-hash matches to archived photographs; inspect their images and markings as evidence, but never infer physical identity or merge from this signal alone. A `failed`, `deduplicated`, or blocked result is a disposition; report it accurately and continue.
2. For each `job`, run `normalize <photo_id> <temp-image.png> --frame N` for every `N` from `0` to `frame_count - 1`, and visually inspect each normalized frame. Enumerate every intentionally photographed physical object; ignore incidental background. Find boundaries from the image itself. Treat nine-pocket pages as nine possible regions, but include only occupied pockets. Inspect partial binders and irregular arrays without assuming grid spacing. Reflections, labels, sleeves, and packaging are not extra objects unless intentionally collectible.
3. For structured arrays, inspect each region and derive its own pixel coordinates. `propose-crops <normalized-image>` may provide OpenCV card-shaped contour suggestions; these are fallible aids only. Visually verify every box, refine it, and ensure it encloses the item. One box per distinct physical object, including repeated copies. Include `frame` for multipage/animated input when applicable.
4. Before identifying or researching, write a temporary region file such as `{"items":[{"frame":0,"box":[left,top,right,bottom]}]}` and run `preview-crops PHOTO_ID --claim-token TOKEN --regions REGIONS.json --output-dir %TEMP%\vault-previews`. Open and visually inspect every returned crop. Refine boundaries and repeat previews until crops isolate the intended objects; previews are outside the workspace and do not change the catalog or archive the source. Only then determine identities from the crop details.
5. Consult the relevant public guide in `<skill>/knowledge/rules/`. Identify from visible markings and corroborating sources. Use `Unknown Item` with low confidence and review flags when unresolved. Research exact names, edition/variant and condition. Search Google/eBay first; inspect result pages, prefer completed/sold comparables, and escalate by category (TCG: set/checklist and TCG marketplaces; sports cards: set checklist and eBay; coins: authoritative catalog/auction records; other categories: specialist catalogs/auction sites). Record actual query strings and opened public pages in each item's `research_activity`; runtime enforces 8 query and 12 page limits and persists provider, URL, query and cache-hit data. Separate sold, dealer, asking, and retail bases; exclude tax/shipping. Without credible evidence, valuation stays null. Store actual URLs and concise notes, not search snippets alone. `research-only` retrieves selected/pending items and unexpired cache results without changing the catalog. `retry-research` persists offline queue work. Independently confirm cached results. Save host research JSON in a temporary file, run `research-cache --item-id ID --put RESULT.json` to cache it for 30 days, then `record-research ID RESULT.json` to append evidence, queries and valuation history. If public search is unavailable, run `research-failed ID --reason ...`; after five failures, use `retry-research --force` only after resolving the issue. Leave price NULL and research pending.
6. Build the final manifest from visually verified crops and research. Run `commit <manifest.json>`. Treat errors/warnings as unresolved; run `resume`, inspect actual DB state with `check`, and continue only after recovery succeeds. Do not manually move/delete source images. ZIP members are independent jobs; the archive remains in Staging until every member has a recorded terminal disposition. Unsupported/corrupt members remain explicit, never silently discarded.
7. Open and visually inspect every committed crop as a final persistence check. Compare it with the preview; if it differs or is wrong, do not claim success: preserve state, correct through the supported catalog edit/review operation, and audit the correction. Do not resubmit a committed photo manifest.
8. Continue `claim` until no eligible work remains or the requested limit is reached. Give brief progress after 10 images or 60 seconds. Finish with `summary`, `check`, and the session counts: archived/failed/pending photos, created/associated items, unknown/review/research-pending counts, evidence-backed total, speculative total, and warnings.

## Manifest contract

Top level: `photo_id` and `claim_token` copied verbatim from `claim`; include `scan_run_id` from the session's `run start` when available; `visual_inspection_complete: true` only after inspection; `items` array (empty only after confirming zero intended objects). Each item:

```json
{
  "box": [left, top, right, bottom],
  "detail_crops": [{"box":[detail_left,detail_top,detail_right,detail_bottom],"frame":0,"label":"signature or barcode"}],
  "quad": [[top-left-x,top-left-y],[top-right-x,top-right-y],[bottom-right-x,bottom-right-y],[bottom-left-x,bottom-left-y]],
  "frame": 0,
  "name": "legible identity or Unknown Item",
  "category": "supportable broad category",
  "type": "specific kind",
  "subtype": null,
  "specificity": "exact",
  "identity_key": "normalized maker-model-set-variant or null",
  "match_item_id": null,
  "confidence": 0,
  "condition": null,
  "condition_confidence": null,
  "metadata": {},
  "distinct_instance": false,
  "review": false,
  "pending_research": true,
  "notes": "visible evidence and uncertainty",
  "evidence": [{"url":"https://…","kind":"identity","description":"what this page supports"}],
  "research_activity": {"queries":[{"query":"exact product query sold eBay","source":"eBay"}],"visited_pages":[{"url":"https://…","source":"eBay","query":"exact product query sold eBay","cache_hit":false}]},
  "valuation": {
    "estimate_cents": null,
    "low_cents": null,
    "high_cents": null,
    "speculative_cents": null,
    "source_url": null,
    "basis": "unavailable",
    "confidence": null,
    "methodology": null,
    "rationale": null,
    "comparables": [{"source_url":"https://…","sale_basis":"sold","original_amount":"12.50","currency":"USD","quantity":1,"sold_at":"2025-01-15","adjusted_unit_cents":1250,"adjustment_notes":""}]
  }
}
```

Coordinates are integer pixels in the EXIF-normalized frame and must satisfy `0 <= left < right <= width`, `0 <= top < bottom <= height`. Optional `quad` supplies four ordered corners for perspective rectification; include it only when the object is clearly quadrilateral and all points are visually verified. Exact identity requires confidence at least 90 and an actual identity evidence URL. Use a normalized exact identity key only for a supported make/model/set/variant. Per the approved catalog policy, a unique prior item with that exact product key is reused across photographs by default (provisional association score 80); when multiple candidates exist, inspect them and set `match_item_id` only when one is a strong match. Set `distinct_instance: true` when visible traits establish a separate physical copy that must retain its own UUID. Within one photograph, repeated copies always receive separate UUIDs. Every evidence URL is real and must be assigned `identity` or `valuation`; a supported estimate requires the same URL as a valuation evidence record and basis `sold`, `dealer`, `asking`, or `retail`. Record each actual comparable's original amount, currency, quantity, sale date, and valuation URL. Non-USD comparables also require a cited `fx_source_url` and decimal `usd_fx_rate`; the runtime stores normalized and adjusted unit cents. Three or more sold comparables require the estimate to equal their adjusted median and methodology `median_sold`. All supported estimates require methodology and a short rationale. Cents are nonnegative integer USD cents. Ranges require a central estimate. Speculative amounts are separate from supported estimates. Confidence is the agent's uncertainty estimate, not a calibrated probability. When neither a supported nor speculative estimate can be recorded for a newly cataloged item, the runtime marks research pending automatically; use `pending_research: true` to request later refresh for existing items.

Optional `detail_crops` contain up to 12 visually verified sub-boxes fully inside the object's primary box, on the same frame, with a concise label such as `signature`, `serial plate`, or `barcode`. Each is persisted as a separate versioned asset attached to the observation; never use detail assets instead of the full primary object crop.

## Commands

All commands put `--root <workspace>` before the subcommand:

- `doctor`, `dry-run`, `run list|start|finish`, `claim`, `normalize ID OUTPUT`, `preview-crops ID --claim-token TOKEN --regions REGIONS.json --output-dir %TEMP%\vault-previews`, `commit MANIFEST`, `resume`, `check`
- `query`, `filter --category X --type X --name X --review 1 --pending-research 1 --confidence-min N --confidence-max N --value-min-cents N --value-max-cents N --basis sold|dealer|asking|retail|unavailable --created-after YYYY-MM-DD --created-before YYYY-MM-DD --has-image 1 --limit N`, `summary`, `review`, `retry-research`, `research-only`, `revalue --item-id ID`, `rescan --item-id ID`, `record-research ITEM_ID RESULT.json`
- `item add|edit|delete|restore|unlock|correct ...`, `merge SOURCE TARGET [--undo]`, `split ITEM_ID OBSERVATION_ID...`, `import SOURCE_ROOT`, `backup [--output PATH]`, `restore --from BACKUP.sqlite`, `rebind --scanned-root PATH` (hash-check and safely copy archived originals from a separately moved Scanned folder)
- `learning --category CATEGORY`, `learning-rules --category CATEGORY`, `learn-rule --category CATEGORY --correction-id ID --rule TEXT [--positive-cue TEXT] [--negative-cue TEXT]`, `taxonomy-alias --kind category|type|subtype --name LABEL --alias ALIAS [--category CATEGORY] [--parent-type TYPE]`
- `review [--resolve ITEM_ID]`, `learning [--category CATEGORY]`, `research-cache --item-id ITEM_ID [--put RESULT.json] [--ttl-days 30]`, `research-failed ITEM_ID --reason TEXT`, `retry-research [--force]`
- `export --format csv|json|html|xls|xlsx --output PATH`, `propose-crops IMAGE`

Translate natural-language read-only requests into `filter` fields (`category`, `type`, escaped partial `name`, `review`, `pending_research`, confidence bounds, valuation cents bounds/basis, created-date bounds, image presence) or inspect `query`; this compiles to allowlisted parameterized SQL, never raw model-generated SQL. Unsupported interpretations must be clarified or reported. `rescan` returns hash-verified archived photographs and prior regions for host visual reinspection; it does not requeue or move originals. `revalue` returns selected/all pending item research snapshots; `record-research` appends valuation history. `review` lists unresolved items; resolve only after inspection/correction. `learning --category` displays private corrections as hints. After a user correction, if its reason supports a general lesson, create a provisional rule with the returned correction ID using `learn-rule`; `learning-rules` returns those candidate cues for future inspection. Candidate rules are hints, never facts to apply automatically. Manual edits and corrections must be audited; lock corrected fields unless the user explicitly unlocks them. A soft delete preserves history. If a command is absent or errors, do not imply the operation happened; report it as pending and continue independent eligible work.

## Privacy and lifecycle

Catalog images are derived crops; original photographs are archived unchanged in sibling `Scanned`. Private inventory, source images, database files, raw private searches, and local learning belong outside the published skill tree. Use the private data home for generalized rules, corrections, and cache; never commit those materials. No unattended service is started and a scan stops when the invoking agent exits.
