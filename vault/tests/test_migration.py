import sqlite3,sys,tempfile,unittest,shutil
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault
from unittest.mock import patch

class MigrationTests(unittest.TestCase):
 def test_failed_migration_rolls_back_and_keeps_verified_backup(self):
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('keep','Keep me','x','y',50,'{}','')")
  skill=Path(tempfile.mkdtemp()); migrations=skill/'migrations'; migrations.mkdir()
  for path in (vault.SKILL/'migrations').glob('*.sql'): shutil.copy2(path,migrations/path.name)
  (migrations/'017.sql').write_text('CREATE TABLE deliberately_broken (',encoding='utf-8')
  with patch.object(vault,'SKILL',skill),patch.object(vault,'SCHEMA_VERSION',17):
   with self.assertRaises(sqlite3.Error):
    with vault.open_catalog(root): pass
  with vault.open_catalog(root) as db:
    self.assertEqual(db.execute('pragma user_version').fetchone()[0],16)
    self.assertEqual(db.execute("select name from items where id='keep'").fetchone()[0],'Keep me')
    self.assertEqual(db.execute('pragma quick_check').fetchone()[0],'ok')
  backups=list((root/'Catalog/Backups').glob('Vault-before-migration-*.sqlite'))
  self.assertEqual(len(backups),1)
  backup=sqlite3.connect(backups[0])
  try: self.assertEqual(backup.execute('pragma user_version').fetchone()[0],16); self.assertEqual(backup.execute('pragma quick_check').fetchone()[0],'ok')
  finally: backup.close()
 def test_v1_upgrade_backup(self):
  root=Path(tempfile.mkdtemp()); cat=root/'Catalog'; (cat/'.vault').mkdir(parents=True); (cat/'Backups').mkdir()
  db=sqlite3.connect(cat/'Vault.sqlite'); db.executescript((vault.SKILL/'migrations/001.sql').read_text()); db.execute('pragma user_version=1'); db.commit(); db.close()
  with vault.open_catalog(root) as db:
   self.assertEqual(db.execute('pragma user_version').fetchone()[0],vault.SCHEMA_VERSION); self.assertIsNotNone(db.execute("select value from catalog_meta where key='catalog_uuid'").fetchone())
   self.assertEqual(db.execute('select count(*) from schema_migrations').fetchone()[0],vault.SCHEMA_VERSION)
  self.assertEqual(len(list((cat/'Backups').glob('Vault-before-migration-*.sqlite'))),1)
  with vault.open_catalog(root) as db:
   for view in ('v_inventory','v_current_valuations','v_item_sources','v_review_queue','v_catalog_totals'): self.assertIsNotNone(db.execute('select * from '+view).fetchall())
 def test_verified_backup_restore_preserves_safety_copy(self):
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Before','x','y',50,'{}','')")
  backup=vault.backup_catalog(root)
  with vault.open_catalog(root) as db: db.execute("update items set name='After' where id='i'")
  result=vault.restore_catalog(root,backup)
  with vault.open_catalog(root) as db:
   self.assertEqual(db.execute("select name from items where id='i'").fetchone()[0],'Before')
   self.assertEqual(db.execute('pragma quick_check').fetchone()[0],'ok')
  self.assertTrue(Path(result['safety_backup']).is_file())
 def test_v12_to_v16_migration_adds_taxonomy_scan_runs_and_photo_hashes_with_verified_backup(self):
  root=Path(tempfile.mkdtemp()); cat=root/'Catalog'; (cat/'.vault').mkdir(parents=True); (cat/'Backups').mkdir()
  db=sqlite3.connect(cat/'Vault.sqlite')
  for n in range(1,13): db.executescript((vault.SKILL/'migrations'/f'{n:03}.sql').read_text())
  db.execute('pragma user_version=12')
  db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('old','Legacy item','Collectible','Trading Card',60,'{}','')")
  for n in range(1,13): db.execute('insert into schema_migrations(version,checksum) values(?,?)',(n,__import__('hashlib').sha256((vault.SKILL/'migrations'/f'{n:03}.sql').read_bytes()).hexdigest()))
  db.commit(); db.close()
  with vault.open_catalog(root) as db:
    self.assertEqual(db.execute('pragma user_version').fetchone()[0],16)
    self.assertIsNotNone(db.execute("select name from sqlite_master where type='table' and name='detail_assets'").fetchone())
    self.assertIsNotNone(db.execute("select name from sqlite_master where type='table' and name='taxonomy_nodes'").fetchone())
    self.assertIsNotNone(db.execute("select name from sqlite_master where type='table' and name='scan_runs'").fetchone())
    self.assertIn('perceptual_hash',[r[1] for r in db.execute('pragma table_info(photos)')])
    self.assertEqual(db.execute("select count(*) from item_taxonomy where item_id='old'").fetchone()[0],2)
  backups=list((cat/'Backups').glob('Vault-before-migration-*.sqlite')); self.assertEqual(len(backups),1)
  self.assertEqual(sqlite3.connect(backups[0]).execute('pragma user_version').fetchone()[0],12)

if __name__=='__main__': unittest.main()
