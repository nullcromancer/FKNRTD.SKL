#!/usr/bin/env python3
"""Safe ZIP image normalization and deterministic object cropping for Vault.

Requires Pillow. The agent, not this script, identifies objects and draws boxes.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import re
import stat
import zipfile
from pathlib import Path, PurePosixPath

from PIL import Image, ImageDraw, ImageFont, ImageOps

Image.MAX_IMAGE_PIXELS = 75_000_000
SUPPORTED = {".jpg", ".jpeg", ".png", ".webp", ".tif", ".tiff", ".bmp", ".gif"}
MAX_FILES = 5000
MAX_FILE_BYTES = 80 * 1024 * 1024
MAX_TOTAL_BYTES = 1024 * 1024 * 1024
ID_RE = re.compile(r"^V[0-9]{3,6}$")


def write_json(path: Path, payload: dict) -> None:
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def safe_entry(info: zipfile.ZipInfo) -> bool:
    p = PurePosixPath(info.filename.replace("\\", "/"))
    if info.is_dir() or p.is_absolute() or ".." in p.parts or info.filename.startswith(("/", "\\")):
        return False
    if re.match(r"^[A-Za-z]:", info.filename) or "\x00" in info.filename:
        return False
    mode = (info.external_attr >> 16) & 0xFFFF
    if stat.S_ISLNK(mode):
        return False
    return p.suffix.lower() in SUPPORTED


def normal_image(raw: bytes) -> Image.Image:
    with Image.open(io.BytesIO(raw)) as src:
        src.seek(0)  # animated GIF: first frame only
        image = ImageOps.exif_transpose(src)
        image.load()
        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
            rgba = image.convert("RGBA")
            white = Image.new("RGB", rgba.size, "white")
            white.paste(rgba, mask=rgba.getchannel("A"))
            return white
        return image.convert("RGB")


def contact_sheets(photos: list[dict], run: Path) -> None:
    for offset in range(0, len(photos), 30):
        block = photos[offset:offset + 30]
        if not block:
            continue
        board = Image.new("RGB", (1200, ((len(block) + 4) // 5) * 188), "#20262c")
        draw = ImageDraw.Draw(board)
        for i, record in enumerate(block):
            with Image.open(run / record["path"]) as original:
                thumb = original.copy()
                thumb.thumbnail((220, 153), Image.Resampling.LANCZOS)
            x, y = (i % 5) * 240, (i // 5) * 188
            board.paste(thumb, (x + (240 - thumb.width) // 2, y + 4))
            draw.text((x + 9, y + 160), record["photo_id"], fill="#b0ffc7")
        board.save(run / f"contact-{offset // 30 + 1:03d}.jpg", quality=82)


def unpack(zip_path: Path, run: Path) -> None:
    run.mkdir(parents=True, exist_ok=True)
    photos_dir = run / "photos"
    photos_dir.mkdir(exist_ok=True)
    photos, skipped = [], []
    total = 0
    with zipfile.ZipFile(zip_path) as archive:
        entries = archive.infolist()
        if len(entries) > MAX_FILES:
            raise ValueError(f"ZIP has too many entries ({len(entries)} > {MAX_FILES})")
        for info in entries:
            if not safe_entry(info):
                if not info.is_dir():
                    skipped.append({"source_name": info.filename, "reason": "unsafe or unsupported entry"})
                continue
            if info.file_size > MAX_FILE_BYTES:
                skipped.append({"source_name": info.filename, "reason": "image exceeds size limit"})
                continue
            total += info.file_size
            if total > MAX_TOTAL_BYTES:
                raise ValueError("ZIP exceeds total expanded-image size limit")
            try:
                raw = archive.read(info)
                image = normal_image(raw)
                number = len(photos) + 1
                photo_id = f"PHOTO{number:03d}"
                rel = f"photos/{photo_id}.jpg"
                image.save(run / rel, "JPEG", quality=90, optimize=True)
                photos.append({
                    "photo_id": photo_id,
                    "source_name": info.filename,
                    "path": rel,
                    "width": image.width,
                    "height": image.height,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                })
            except Exception as exc:
                skipped.append({"source_name": info.filename, "reason": f"unreadable image: {type(exc).__name__}"})
    if not photos:
        raise ValueError("No supported readable images in ZIP")
    write_json(run / "photos.json", {"photos": photos, "skipped": skipped})
    contact_sheets(photos, run)
    print(f"Normalized {len(photos)} photos; skipped {len(skipped)}. See {run / 'photos.json'}")


def crop(run: Path, boxes_path: Path) -> None:
    original = json.loads((run / "photos.json").read_text(encoding="utf-8"))
    boxes = json.loads(boxes_path.read_text(encoding="utf-8"))["boxes"]
    by_id = {photo["photo_id"]: photo for photo in original["photos"]}
    crops_dir = run / "crops"
    crops_dir.mkdir(exist_ok=True)
    seen = set()
    validated = []
    output = []
    for row in boxes:
        item_id, photo_id, coords = row["item_id"], row["photo_id"], row["box"]
        if not ID_RE.fullmatch(item_id) or item_id in seen:
            raise ValueError(f"Invalid or duplicate item ID: {item_id}")
        seen.add(item_id)
        if photo_id not in by_id:
            raise ValueError(f"Unknown photo ID: {photo_id}")
        if len(coords) != 4 or any(not isinstance(x, int) for x in coords):
            raise ValueError(f"Invalid pixel box for {item_id}")
        l, t, r, b = coords
        photo = by_id[photo_id]
        if not (0 <= l < r <= photo["width"] and 0 <= t < b <= photo["height"]):
            raise ValueError(f"Out-of-bounds box for {item_id}")
        if photo["path"] != f"photos/{photo_id}.jpg":
            raise ValueError(f"Unexpected normalized photo path for {photo_id}")
        validated.append((item_id, photo_id, coords, photo, l, t, r, b))
    for item_id, photo_id, coords, photo, l, t, r, b in validated:
        with Image.open(run / photo["path"]) as frame:
            item = frame.crop((l, t, r, b))
            rel = f"crops/{item_id}.jpg"
            item.save(run / rel, "JPEG", quality=93, optimize=True)
        output.append({"item_id": item_id, "photo_id": photo_id, "source_name": photo["source_name"],
                       "crop": rel, "box": coords})
    write_json(run / "crops.json", {"crops": output})
    print(f"Made {len(output)} individual crops. See {run / 'crops.json'}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    u = commands.add_parser("unpack")
    u.add_argument("zip", type=Path)
    u.add_argument("--out", required=True, type=Path)
    c = commands.add_parser("crop")
    c.add_argument("--run", required=True, type=Path)
    c.add_argument("--boxes", required=True, type=Path)
    args = parser.parse_args()
    if args.command == "unpack":
        unpack(args.zip, args.out)
    else:
        crop(args.run, args.boxes)


if __name__ == "__main__":
    main()
