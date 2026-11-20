import sys, tempfile, unittest, sqlite3, shutil
from pathlib import Path
from unittest.mock import patch
from PIL import Image, ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault as v

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        (self.root/'Staging').mkdir()
    def tearDown(self): self.tmp.cleanup()
    def test_doctor_reports_runtime_and_host_capabilities(self):
        report=v.doctor(self.root)
        self.assertEqual(report['schema_version'],v.SCHEMA_VERSION); self.assertEqual(report['database_check']['integrity'],'ok')
        self.assertIn('host agent must verify image inspection',report['capabilities']['visual_identification'])
        self.assertTrue(report['catalog_writable'])
    def test_summary_separates_unknown_and_unvalued_state(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(job,[self.row()]))
        summary=v.catalog_summary(self.root)
        self.assertEqual(summary['active_items'],1); self.assertEqual(summary['unknown_items'],1)
        self.assertEqual(summary['unvalued_items'],1); self.assertEqual(summary['archived_photos'],1)
        with v.open_catalog(self.root) as db:
            self.assertEqual(db.execute('select pending_research from items').fetchone()[0],1)
    def test_detail_crop_is_versioned_and_integrity_checked(self):
        p=self.photo()
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; item=self.row(); item['detail_crops']=[{'box':[10,20,40,60],'label':'signature'}]
            result=v.commit(self.root,db,self.manifest(job,[item])); self.assertEqual(result['created'],1)
            detail=db.execute('select * from detail_assets').fetchone()
            self.assertEqual(detail['label'],'signature'); self.assertTrue(detail['path'].startswith('Images/Details/'))
            with Image.open(self.root/'Catalog'/detail['path']) as im: self.assertEqual(im.size,(30,40))
            self.assertEqual(v.check_catalog(self.root,db)['integrity'],'ok')
    def test_detail_crop_staging_recovers_without_duplicate_rows(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; item=self.row(); item['detail_crops']=[{'box':[10,20,40,60],'label':'serial'}]
            original=v.register_asset; calls={'n':0}
            def fail_detail(*args):
                calls['n']+=1
                if calls['n']==2: raise OSError('injected detail registration interruption')
                return original(*args)
            with patch.object(v,'register_asset',side_effect=fail_detail):
                with self.assertRaises(OSError): v.commit(self.root,db,self.manifest(job,[item]))
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],0)
            self.assertEqual(len(list((self.root/'Catalog/Images').rglob('*.jpg'))),2)
            result=v.commit(self.root,db,self.manifest(job,[item])); self.assertEqual(result['created'],1)
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from detail_assets').fetchone()[0],1)
            self.assertEqual(v.check_catalog(self.root,db)['integrity'],'ok')
    def test_detail_crop_must_be_inside_primary_region(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; item=self.row(); item['detail_crops']=[{'box':[0,0,40,60],'label':'outside'}]
            with self.assertRaises(ValueError): v.commit(self.root,db,self.manifest(job,[item]))
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],0)
    def test_preview_crops_are_claim_bound_and_non_mutating(self):
        source=self.photo()
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']
        result=v.preview_crops(self.root,job['id'],job['claim_token'],[{'frame':0,'box':[5,5,95,135]}],self.root.parent/'vault-preview-test')
        self.assertFalse(result['catalog_mutated']); self.assertFalse(result['source_archived'])
        with Image.open(result['previews'][0]['path']) as im: self.assertEqual(im.size,(90,130))
        self.assertTrue(source.is_file())
        with v.open_catalog(self.root) as db:
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],0)
        with self.assertRaisesRegex(ValueError,'outside the catalog workspace'):
            v.preview_crops(self.root,job['id'],job['claim_token'],[{'box':[5,5,95,135]}],self.root/'Staging/previews')
        with self.assertRaisesRegex(ValueError,'matching token'):
            v.preview_crops(self.root,job['id'],'wrong-token',[{'box':[5,5,95,135]}],self.root.parent/'vault-preview-test')
        self.assertEqual(len(list((self.root/'Catalog/Images').rglob('*.jpg'))),0)
    def test_commit_persists_validated_bounded_research_activity(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; item=self.row()
            item['research_activity']={'queries':[{'query':'visible label Coca-Cola Original Taste eBay sold','source':'Google'},{'query':'Coca-Cola Original Taste 250 ml can eBay','source':'eBay'}],'visited_pages':[{'url':'https://www.ebay.com/itm/123456789012','source':'eBay','query':'Coca-Cola Original Taste 250 ml can eBay','cache_hit':False}]}
            v.commit(self.root,db,self.manifest(job,[item]))
        with v.open_catalog(self.root) as db:
            logs=db.execute("select query,source,visited_url,cache_hit from research_runs where item_id=(select id from items limit 1) order by rowid").fetchall()
            self.assertEqual(len(logs),3); self.assertEqual(logs[0]['source'],'Google'); self.assertEqual(logs[1]['source'],'eBay')
            self.assertEqual(logs[2]['visited_url'],'https://www.ebay.com/itm/123456789012')
            self.assertEqual(logs[2]['cache_hit'],0)
        bad=self.photo('bad-budget.png',40)
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; item=self.row(); item['research_activity']={'queries':[{'query':'q','source':'Google'}]*9}
            with self.assertRaisesRegex(ValueError,'budget exceeded'): v.commit(self.root,db,self.manifest(job,[item]))
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)
            self.assertTrue(bad.is_file())
    def test_scan_run_links_committed_photos_and_closes_with_count(self):
        self.photo(); run=v.start_scan_run(self.root,'Codex','gpt-test')
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; manifest=self.manifest(job,[self.row()]); manifest['scan_run_id']=run['run_id']
            v.commit(self.root,db,manifest)
        result=v.finish_scan_run(self.root,run['run_id'])
        self.assertEqual(result,{'run_id':run['run_id'],'state':'complete','photos':1})
        with v.open_catalog(self.root) as db:
            row=db.execute('select scan_run_id,state from photos').fetchone()
            self.assertEqual(row['scan_run_id'],run['run_id']); self.assertEqual(row['state'],'archived')
            persisted=db.execute('select agent,model,state from scan_runs where id=?',(run['run_id'],)).fetchone()
            self.assertEqual(tuple(persisted),('Codex','gpt-test','complete'))
        with self.assertRaisesRegex(ValueError,'Active scan run'):
            v.finish_scan_run(self.root,run['run_id'])
    def photo(self,name='cards.png',shade=20):
        p=self.root/'Staging'/name; p.parent.mkdir(parents=True,exist_ok=True)
        im=Image.new('RGB',(300,420),(shade,shade,shade)); d=ImageDraw.Draw(im)
        for y in range(3):
            for x in range(3): d.rectangle((x*100+5,y*140+5,x*100+94,y*140+134),fill='white')
        im.save(p); return p
    def row(self,x=0,y=0,exact=False):
        # Synthetic fixture, not actual identification or valuation evidence.
        return {'box':[x*100+5,y*140+5,x*100+95,y*140+135],'name':'Synthetic card' if exact else 'Unknown Item','category':'Collectible','type':'Trading Card','confidence':95 if exact else 20,'specificity':'exact' if exact else 'unknown','identity_key':'fixture-card' if exact else None,'evidence':[{'url':'https://example.org/synthetic','kind':'identity'}] if exact else [],'pending_research':True}
    def manifest(self,job,rows): return {'photo_id':job['id'],'claim_token':job['claim_token'],'visual_inspection_complete':True,'items':rows}
    def test_nine_cards(self):
        p=self.photo(); digest=v.hashfile(p)
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; result=v.commit(self.root,db,self.manifest(j,[self.row(x,y,True) for y in range(3) for x in range(3)]))
            self.assertEqual(result['created'],9); self.assertEqual(db.execute('select count(distinct item_id) from observations').fetchone()[0],9)
            self.assertEqual(len(list((self.root/'Catalog/Images').glob('*.jpg'))),9)
            self.assertEqual(v.hashfile(self.root/'Scanned/cards.png'),digest); self.assertFalse(p.exists())
            for f in (self.root/'Catalog/Images').glob('*.jpg'):
                with Image.open(f) as im: self.assertEqual(im.size,(90,130))
    def test_identical_photo(self):
        p=self.photo(); shutil.copy2(p,self.root/'Staging/copy.png')
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(j,[self.row()])); self.assertIn('deduplicated',v.claim(self.root,db))
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1); self.assertEqual(db.execute('select count(*) from photos where state=\'archived\'').fetchone()[0],2)
    def test_recover_after_commit(self):
        p=self.photo()
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; m=self.manifest(j,[self.row()])
            with patch.object(v,'copy_archive',side_effect=OSError('injected failure')): self.assertTrue(v.commit(self.root,db,m)['warnings'])
            self.assertTrue(p.exists()); self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)
        with v.open_catalog(self.root) as db:
            self.assertFalse(v.recover(self.root,db)); self.assertTrue(v.commit(self.root,db,m)['already_committed']); self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)
    def test_bad_box_no_partial_commit(self):
        p=self.photo()
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; bad=self.row(); bad['box']=[0,0,500,500]
            with self.assertRaises(ValueError): v.commit(self.root,db,self.manifest(j,[self.row(),bad]))
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],0); self.assertTrue(p.exists())
    def test_price_without_evidence_rejected(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; r=self.row(); r['valuation']={'estimate_cents':1000,'basis':'sold'}
            with self.assertRaises(ValueError): v.commit(self.root,db,self.manifest(j,[r]))
    def test_cross_photo_association(self):
        self.photo('a.png'); self.photo('b.png',30)
        with v.open_catalog(self.root) as db:
            a=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(a,[self.row(exact=True)])); first=db.execute('select id from items').fetchone()[0]
            b=v.claim(self.root,db)['job']; row=self.row(exact=True); row['match_item_id']=first
            res=v.commit(self.root,db,self.manifest(b,[row])); self.assertEqual(res['associated'],1); self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)
    def test_same_product_key_reuses_unique_existing_item_by_default(self):
        self.photo('a.png'); self.photo('b.png',30)
        with v.open_catalog(self.root) as db:
            a=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(a,[self.row(exact=True)]))
            b=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(b,[self.row(exact=True)]))
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)
            self.assertEqual(db.execute('select count(*) from observations').fetchone()[0],2)
            self.assertEqual(db.execute('select duplicate_confidence from observations where photo_id=?',(b['id'],)).fetchone()[0],80)
    def test_existing_supported_valuation_is_not_requeued_by_new_photo(self):
        self.photo('a.png'); self.photo('b.png',30)
        with v.open_catalog(self.root) as db:
            a=v.claim(self.root,db)['job']; item=self.row(exact=True)
            item['pending_research']=False
            item['evidence']=[{'url':'https://example.org/item','kind':'identity','description':'matching product record'},{'url':'https://example.org/sale','kind':'valuation','description':'matching completed sale'}]
            item['valuation']={'estimate_cents':1000,'source_url':'https://example.org/sale','basis':'sold','confidence':70,'methodology':'limited_sold','rationale':'One matching completed sale.'}
            v.commit(self.root,db,self.manifest(a,[item]))
            item_id=db.execute('select id from items').fetchone()[0]
            self.assertEqual(db.execute('select pending_research from items where id=?',(item_id,)).fetchone()[0],0)
            b=v.claim(self.root,db)['job']; next_item=self.row(exact=True); next_item['pending_research']=False
            v.commit(self.root,db,self.manifest(b,[next_item]))
            self.assertEqual(db.execute('select pending_research from items where id=?',(item_id,)).fetchone()[0],0)
    def test_distinct_product_instance_stays_separate(self):
        self.photo('a.png'); self.photo('b.png',30)
        with v.open_catalog(self.root) as db:
            a=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(a,[self.row(exact=True)]))
            b=v.claim(self.root,db)['job']; separate=self.row(exact=True); separate['distinct_instance']=True
            v.commit(self.root,db,self.manifest(b,[separate]))
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],2)
    def test_collision(self):
        self.photo(); (self.root/'Scanned').mkdir(); old=self.root/'Scanned/cards.png'; old.write_bytes(b'old')
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(j,[])); self.assertEqual(old.read_bytes(),b'old'); self.assertNotEqual(j['destination'],'Scanned/cards.png')
    def test_corrupt(self):
        (self.root/'Staging/broken.png').write_bytes(b'invalid')
        with v.open_catalog(self.root) as db:
            self.assertIn('failed',v.claim(self.root,db)); self.assertTrue((self.root/'Failed/broken.png').exists())
    def test_resume_claim(self):
        self.photo()
        with v.open_catalog(self.root) as db: j=v.claim(self.root,db)['job']
        with v.open_catalog(self.root) as db: self.assertEqual(v.claim(self.root,db)['job']['id'],j['id'])

    def test_perceptual_hash_suggests_similar_photos_without_merging(self):
        first=self.root/'Staging/first.png'; second=self.root/'Staging/second.png'
        image=Image.new('RGB',(160,220),'white'); draw=ImageDraw.Draw(image)
        draw.rectangle((25,20,135,200),fill='black'); draw.ellipse((55,65,105,115),fill='white')
        image.save(first)
        image.rotate(0.2,resample=Image.Resampling.BICUBIC,fillcolor='white').save(second)
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']
            self.assertEqual(len(job['perceptual_hash']),16)
            v.commit(self.root,db,self.manifest(job,[self.row()]))
            db.execute('update photos set perceptual_hash=NULL where id=?',(job['id'],))
            result=v.claim(self.root,db)
            self.assertEqual(result['job']['source'],'Staging/second.png')
            self.assertTrue(result['near_duplicate_suggestions'])
            suggestion=result['near_duplicate_suggestions'][0]
            self.assertEqual(suggestion['photo_id'],job['id'])
            self.assertLessEqual(suggestion['hamming_distance'],8)
            self.assertEqual(suggestion['identity_decision'],'host_review_required')
            self.assertEqual(len(suggestion['observations']),1)
            self.assertTrue(suggestion['observations'][0]['image'].startswith('Images/'))
            self.assertEqual(v.perceptual_candidates(db,'not-a-hex-hash'),[])
            self.assertNotEqual(db.execute('select sha256 from photos where id=?',(suggestion['photo_id'],)).fetchone()[0],result['job']['sha256'])
            self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)

    def test_multiframe_records_each_frame(self):
        p=self.root/'Staging/multi.tiff'; frames=[Image.new('RGB',(300,420),(i*80,0,0)) for i in range(2)]; frames[0].save(p,save_all=True,append_images=frames[1:])
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; a=self.row(); b=self.row(); b['frame']=1
            v.commit(self.root,db,self.manifest(j,[a,b]))
            self.assertEqual([r[0] for r in db.execute('select frame from observations order by frame')],[0,1])
    def test_normalize_selects_requested_frame(self):
        p=self.root/'Staging/multi.tiff'; frames=[Image.new('RGB',(20,20),(20,0,0)),Image.new('RGB',(20,20),(220,0,0))]; frames[0].save(p,save_all=True,append_images=frames[1:])
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; out=self.root/'frame.png'; v.normalize(self.root,db,job['id'],out,1)
            with Image.open(out) as im: self.assertGreater(im.getpixel((0,0))[0],200)
    def test_rescan_snapshot_verifies_archived_original(self):
        self.photo('archived.png')
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(job,[self.row()]))
            item=db.execute('select id from items').fetchone()[0]
            report=v.rescan_snapshot(self.root,item)
            self.assertEqual(len(report['original_photographs']),1)
            self.assertTrue(Path(report['original_photographs'][0]['path']).is_file())
    def test_asset_integrity_detects_missing_crop(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(j,[self.row()]));
            image=db.execute('select image from observations').fetchone()[0]; (self.root/'Catalog'/image).unlink()
            with self.assertRaises(RuntimeError): v.check_catalog(self.root,db)
    def test_asset_integrity_detects_crop_content_change(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            job=v.claim(self.root,db)['job']; v.commit(self.root,db,self.manifest(job,[self.row()]))
            image=db.execute('select image from observations').fetchone()[0]; Image.new('RGB',(90,130),'black').save(self.root/'Catalog'/image)
            with self.assertRaises(RuntimeError): v.check_catalog(self.root,db)
    def test_perspective_quad_crop(self):
        self.photo()
        with v.open_catalog(self.root) as db:
            j=v.claim(self.root,db)['job']; row=self.row(); row['box']=[5,5,95,135]; row['quad']=[[10,10],[90,6],[94,130],[7,132]]
            v.commit(self.root,db,self.manifest(j,[row]))
            image=db.execute('select image from observations').fetchone()[0]
            with Image.open(self.root/'Catalog'/image) as crop: self.assertGreater(crop.width,70); self.assertGreater(crop.height,100)

if __name__=='__main__': unittest.main()
