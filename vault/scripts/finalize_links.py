#!/usr/bin/env python3
"""Add native Excel hyperlinks to an artifact-tool XLSX (stdlib OOXML repair).

Usage: python finalize_links.py inventory.xlsx items.json. This repairs an
artifact-tool limitation: HYPERLINK() formulas currently cache an error.
"""

from __future__ import annotations

import json
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

SHEET = "xl/worksheets/sheet1.xml"
RELS = "xl/worksheets/_rels/sheet1.xml.rels"
MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
DOC_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
HYPERLINK = DOC_REL + "/hyperlink"
ET.register_namespace("x", MAIN)
ET.register_namespace("r", DOC_REL)
ET.register_namespace("", PKG_REL)


def finish(book_path: Path, entries: list[dict]) -> None:
    if not entries:
        return
    for entry in entries:
        if not re.fullmatch(r"E[1-9][0-9]*", entry["cell"]):
            raise ValueError("Hyperlink cell must be in column E")
        if not re.fullmatch(r"https://[^\s]+", entry["url"]):
            raise ValueError("Invalid HTTPS link")
    with zipfile.ZipFile(book_path) as book:
        sheet = ET.fromstring(book.read(SHEET))
        if RELS in book.namelist():
            rels = ET.fromstring(book.read(RELS))
        else:
            rels = ET.Element(f"{{{PKG_REL}}}Relationships")
        ids = {entry.get("Id") for entry in rels}
        present = {cell.get("r"): cell for cell in sheet.iter(f"{{{MAIN}}}c")}
        links = sheet.find(f"{{{MAIN}}}hyperlinks")
        if links is None:
            links = ET.Element(f"{{{MAIN}}}hyperlinks")
            before = next((i for i, node in enumerate(sheet)
                           if node.tag in {f"{{{MAIN}}}drawing", f"{{{MAIN}}}tableParts"}), len(sheet))
            sheet.insert(before, links)
        for number, entry in enumerate(entries, 1):
            cell_id = entry["cell"]
            if cell_id not in present:
                raise ValueError(f"Missing link cell: {cell_id}")
            cell = present[cell_id]
            for child in list(cell):
                if child.tag in {f"{{{MAIN}}}f", f"{{{MAIN}}}v", f"{{{MAIN}}}is"}:
                    cell.remove(child)
            cell.set("t", "str")
            ET.SubElement(cell, f"{{{MAIN}}}v").text = "Open price source"
            ident = f"rIdVault{number}"
            while ident in ids:
                number += 1
                ident = f"rIdVault{number}"
            ids.add(ident)
            ET.SubElement(rels, f"{{{PKG_REL}}}Relationship", {
                "Id": ident, "Type": HYPERLINK, "Target": entry["url"], "TargetMode": "External",
            })
            ET.SubElement(links, f"{{{MAIN}}}hyperlink", {
                "ref": cell_id, f"{{{DOC_REL}}}id": ident, "display": "Open price source",
            })
        replacements = {
            SHEET: ET.tostring(sheet, encoding="utf-8", xml_declaration=True),
            RELS: ET.tostring(rels, encoding="utf-8", xml_declaration=True),
        }
        handle, temp_name = tempfile.mkstemp(prefix=".vault-links-", suffix=".xlsx", dir=book_path.parent)
        os.close(handle)
        try:
            with zipfile.ZipFile(temp_name, "w") as output:
                for info in book.infolist():
                    output.writestr(info, replacements.pop(info.filename, book.read(info.filename)))
                for name, payload in replacements.items():
                    output.writestr(name, payload, compress_type=zipfile.ZIP_DEFLATED)
        except Exception:
            if os.path.exists(temp_name):
                os.unlink(temp_name)
            raise
    try:
        os.replace(temp_name, book_path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Usage: finalize_links.py output.xlsx items.json")
    manifest = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    entries = [{"cell": f"E{i + 7}", "url": row["value_url"]}
               for i, row in enumerate(manifest["items"]) if row.get("value_url")]
    finish(Path(sys.argv[1]), entries)
