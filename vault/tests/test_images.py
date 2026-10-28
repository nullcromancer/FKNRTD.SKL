"""Smoke and safety tests for ZIP intake and per-object cropping."""

import io
import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from images import crop, unpack  # noqa: E402


class ImagePipelineTests(unittest.TestCase):
    def test_two_objects_from_one_photo_and_unsafe_entries(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = Image.new("RGB", (400, 200), "white")
            draw = ImageDraw.Draw(image)
            draw.rectangle((10, 10, 170, 180), fill="red")
            draw.rectangle((225, 15, 390, 190), fill="blue")
            buf = io.BytesIO()
            image.save(buf, format="PNG")
            archive = root / "input.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr("folder/frame.png", buf.getvalue())
                z.writestr("../unsafe.png", buf.getvalue())
                z.writestr("notes.txt", "untrusted text")
            run = root / "run"
            unpack(archive, run)
            data = json.loads((run / "photos.json").read_text(encoding="utf-8"))
            self.assertEqual(len(data["photos"]), 1)
            self.assertEqual(len(data["skipped"]), 2)
            self.assertEqual((data["photos"][0]["width"], data["photos"][0]["height"]), (400, 200))
            boxes_file = root / "boxes.json"
            boxes_file.write_text(json.dumps({"boxes": [
                {"item_id": "V001", "photo_id": "PHOTO001", "box": [10, 10, 171, 181]},
                {"item_id": "V002", "photo_id": "PHOTO001", "box": [225, 15, 391, 191]},
            ]}), encoding="utf-8")
            crop(run, boxes_file)
            crops = json.loads((run / "crops.json").read_text(encoding="utf-8"))
            self.assertEqual(len(crops["crops"]), 2)
            self.assertTrue((run / "crops/V001.jpg").is_file())
            self.assertTrue((run / "crops/V002.jpg").is_file())
            with Image.open(run / "crops/V001.jpg") as first:
                self.assertEqual(first.size, (161, 171))
            with Image.open(run / "crops/V002.jpg") as second:
                self.assertEqual(second.size, (166, 176))

    def test_duplicate_ids_do_not_overwrite(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            run = root / "run"
            (run / "photos").mkdir(parents=True)
            Image.new("RGB", (10, 10), "white").save(run / "photos/PHOTO001.jpg")
            (run / "photos.json").write_text(json.dumps({"photos": [
                {"photo_id": "PHOTO001", "path": "photos/PHOTO001.jpg",
                 "source_name": "photo.jpg", "width": 10, "height": 10}
            ]}), encoding="utf-8")
            boxes = root / "boxes.json"
            boxes.write_text(json.dumps({"boxes": [
                {"item_id": "V001", "photo_id": "PHOTO001", "box": [0, 0, 5, 5]},
                {"item_id": "V001", "photo_id": "PHOTO001", "box": [5, 5, 10, 10]},
            ]}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate"):
                crop(run, boxes)


if __name__ == "__main__":
    unittest.main()
