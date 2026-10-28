# Data contracts and QA

Use UTF-8 JSON. Paths are relative to the run directory, never absolute or traversal paths.

## `photos.json` (from unpack)

```json
{"photos":[{"photo_id":"PHOTO001","source_name":"camera/IMG_001.jpg","path":"photos/PHOTO001.jpg","width":1200,"height":900,"sha256":"..."}],"skipped":[]}
```

## `boxes.json` (from visual inspection)

Pixel boxes use the *normalized* photo's orientation and `[left,top,right,bottom]`. Assign one stable ID per distinct object; choose a primary photo crop even when multiple views exist.

```json
{"boxes":[
  {"item_id":"V001","photo_id":"PHOTO001","box":[20,45,550,830]},
  {"item_id":"V002","photo_id":"PHOTO001","box":[580,30,1150,855]}
]}
```

The crop tool writes `crops/V001.jpg` etc. and `crops.json`. Duplicate IDs are errors, not overwrite requests.

## `items.json` (after research)

```json
{
  "batch_id": "2026-10-28-01",
  "research_date": "2026-10-28",
  "market": "US secondhand resale",
  "currency": "USD",
  "items": [
    {
      "item_id": "V001",
      "crop": "crops/V001.jpg",
      "source_photo": "PHOTO001 | camera/IMG_001.jpg",
      "item_name": "Example brand and model",
      "item_type": "Hand tool",
      "value_estimate": 55,
      "value_low": 40,
      "value_high": 70,
      "value_url": "https://example.com/sold-item",
      "id_confidence": 0.88,
      "match_specificity": "likely",
      "price_basis": "sold",
      "notes": "Condition unknown; comparable is used."
    }
  ]
}
```

This is a schema example, **not price evidence**. Set unsupported prices to `null`, value URL to `null`, and basis to `unavailable`. A populated estimated value requires a verified HTTPS comparable source, except a documented zero value backed by evidence. `id_confidence` is a number from `0` to `1`. Monetary values are nonnegative numbers. The workbook generator validates rows.

## Acceptance checks

- Every usable original photo visually inspected; skipped photos reported.
- Item count reflects physical objects, not file count; distinct objects are neither omitted nor double counted.
- Every item has a matching readable crop and source filename reference.
- Every value has directly relevant price evidence; asking/retail source classes are visible.
- Confidence is specific to identification, and ambiguity is recorded.
- Workbook has the right row/image count, working URL links, numeric value/confidence cells, and readable photos.
