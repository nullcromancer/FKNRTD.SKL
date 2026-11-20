import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault

class CacheTests(unittest.TestCase):
 def test_cache_roundtrip(self):
  root=Path(tempfile.mkdtemp()); vault.cache_research(root,'card:abc',{'median_cents':1200},['https://example.org/sale'])
  r=vault.get_cached_research(root,'card:abc'); self.assertTrue(r['cache_hit']); self.assertEqual(r['result']['median_cents'],1200)
  self.assertIsNone(vault.get_cached_research(root,'missing'))
 def test_research_records_append_history_and_validate(self):
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image,pending_research) values('i','Card','Cards','Trading Card',50,'{}','',1)")
  val={'evidence':[{'url':'https://example.org/sold','kind':'valuation','description':'matching completed sale'},{'url':'https://example.org/fx','kind':'valuation','description':'dated exchange rate'}],'valuation':{'estimate_cents':1200,'low_cents':1000,'high_cents':1400,'source_url':'https://example.org/sold','basis':'sold','confidence':70,'methodology':'limited_sold','rationale':'One matching completed sale adjusted for visible condition.','comparables':[{'source_url':'https://example.org/sold','sale_basis':'sold','original_amount':'12.50','currency':'EUR','quantity':1,'sold_at':'2026-01-02','usd_fx_rate':'1.08','fx_source_url':'https://example.org/fx','adjusted_unit_cents':1400,'adjustment_notes':'visible condition adjustment'}]},'research_activity':{'queries':['Maker model sold eBay'],'visited_pages':[{'url':'https://example.org/sold','source':'eBay','query':'Maker model sold eBay'}]}}
  self.assertTrue(vault.record_research(root,'i',val)['valuation_recorded'])
  self.assertIsNotNone(vault.get_cached_research(root,vault.research_key_for_item(root,'i')))
  val['valuation']['estimate_cents']=1500; val['valuation']['low_cents']=1300; val['valuation']['high_cents']=1600
  vault.record_research(root,'i',val)
  with vault.open_catalog(root) as db:
   self.assertEqual(db.execute("select count(*) from valuations where item_id='i'").fetchone()[0],2)
   self.assertEqual(db.execute("select pending_research from items where id='i'").fetchone()[0],0)
   self.assertEqual(db.execute("select count(*) from research_runs where item_id='i'").fetchone()[0],4)
   comp=db.execute("select currency,normalized_unit_cents,adjusted_unit_cents,fx_source_url from valuation_comparables where item_id='i'").fetchone()
   self.assertEqual(tuple(comp),('EUR',1350,1400,'https://example.org/fx'))
   summary=db.execute("select methodology,comparable_count from current_inventory where id='i'").fetchone()
   self.assertEqual(tuple(summary),('limited_sold',1))
  bad={'evidence':[],'valuation':{'estimate_cents':100,'source_url':'https://example.org','basis':'sold'}}
  with self.assertRaises(ValueError): vault.record_research(root,'i',bad)
  excessive={**val,'research_activity':{'queries':['x']*9,'visited_pages':[]}}
  with self.assertRaises(ValueError): vault.record_research(root,'i',excessive)
  invalid={**val,'valuation':{**val['valuation'],'comparables':[{'source_url':'https://example.org/sold','currency':'EUR','original_amount':'10'}]}}
  with self.assertRaises(ValueError): vault.record_research(root,'i',invalid)
 def test_research_without_supported_value_remains_pending(self):
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image,pending_research) values('i','Item','x','y',60,'{}','',0)")
  result={'evidence':[{'url':'https://example.org/listing','kind':'valuation','description':'active new bundle, not comparable'}],'research_activity':{'queries':[{'query':'item sold single eBay','source':'Google'},{'query':'item sale eBay','source':'eBay'}],'visited_pages':[{'url':'https://example.org/listing','source':'eBay','query':'item sale eBay','cache_hit':False}]},'valuation':{'estimate_cents':None,'basis':'unavailable','confidence':None,'rationale':'No directly comparable public sale evidence.','comparables':[]}}
  stored=vault.record_research(root,'i',result)
  self.assertTrue(stored['pending_research'])
  with vault.open_catalog(root) as db:
   self.assertEqual(db.execute("select pending_research from items where id='i'").fetchone()[0],1)
   self.assertEqual(db.execute("select count(*) from research_runs where item_id='i'").fetchone()[0],3)
  self.assertEqual(vault.queue_research(root,['i'])[0]['status'],'cached')
 def test_item_cache_key_and_queue_cache_hit(self):
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image,pending_research) values('i','Card','Cards','Trading Card',50,'{}','',1)")
  result={'evidence':[{'url':'https://example.org/sold','kind':'valuation'}],'valuation':{'estimate_cents':100,'source_url':'https://example.org/sold','basis':'sold','confidence':70,'methodology':'limited_sold','rationale':'One completed sale, low confidence.'}}
  vault.cache_item_research(root,'i',result)
  queued=vault.queue_research(root,['i'])
  self.assertEqual(queued[0]['status'],'cached'); self.assertEqual(queued[0]['cached_result'],result)
  with self.assertRaises(ValueError): vault.cache_research(root,'bad',{},['file:///private'])
  snapshot=vault.research_snapshot(root,['i']); self.assertFalse(snapshot['catalog_mutated'])
  with vault.open_catalog(root) as db: self.assertEqual(db.execute('select count(*) from research_queue').fetchone()[0],1)
  other=Path(tempfile.mkdtemp())
  with vault.open_catalog(other) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image,pending_research) values('i','Card','Cards','Trading Card',50,'{}','',1)")
  vault.research_snapshot(other,['i'])
  with vault.open_catalog(other) as db: self.assertEqual(db.execute('select count(*) from research_queue').fetchone()[0],0)
 def test_offline_queue_has_bounded_retry_and_force(self):
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image,pending_research) values('i','Card','Cards','Trading Card',50,'{}','',1)")
  for n in range(5): result=vault.research_failed(root,'i',f'network unavailable {n}')
  self.assertEqual(result['status'],'failed')
  self.assertEqual(vault.queue_research(root,['i'])[0]['status'],'failed')
  self.assertEqual(vault.queue_research(root,['i'],force=True)[0]['status'],'pending')
 def test_three_sold_comparables_require_median_estimate(self):
  root=Path(tempfile.mkdtemp())
  with vault.open_catalog(root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Item','x','y',70,'{}','')")
  urls=[f'https://example.org/sale/{i}' for i in range(3)]
  result={'evidence':[{'url':u,'kind':'valuation'} for u in urls],'valuation':{'estimate_cents':2000,'source_url':urls[1],'basis':'sold','confidence':80,'methodology':'median_sold','rationale':'Median of the three closest completed sales.','comparables':[{'source_url':u,'original_amount':str(10*(i+1)),'currency':'USD','sale_basis':'sold'} for i,u in enumerate(urls)]}}
  vault.record_research(root,'i',result)
  with vault.open_catalog(root) as db: self.assertEqual(db.execute("select methodology from valuations where item_id='i'").fetchone()[0],'median_sold')
  result['valuation']['estimate_cents']=2200
  with self.assertRaises(ValueError): vault.record_research(root,'i',result)

if __name__=='__main__': unittest.main()
