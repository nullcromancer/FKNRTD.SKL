#!/usr/bin/env node
/**
 * Vault inventory XLSX generator. Run with the Codex primary runtime's Node,
 * with @oai/artifact-tool resolvable in node_modules.
 * Usage: node build_workbook.mjs RUN_DIR/items.json RUN_DIR/vault.xlsx
 */
import fs from "node:fs/promises";
import path from "node:path";
import { SpreadsheetFile, Workbook } from "@oai/artifact-tool";

const [inputFile, outputFile] = process.argv.slice(2);
if (!inputFile || !outputFile) {
  throw new Error("Usage: node build_workbook.mjs items.json output.xlsx");
}
if (path.extname(outputFile).toLowerCase() !== ".xlsx") {
  throw new Error("Output must have .xlsx extension; legacy .xls needs verified conversion.");
}
const input = JSON.parse(await fs.readFile(inputFile, "utf8"));
const root = path.dirname(path.resolve(inputFile));
const items = input.items;
if (!Array.isArray(items) || !items.length) throw new Error("items must be a nonempty array");
if (input.currency !== "USD") throw new Error("This workbook formatter expects currency USD");
const allowedSpecificity = new Set(["exact", "likely", "generic", "unknown"]);
const allowedBases = new Set(["sold", "dealer", "asking", "retail", "unavailable"]);
const ids = new Set();
const checked = [];

function isMoney(x) {
  return x === null || (typeof x === "number" && Number.isFinite(x) && x >= 0);
}
function cleanText(value) {
  const text = String(value ?? "");
  return /^[=+@\-\t\r]/.test(text) ? "'" + text : text;
}
function safePath(relative) {
  if (typeof relative !== "string" || path.isAbsolute(relative)) throw new Error("Invalid image path");
  const file = path.resolve(root, relative);
  if (!file.startsWith(root + path.sep)) throw new Error("Image path leaves run directory");
  return file;
}
for (const [idx, row] of items.entries()) {
  const tag = `Item ${idx + 1}`;
  if (!/^V\d{3,6}$/.test(row.item_id) || ids.has(row.item_id)) throw new Error(`${tag}: duplicate/invalid ID`);
  ids.add(row.item_id);
  if (!row.item_name || !row.item_type || !row.source_photo) throw new Error(`${tag}: missing identity/category/source`);
  if (!allowedSpecificity.has(row.match_specificity)) throw new Error(`${tag}: invalid specificity`);
  if (!allowedBases.has(row.price_basis)) throw new Error(`${tag}: invalid price basis`);
  if (typeof row.id_confidence !== "number" || row.id_confidence < 0 || row.id_confidence > 1)
    throw new Error(`${tag}: confidence must be 0..1`);
  for (const field of ["value_estimate", "value_low", "value_high"]) {
    if (!isMoney(row[field] ?? null)) throw new Error(`${tag}: invalid ${field}`);
  }
  if (row.value_url && !/^https:\/\/[^\s]+$/.test(row.value_url))
    throw new Error(`${tag}: invalid evidence URL`);
  if (row.value_estimate != null) {
    if (!row.value_url) throw new Error(`${tag}: valued item needs HTTPS evidence URL`);
    if (row.price_basis === "unavailable") throw new Error(`${tag}: value cannot have unavailable basis`);
  } else if (row.value_low != null || row.value_high != null) {
    throw new Error(`${tag}: value range without central estimate`);
  }
  if (row.value_low != null && row.value_high != null && row.value_low > row.value_high)
    throw new Error(`${tag}: lower value exceeds upper`);
  if (row.value_estimate != null && row.value_low != null && row.value_estimate < row.value_low)
    throw new Error(`${tag}: estimated value lower than range`);
  if (row.value_estimate != null && row.value_high != null && row.value_estimate > row.value_high)
    throw new Error(`${tag}: estimated value higher than range`);
  const file = safePath(row.crop);
  const bytes = await fs.readFile(file);
  if (bytes.length > 15_000_000) throw new Error(`${tag}: image too large`);
  const ext = path.extname(file).toLowerCase();
  const mime = ext === ".png" ? "image/png" : ext === ".jpg" || ext === ".jpeg" ? "image/jpeg" : null;
  if (!mime) throw new Error(`${tag}: crop must be PNG or JPG`);
  checked.push({ ...row, imageData: `data:${mime};base64,${bytes.toString("base64")}` });
}

const wb = Workbook.create();
const sheet = wb.worksheets.add("Inventory");
sheet.showGridLines = false;
sheet.tabColor = "#132c25";
sheet.getRange("A2").values = [["VAULT | Item inventory"]];
sheet.getRange("A3").values = [[`Batch: ${cleanText(input.batch_id || "unspecified")}  |  Research: ${cleanText(input.research_date || "unspecified")}  |  ${cleanText(input.market || "US secondhand resale")}  |  USD`]];
sheet.getRange("A4").values = [["Values are approximate resale estimates; identification and condition may require verification."]];
const headers = ["Item photo", "Item name", "Item type", "Approx. value (USD)", "Value source",
  "ID confidence", "Low estimate (USD)", "High estimate (USD)", "Match specificity",
  "Price basis", "Source photo", "Notes", "Item ID"];
sheet.getRange("A6:M6").values = [headers];
const header = sheet.getRange("A6:M6");
header.format.fill = "#1a2725";
header.format.font.color = "#ffffff";
header.format.font.bold = true;
header.format.rowHeightPx = 35;
header.format.verticalAlignment = "center";
header.format.horizontalAlignment = "center";
header.format.wrapText = true;
sheet.getRange("A2").format.font.bold = true;
sheet.getRange("A2").format.font.size = 15;
sheet.getRange("A3:A4").format.font.color = "#52625c";
const widths = [142, 260, 165, 140, 155, 105, 133, 133, 120, 104, 225, 290, 75];
for (let col = 0; col < widths.length; col++) {
  sheet.getRangeByIndexes(5, col, checked.length + 1, 1).format.columnWidthPx = widths[col];
}
for (let i = 0; i < checked.length; i++) {
  const row = checked[i];
  const excelRow = i + 7;
  sheet.getRange(`A${excelRow}:M${excelRow}`).values = [[null,
    cleanText(row.item_name), cleanText(row.item_type), row.value_estimate ?? null,
    row.value_url ? "Open source" : "Not found", row.id_confidence,
    row.value_low ?? null, row.value_high ?? null, row.match_specificity,
    row.price_basis, cleanText(row.source_photo), cleanText(row.notes),
    row.item_id]];
  sheet.getRange(`A${excelRow}:M${excelRow}`).format.rowHeightPx = 112;
  sheet.getRange(`A${excelRow}:M${excelRow}`).format.verticalAlignment = "center";
  if (i % 2 === 1) sheet.getRange(`A${excelRow}:M${excelRow}`).format.fill = "#f2f5f3";
  sheet.getRange(`B${excelRow}:C${excelRow}`).format.wrapText = true;
  sheet.getRange(`K${excelRow}:L${excelRow}`).format.wrapText = true;
  sheet.images.add({ dataUrl: row.imageData,
    anchor: { from: { row: excelRow - 1, col: 0, rowOffsetPx: 4, colOffsetPx: 5 },
      extent: { widthPx: 132, heightPx: 102 } } });
}
const last = checked.length + 6;
sheet.getRange(`D7:D${last}`).setNumberFormat('"$"#,##0.00');
sheet.getRange(`F7:F${last}`).setNumberFormat("0%");
sheet.getRange(`G7:H${last}`).setNumberFormat('"$"#,##0.00');
sheet.freezePanes.freezeRows(6);
const table = sheet.tables.add(`A6:M${last}`, true, "VaultInventory");
table.showFilterButton = true;
wb.recalculate();
const inspect = await wb.inspect({kind: "table", range: `Inventory!B6:M${Math.min(last, 9)}`,
  include: "values,formulas", tableMaxRows: 4, tableMaxCols: 12, maxChars: 3500});
console.log(inspect.ndjson);
await fs.mkdir(path.dirname(path.resolve(outputFile)), { recursive: true });
const output = await SpreadsheetFile.exportXlsx(wb);
await output.save(outputFile);
console.log(`Wrote ${checked.length} rows and images to ${outputFile}; run finalize_links.py for clickable URLs`);
