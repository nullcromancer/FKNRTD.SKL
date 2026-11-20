import hashlib,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault

class RebindTests(unittest.TestCase):
 def test_rebind_restores_missing_scanned_photo_and_archive_without_deleting_source(self):
  root=Path(tempfile.mkdtemp()); external=Path(tempfile.mkdtemp())/'Scanned'
  photo=b'public-test-photo-bytes'; archive=b'public-test-zip-bytes'; external.mkdir()
  (external/'photo.jpg').write_bytes(photo); (external/'Archives').mkdir(); (external/'Archives'/'batch.zip').write_bytes(archive)
  with vault.open_catalog(root) as db:
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token) values('p','Staging/photo.jpg',?,'archived','Scanned/photo.jpg','t')",(hashlib.sha256(photo).hexdigest(),))
   db.execute("insert into archives(id,source,sha256,state,destination) values('a','Staging/batch.zip',?,'archived','Scanned/Archives/batch.zip')",(hashlib.sha256(archive).hexdigest(),))
  result=vault.rebind_scanned(root,external)
  self.assertEqual(len(result['restored']),2); self.assertEqual(result['missing'],[])
  self.assertEqual((root/'Scanned/photo.jpg').read_bytes(),photo)
  self.assertEqual((root/'Scanned/Archives/batch.zip').read_bytes(),archive)
  self.assertEqual((external/'photo.jpg').read_bytes(),photo)
  with vault.open_catalog(root) as db: self.assertTrue(vault.check_catalog(root,db)['integrity']=='ok')

 def test_rebind_reports_missing_and_refuses_destination_conflict(self):
  root=Path(tempfile.mkdtemp()); external=Path(tempfile.mkdtemp())/'Scanned'; external.mkdir()
  wanted=b'wanted'; wrong=b'wrong'; (external/'candidate.bin').write_bytes(wrong)
  with vault.open_catalog(root) as db:
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token) values('missing','x',?,'archived','Scanned/not-there.jpg','t')",(hashlib.sha256(wanted).hexdigest(),))
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token) values('conflict','y',?,'archived','Scanned/conflict.jpg','t')",(hashlib.sha256(wrong).hexdigest(),))
  result=vault.rebind_scanned(root,external)
  self.assertEqual(len(result['missing']),1); self.assertTrue((root/'Scanned/conflict.jpg').is_file())
  self.assertEqual((root/'Scanned/conflict.jpg').read_bytes(),wrong)
  # An existing destination with a different hash must never be overwritten.
  (root/'Scanned/not-there.jpg').parent.mkdir(parents=True,exist_ok=True); (root/'Scanned/not-there.jpg').write_bytes(wrong)
  (external/'candidate.bin').write_bytes(wanted)
  with self.assertRaisesRegex(RuntimeError,'Refusing to overwrite'):
   vault.rebind_scanned(root,external)
  self.assertEqual((root/'Scanned/not-there.jpg').read_bytes(),wrong)

if __name__=='__main__': unittest.main()
