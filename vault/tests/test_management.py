import sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault
from unittest.mock import patch

class ManagementTests(unittest.TestCase):
 def setUp(self): self.root=Path(tempfile.mkdtemp());
 def test_lock_delete_restore(self):
  with vault.open_catalog(self.root) as db:
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('a','Old','x','y',50,'{}','')")
  vault.mutate_item(self.root,'edit','a','name','Corrected')
  with self.assertRaises(ValueError): vault.mutate_item(self.root,'edit','a','name','Overwrite')
  vault.mutate_item(self.root,'delete','a'); self.assertEqual(vault.read_inventory(self.root),[])
  vault.mutate_item(self.root,'restore','a'); self.assertEqual(vault.read_inventory(self.root)[0]['name'],'Corrected')
 def test_correction_persists_private_learning(self):
  data=Path(tempfile.mkdtemp());
  with vault.open_catalog(self.root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('a','Old','Cards','Card',50,'{}','')")
  with patch.dict('os.environ',{'VAULT_DATA_HOME':str(data)}):
   corrected=vault.add_observation_result(self.root,'a','name','New','misread the small logo on the reverse')
   learned=vault.private_learning('Cards')
   rule=vault.record_learning_rule('Cards',corrected['correction_id'],'Inspect the small reverse-side logo before selecting the card edition.',['reverse-side logo present'],['front-only resemblance'],)
   learned_rules=vault.private_learning_rules('Cards')
  self.assertEqual(learned[0]['new_value'],'New')
  self.assertEqual(rule['status'],'candidate'); self.assertEqual(learned_rules[0]['correction_id'],corrected['correction_id'])
  with patch.dict('os.environ',{'VAULT_DATA_HOME':str(data)}):
   with self.assertRaisesRegex(ValueError,'match its correction category'): vault.record_learning_rule('Coins',corrected['correction_id'],'This category does not match the correction context.')
  text=(data/'corrections/corrections.jsonl').read_text(); self.assertIn('small logo',text); self.assertIn('Old',text)
  self.assertIn('reverse-side logo',(data/'knowledge/rules.jsonl').read_text())
 def test_merge_undo(self):
  with vault.open_catalog(self.root) as db:
   for i in ('a','b'): db.execute('insert into items(id,name,category,type,confidence,metadata,primary_image) values(?,?,?,?,?,?,?)',(i,i,'x','y',50,'{}',''))
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token) values('p','Scanned/a.jpg','x','archived','Scanned/a.jpg','t')")
   db.execute("insert into observations values('oa','p','a',0,'[0,0,1,1]','Images/a.jpg','new',null,null)")
   db.execute("insert into evidence(id,item_id,url,kind) values('ea','a','https://example.org','identity')")
   db.execute("insert into valuations(id,item_id,estimate_cents,basis) values('va','a',100,'sold')")
  vault.merge_items(self.root,'a','b')
  with vault.open_catalog(self.root) as db:
   self.assertEqual(db.execute("select active from items where id='a'").fetchone()[0],0)
   self.assertEqual(db.execute("select item_id from observations where id='oa'").fetchone()[0],'b')
  vault.merge_items(self.root,'a','',undo=True)
  with vault.open_catalog(self.root) as db:
   self.assertEqual(db.execute("select active from items where id='a'").fetchone()[0],1)
   for table in ('observations','evidence','valuations'): self.assertEqual(db.execute(f"select item_id from {table} where id=?",({'observations':'oa','evidence':'ea','valuations':'va'}[table],)).fetchone()[0],'a')
 def test_merge_refuses_same_photo_instances(self):
  with vault.open_catalog(self.root) as db:
   for i in ('a','b'): db.execute('insert into items(id,name,category,type,confidence,metadata,primary_image) values(?,?,?,?,?,?,?)',(i,i,'x','y',50,'{}',''))
   db.execute("insert into photos(id,source,sha256,state,destination,claim_token) values('p','Scanned/a.jpg','x','archived','Scanned/a.jpg','t')")
   for iid in ('a','b'): db.execute('insert into observations values(?,?,?,?,?,?,?,?,?)',('o'+iid,'p',iid,0,'[0,0,1,1]','Images/'+iid+'.jpg','new',None,None))
  with self.assertRaises(ValueError): vault.merge_items(self.root,'a','b')
 def test_split_moves_selected_observations_and_linked_history(self):
  with vault.open_catalog(self.root) as db:
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('i','Card','Cards','Trading Card',80,'{}','Images/a.jpg')")
   for n in ('a','b'):
    db.execute('insert into photos(id,source,sha256,state,destination,claim_token) values(?,?,?,?,?,?)',('p'+n,'Scanned/'+n+'.jpg',n,'archived','Scanned/'+n+'.jpg','t'))
    db.execute('insert into observations values(?,?,?,?,?,?,?,?,?)',('o'+n,'p'+n,'i',0,'[0,0,1,1]','Images/'+n+'.jpg','new',None,None))
   db.execute("insert into evidence(id,item_id,observation_id,url,kind) values('e','i','oa','https://example.org','identity')")
   db.execute("insert into valuations(id,item_id,observation_id,estimate_cents,basis) values('v','i','oa',100,'sold')")
  result=vault.split_item(self.root,'i',['oa'],'different copies')
  self.assertNotEqual(result['new_item_id'],'i')
  with vault.open_catalog(self.root) as db:
   self.assertEqual(db.execute("select item_id from observations where id='oa'").fetchone()[0],result['new_item_id'])
   self.assertEqual(db.execute("select item_id from evidence where id='e'").fetchone()[0],result['new_item_id'])
   self.assertEqual(db.execute("select item_id from valuations where id='v'").fetchone()[0],result['new_item_id'])
   self.assertEqual(db.execute('pragma foreign_key_check').fetchall(),[])
 def test_parameterized_filter(self):
  with vault.open_catalog(self.root) as db:
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image,created) values('q','Card','TCG','card',70,'{}','Images/card.jpg','2025-03-04 12:00:00')")
   db.execute("insert into valuations(id,item_id,estimate_cents,basis) values('vq','q',2500,'sold')")
  self.assertEqual(len(vault.query_inventory(self.root,{'category':'TCG'})),1)
  self.assertEqual(len(vault.query_inventory(self.root,{'confidence_min':70,'value_min_cents':2000,'value_max_cents':3000,'basis':'sold','created_after':'2025-03-01','created_before':'2025-03-31','has_image':1})),1)
  self.assertEqual(vault.query_inventory(self.root,{'value_min_cents':3000}),[])
  with self.assertRaises(ValueError): vault.query_inventory(self.root,{'name; DROP TABLE items;--':'x'})
  with self.assertRaises(ValueError): vault.query_inventory(self.root,{'created_after':'2025/03/01'})
 def test_review_resolution_is_audited(self):
  with vault.open_catalog(self.root) as db: db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image,review) values('i','Card','Cards','Trading Card',30,'{}','',1)")
  self.assertEqual(vault.resolve_review(self.root,'i')['review'],False)
  with vault.open_catalog(self.root) as db: self.assertEqual(db.execute("select action from audit where item_id='i' order by id desc limit 1").fetchone()[0],'review_resolved')
 def test_dynamic_hierarchical_taxonomy_reuses_normalized_alias_and_reclassifies(self):
  item=vault.mutate_item(self.root,'add',None,value={'name':'Card','category':'Collectible','type':'Trading Card','subtype':'Sports Card','confidence':80})
  with vault.open_catalog(self.root) as db:
   cat=db.execute("select n.id from taxonomy_nodes n join item_taxonomy t on t.node_id=n.id where t.item_id=? and t.kind='category'",(item,)).fetchone()[0]
   type_id=db.execute("select n.id from taxonomy_nodes n join item_taxonomy t on t.node_id=n.id where t.item_id=? and t.kind='type'",(item,)).fetchone()[0]
   self.assertEqual(db.execute('select parent_id from taxonomy_nodes where id=?',(type_id,)).fetchone()[0],cat)
   db.execute("insert into items(id,name,category,type,confidence,metadata,primary_image) values('legacy','Old','collectible','trading-card',50,'{}','')")
  with vault.open_catalog(self.root) as db:
   mapped=db.execute("select node_id from item_taxonomy where item_id='legacy' and kind='category'").fetchone()[0]
   self.assertEqual(mapped,cat)
  result=vault.add_taxonomy_alias(self.root,'category','Collectible','Collections')
  with vault.open_catalog(self.root) as db:
   alias_node=vault.taxonomy_node(db,'category','Collections')
   self.assertEqual(alias_node,result['node_id'])
  vault.mutate_item(self.root,'edit',item,'category','Vintage Memorabilia')
  with vault.open_catalog(self.root) as db:
   rel={r['kind']:r['node_id'] for r in db.execute('select kind,node_id from item_taxonomy where item_id=?',(item,))}
   self.assertNotEqual(rel['category'],cat)
   self.assertEqual(db.execute('select name from taxonomy_nodes where id=?',(rel['category'],)).fetchone()[0],'Vintage Memorabilia')
   self.assertEqual(db.execute('pragma foreign_key_check').fetchall(),[])

if __name__=='__main__': unittest.main()
