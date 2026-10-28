# Vault

Identify and price objects from ZIPs of photographs, including pictures containing several saleable items.

Start with [SKILL.md](SKILL.md). The skill guides an assistant through inspecting every photo, drawing separate object crops, researching exact identities and resale comparables, and building a confidence-scored Excel inventory.

## Output

An `.xlsx` workbook with one row per distinct item: an embedded crop, item name, item type, approximate value in USD, direct price source, identity confidence, range, match specificity, price basis, original photo name, notes and item ID. `.xls` can be supplied only after a verified legacy conversion because simply renaming `.xlsx` is invalid.

## Dependencies

- Python with Pillow for safe ZIP image normalization and cropping (`scripts/images.py`).
- Web browsing and image inspection for identification and live comparable-price research; scripts do not guess the object or its price.
- The Codex primary Node runtime with `@oai/artifact-tool` to run `scripts/build_workbook.mjs`, or another XLSX writer with embedded-image support. Copy the `.mjs` into a temporary work directory and make the runtime's `node_modules` available there.
- Python standard library `scripts/finalize_links.py` to add native Excel hyperlinks after export.

## Improve accuracy

Corrections are recorded as general recognition rules in `references/recognition_rules.md` after the user confirms the item. Never add raw personal photographs or inventories to the repository without permission.

## Tests

`python -m unittest discover -s tests -v` checks ZIP safety, multiple-object cropping, and workbook media/links (the latter runs when the artifact-tool runtime is available).
