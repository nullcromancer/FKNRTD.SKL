"""Integration smoke test; requires Codex artifact-tool runtime."""

import json
import os
import shutil
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path

from PIL import Image

SKILL = Path(__file__).resolve().parents[1]


class WorkbookTests(unittest.TestCase):
    @unittest.skipUnless(os.environ.get("CODEX_PRIMARY_RUNTIME_NODE_MODULES"), "Codex artifact-tool unavailable")
    def test_embedded_crops_and_price_links(self):
        with tempfile.TemporaryDirectory() as directory:
            run = Path(directory)
            (run / "crops").mkdir()
            for item_id, color in (("V001", "red"), ("V002", "blue")):
                Image.new("RGB", (150, 100), color).save(run / "crops" / (item_id + ".jpg"))
            rows = []
            for i, item_id in enumerate(("V001", "V002")):
                rows.append({
                    "item_id": item_id, "crop": f"crops/{item_id}.jpg",
                    "source_photo": "PHOTO001 | photo.jpg",
                    "item_name": f"Test object {i+1}", "item_type": "Test item",
                    "value_estimate": 12 + i, "value_low": 10 + i, "value_high": 15 + i,
                    "value_url": f"https://example.org/comp/{i+1}",
                    "id_confidence": 0.8, "match_specificity": "likely",
                    "price_basis": "sold", "notes": "Synthetic smoke-test data",
                })
            input_path = run / "items.json"
            input_path.write_text(json.dumps({
                "batch_id": "test", "research_date": "2026-10-28",
                "market": "US secondhand resale", "currency": "USD", "items": rows
            }), encoding="utf-8")
            shutil.copy2(SKILL / "scripts/build_workbook.mjs", run / "build_workbook.mjs")
            shutil.copy2(SKILL / "scripts/finalize_links.py", run / "finalize_links.py")
            (run / "node_modules").symlink_to(os.environ["CODEX_PRIMARY_RUNTIME_NODE_MODULES"], target_is_directory=True)
            output_path = run / "inventory.xlsx"
            node = os.environ.get("CODEX_PRIMARY_RUNTIME_NODE", "node")
            proc = subprocess.run([node, str(run / "build_workbook.mjs"), str(input_path), str(output_path)],
                                  capture_output=True, text=True, timeout=60)
            self.assertEqual(proc.returncode, 0, proc.stderr + "\n" + proc.stdout)
            fix = subprocess.run([os.environ.get("CODEX_PRIMARY_RUNTIME_PYTHON", "python3"),
                                  str(run / "finalize_links.py"), str(output_path), str(input_path)],
                                 capture_output=True, text=True, timeout=20)
            self.assertEqual(fix.returncode, 0, fix.stderr)
            self.assertTrue(output_path.is_file())
            with zipfile.ZipFile(output_path) as book:
                media = [f for f in book.namelist() if f.startswith("xl/media/")]
                self.assertEqual(len(media), 2)
                text = book.read("xl/worksheets/sheet1.xml").decode("utf-8")
                self.assertIn('ref="E7"', text)
                self.assertIn('ref="E8"', text)
                rels = book.read("xl/worksheets/_rels/sheet1.xml.rels").decode("utf-8")
                self.assertIn("https://example.org/comp/1", rels)
                self.assertIn("https://example.org/comp/2", rels)


if __name__ == "__main__":
    unittest.main()
