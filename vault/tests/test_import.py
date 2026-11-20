import sys,tempfile,unittest
from pathlib import Path
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault

class ImportTests(unittest.TestCase):
 def test_import_idempotent_and_preserves_source(self):
  a=Path(tempfile.mkdtemp()); b=Path(tempfile.mkdtemp())
  with vault.open_catalog(a) as db:
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token,perceptual_hash) values('p','Scanned/a.png','hash','archived','Scanned/a.png','t','0102030405060708')")
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Card','cards','Trading Card',90,'{}','Images/i.jpg')")
   db.execute("insert into observations values('o','p','i',0,'[0,0,2,2]','Images/i.jpg','new',null,null)")
   Image.new('RGB',(2,2),'red').save(a/'Catalog/Images/i.jpg')
   detail_path=a/'Catalog/Images/Details/detail.jpg'; detail_path.parent.mkdir(parents=True); Image.new('RGB',(1,1),'blue').save(detail_path)
   db.execute('insert into detail_assets(id,observation_id,frame,box,path,label,sha256,bytes) values(?,?,?,?,?,?,?,?)',('d','o',0,'[0,0,1,1]','Images/Details/detail.jpg','marking',vault.hashfile(detail_path),detail_path.stat().st_size))
  before=(a/'Catalog/Vault.sqlite').read_bytes()
  vault.import_catalog(b,a); vault.import_catalog(b,a)
  with vault.open_catalog(b) as db:
   self.assertEqual(db.execute('select count(*) from items').fetchone()[0],1)
   self.assertEqual(db.execute('select count(*) from observations').fetchone()[0],1)
   self.assertEqual(db.execute("select perceptual_hash from photos where id='p'").fetchone()[0],'0102030405060708')
   detail=db.execute('select * from detail_assets').fetchone()
   self.assertEqual(detail['label'],'marking'); self.assertTrue((b/'Catalog'/detail['path']).is_file())
  self.assertEqual((a/'Catalog/Vault.sqlite').read_bytes(),before)
 def test_uuid_collision_is_reported_and_preserved(self):
  source=Path(tempfile.mkdtemp()); dest=Path(tempfile.mkdtemp())
  with vault.open_catalog(source) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('same','Source','x','y',50,'{}','')")
  with vault.open_catalog(dest) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('same','Local','x','y',50,'{}','')")
  result=vault.import_catalog(dest,source); self.assertEqual(len(result['conflicts']),1)
  with vault.open_catalog(dest) as db:
   self.assertEqual(db.execute("select name from items where id='same'").fetchone()[0],'Local')
   self.assertEqual(db.execute('select count(*) from items').fetchone()[0],2)
 def test_entity_and_asset_collisions_remap_relationships_idempotently(self):
  source=Path(tempfile.mkdtemp()); dest=Path(tempfile.mkdtemp())
  for root in (source,dest): Image.new('RGB',(3,3),'red' if root==source else 'blue').save(root/'placeholder.png')
  with vault.open_catalog(source) as db:
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token) values('p','Scanned/a.png','h','archived','Scanned/a.png','t')")
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Imported','x','y',80,'{}','Images/same.jpg')")
   db.execute("insert into observations values('o','p','i',0,'[0,0,3,3]','Images/same.jpg','new',null,null)")
   db.execute("insert into evidence(id,item_id,observation_id,url,kind,description) values('e','i','o','https://example.org/id','identity','source')")
   db.execute("insert into valuations(id,item_id,observation_id,estimate_cents,low_cents,high_cents,speculative_cents,source_url,basis,confidence) values('v','i','o',100,90,110,null,'https://example.org/price','sold',75)")
   db.execute("insert into field_locks(item_id,field,reason) values('i','name','manual correction')")
   db.execute("insert into audit(item_id,action,detail) values('i','correction','name verified by owner')")
   Image.new('RGB',(3,3),'red').save(source/'Catalog/Images/same.jpg')
  with vault.open_catalog(dest) as db:
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token) values('p','Scanned/local.png','local','archived','Scanned/local.png','t')")
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Local','x','y',80,'{}','')")
   db.execute("insert into observations values('o','p','i',0,'[0,0,1,1]','Images/same.jpg','new',null,null)")
   db.execute("insert into evidence(id,item_id,url,kind) values('e','i','https://example.org/local','identity')")
   db.execute("insert into valuations(id,item_id,estimate_cents,basis) values('v','i',200,'dealer')")
   Image.new('RGB',(3,3),'blue').save(dest/'Catalog/Images/same.jpg')
  result=vault.import_catalog(dest,source)
  self.assertEqual({x['entity_type'] for x in result['conflicts']},{'item','photo','observation','evidence','valuation'})
  vault.import_catalog(dest,source)
  with vault.open_catalog(dest) as db:
   item=db.execute("select id,primary_image from items where name='Imported'").fetchone()
   obs=db.execute('select id,item_id,photo_id,image from observations where item_id=?',(item['id'],)).fetchone()
   ev=db.execute("select id,observation_id from evidence where item_id=? and url='https://example.org/id'",(item['id'],)).fetchone()
   val=db.execute("select id,observation_id from valuations where item_id=? and estimate_cents=100",(item['id'],)).fetchone()
   self.assertNotEqual(item['id'],'i'); self.assertNotEqual(obs['id'],'o'); self.assertNotEqual(obs['photo_id'],'p')
   self.assertEqual(ev['observation_id'],obs['id']); self.assertEqual(val['observation_id'],obs['id'])
   self.assertEqual(item['primary_image'],obs['image']); self.assertEqual(vault.hashfile(dest/'Catalog'/obs['image']),vault.hashfile(source/'Catalog/Images/same.jpg'))
   self.assertEqual(db.execute("select reason from field_locks where item_id=? and field='name'",(item['id'],)).fetchone()[0],'manual correction')
   self.assertEqual(db.execute("select count(*) from audit where item_id=? and action='correction'",(item['id'],)).fetchone()[0],1)
   self.assertEqual(db.execute('select count(*) from items').fetchone()[0],2)
   self.assertEqual(db.execute('pragma foreign_key_check').fetchall(),[])
 def test_imported_merge_can_be_undone(self):
  source=Path(tempfile.mkdtemp()); dest=Path(tempfile.mkdtemp())
  with vault.open_catalog(source) as db:
   for item in ('a','b'): db.execute('insert into items(id,name,category,type,confidence,metadata,primary_image) values(?,?,?,?,?,?,?)',(item,item,'x','y',50,'{}',''))
  vault.merge_items(source,'a','b','same object verified')
  vault.import_catalog(dest,source)
  with vault.open_catalog(dest) as db:
   mapped={r['source_item_id']:r['local_item_id'] for r in db.execute('select source_item_id,local_item_id from item_origins')}
   self.assertEqual(db.execute('select active from items where id=?',(mapped['a'],)).fetchone()[0],0)
  vault.merge_items(dest,mapped['a'],'',undo=True)
  with vault.open_catalog(dest) as db: self.assertEqual(db.execute('select active from items where id=?',(mapped['a'],)).fetchone()[0],1)
 def test_import_preserves_comparable_with_uuid_collision(self):
  source=Path(tempfile.mkdtemp()); dest=Path(tempfile.mkdtemp())
  with vault.open_catalog(source) as db:
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Source','x','y',70,'{}','')")
   db.execute("insert into evidence(id,item_id,url,kind) values('e','i','https://example.org/sold','valuation')")
   db.execute("insert into valuations(id,item_id,estimate_cents,source_url,basis,methodology,rationale) values('v','i',1000,'https://example.org/sold','sold','limited_sold','one sale')")
   db.execute("insert into valuation_comparables(id,valuation_id,item_id,source_url,sale_basis,original_amount,currency,quantity,normalized_unit_cents,adjusted_unit_cents) values('c','v','i','https://example.org/sold','sold','10.00','USD',1,1000,1000)")
  with vault.open_catalog(dest) as db:
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Local','x','y',70,'{}','')")
   db.execute("insert into valuations(id,item_id,estimate_cents,basis) values('v','i',500,'dealer')")
   db.execute("insert into valuation_comparables(id,valuation_id,item_id,source_url,sale_basis,original_amount,currency,quantity,normalized_unit_cents,adjusted_unit_cents) values('c','v','i','https://example.org/local','dealer','5.00','USD',1,500,500)")
  result=vault.import_catalog(dest,source); self.assertIn('comparable',{x['entity_type'] for x in result['conflicts']})
  vault.import_catalog(dest,source)
  with vault.open_catalog(dest) as db:
   row=db.execute("select vc.id,vc.adjusted_unit_cents from valuation_comparables vc join items i on i.id=vc.item_id where i.name='Source'").fetchone()
   self.assertNotEqual(row['id'],'c'); self.assertEqual(row['adjusted_unit_cents'],1000)

if __name__=='__main__': unittest.main()
