import sys, tempfile, unittest, zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault
from unittest.mock import patch
import io
from PIL import Image

class ZipTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(tempfile.mkdtemp()); (self.root/'Staging').mkdir()
    def test_extract_provenance_and_resume(self):
        z=self.root/'Staging/cards.zip'
        with zipfile.ZipFile(z,'w') as f: f.writestr('binder/card.txt','payload')
        with vault.open_catalog(self.root) as db:
            result=vault.ingest_zip(self.root,db,z,vault.hashfile(z))
            self.assertEqual(result['state'],'members_pending')
            row=db.execute('select * from archive_members').fetchone()
            self.assertEqual(row['member_name'],'binder/card.txt')
            self.assertEqual((self.root/row['extracted_path']).read_bytes(),b'payload')
            self.assertEqual(vault.ingest_zip(self.root,db,z,vault.hashfile(z))['resumed'],True)
    def test_reject_traversal(self):
        z=self.root/'Staging/bad.zip'
        with zipfile.ZipFile(z,'w') as f: f.writestr('../escape.txt','bad')
        with vault.open_catalog(self.root) as db:
            self.assertEqual(vault.ingest_zip(self.root,db,z,vault.hashfile(z))['state'],'rejected')
        self.assertFalse((self.root/'escape.txt').exists())
    def test_archive_waits_for_member_disposition(self):
        z=self.root/'Staging/cards.zip'
        b=io.BytesIO(); Image.new('RGB',(30,40),'white').save(b,format='PNG')
        with zipfile.ZipFile(z,'w') as f: f.writestr('card.png',b.getvalue())
        with vault.open_catalog(self.root) as db:
            vault.ingest_zip(self.root,db,z,vault.hashfile(z)); j=vault.claim(self.root,db)['job']
            manifest={'photo_id':j['id'],'claim_token':j['claim_token'],'visual_inspection_complete':True,'items':[]}
            result=vault.commit(self.root,db,manifest)
            self.assertFalse(result['warnings']); self.assertFalse(z.exists())
            self.assertTrue((self.root/'Scanned/Archives/cards.zip').exists())
            self.assertEqual(db.execute('select disposition from archive_members').fetchone()[0],'scanned')
    def test_partial_completion_then_resume(self):
        z=self.root/'Staging/two.zip'; buf=io.BytesIO(); Image.new('RGB',(30,40),'white').save(buf,format='PNG')
        buf2=io.BytesIO(); Image.new('RGB',(31,40),'white').save(buf2,format='PNG')
        with zipfile.ZipFile(z,'w') as f: f.writestr('a.png',buf.getvalue()); f.writestr('b.png',buf2.getvalue())
        with vault.open_catalog(self.root) as db:
            vault.ingest_zip(self.root,db,z,vault.hashfile(z)); j=vault.claim(self.root,db)['job']
            vault.commit(self.root,db,{'photo_id':j['id'],'claim_token':j['claim_token'],'visual_inspection_complete':True,'items':[]})
            self.assertTrue(z.exists()); self.assertEqual(db.execute("select count(*) from archive_members where disposition='pending'").fetchone()[0],1)
        with vault.open_catalog(self.root) as db:
            j=vault.claim(self.root,db)['job']; vault.commit(self.root,db,{'photo_id':j['id'],'claim_token':j['claim_token'],'visual_inspection_complete':True,'items':[]})
            self.assertFalse(z.exists()); self.assertEqual(db.execute("select count(*) from archive_members where disposition='scanned'").fetchone()[0],2)
    def test_duplicate_member_names_get_distinct_paths(self):
        z=self.root/'Staging/dupes.zip'; buf=io.BytesIO(); Image.new('RGB',(30,40),'white').save(buf,format='PNG')
        with zipfile.ZipFile(z,'w') as f: f.writestr('same.png',buf.getvalue()); f.writestr('same.png',buf.getvalue())
        with vault.open_catalog(self.root) as db:
            out=vault.ingest_zip(self.root,db,z,vault.hashfile(z)); self.assertEqual(out['state'],'members_pending')
            rows=db.execute('select member_index,extracted_path from archive_members order by member_index').fetchall()
            self.assertEqual(len(rows),2); self.assertNotEqual(rows[0]['extracted_path'],rows[1]['extracted_path'])
    def test_corrupt_and_unsupported_members_terminal_without_loss(self):
        z=self.root/'Staging/mixed.zip'
        with zipfile.ZipFile(z,'w') as f: f.writestr('bad.png',b'broken image'); f.writestr('notes.txt',b'keep me')
        with vault.open_catalog(self.root) as db:
            vault.ingest_zip(self.root,db,z,vault.hashfile(z));
            for _ in range(6):
                job=vault.claim(self.root,db)
                if db.execute("select count(*) from archive_members where disposition='pending'").fetchone()[0]==0: break
            rows=db.execute('select member_name,disposition from archive_members order by member_name').fetchall()
            self.assertEqual({r['disposition'] for r in rows},{'failed','unsupported'})
            self.assertFalse(z.exists()); self.assertTrue((self.root/'Staging/.vault-zip'/db.execute('select id from archives').fetchone()[0]/'notes.txt').exists())
            self.assertTrue((self.root/'Scanned/Archives/mixed.zip').exists())
    def test_archive_name_collision_and_failed_move_retry(self):
        z=self.root/'Staging/name.zip'; buf=io.BytesIO(); Image.new('RGB',(30,40),'white').save(buf,format='PNG')
        with zipfile.ZipFile(z,'w') as f: f.writestr('x.png',buf.getvalue())
        (self.root/'Scanned/Archives').mkdir(parents=True); (self.root/'Scanned/Archives/name.zip').write_bytes(b'preserve')
        with vault.open_catalog(self.root) as db:
            vault.ingest_zip(self.root,db,z,vault.hashfile(z)); j=vault.claim(self.root,db)['job']
            with patch.object(vault,'copy_archive',side_effect=OSError('injected archive move failure')):
                result=vault.commit(self.root,db,{'photo_id':j['id'],'claim_token':j['claim_token'],'visual_inspection_complete':True,'items':[]})
                self.assertTrue(any('injected' in x['error'] for x in result['warnings']))
            self.assertTrue(z.exists()); self.assertEqual((self.root/'Scanned/Archives/name.zip').read_bytes(),b'preserve')
            self.assertFalse(vault.recover(self.root,db)); self.assertFalse(z.exists())
            dest=db.execute("select destination from archives").fetchone()[0]
            self.assertNotEqual(dest,'Scanned/Archives/name.zip'); self.assertTrue((self.root/dest).exists())
    def test_pending_archive_destinations_are_reserved(self):
        with vault.open_catalog(self.root) as db:
            db.execute("insert into archives(id,source,sha256,state,destination) values('a','Staging/a.zip','a','members_pending','Scanned/Archives/same.zip')")
            self.assertNotEqual(vault.reserve(self.root,db,'same.zip','Scanned/Archives'),'Scanned/Archives/same.zip')

if __name__=='__main__': unittest.main()
