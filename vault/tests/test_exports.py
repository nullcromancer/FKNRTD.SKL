import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault

class ExportTests(unittest.TestCase):
 def test_empty_exports_formats(self):
  root=Path(tempfile.mkdtemp()); (root/'Catalog').mkdir(); dbpath=root/'Catalog/Vault.sqlite'
  # Initialize through the public catalog context.
  with vault.open_catalog(root): pass
  for fmt,suffix in [('json','.json'),('csv','.csv'),('html','.html'),('xls','.xls'),('xlsx','.xlsx')]:
   out=root/('inventory'+suffix); vault.export_catalog(root,fmt,out); self.assertTrue(out.exists())
   if fmt=='json': self.assertIn('schema_version',out.read_text())
   if fmt=='xls': self.assertEqual(out.read_bytes()[:8],b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1')
   if fmt=='xlsx': self.assertTrue(out.read_bytes().startswith(b'PK'))
  self.assertIn('name', (root/'inventory.csv').read_text(encoding='utf-8-sig').splitlines()[0])
  html=(root/'inventory.html').read_text(encoding='utf-8')
  self.assertIn('Sort',html); self.assertNotIn('https://cdn',html)
 def test_spreadsheets_embed_image_and_link(self):
  from PIL import Image
  import openpyxl,xlrd,olefile
  root=Path(tempfile.mkdtemp());
  with vault.open_catalog(root) as db:
   image='Images/item.jpg'; Image.new('RGB',(30,40),'red').save(root/'Catalog'/image)
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('item','Sample','Cards','Card',90,'{}',?)",(image,))
   db.execute("insert into valuations(id,item_id,estimate_cents,source_url,basis,confidence) values('v','item',100,'https://example.org/sale','sold',80)")
  xlsx=root/'out.xlsx'; vault.export_catalog(root,'xlsx',xlsx)
  wb=openpyxl.load_workbook(xlsx); ws=wb.active
  self.assertTrue(any(c.hyperlink for row in ws.iter_rows() for c in row)); self.assertEqual(len(ws._images),1)
  xls=root/'out.xls'; vault.export_catalog(root,'xls',xls); book=xlrd.open_workbook(xls); sheet=book.sheet_by_index(0)
  self.assertIn('Sample',[sheet.cell_value(1,c) for c in range(sheet.ncols)])
  ole=olefile.OleFileIO(str(xls)); stream=ole.openstream('Workbook').read(); ole.close()
  self.assertIn(b'\x7f\x00',stream)  # BIFF IMDATA record for embedded bitmap
  page=root/'catalog.html'; vault.export_catalog(root,'html',page); text=page.read_text(encoding='utf-8')
  self.assertIn('data:image/jpeg;base64,',text); self.assertNotIn('src="Images/',text)
 def test_spreadsheet_row_limit_splits_sheets(self):
  import openpyxl,xlrd
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db:
   for n in range(5): db.execute('insert into items(id,name,category,type,confidence,metadata,primary_image) values(?,?,?,?,?,?,?)',(f'i{n}',f'Item {n}','x','y',50,'{}',''))
  old_xls,old_xlsx=vault.XLS_MAX_DATA_ROWS,vault.XLSX_MAX_DATA_ROWS
  try:
   vault.XLS_MAX_DATA_ROWS=2; vault.XLSX_MAX_DATA_ROWS=2
   xls=root/'split.xls'; xlsx=root/'split.xlsx'; vault.export_catalog(root,'xls',xls); vault.export_catalog(root,'xlsx',xlsx)
  finally: vault.XLS_MAX_DATA_ROWS, vault.XLSX_MAX_DATA_ROWS=old_xls,old_xlsx
  self.assertEqual(len(xlrd.open_workbook(xls).sheets()),3)
  self.assertEqual(len(openpyxl.load_workbook(xlsx).sheetnames),3)

if __name__=='__main__': unittest.main()
