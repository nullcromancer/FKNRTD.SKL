#!/usr/bin/env python3
"""Vault local-handoff candidate. Host agent supplies actual vision and research."""
import argparse
import contextlib
import csv
import time
import hashlib
import importlib.util
import io
import json
import math
import os
import re
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
import shutil
import sqlite3
import sys
import tempfile
import uuid
import zipfile
import csv
from urllib.parse import urlsplit
from PIL import Image, ImageOps, ImageSequence

try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

VERSION = '2.0.0-dev13'
SCHEMA_VERSION=16
SKILL = Path(__file__).resolve().parents[1]
Image.MAX_IMAGE_PIXELS = 60_000_000
RAW_SUFFIXES={'.dng','.cr2','.cr3','.nef','.arw','.raf','.orf','.rw2'}
INVENTORY_FIELDS=('id','product_id','name','category','type','subtype','confidence','condition','condition_confidence','metadata','primary_image','active','review','pending_research','created','updated','estimate_cents','low_cents','high_cents','speculative_cents','source_url','basis','valuation_confidence')
XLS_MAX_DATA_ROWS=65535
XLSX_MAX_DATA_ROWS=1048575

def uid(): return str(uuid.uuid4())
def js(obj): return json.dumps(obj, ensure_ascii=False, allow_nan=False)
def taxonomy_key(value): return re.sub(r'[^\w]+',' ',str(value).casefold(),flags=re.UNICODE).strip()
def taxonomy_slug(value): return re.sub(r'[^\w]+','-',str(value).casefold(),flags=re.UNICODE).strip('-') or 'unknown'
def taxonomy_node(db,kind,name,parent_id=None):
    if kind not in ('category','type','subtype') or not isinstance(name,str) or not name.strip(): raise ValueError('Taxonomy labels must be non-empty strings and use category/type/subtype kinds')
    parent_key=parent_id or ''; slug=taxonomy_slug(name); key=taxonomy_key(name)
    row=db.execute('SELECT id FROM taxonomy_nodes WHERE kind=? AND parent_key=? AND slug=?',(kind,parent_key,slug)).fetchone()
    if not row: row=db.execute('SELECT node_id AS id FROM taxonomy_aliases WHERE kind=? AND parent_key=? AND alias_key=?',(kind,parent_key,key)).fetchone()
    if row: node=row['id']
    else:
        node=uid(); db.execute('INSERT INTO taxonomy_nodes(id,kind,parent_id,parent_key,name,slug) VALUES (?,?,?,?,?,?)',(node,kind,parent_id,parent_key,name.strip(),slug))
    db.execute('INSERT OR IGNORE INTO taxonomy_aliases(kind,parent_key,alias_key,node_id,alias) VALUES (?,?,?,?,?)',(kind,parent_key,key,node,name.strip()))
    return node
def ensure_item_taxonomy(db,item_id,category,typ,subtype=None):
    cat=taxonomy_node(db,'category',category); type_id=taxonomy_node(db,'type',typ,cat)
    values={'category':cat,'type':type_id}
    if subtype and str(subtype).strip(): values['subtype']=taxonomy_node(db,'subtype',str(subtype),type_id)
    for kind,node in values.items(): db.execute('INSERT INTO item_taxonomy(item_id,kind,node_id) VALUES (?,?,?) ON CONFLICT(item_id,kind) DO UPDATE SET node_id=excluded.node_id',(item_id,kind,node))
    if 'subtype' not in values: db.execute("DELETE FROM item_taxonomy WHERE item_id=? AND kind='subtype'",(item_id,))
def backfill_taxonomy(db):
    rows=db.execute("SELECT i.id,i.category,i.type,i.subtype FROM items i LEFT JOIN item_taxonomy t ON t.item_id=i.id AND t.kind='category' WHERE t.item_id IS NULL").fetchall()
    for row in rows: ensure_item_taxonomy(db,row['id'],row['category'] or 'Unclassified',row['type'] or 'Unknown',row['subtype'])
def add_taxonomy_alias(root,kind,name,alias,category=None,parent_type=None):
    if kind not in ('category','type','subtype'): raise ValueError('kind must be category, type or subtype')
    if kind!='category' and not category: raise ValueError('A parent category is required')
    if kind=='subtype' and not parent_type: raise ValueError('A parent type is required')
    with open_catalog(root) as db:
        parent=None
        if kind!='category': parent=taxonomy_node(db,'category',category)
        if kind=='subtype': parent=taxonomy_node(db,'type',parent_type,parent)
        node=taxonomy_node(db,kind,name,parent); key=taxonomy_key(alias)
        if not key: raise ValueError('Alias must contain letters or digits')
        with db: db.execute('INSERT OR IGNORE INTO taxonomy_aliases(kind,parent_key,alias_key,node_id,alias) VALUES (?,?,?,?,?)',(kind,parent or '',key,node,alias.strip()))
        return {'node_id':node,'kind':kind,'name':name,'alias':alias}
def start_scan_run(root,agent=None,model=None):
    for value,label in ((agent,'agent'),(model,'model')):
        if value is not None and (not isinstance(value,str) or len(value)>160): raise ValueError(f'{label} must be text up to 160 characters')
    with open_catalog(root) as db:
        run_id=uid()
        with db: db.execute('INSERT INTO scan_runs(id,agent,model) VALUES (?,?,?)',(run_id,agent,model))
        return {'run_id':run_id,'state':'active','agent':agent,'model':model}
def finish_scan_run(root,run_id,interrupted=False):
    with open_catalog(root) as db:
        with db:
            cur=db.execute("UPDATE scan_runs SET state=?,finished=CURRENT_TIMESTAMP WHERE id=? AND state='active'",('interrupted' if interrupted else 'complete',run_id))
            if cur.rowcount!=1: raise ValueError('Active scan run not found')
            count=db.execute('SELECT count(*) FROM photos WHERE scan_run_id=?',(run_id,)).fetchone()[0]
        return {'run_id':run_id,'state':'interrupted' if interrupted else 'complete','photos':count}
def list_scan_runs(root,limit=50):
    with open_catalog(root) as db: return [dict(r) for r in db.execute('SELECT r.*,count(p.id) AS photos FROM scan_runs r LEFT JOIN photos p ON p.scan_run_id=r.id GROUP BY r.id ORDER BY r.started DESC LIMIT ?',(max(1,min(int(limit),500)),))]
def hashfile(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024), b''): h.update(b)
    return h.hexdigest()
def difference_hash(image):
    """Return a 64-bit dHash advisory signature; it is never an identity key."""
    im=ImageOps.exif_transpose(image).convert('L').resize((9,8),Image.Resampling.LANCZOS)
    pixels=im.tobytes(); bits=0
    for y in range(8):
        offset=y*9
        for x in range(8): bits=(bits<<1) | int(pixels[offset+x]>pixels[offset+x+1])
    return f'{bits:016x}'
def perceptual_candidates(db,signature,exclude_id=None,limit=8,max_distance=8):
    """Find visually similar archived photos for host review, without merging."""
    if not signature: return []
    try: bits=int(signature,16)
    except (ValueError,TypeError): return []
    query="SELECT id,source,destination,sha256,perceptual_hash FROM photos WHERE perceptual_hash IS NOT NULL AND state IN ('archived','committed_pending_move')"
    params=[]
    if exclude_id: query+=' AND id<>?'; params.append(exclude_id)
    out=[]
    for row in db.execute(query,params):
        try: distance=(bits^int(row['perceptual_hash'],16)).bit_count()
        except (ValueError,TypeError): continue
        if distance<=max_distance:
            observations=[dict(x) for x in db.execute('SELECT o.item_id,i.name,i.category,i.type,i.active,o.image FROM observations o JOIN items i ON i.id=o.item_id WHERE o.photo_id=? ORDER BY o.rowid',(row['id'],))]
            out.append({'photo_id':row['id'],'source':row['source'],'destination':row['destination'],'sha256':row['sha256'],'hamming_distance':distance,'observations':observations,'identity_decision':'host_review_required'})
    return sorted(out,key=lambda x:(x['hamming_distance'],x['photo_id']))[:limit]
def backfill_perceptual_hashes(root,db):
    """Lazily hash archived legacy originals; unreadable/missing files remain NULL."""
    rows=db.execute("SELECT id,destination FROM photos WHERE perceptual_hash IS NULL AND state IN ('archived','committed_pending_move') AND destination<>'' ORDER BY rowid").fetchall()
    for row in rows:
        try:
            path=inside(root,row['destination'])
            if not path.is_file(): continue
            with open_image(path) as im:
                im.seek(0); signature=difference_hash(im)
            with db: db.execute('UPDATE photos SET perceptual_hash=? WHERE id=? AND perceptual_hash IS NULL',(signature,row['id']))
        except (OSError,ValueError,EOFError,Image.DecompressionBombError):
            continue
def inside(root, rel):
    p=(root/rel).resolve()
    if not p.is_relative_to(root.resolve()): raise ValueError('Path escapes workspace')
    return p
def url_ok(s):
    if not isinstance(s,str): return False
    p=urlsplit(s)
    return p.scheme in ('http','https') and bool(p.hostname) and not p.username and not p.password and not any(c.isspace() for c in s)
def score(v):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not 0<=v<=100: raise ValueError('Invalid confidence')
    return float(v)
def money(v):
    if v is None: return None
    if type(v) is not int or not 0<=v<=9_000_000_000_000: raise ValueError('Money must be nonnegative integer USD cents')
    return v

def open_image(path):
    """Open Pillow formats, HEIF via its registered plugin, and camera RAW via rawpy."""
    path=Path(path)
    if path.suffix.lower() in RAW_SUFFIXES:
        try: import rawpy
        except ImportError as exc: raise OSError('Camera RAW decoder rawpy is not installed') from exc
        with rawpy.imread(str(path)) as raw:
            return Image.fromarray(raw.postprocess())
    return Image.open(path)

def validate_comparables(comps,evidence):
    if not isinstance(comps,list): raise ValueError('Comparables must be an array')
    evidence_urls={e['url'] for e in evidence if e.get('kind')=='valuation'}
    out=[]
    for comp in comps:
        if not isinstance(comp,dict): raise ValueError('Comparable must be an object')
        url=comp.get('source_url'); basis=comp.get('sale_basis','sold'); currency=comp.get('currency','USD'); amount=comp.get('original_amount')
        if not url_ok(url) or url not in evidence_urls: raise ValueError('Comparable URL must have a matching valuation evidence record')
        if basis not in ('sold','dealer','asking','retail'): raise ValueError('Invalid comparable basis')
        if not isinstance(currency,str) or not re.fullmatch('[A-Z]{3}',currency): raise ValueError('Comparable currency must be a three-letter uppercase code')
        if isinstance(amount,bool) or amount is None: raise ValueError('Comparable original amount is required')
        try: original=Decimal(str(amount))
        except InvalidOperation: raise ValueError('Invalid comparable amount')
        if not original.is_finite() or original<=0: raise ValueError('Comparable amount must be positive and finite')
        quantity=comp.get('quantity',1)
        if type(quantity) is not int or quantity<1: raise ValueError('Comparable quantity must be a positive integer')
        sold_at=comp.get('sold_at')
        if sold_at is not None:
            try: time.strptime(sold_at,'%Y-%m-%d')
            except (TypeError,ValueError): raise ValueError('Comparable sold_at must use YYYY-MM-DD')
        fx=comp.get('usd_fx_rate'); fx_url=comp.get('fx_source_url')
        try: rate=Decimal('1') if currency=='USD' and fx is None else Decimal(str(fx))
        except InvalidOperation: raise ValueError('Comparable FX rate must be a positive decimal')
        if not rate.is_finite() or rate<=0: raise ValueError('Comparable FX rate must be a positive decimal')
        if currency!='USD' and (not url_ok(fx_url) or fx_url not in evidence_urls): raise ValueError('Non-USD comparable requires a cited FX source URL')
        normalized=int((original*rate*Decimal(100)/Decimal(quantity)).quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        normalized=money(normalized); adjusted=money(comp.get('adjusted_unit_cents',normalized))
        notes=comp.get('adjustment_notes','')
        if adjusted!=normalized and (not isinstance(notes,str) or not notes.strip()): raise ValueError('Adjusted comparable requires rationale')
        out.append({'source_url':url,'sale_basis':basis,'original_amount':format(original,'f'),'currency':currency,'quantity':quantity,'sold_at':sold_at,'usd_fx_rate':format(rate,'f') if currency!='USD' or fx is not None else None,'fx_source_url':fx_url,'normalized_unit_cents':normalized,'adjusted_unit_cents':adjusted,'adjustment_notes':notes})
    return out

def save_comparables(db,item_id,valuation_id,comps):
    for c in comps:
        db.execute('INSERT INTO valuation_comparables(id,valuation_id,item_id,source_url,sale_basis,original_amount,currency,quantity,sold_at,fx_rate,fx_source_url,normalized_unit_cents,adjusted_unit_cents,adjustment_notes) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(uid(),valuation_id,item_id,c['source_url'],c['sale_basis'],c['original_amount'],c['currency'],c['quantity'],c['sold_at'],c['usd_fx_rate'],c['fx_source_url'],c['normalized_unit_cents'],c['adjusted_unit_cents'],c['adjustment_notes']))

def validate_valuation_method(val,estimate,comps):
    method=val.get('methodology'); rationale=val.get('rationale')
    if estimate is None: return method,rationale
    if method not in ('median_sold','limited_sold','dealer_evidence','asking_proxy','retail_proxy','other'):
        raise ValueError('Supported estimate requires a recognized valuation methodology')
    if not isinstance(rationale,str) or not rationale.strip(): raise ValueError('Supported estimate requires a concise rationale')
    sold=sorted(c['adjusted_unit_cents'] for c in comps if c['sale_basis']=='sold')
    if len(sold)>=3:
        middle=len(sold)//2
        median=Decimal(sold[middle]) if len(sold)%2 else (Decimal(sold[middle-1])+Decimal(sold[middle]))/2
        expected=int(median.quantize(Decimal('1'),rounding=ROUND_HALF_UP))
        if method!='median_sold' or estimate!=expected: raise ValueError('Three or more sold comparables require the adjusted sold-comparable median as the initial estimate')
    elif method=='median_sold': raise ValueError('median_sold requires at least three sold comparables')
    return method,rationale.strip()

def validate_research_activity(activity):
    if activity is None: activity={}
    if not isinstance(activity,dict): raise ValueError('research_activity must be an object')
    queries=activity.get('queries',[]); visits=activity.get('visited_pages',[])
    if not isinstance(queries,list) or not isinstance(visits,list) or len(queries)>8 or len(visits)>12: raise ValueError('Research budget exceeded (maximum 8 queries and 12 opened pages per item)')
    normalized_queries=[]; normalized_visits=[]
    for entry in queries:
        if isinstance(entry,str): entry={'query':entry,'source':'agent'}
        if not isinstance(entry,dict) or not isinstance(entry.get('query'),str) or not entry['query'].strip() or len(entry['query'])>500: raise ValueError('Each research query must contain 1..500 characters')
        provider=entry.get('source','agent')
        if not isinstance(provider,str) or not provider.strip() or len(provider)>80: raise ValueError('Research query source must be a short nonempty label')
        normalized_queries.append({'query':entry['query'].strip(),'source':provider.strip()})
    for entry in visits:
        if not isinstance(entry,dict) or not url_ok(entry.get('url')): raise ValueError('Research page log requires an actual public HTTP(S) URL')
        provider=entry.get('source')
        query=entry.get('query','')
        cache_hit=entry.get('cache_hit',False)
        if not isinstance(provider,str) or not provider.strip() or len(provider)>80: raise ValueError('Research page requires a short nonempty source label')
        if not isinstance(query,str) or len(query)>500 or type(cache_hit) is not bool: raise ValueError('Invalid research page query or cache-hit flag')
        normalized_visits.append({'url':entry['url'],'source':provider.strip(),'query':query,'cache_hit':cache_hit})
    return {'queries':normalized_queries,'visited_pages':normalized_visits}

def files(root):
    stage=root/'Staging'
    if not stage.exists(): return
    for folder,dirs,names in os.walk(stage,followlinks=False):
        dirs[:]=sorted(d for d in dirs if not (Path(folder)/d).is_symlink() and not getattr(Path(folder)/d,'is_junction',lambda:False)())
        for name in sorted(names):
            p=Path(folder)/name
            if name.startswith('.') or name.lower().endswith(('.tmp','.part','.crdownload')) or p.is_symlink() or not p.is_file(): continue
            if not p.resolve().is_relative_to(stage.resolve()): continue
            yield p

@contextlib.contextmanager
def lock(path):
    with path.open('a+b') as f:
        f.seek(0,2)
        if f.tell()==0: f.write(b'0'); f.flush()
        f.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(f.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(f,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try: yield
        finally:
            if os.name=='nt':
                msvcrt.locking(f.fileno(),msvcrt.LK_UNLCK,1)
            else: fcntl.flock(f,fcntl.LOCK_UN)

def check(db):
    if db.execute('PRAGMA quick_check').fetchone()[0]!='ok' or db.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('SQLite integrity check failed')

def verify_migrations(db):
    version=db.execute('PRAGMA user_version').fetchone()[0]
    rows=db.execute('SELECT version,checksum FROM schema_migrations ORDER BY version').fetchall()
    if not rows or rows[-1]['version']!=version: raise RuntimeError('Migration ledger does not match database version')
    for row in rows:
        path=SKILL/'migrations'/f"{row['version']:03}.sql"
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=row['checksum']:
            raise RuntimeError(f"Migration checksum mismatch at version {row['version']}; preserve the catalog")

def register_asset(db,path,catalog_root):
    catalog_root=Path(catalog_root).resolve(); path=Path(path)
    asset=path.resolve() if path.is_absolute() else inside(catalog_root,path)
    rel=asset.relative_to(catalog_root).as_posix()
    db.execute('INSERT OR IGNORE INTO catalog_assets(path,sha256,bytes) VALUES (?,?,?)',(rel,hashfile(asset),asset.stat().st_size))

def reconcile_asset_ledger(root,db):
    paths={r[0] for r in db.execute('SELECT image FROM observations UNION SELECT primary_image FROM items WHERE primary_image<>\'\' UNION SELECT path FROM detail_assets')}
    for rel in paths:
        asset=inside(root/'Catalog',rel)
        if asset.is_file() and not db.execute('SELECT 1 FROM catalog_assets WHERE path=?',(Path(rel).as_posix(),)).fetchone(): register_asset(db,asset,root/'Catalog')

def check_catalog(root,db):
    check(db); cat=(root/'Catalog').resolve(); missing=[]
    for row in db.execute('SELECT path,sha256,bytes FROM catalog_assets'):
        p=inside(cat,row['path'])
        if not p.is_file() or p.stat().st_size!=row['bytes'] or hashfile(p)!=row['sha256']:
            missing.append({'asset':row['path'],'reason':'missing or content hash mismatch'})
    for row in db.execute('SELECT id,image FROM observations'):
        p=inside(cat,row['image'])
        if not p.is_file(): missing.append({'observation_id':row['id'],'asset':row['image']})
    for row in db.execute("SELECT id,primary_image FROM items WHERE active=1 AND primary_image<>''"):
        p=inside(cat,row['primary_image'])
        if not p.is_file(): missing.append({'item_id':row['id'],'asset':row['primary_image']})
    for row in db.execute('SELECT id,observation_id,path,sha256,bytes FROM detail_assets'):
        p=inside(cat,row['path'])
        if not p.is_file() or p.stat().st_size!=row['bytes'] or hashfile(p)!=row['sha256']: missing.append({'detail_id':row['id'],'observation_id':row['observation_id'],'asset':row['path'],'reason':'missing or content hash mismatch'})
    if missing: raise RuntimeError('Missing or unsafe catalog assets: '+js(missing[:50]))
    return {'integrity':'ok','observation_assets_checked':db.execute('SELECT count(*) FROM observations').fetchone()[0]}

def doctor(root):
    import importlib.metadata
    deps={}
    for name in ('Pillow','xlwt','openpyxl','opencv-python-headless','numpy','xlrd','olefile','pillow-heif','rawpy'):
        try: deps[name]=importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError: deps[name]=None
    report={'version':VERSION,'python':sys.version.split()[0],'executable':sys.executable,'sqlite':sqlite3.sqlite_version,'dependencies':deps,'workspace':str(root.resolve()),'paths':{},'image_formats':{'registered':len(Image.registered_extensions()),'heic':'.heic' in Image.registered_extensions(),'raw':importlib.util.find_spec('rawpy') is not None},'capabilities':{'visual_identification':'host agent must verify image inspection','public_research':'host agent must verify web search'},'warnings':[]}
    report['paths']={n:str(root/n) for n in ('Staging','Scanned','Failed','Catalog')}
    with open_catalog(root) as db:
        report['schema_version']=db.execute('PRAGMA user_version').fetchone()[0]
        report['database_check']=check_catalog(root,db)
    probe=root/'Catalog/.vault'/'doctor-write-test.tmp'
    try:
        probe.write_bytes(b'vault'); probe.unlink()
        report['catalog_writable']=True
    except OSError as e: report['catalog_writable']=False; report['warnings'].append('Catalog not writable: '+str(e))
    for name,version in deps.items():
        if version is None: report['warnings'].append('Missing dependency: '+name)
    if not report['image_formats']['heic']: report['warnings'].append('HEIC decoding is not installed')
    if not report['image_formats']['raw']: report['warnings'].append('Camera RAW decoding is not installed')
    return report

@contextlib.contextmanager
def open_catalog(root):
    root=root.resolve(); cat=root/'Catalog'
    for name in ('Staging','Scanned','Failed','Catalog','Catalog/Images','Catalog/.vault','Catalog/Backups'):
        p=root/name
        if p.exists() and (p.is_symlink() or p.resolve()!=p): raise ValueError('Redirected workspace path: '+name)
        p.mkdir(parents=True,exist_ok=True)
    with lock(cat/'.vault/writer.lock'):
        db=sqlite3.connect(cat/'Vault.sqlite',timeout=5)
        db.row_factory=sqlite3.Row
        try:
            db.execute('PRAGMA foreign_keys=ON'); db.execute('PRAGMA busy_timeout=5000'); check(db)
            v=db.execute('PRAGMA user_version').fetchone()[0]
            if v==0:
                if db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone(): raise RuntimeError('Unknown unversioned database; migration requires review')
                migration='\n'.join((SKILL/'migrations'/f'{n:03}.sql').read_text(encoding='utf-8') for n in range(1,SCHEMA_VERSION+1))
                db.executescript('BEGIN IMMEDIATE;\n'+migration+f'\nPRAGMA user_version={SCHEMA_VERSION}; COMMIT;')
                for n in range(1,SCHEMA_VERSION+1):
                    digest=hashlib.sha256((SKILL/'migrations'/f'{n:03}.sql').read_bytes()).hexdigest()
                    db.execute('INSERT OR IGNORE INTO schema_migrations(version,checksum) VALUES (?,?)',(n,digest))
            elif v<SCHEMA_VERSION:
                backup=cat/'Backups'/('Vault-before-migration-'+uid()+'.sqlite')
                target=sqlite3.connect(backup)
                try: db.backup(target)
                finally: target.close()
                migration='\n'.join((SKILL/'migrations'/f'{n:03}.sql').read_text(encoding='utf-8') for n in range(v+1,SCHEMA_VERSION+1))
                migration+=f'\nPRAGMA user_version={SCHEMA_VERSION};'
                db.executescript('BEGIN IMMEDIATE;\n'+migration+'\nCOMMIT;')
                verify=sqlite3.connect(backup)
                try:
                    if verify.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise RuntimeError('Migration backup verification failed')
                finally: verify.close()
                for n in range(1,SCHEMA_VERSION+1):
                    digest=hashlib.sha256((SKILL/'migrations'/f'{n:03}.sql').read_bytes()).hexdigest()
                    db.execute('INSERT OR IGNORE INTO schema_migrations(version,checksum) VALUES (?,?)',(n,digest))
            elif v!=SCHEMA_VERSION: raise RuntimeError('Unsupported schema version; preserve DB')
            verify_migrations(db)
            reconcile_asset_ledger(root,db)
            backfill_taxonomy(db)
            yield db
            db.commit()
            check(db)
        finally: db.close()

def reserve(root,db,name,folder):
    p=Path(name); candidate=folder+'/'+p.name
    while (root/candidate).exists() or db.execute('SELECT 1 FROM photos WHERE destination=?',(candidate,)).fetchone() or db.execute('SELECT 1 FROM archives WHERE destination=?',(candidate,)).fetchone():
        candidate=folder+'/'+p.stem+'-'+uid()[:12]+p.suffix
    return candidate

def ingest_zip(root,db,path,digest):
    """Safely extract bounded regular-file members beneath Staging/.vault-zip."""
    rel=path.relative_to(root).as_posix()
    old=db.execute('SELECT * FROM archives WHERE source=? AND sha256=?',(rel,digest)).fetchone()
    if old and old['state']=='members_pending': return {'archive':old['id'],'resumed':True}
    aid=old['id'] if old else uid()
    if not old:
        with db: db.execute('INSERT INTO archives(id,source,sha256,state) VALUES (?,?,?,?)',(aid,rel,digest,'extracting'))
    outdir=root/'Staging'/'.vault-zip'/aid
    outdir.mkdir(parents=True,exist_ok=True)
    try:
        with zipfile.ZipFile(path) as z:
            infos=[i for i in z.infolist() if not i.is_dir()]
            if len(infos)>500: raise ValueError('ZIP member count exceeds 500')
            total=0
            name_counts={}
            for member_index,info in enumerate(infos):
                name=info.filename.replace('\\','/')
                parts=Path(name).parts
                mode=(info.external_attr>>16)&0xffff
                if not name or name.startswith('/') or any(p in ('..','') for p in parts) or (len(parts)>0 and ':' in parts[0]) or (mode and (mode&0o170000)==0o120000): raise ValueError('Unsafe ZIP member path or link')
                if info.file_size>100_000_000: raise ValueError('ZIP member exceeds size limit')
                total+=info.file_size
                if total>1_000_000_000: raise ValueError('ZIP expanded size exceeds 1 GB')
                if info.file_size and info.file_size/max(1,info.compress_size)>200: raise ValueError('ZIP compression ratio exceeds limit')
                name_counts[name]=name_counts.get(name,0)+1
                safe_parts=list(parts)
                if name_counts[name]>1: safe_parts[-1]=safe_parts[-1]+f'.duplicate-{name_counts[name]}'
                dest=outdir.joinpath(*safe_parts).resolve()
                if not dest.is_relative_to(outdir.resolve()): raise ValueError('ZIP member escapes extraction root')
                dest.parent.mkdir(parents=True,exist_ok=True)
                h=hashlib.sha256(); n=0
                with z.open(info) as src, dest.open('xb') as out:
                    while True:
                        chunk=src.read(1024*1024)
                        if not chunk: break
                        n+=len(chunk)
                        if n>info.file_size or n>100_000_000: raise ValueError('ZIP member expanded beyond declared limit')
                        h.update(chunk); out.write(chunk)
                    out.flush(); os.fsync(out.fileno())
                member_id=uid(); extracted=dest.relative_to(root.resolve()).as_posix()
                with db:
                    db.execute('INSERT OR IGNORE INTO archive_members(id,archive_id,member_name,member_index,extracted_path,sha256,disposition) VALUES (?,?,?,?,?,?,?)',(member_id,aid,name,member_index,extracted,h.hexdigest(),'pending'))
        with db: db.execute("UPDATE archives SET state='members_pending',updated=CURRENT_TIMESTAMP WHERE id=?",(aid,))
        return {'archive':aid,'members':len(infos),'state':'members_pending'}
    except Exception as e:
        with db: db.execute("UPDATE archives SET state='rejected',error=?,updated=CURRENT_TIMESTAMP WHERE id=?",(str(e),aid))
        shutil.rmtree(outdir,ignore_errors=True)
        return {'archive':aid,'error':str(e),'state':'rejected'}

def copy_archive(src,dest,digest):
    # Publish a verified copy using a no-overwrite hard link in the destination volume.
    # If hard links are unsupported, fail safely and leave the pending state intact.
    if dest.exists():
        if not dest.is_file() or dest.is_symlink() or hashfile(dest)!=digest: raise RuntimeError('Archive destination conflict')
    else:
        dest.parent.mkdir(parents=True,exist_ok=True)
        if not src.is_file() or src.is_symlink() or hashfile(src)!=digest: raise RuntimeError('Source missing or changed')
        fd,tmp=tempfile.mkstemp(prefix='.vault-move-',dir=dest.parent); os.close(fd); tmp=Path(tmp)
        try:
            with src.open('rb') as inp, tmp.open('wb') as out:
                shutil.copyfileobj(inp,out); out.flush(); os.fsync(out.fileno())
            shutil.copystat(src,tmp)
            if hashfile(tmp)!=digest: raise RuntimeError('Copy verification failed')
            os.link(tmp,dest)
        finally: tmp.unlink(missing_ok=True)
    if src.exists():
        if src.is_symlink() or hashfile(src)!=digest: raise RuntimeError('Source changed before archive removal')
        # Windows cannot unlink an open/locked source. The verified destination
        # is already durable; retry on the next recovery pass if removal fails.
        src.unlink()

def finish_zip_member(root,db,photo_id,state):
    row=db.execute('SELECT source FROM photos WHERE id=?',(photo_id,)).fetchone()
    if not row: return
    p=Path(row['source'])
    if '.vault-zip' not in p.parts: return
    member=db.execute('SELECT id,archive_id FROM archive_members WHERE extracted_path=?',(row['source'],)).fetchone()
    if not member: return
    disp='scanned' if state=='archived' else 'failed'
    with db: db.execute('UPDATE archive_members SET disposition=?,photo_id=? WHERE id=?',(disp,photo_id,member['id']))
    finish_zip_archive(root,db,member['archive_id'])

def finish_zip_archive(root,db,archive_id):
    pending=db.execute("SELECT count(*) FROM archive_members WHERE archive_id=? AND disposition='pending'",(archive_id,)).fetchone()[0]
    if pending==0:
        a=db.execute('SELECT * FROM archives WHERE id=?',(archive_id,)).fetchone()
        if a['state']=='archived': return None
        dest=a['destination'] or reserve(root,db,Path(a['source']).name,'Scanned/Archives')
        try:
            copy_archive(inside(root,a['source']),inside(root,dest),a['sha256'])
            with db: db.execute("UPDATE archives SET state='archived',destination=?,error=NULL,updated=CURRENT_TIMESTAMP WHERE id=?",(dest,archive_id))
            return None
        except (OSError,RuntimeError,ValueError) as e:
            with db: db.execute("UPDATE archives SET state='members_pending',destination=?,error=?,updated=CURRENT_TIMESTAMP WHERE id=?",(dest,str(e),archive_id))
            return str(e)
    return None

def mark_zip_member_unsupported(root,db,relative,reason):
    row=db.execute('SELECT id,archive_id FROM archive_members WHERE extracted_path=?',(relative,)).fetchone()
    if not row: return False
    with db: db.execute("UPDATE archive_members SET disposition='unsupported',error=? WHERE id=?",(reason,row['id']))
    finish_zip_archive(root,db,row['archive_id'])
    return True

def recover(root,db):
    warnings=[]
    for r in db.execute('SELECT * FROM photos WHERE state IN (\'committed_pending_move\',\'failed_pending_move\')').fetchall():
        try:
            if r['state']=='committed_pending_move':
                for a in db.execute('SELECT image FROM observations WHERE photo_id=?',(r['id'],)):
                    with Image.open(inside(root/'Catalog',a['image'])) as im: im.verify()
                for a in db.execute('SELECT d.path,d.sha256,d.bytes FROM detail_assets d JOIN observations o ON o.id=d.observation_id WHERE o.photo_id=?',(r['id'],)):
                    detail_path=inside(root/'Catalog',a['path'])
                    if not detail_path.is_file() or detail_path.stat().st_size!=a['bytes'] or hashfile(detail_path)!=a['sha256']: raise RuntimeError('Detail crop missing or hash mismatch: '+a['path'])
                    with Image.open(detail_path) as im: im.verify()
            copy_archive(inside(root,r['source']),inside(root,r['destination']),r['sha256'])
            with db: db.execute('UPDATE photos SET state=?,updated=CURRENT_TIMESTAMP WHERE id=?',('archived' if r['state']=='committed_pending_move' else 'failed_archived',r['id']))
            finish_zip_member(root,db,r['id'],'archived' if r['state']=='committed_pending_move' else 'failed_archived')
        except (OSError,RuntimeError,ValueError) as e: warnings.append({'photo':r['id'],'error':str(e)})
    for a in db.execute("SELECT id FROM archives WHERE state='members_pending' AND NOT EXISTS (SELECT 1 FROM archive_members m WHERE m.archive_id=archives.id AND m.disposition='pending')").fetchall():
        error=finish_zip_archive(root,db,a['id'])
        if error: warnings.append({'archive':a['id'],'error':error})
    return warnings

def claim(root,db):
    warnings=recover(root,db)
    backfill_perceptual_hashes(root,db)
    r=db.execute("SELECT * FROM photos WHERE state='claimed' ORDER BY rowid LIMIT 1").fetchone()
    if r: return {'job':dict(r),'resumed':True,'warnings':warnings,'near_duplicate_suggestions':perceptual_candidates(db,r['perceptual_hash'],r['id'])}
    blocked=[]
    for p in files(root):
        rel=p.relative_to(root).as_posix()
        member_state=db.execute('SELECT disposition FROM archive_members WHERE extracted_path=?',(rel,)).fetchone()
        if member_state and member_state['disposition']!='pending': continue
        if db.execute("SELECT 1 FROM photos WHERE source=? AND state IN ('committed_pending_move','failed_pending_move')",(rel,)).fetchone(): continue
        st=p.stat(); digest=hashfile(p); now=p.stat()
        if (st.st_size,st.st_mtime_ns)!=(now.st_size,now.st_mtime_ns): continue
        id=uid(); token=uid(); dest=reserve(root,db,p.name,'Scanned'); phash=None
        prior=db.execute("SELECT id,perceptual_hash FROM photos WHERE sha256=? AND state IN ('archived','committed_pending_move') ORDER BY rowid LIMIT 1",(digest,)).fetchone()
        if prior:
            with db:
                db.execute('INSERT INTO photos(id,source,sha256,state,destination,claim_token,perceptual_hash) VALUES (?,?,?,?,?,?,?)',(id,rel,digest,'committed_pending_move',dest,token,prior['perceptual_hash']))
                for o in db.execute('SELECT * FROM observations WHERE photo_id=?',(prior['id'],)).fetchall():
                    obs_id=uid()
                    db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',(obs_id,id,o['item_id'],o['frame'],o['box'],o['image'],'identical_bytes',100,o['notes']))
                    for detail in db.execute('SELECT * FROM detail_assets WHERE observation_id=?',(o['id'],)).fetchall():
                        db.execute('INSERT INTO detail_assets(id,observation_id,frame,box,path,label,sha256,bytes,created) VALUES (?,?,?,?,?,?,?,?,?)',(uid(),obs_id,detail['frame'],detail['box'],detail['path'],detail['label'],detail['sha256'],detail['bytes'],detail['created']))
                db.execute('INSERT INTO audit(photo_id,action,detail) VALUES (?,?,?)',(id,'identical_photo',js({'original':prior['id']})))
            return {'deduplicated':id,'warnings':warnings+recover(root,db),'near_duplicate_suggestions':[]}
        if p.suffix.lower()=='.zip':
            result=ingest_zip(root,db,p,digest)
            if result.get('state')=='members_pending':
                # Keep the source archive until each member has its own recorded disposition.
                blocked.append({'file':rel,'reason':'ZIP members extracted; scan members before archive disposition','archive':result['archive']})
            else: blocked.append({'file':rel,'reason':result.get('error','ZIP awaiting recovery')})
            continue
        if p.suffix.lower() in RAW_SUFFIXES and importlib.util.find_spec('rawpy') is None:
            mark_zip_member_unsupported(root,db,rel,'Optional decoder unavailable; extracted member retained')
            blocked.append({'file':rel,'reason':'Optional decoder unavailable; preserved'}); continue
        if p.suffix.lower() not in Image.registered_extensions() and p.suffix.lower() not in RAW_SUFFIXES:
            mark_zip_member_unsupported(root,db,rel,'Unsupported image format; extracted member retained')
            blocked.append({'file':rel,'reason':'Unsupported image format; preserved'}); continue
        try:
            with open_image(p) as im:
                n=getattr(im,'n_frames',1); normalized=ImageOps.exif_transpose(im); w,h=normalized.size
                phash=difference_hash(normalized)
                im.load()
        except (OSError,ValueError,Image.DecompressionBombError) as e:
            dest=reserve(root,db,p.name,'Failed')
            with db: db.execute('INSERT INTO photos(id,source,sha256,state,destination,claim_token,error) VALUES (?,?,?,?,?,?,?)',(id,rel,digest,'failed_pending_move',dest,token,str(e)))
            return {'failed':id,'warnings':warnings+recover(root,db)}
        if n<1: continue
        suggestions=perceptual_candidates(db,phash)
        with db: db.execute('INSERT INTO photos(id,source,sha256,state,destination,claim_token,width,height,frame_count,perceptual_hash) VALUES (?,?,?,?,?,?,?,?,?,?)',(id,rel,digest,'claimed',dest,token,w,h,n,phash))
        return {'job':dict(db.execute('SELECT * FROM photos WHERE id=?',(id,)).fetchone()),'warnings':warnings,'near_duplicate_suggestions':suggestions}
    return {'job':None,'warnings':warnings,'blocked':blocked}

def normalize(root,db,id,output,frame_index=0):
    r=db.execute("SELECT * FROM photos WHERE id=? AND state='claimed'",(id,)).fetchone()
    if not r: raise ValueError('No active job')
    src=inside(root,r['source'])
    if hashfile(src)!=r['sha256']: raise ValueError('Source changed')
    if type(frame_index) is not int or not 0<=frame_index<r['frame_count']: raise ValueError('Invalid frame index')
    with output.open('xb') as out, open_image(src) as im:
        im.seek(frame_index); ImageOps.exif_transpose(im).convert('RGB').save(out,'PNG')

def propose_card_regions(image_path):
    """Return conservative card-shaped contour proposals for host-agent review."""
    try:
        import cv2
        import numpy as np
    except ImportError:
        return {'available':False,'regions':[],'reason':'Install optional opencv-python-headless and numpy for geometric proposals'}
    image=cv2.imread(str(image_path))
    if image is None: raise ValueError('Image decoder could not read input')
    gray=cv2.cvtColor(image,cv2.COLOR_BGR2GRAY); edges=cv2.Canny(cv2.GaussianBlur(gray,(5,5),0),35,110)
    contours,_=cv2.findContours(edges,cv2.RETR_LIST,cv2.CHAIN_APPROX_SIMPLE); h,w=gray.shape; regions=[]
    for contour in contours:
        peri=cv2.arcLength(contour,True); poly=cv2.approxPolyDP(contour,.02*peri,True)
        if len(poly)!=4 or not cv2.isContourConvex(poly): continue
        rect=cv2.minAreaRect(poly); rw,rh=rect[1]; area=rw*rh
        if not area or area<.002*w*h: continue
        ratio=max(rw,rh)/max(1,min(rw,rh))
        if not 1.25<=ratio<=1.9: continue
        pts=poly.reshape(-1,2).tolist(); xs=[p[0] for p in pts]; ys=[p[1] for p in pts]
        box=[max(0,min(xs)),max(0,min(ys)),min(w,max(xs)),min(h,max(ys))]
        if not any(sum(abs(a-b) for a,b in zip(box,r['box']))<.06*max(w,h) for r in regions): regions.append({'box':box,'polygon':pts,'proposal':'card-shaped contour; visual confirmation required'})
    return {'available':True,'regions':sorted(regions,key=lambda r:(r['box'][1],r['box'][0])),'method':'opencv contours; not identity recognition'}

def preview_crops(root,photo_id,claim_token,items,output_dir):
    """Render temporary crops for host inspection before identification/commit."""
    root=Path(root).resolve(); output_dir=Path(output_dir).resolve()
    if not isinstance(items,list) or not items or len(items)>200: raise ValueError('Preview requires 1..200 item regions')
    if output_dir.is_relative_to(root): raise ValueError('Preview output must be outside the catalog workspace')
    with open_catalog(root) as db:
        row=db.execute("SELECT * FROM photos WHERE id=? AND claim_token=? AND state='claimed'",(photo_id,claim_token)).fetchone()
        if not row: raise ValueError('Preview requires an active photo claim and matching token')
        src=inside(root,row['source'])
        if hashfile(src)!=row['sha256']: raise ValueError('Claimed source hash changed')
        output_dir.mkdir(parents=True,exist_ok=True); results=[]
        with open_image(src) as image:
            for index,spec in enumerate(items):
                if not isinstance(spec,dict): raise ValueError('Each preview region must be an object')
                frame_index=spec.get('frame',0); box=spec.get('box'); quad=spec.get('quad')
                if type(frame_index) is not int or not 0<=frame_index<row['frame_count']: raise ValueError('Invalid preview frame')
                image.seek(frame_index); frame=ImageOps.exif_transpose(image).convert('RGB'); w,h=frame.size
                if not isinstance(box,list) or len(box)!=4 or any(type(v) is not int for v in box) or not (0<=box[0]<box[2]<=w and 0<=box[1]<box[3]<=h): raise ValueError('Invalid preview box')
                target=output_dir/f'vault-preview-{photo_id}-{index+1:03}-{uid()}.jpg'
                if quad is not None:
                    if not isinstance(quad,list) or len(quad)!=4 or any(not isinstance(pt,list) or len(pt)!=2 or any(type(v) is not int for v in pt) for pt in quad) or any(not (box[0]<=pt[0]<box[2] and box[1]<=pt[1]<box[3]) for pt in quad): raise ValueError('Invalid preview perspective quadrilateral')
                    import cv2
                    import numpy as np
                    q=np.array(quad,dtype=np.float32); width=max(2,int(max(np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[2]-q[3])))); height=max(2,int(max(np.linalg.norm(q[3]-q[0]),np.linalg.norm(q[2]-q[1]))))
                    dst=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],dtype=np.float32)
                    corrected=cv2.warpPerspective(np.array(frame),cv2.getPerspectiveTransform(q,dst),(width,height)); Image.fromarray(corrected).save(target,'JPEG',quality=95)
                else: frame.crop(box).save(target,'JPEG',quality=95)
                with Image.open(target) as check_image: check_image.verify(); dimensions=check_image.size
                results.append({'index':index,'frame':frame_index,'box':box,'path':str(target),'width':dimensions[0],'height':dimensions[1]})
        if hashfile(src)!=row['sha256']: raise ValueError('Claimed source changed while previewing')
        return {'photo_id':photo_id,'previews':results,'catalog_mutated':False,'source_archived':False}

def commit(root,db,doc):
    r=db.execute('SELECT * FROM photos WHERE id=?',(doc['photo_id'],)).fetchone()
    if not r or r['claim_token']!=doc['claim_token']: raise ValueError('Unknown job or token')
    if r['state'] in ('committed_pending_move','archived'): return {'already_committed':True,'warnings':recover(root,db)}
    if r['state']!='claimed' or doc.get('visual_inspection_complete') is not True: raise ValueError('Claimed job and explicit visual inspection required')
    run_id=doc.get('scan_run_id')
    if run_id is not None and not db.execute("SELECT 1 FROM scan_runs WHERE id=? AND state='active'",(run_id,)).fetchone(): raise ValueError('scan_run_id must reference an active scan run')
    roster=doc['items']; src=inside(root,r['source']); cat=root/'Catalog'
    if not isinstance(roster,list): raise ValueError('Items must be list')
    if hashfile(src)!=r['sha256']: raise ValueError('Source changed')
    # Reclaim only journaled, unreferenced assets belonging to this uncommitted photo.
    for j in db.execute('SELECT path FROM asset_journal WHERE photo_id=?',(r['id'],)).fetchall():
        if db.execute('SELECT 1 FROM observations WHERE image=?',(j['path'],)).fetchone() or db.execute('SELECT 1 FROM detail_assets WHERE path=?',(j['path'],)).fetchone(): raise RuntimeError('Journal unexpectedly references committed asset')
        inside(cat,j['path']).unlink(missing_ok=True)
    with db: db.execute('DELETE FROM asset_journal WHERE photo_id=?',(r['id'],))
    plan=[]; used=set(); boxes=set()
    for x in roster:
        frame_index=x.get('frame',0)
        if type(frame_index) is not int or not 0<=frame_index<r['frame_count']: raise ValueError('Invalid frame index')
        b=x['box']
        quad=x.get('quad')
        if quad is not None:
            if not isinstance(quad,list) or len(quad)!=4 or any(not isinstance(pt,list) or len(pt)!=2 or any(type(v) is not int for v in pt) for pt in quad): raise ValueError('quad must contain four integer points')
        with open_image(src) as frame_check:
            frame_check.seek(frame_index); fw,fh=ImageOps.exif_transpose(frame_check).size
        if quad is not None and any(not (0<=pt[0]<fw and 0<=pt[1]<fh) for pt in quad): raise ValueError('Perspective points outside frame')
        if not isinstance(b,list) or len(b)!=4 or any(type(k) is not int for k in b) or not (0<=b[0]<b[2]<=fw and 0<=b[1]<b[3]<=fh) or (frame_index,tuple(b)) in boxes: raise ValueError('Invalid or duplicate crop box')
        boxes.add((frame_index,tuple(b))); conf=score(x['confidence']); name=x['name']; typ=x['type']; category=x['category']
        if not all(isinstance(s,str) and s.strip() for s in (name,typ,category)): raise ValueError('Missing identity fields')
        evidence=x.get('evidence',[])
        for e in evidence:
            if not url_ok(e['url']) or not e.get('kind'): raise ValueError('Invalid evidence')
        exact=x.get('specificity')=='exact'
        if exact and (conf<90 or not any(e['kind']=='identity' for e in evidence)): raise ValueError('Exact identity needs >=90 confidence and cited identity evidence')
        key=x.get('identity_key') if exact else None
        if key is not None and not isinstance(key,str): raise ValueError('Invalid identity key')
        key=key.strip().casefold() if key else None
        activity=validate_research_activity(x.get('research_activity',{}))
        v=x.get('valuation',{}); est,lo,hi,spec=(money(v.get(k)) for k in ('estimate_cents','low_cents','high_cents','speculative_cents'))
        x['_validated_comparables']=validate_comparables(v.get('comparables',[]),evidence)
        x['_valuation_method'],x['_valuation_rationale']=validate_valuation_method(v,est,x['_validated_comparables'])
        if est is not None and (not url_ok(v.get('source_url')) or v.get('basis') not in ('sold','dealer','asking','retail') or not any(e['url']==v['source_url'] and e['kind']=='valuation' for e in evidence)): raise ValueError('Price requires matching price evidence and basis')
        if est is None and (lo is not None or hi is not None): raise ValueError('Range requires central estimate')
        if est is not None and ((lo is not None and lo>est) or (hi is not None and hi<est)): raise ValueError('Invalid range')
        if v.get('confidence') is not None: score(v['confidence'])
        if x.get('condition_confidence') is not None: score(x['condition_confidence'])
        detail_plan=[]; details=x.get('detail_crops',[])
        if not isinstance(details,list) or len(details)>12: raise ValueError('detail_crops must be a list of at most 12 entries')
        detail_boxes=set()
        for detail in details:
            if not isinstance(detail,dict): raise ValueError('Each detail crop must be an object')
            detail_frame=detail.get('frame',frame_index); dbx=detail.get('box'); label=detail.get('label')
            if detail_frame!=frame_index: raise ValueError('A detail crop must use its observation frame')
            if not isinstance(dbx,list) or len(dbx)!=4 or any(type(k) is not int for k in dbx) or not (b[0]<=dbx[0]<dbx[2]<=b[2] and b[1]<=dbx[1]<dbx[3]<=b[3]): raise ValueError('Detail crop must be a valid subregion of its item crop')
            if not isinstance(label,str) or not label.strip() or len(label)>120: raise ValueError('Detail crop requires a concise label')
            if tuple(dbx) in detail_boxes: raise ValueError('Duplicate detail crop box')
            detail_boxes.add(tuple(dbx)); detail_id=uid(); detail_path=f'Images/Details/{detail_id}.jpg'
            detail_plan.append((detail_id,detail_frame,dbx,label,detail_path))
        product=db.execute('SELECT id FROM products WHERE identity_key=?',(key,)).fetchone() if key else None
        match_id=x.get('match_item_id'); matches=[]; candidate_count=0; dup_conf=0
        if match_id is not None:
            if not isinstance(match_id,str) or not product: raise ValueError('match_item_id requires a known exact product identity')
            target=db.execute('SELECT id FROM items WHERE id=? AND product_id=? AND active=1',(match_id,product['id'])).fetchone()
            if not target or match_id in used: raise ValueError('match_item_id must reference an active matching product and be unique in this photo')
            matches=[match_id]; candidate_count=1; dup_conf=score(x.get('duplicate_confidence',100))
        elif product and not x.get('distinct_instance',False):
            candidates=[row['id'] for row in db.execute('SELECT id FROM items WHERE product_id=? AND active=1 ORDER BY created,id',(product['id'],)) if row['id'] not in used]
            candidate_count=len(candidates)
            if len(candidates)==1:
                matches=[candidates[0]]; dup_conf=80
        item=matches[0] if matches else uid(); used.add(item); obs=uid(); new=not matches
        image='Images/'+(item if new else item+'-'+obs)+'.jpg'
        plan.append((x,key,conf,item,obs,new,image,candidate_count,dup_conf,est,lo,hi,spec,frame_index,detail_plan,activity))
    with db:
        for row in plan:
            db.execute('INSERT INTO asset_journal VALUES (?,?)',(r['id'],row[6]))
            for detail in row[14]: db.execute('INSERT INTO asset_journal VALUES (?,?)',(r['id'],detail[4]))
    with open_image(src) as im:
        frame=ImageOps.exif_transpose(im).convert('RGB')
        for x,key,conf,item,obs,new,image,candidate_count,dup_conf,est,lo,hi,spec,frame_index,detail_plan,activity in plan:
            im.seek(frame_index)
            oriented=ImageOps.exif_transpose(im)
            frame=oriented.convert('RGB')
            path=inside(cat,image)
            with path.open('xb') as out:
                if x.get('quad') is not None:
                    import cv2
                    import numpy as np
                    q=np.array(x['quad'],dtype=np.float32)
                    width=max(2,int(max(np.linalg.norm(q[1]-q[0]),np.linalg.norm(q[2]-q[3])))); height=max(2,int(max(np.linalg.norm(q[3]-q[0]),np.linalg.norm(q[2]-q[1]))))
                    dst=np.array([[0,0],[width-1,0],[width-1,height-1],[0,height-1]],dtype=np.float32)
                    corrected=cv2.warpPerspective(np.array(frame),cv2.getPerspectiveTransform(q,dst),(width,height))
                    Image.fromarray(corrected).save(out,'JPEG',quality=95)
                else: frame.crop(x['box']).save(out,'JPEG',quality=95)
                out.flush(); os.fsync(out.fileno())
            with Image.open(path) as check_image: check_image.verify()
            for detail_id,detail_frame,detail_box,label,detail_rel in detail_plan:
                im.seek(detail_frame); detail_image=ImageOps.exif_transpose(im).convert('RGB')
                detail_path=inside(cat,detail_rel); detail_path.parent.mkdir(parents=True,exist_ok=True)
                with detail_path.open('xb') as out:
                    detail_image.crop(detail_box).save(out,'JPEG',quality=95); out.flush(); os.fsync(out.fileno())
                with Image.open(detail_path) as check_image: check_image.verify()
    if hashfile(src)!=r['sha256']: raise ValueError('Source changed during crop generation')
    with db:
        for x,key,conf,item,obs,new,image,candidate_count,dup_conf,est,lo,hi,spec,frame_index,detail_plan,activity in plan:
            product=None
            if key:
                db.execute('INSERT OR IGNORE INTO products(id,identity_key,name,metadata) VALUES (?,?,?,?)',(uid(),key,x['name'],js(x.get('metadata',{}))))
                product=db.execute('SELECT id FROM products WHERE identity_key=?',(key,)).fetchone()[0]
            previous_supported=db.execute('SELECT 1 FROM valuations WHERE item_id=? AND (estimate_cents IS NOT NULL OR speculative_cents IS NOT NULL) LIMIT 1',(item,)).fetchone()
            review=int(conf<75 or x.get('specificity')=='unknown' or est is None or candidate_count>1 or x.get('review',False))
            pending=int(bool(x.get('pending_research',False)) or (est is None and spec is None and (new or not previous_supported)))
            if new:
                db.execute('INSERT INTO items(id,product_id,name,category,type,subtype,confidence,condition,condition_confidence,metadata,primary_image,review,pending_research) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',(item,product,x['name'],x['category'],x['type'],x.get('subtype'),conf,x.get('condition'),x.get('condition_confidence'),js(x.get('metadata',{})),image,review,pending))
                ensure_item_taxonomy(db,item,x['category'],x['type'],x.get('subtype'))
            elif review or pending: db.execute('UPDATE items SET review=max(review,?),pending_research=max(pending_research,?) WHERE id=?',(review,pending,item))
            db.execute('INSERT INTO observations VALUES (?,?,?,?,?,?,?,?,?)',(obs,r['id'],item,frame_index,js(x['box']),image,'new' if new else ('explicit_physical_match' if x.get('match_item_id') else 'provisional_product_match'),dup_conf if not new else None,x.get('notes')))
            for detail_id,detail_frame,detail_box,label,detail_rel in detail_plan:
                detail_path=inside(cat,detail_rel); register_asset(db,detail_path,cat)
                db.execute('INSERT INTO detail_assets(id,observation_id,frame,box,path,label,sha256,bytes) VALUES (?,?,?,?,?,?,?,?)',(detail_id,obs,detail_frame,js(detail_box),detail_rel,label,hashfile(detail_path),detail_path.stat().st_size))
            for e in x.get('evidence',[]): db.execute('INSERT INTO evidence(id,item_id,observation_id,url,kind,description) VALUES (?,?,?,?,?,?)',(uid(),item,obs,e['url'],e['kind'],e.get('description')))
            for query in activity['queries']: db.execute('INSERT INTO research_runs(id,item_id,query,source,visited_url,cache_hit) VALUES (?,?,?,?,NULL,0)',(uid(),item,query['query'],query['source']))
            for visit in activity['visited_pages']: db.execute('INSERT INTO research_runs(id,item_id,query,source,visited_url,cache_hit) VALUES (?,?,?,?,?,?)',(uid(),item,visit['query'],visit['source'],visit['url'],int(visit['cache_hit'])))
            register_asset(db,inside(cat,image),cat)
            v=x.get('valuation',{})
            if new or est is not None or spec is not None or x['_validated_comparables']:
                valuation_id=uid()
                db.execute('INSERT INTO valuations(id,item_id,observation_id,estimate_cents,low_cents,high_cents,speculative_cents,source_url,basis,confidence,methodology,rationale) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)',(valuation_id,item,obs,est,lo,hi,spec,v.get('source_url') if est is not None else None,v.get('basis') if est is not None else 'unavailable',v.get('confidence'),x['_valuation_method'],x['_valuation_rationale']))
                save_comparables(db,item,valuation_id,x['_validated_comparables'])
            db.execute('INSERT INTO audit(item_id,photo_id,action,detail) VALUES (?,?,?,?)',(item,r['id'],'created' if new else 'provisional_association',js({'observation':obs,'identity_key':key,'candidate_count':candidate_count,'duplicate_confidence':dup_conf,'explicit_match':bool(x.get('match_item_id')),'distinct_instance':bool(x.get('distinct_instance')),'reason':x.get('notes')})))
        db.execute('UPDATE photos SET state=\'committed_pending_move\',scan_run_id=?,updated=CURRENT_TIMESTAMP WHERE id=?',(run_id,r['id']))
        db.execute('DELETE FROM asset_journal WHERE photo_id=?',(r['id'],))
    return {'created':sum(p[5] for p in plan),'associated':sum(not p[5] for p in plan),'warnings':recover(root,db)}

def read_inventory(root):
    db=sqlite3.connect((root/'Catalog/Vault.sqlite').resolve().as_uri()+'?mode=ro',uri=True); db.row_factory=sqlite3.Row
    try: return [dict(r) for r in db.execute('SELECT * FROM current_inventory ORDER BY id')]
    finally: db.close()

def query_inventory(root,filters=None,limit=500):
    allowed={'category','type','name','review','pending_research','confidence_min','confidence_max','value_min_cents','value_max_cents','basis','created_after','created_before','has_image'}; filters=filters or {}; clauses=[]; params=[]
    for k,v in filters.items():
        if k not in allowed: raise ValueError('Unsupported query filter: '+k)
        if k=='name': clauses.append("name LIKE ? ESCAPE '\\'"); params.append('%'+str(v).replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%')
        elif k in ('category','type','review','pending_research','basis'): clauses.append(k+'=?'); params.append(v)
        elif k in ('confidence_min','confidence_max'):
            clauses.append('confidence'+('>=' if k=='confidence_min' else '<=')+'?'); params.append(score(v))
        elif k in ('value_min_cents','value_max_cents'):
            clauses.append('estimate_cents'+('>=' if k=='value_min_cents' else '<=')+'?'); params.append(money(v))
        elif k in ('created_after','created_before'):
            try: time.strptime(v,'%Y-%m-%d')
            except (TypeError,ValueError): raise ValueError(k+' must use YYYY-MM-DD')
            clauses.append("date(created)"+('>=' if k.endswith('after') else '<=')+'date(?)'); params.append(v)
        elif k=='has_image': clauses.append("(primary_image<>'')=?"); params.append(bool(v))
    sql='SELECT * FROM current_inventory'+((' WHERE '+' AND '.join(clauses)) if clauses else '')+' ORDER BY id LIMIT ?'; params.append(max(1,min(int(limit),5000)))
    db=sqlite3.connect(f'file:{(root/"Catalog/Vault.sqlite").as_posix()}?mode=ro',uri=True); db.row_factory=sqlite3.Row
    try: return [dict(r) for r in db.execute(sql,params)]
    finally: db.close()

def catalog_summary(root):
    db=sqlite3.connect(f'file:{(root/"Catalog/Vault.sqlite").as_posix()}?mode=ro',uri=True); db.row_factory=sqlite3.Row
    try:
        photos={r['state']:r['count'] for r in db.execute('SELECT state,count(*) AS count FROM photos GROUP BY state')}
        members={r['disposition']:r['count'] for r in db.execute('SELECT disposition,count(*) AS count FROM archive_members GROUP BY disposition')}
        totals=db.execute('SELECT count(*) AS active_items,coalesce(sum(CASE WHEN v.estimate_cents IS NOT NULL THEN v.estimate_cents ELSE 0 END),0) AS evidence_value_cents,coalesce(sum(CASE WHEN v.estimate_cents IS NULL THEN coalesce(v.speculative_cents,0) ELSE 0 END),0) AS speculative_unvalued_cents,coalesce(sum(CASE WHEN v.estimate_cents IS NULL AND v.speculative_cents IS NULL THEN 1 ELSE 0 END),0) AS unvalued_items,coalesce(sum(i.review),0) AS review_items,coalesce(sum(i.pending_research),0) AS pending_research_items,coalesce(sum(CASE WHEN lower(i.name)=\'unknown item\' THEN 1 ELSE 0 END),0) AS unknown_items FROM items i LEFT JOIN v_current_valuations v ON v.item_id=i.id WHERE i.active=1').fetchone()
        return {'photos_by_state':photos,'archived_photos':photos.get('archived',0),'failed_photos':photos.get('failed_archived',0)+photos.get('failed_pending_move',0),'pending_photo_moves':photos.get('committed_pending_move',0),'zip_members_by_disposition':members,'observations':db.execute('SELECT count(*) FROM observations').fetchone()[0],'associations':db.execute("SELECT count(*) FROM observations WHERE association<>'new'").fetchone()[0],**dict(totals)}
    finally: db.close()

def backup_catalog(root,output=None):
    cat=root/'Catalog'; src=sqlite3.connect(cat/'Vault.sqlite')
    dest=Path(output) if output else cat/'Backups'/('Vault-'+uid()+'.sqlite')
    dest.parent.mkdir(parents=True,exist_ok=True); temp=dest.with_name(dest.name+'.tmp-'+uid()); out=sqlite3.connect(temp)
    try:
        if src.execute('PRAGMA quick_check').fetchone()[0]!='ok' or src.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Source catalog failed verification')
        src.backup(out)
        if out.execute('PRAGMA integrity_check').fetchone()[0]!='ok' or out.execute('PRAGMA foreign_key_check').fetchone(): raise RuntimeError('Backup verification failed')
        out.close(); src.close(); os.replace(temp,dest)
    except Exception:
        out.close(); src.close(); temp.unlink(missing_ok=True); raise
    return dest

def restore_catalog(root,backup_path):
    root=Path(root).resolve(); cat=root/'Catalog'; live=cat/'Vault.sqlite'; source=Path(backup_path).resolve()
    if source==live.resolve() or not source.is_file(): raise ValueError('Restore source must be a separate existing SQLite backup')
    cat.mkdir(parents=True,exist_ok=True); lock_path=cat/'.vault/writer.lock'; lock_path.parent.mkdir(parents=True,exist_ok=True)
    staged=cat/'.vault/restore-candidate.sqlite'; staged.unlink(missing_ok=True)
    src=sqlite3.connect(f'file:{source.as_posix()}?mode=ro',uri=True)
    dst=sqlite3.connect(staged)
    try:
        if src.execute('PRAGMA quick_check').fetchone()[0]!='ok' or src.execute('PRAGMA foreign_key_check').fetchall(): raise ValueError('Restore source failed SQLite integrity checks')
        if src.execute('PRAGMA user_version').fetchone()[0]!=SCHEMA_VERSION: raise ValueError(f'Restore source schema must be migrated to version {SCHEMA_VERSION} before restore')
        src.backup(dst); dst.commit()
    finally: dst.close(); src.close()
    candidate=sqlite3.connect(staged); candidate.row_factory=sqlite3.Row; candidate.execute('PRAGMA foreign_keys=ON')
    try: verify_migrations(candidate); check_catalog(root,candidate)
    finally: candidate.close()
    pre=cat/'Backups'/('Vault-before-restore-'+uid()+'.sqlite'); pre.parent.mkdir(parents=True,exist_ok=True)
    with lock(lock_path):
        current=sqlite3.connect(live); safety=sqlite3.connect(pre)
        try:
            current.backup(safety); safety.commit()
            if safety.execute('PRAGMA quick_check').fetchone()[0]!='ok': raise RuntimeError('Pre-restore safety backup failed verification')
        finally: safety.close(); current.close()
        try: os.replace(staged,live)
        except Exception:
            staged.unlink(missing_ok=True)
            raise
    return {'restored_from':str(source),'safety_backup':str(pre)}

def rebind_scanned(root,scanned_root):
    """Reconstruct a sibling Scanned tree from a relocated copy, without deleting sources."""
    root=Path(root).resolve(); source_root=Path(scanned_root).resolve()
    if not source_root.is_dir() or source_root.is_symlink(): raise ValueError('Scanned source must be an existing directory')
    with open_catalog(root) as db:
        requested=[]
        requested.extend(dict(r) for r in db.execute("SELECT id,sha256,destination,'photo' AS kind FROM photos WHERE state IN ('archived','failed_archived')"))
        requested.extend(dict(r) for r in db.execute("SELECT id,sha256,destination,'archive' AS kind FROM archives WHERE state='archived' AND destination IS NOT NULL"))
        inventory={}
        for folder,dirs,names in os.walk(source_root,followlinks=False):
            dirs[:]=[d for d in dirs if not (Path(folder)/d).is_symlink() and not getattr(Path(folder)/d,'is_junction',lambda:False)()]
            for name in names:
                candidate=Path(folder)/name
                if candidate.is_symlink() or not candidate.is_file(): continue
                try: inventory.setdefault(hashfile(candidate),[]).append(candidate)
                except OSError: continue
        restored=[]; already=[]; missing=[]
        for record in requested:
            relative=record['destination']
            if not relative: continue
            target=inside(root,relative)
            if target.is_file() and not target.is_symlink() and hashfile(target)==record['sha256']:
                already.append(record['id']); continue
            candidates=inventory.get(record['sha256'],[])
            if not candidates:
                missing.append({'id':record['id'],'kind':record['kind'],'destination':relative,'sha256':record['sha256']}); continue
            # If identical content has several copies, any is byte-identical. Prefer the expected
            # relative suffix to keep deterministic provenance; otherwise use a stable path order.
            candidates=sorted(candidates,key=lambda p:(not p.as_posix().casefold().endswith(relative.replace('\\','/').casefold()),str(p).casefold()))
            target.parent.mkdir(parents=True,exist_ok=True)
            temp=target.with_name(target.name+'.rebind-'+uid())
            try:
                with candidates[0].open('rb') as src,temp.open('xb') as dst: shutil.copyfileobj(src,dst,1024*1024); dst.flush(); os.fsync(dst.fileno())
                if hashfile(temp)!=record['sha256']: raise RuntimeError('Rebound file hash mismatch')
                if target.exists():
                    if target.is_symlink() or hashfile(target)!=record['sha256']: raise RuntimeError('Refusing to overwrite a different destination file')
                    temp.unlink()
                else: os.replace(temp,target)
                restored.append({'id':record['id'],'kind':record['kind'],'destination':relative,'source':str(candidates[0])})
            finally: temp.unlink(missing_ok=True)
        if restored:
            with db:
                for item in restored:
                    db.execute('INSERT INTO audit(photo_id,action,detail) VALUES (?,?,?)',(item['id'] if item['kind']=='photo' else None,'rebind_scanned',js(item)))
        return {'restored':restored,'already_present':already,'missing':missing,'source_preserved':True}

def mutate_item(root,action,item_id,field=None,value=None,reason='user request'):
    allowed={'name','category','type','subtype','condition','metadata','confidence'}
    with open_catalog(root) as db:
        row=db.execute('SELECT * FROM items WHERE id=?',(item_id,)).fetchone()
        if action=='add':
            iid=item_id or uid(); name=value.get('name','Unknown Item'); image=''
            with db:
                db.execute('INSERT INTO items(id,name,category,type,confidence,metadata,primary_image,review) VALUES (?,?,?,?,?,?,?,1)',(iid,name,value.get('category','Unclassified'),value.get('type','Unknown'),float(value.get('confidence',0)),js(value.get('metadata',{})),image))
                ensure_item_taxonomy(db,iid,value.get('category','Unclassified'),value.get('type','Unknown'),value.get('subtype'))
                db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(iid,'manual_add',js({'reason':reason})))
            return iid
        if not row: raise ValueError('Unknown item')
        if action=='edit':
            if field not in allowed: raise ValueError('Unsupported field')
            if db.execute('SELECT 1 FROM field_locks WHERE item_id=? AND field=?',(item_id,field)).fetchone(): raise ValueError('Field is locked; explicitly unlock first')
            with db:
                db.execute(f'UPDATE items SET {field}=?,updated=CURRENT_TIMESTAMP WHERE id=?',(js(value) if field=='metadata' else value,item_id))
                if field in ('category','type','subtype'):
                    latest=db.execute('SELECT category,type,subtype FROM items WHERE id=?',(item_id,)).fetchone()
                    ensure_item_taxonomy(db,item_id,latest['category'],latest['type'],latest['subtype'])
                db.execute('INSERT INTO field_locks(item_id,field,reason) VALUES (?,?,?)',(item_id,field,reason))
                db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(item_id,'manual_edit',js({'field':field,'value':value,'reason':reason})))
        elif action in ('delete','restore'):
            with db:
                db.execute('UPDATE items SET active=?,updated=CURRENT_TIMESTAMP WHERE id=?',(0 if action=='delete' else 1,item_id))
                db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(item_id,action,js({'reason':reason})))
        elif action=='unlock':
            with db: db.execute('DELETE FROM field_locks WHERE item_id=? AND field=?',(item_id,field))
        return item_id

def merge_items(root,source_id,target_id,reason='user confirmed duplicate',undo=False):
    with open_catalog(root) as db:
        if undo:
            alias=db.execute('SELECT * FROM item_aliases WHERE alias_id=?',(source_id,)).fetchone()
            if not alias: raise ValueError('No reversible merge exists')
            rows=db.execute('SELECT * FROM merge_members WHERE source_id=? AND target_id=?',(source_id,alias['item_id'])).fetchall()
            with db:
                for r in rows:
                    table={'observation':'observations','evidence':'evidence','valuation':'valuations'}[r['entity_type']]
                    db.execute(f'UPDATE {table} SET item_id=? WHERE id=?',(source_id,r['entity_id']))
                db.execute('UPDATE items SET active=1 WHERE id=?',(source_id,)); db.execute('DELETE FROM item_aliases WHERE alias_id=?',(source_id,))
                db.execute('DELETE FROM merge_members WHERE source_id=? AND target_id=?',(source_id,alias['item_id']))
                db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(source_id,'undo_merge',js({'target':alias['item_id']})))
            return
        if source_id==target_id: raise ValueError('Cannot merge item into itself')
        if not db.execute('SELECT 1 FROM items WHERE id=? AND active=1',(source_id,)).fetchone() or not db.execute('SELECT 1 FROM items WHERE id=? AND active=1',(target_id,)).fetchone(): raise ValueError('Both items must be active')
        if db.execute('SELECT 1 FROM observations s JOIN observations t ON s.photo_id=t.photo_id WHERE s.item_id=? AND t.item_id=? LIMIT 1',(source_id,target_id)).fetchone(): raise ValueError('Cannot merge two distinct observations from the same photo')
        merge_id=uid()
        with db:
            for typ,table in (('observation','observations'),('evidence','evidence'),('valuation','valuations')):
                for entity in db.execute(f'SELECT id FROM {table} WHERE item_id=?',(source_id,)).fetchall():
                    db.execute('INSERT INTO merge_members VALUES (?,?,?,?,?)',(merge_id,typ,entity['id'],source_id,target_id))
                    if typ=='observation': db.execute('UPDATE observations SET item_id=?,association=? WHERE id=?',(target_id,'merged',entity['id']))
                    else: db.execute(f'UPDATE {table} SET item_id=? WHERE id=?',(target_id,entity['id']))
            db.execute('INSERT INTO item_aliases(alias_id,item_id,reason) VALUES (?,?,?)',(source_id,target_id,reason)); db.execute('UPDATE items SET active=0 WHERE id=?',(source_id,))
            db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(target_id,'merge',js({'source':source_id,'reason':reason,'merge_id':merge_id})))

def split_item(root,item_id,observation_ids,reason='user split distinct physical items'):
    ids=list(dict.fromkeys(observation_ids))
    if not ids: raise ValueError('At least one observation ID is required')
    with open_catalog(root) as db:
        source=db.execute('SELECT * FROM items WHERE id=? AND active=1',(item_id,)).fetchone()
        if not source: raise ValueError('Active item not found')
        total=db.execute('SELECT count(*) FROM observations WHERE item_id=?',(item_id,)).fetchone()[0]
        selected=db.execute('SELECT * FROM observations WHERE item_id=? AND id IN ('+','.join('?' for _ in ids)+')',(item_id,*ids)).fetchall()
        if len(selected)!=len(ids) or len(selected)>=total: raise ValueError('Split must move a proper nonempty subset of this item\'s observations')
        new_id=uid(); fields=[k for k in source.keys() if k!='id']
        values={k:source[k] for k in fields}; values['primary_image']=selected[0]['image']; values['review']=1; values['created']=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime()); values['updated']=values['created']
        with db:
            db.execute('INSERT INTO items(id,'+','.join(fields)+') VALUES ('+','.join('?' for _ in range(len(fields)+1))+')',[new_id]+[values[k] for k in fields])
            ensure_item_taxonomy(db,new_id,values['category'],values['type'],values.get('subtype'))
            db.execute('UPDATE observations SET item_id=?,association=\'split\' WHERE id IN ('+','.join('?' for _ in ids)+')',(new_id,*ids))
            db.execute('UPDATE evidence SET item_id=? WHERE observation_id IN ('+','.join('?' for _ in ids)+')',(new_id,*ids))
            db.execute('UPDATE valuations SET item_id=? WHERE observation_id IN ('+','.join('?' for _ in ids)+')',(new_id,*ids))
            db.execute('INSERT OR IGNORE INTO field_locks(item_id,field,reason) SELECT ?,field,reason FROM field_locks WHERE item_id=?',(new_id,item_id))
            db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(item_id,'split',js({'new_item_id':new_id,'observation_ids':ids,'reason':reason})))
            db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(new_id,'split_from',js({'source_item_id':item_id,'observation_ids':ids,'reason':reason})))
        return {'source_item_id':item_id,'new_item_id':new_id,'observations_moved':ids}

def import_catalog(root,source_root):
    source_root=Path(source_root).resolve(); src=sqlite3.connect(f'file:{(source_root/"Catalog/Vault.sqlite").as_posix()}?mode=ro',uri=True); src.row_factory=sqlite3.Row
    conflicts=[]; imported=0
    try:
        src.execute('BEGIN')
        if src.execute('PRAGMA quick_check').fetchone()[0]!='ok' or src.execute('PRAGMA foreign_key_check').fetchone(): raise ValueError('Source database integrity failed')
        if src.execute('PRAGMA user_version').fetchone()[0]!=SCHEMA_VERSION: raise ValueError(f'Source catalog must use the supported schema version {SCHEMA_VERSION}')
        verify_migrations(src)
        with open_catalog(root) as db:
            sid=src.execute("SELECT value FROM catalog_meta WHERE key='catalog_uuid'").fetchone() if src.execute("SELECT 1 FROM sqlite_master WHERE name='catalog_meta'").fetchone() else None
            origin=sid[0] if sid else str(source_root)
            asset_map={}
            def import_asset(rel):
                if not rel: return rel
                if rel in asset_map: return asset_map[rel]
                src_asset=inside(source_root/'Catalog',rel)
                if not src_asset.is_file(): raise ValueError('Missing source catalog asset: '+str(rel))
                digest=hashfile(src_asset); original=Path(rel)
                candidate=original.as_posix()
                target=inside(root/'Catalog',candidate)
                ledger=db.execute('SELECT sha256 FROM catalog_assets WHERE path=?',(Path(candidate).as_posix(),)).fetchone()
                if (target.exists() and hashfile(target)!=digest) or (ledger and ledger['sha256']!=digest):
                    candidate=f'Images/import-{digest[:20]}-{original.name}'
                    target=inside(root/'Catalog',candidate)
                    if target.exists() and hashfile(target)!=digest:
                        candidate=f'Images/import-{digest}-{original.name}'
                        target=inside(root/'Catalog',candidate)
                target.parent.mkdir(parents=True,exist_ok=True)
                if not target.exists(): shutil.copy2(src_asset,target)
                if hashfile(target)!=digest: raise RuntimeError('Imported crop hash mismatch')
                register_asset(db,target,root/'Catalog')
                asset_map[rel]=Path(candidate).as_posix()
                return asset_map[rel]
            def mapped_id(kind,source_id,table):
                row=db.execute('SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type=? AND source_id=?',(origin,kind,source_id)).fetchone()
                if row: return row['local_id']
                occupied=db.execute(f'SELECT 1 FROM {table} WHERE id=?',(source_id,)).fetchone()
                local=source_id if not occupied else uid()
                if occupied: conflicts.append({'entity_type':kind,'source_id':source_id,'remapped_to':local,'reason':'local UUID already exists'})
                db.execute('INSERT INTO import_entity_origins VALUES (?,?,?,?)',(origin,kind,source_id,local))
                return local
            for row in src.execute('SELECT * FROM items'):
                existing=db.execute('SELECT local_item_id FROM item_origins WHERE origin=? AND source_item_id=?',(origin,row['id'])).fetchone()
                if existing: continue
                local=mapped_id('item',row['id'],'items')
                fields=[k for k in row.keys() if k!='id']
                values={k:row[k] for k in fields}
                values['primary_image']=import_asset(values['primary_image'])
                db.execute('INSERT INTO items(id,'+','.join(fields)+') VALUES ('+','.join('?' for _ in range(len(fields)+1))+')',[local]+[values[k] for k in fields])
                db.execute('INSERT INTO item_origins VALUES (?,?,?)',(origin,row['id'],local))
                imported+=1
                db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(local,'catalog_import',js({'origin':origin,'source_item':row['id']})))
            item_map={r['source_item_id']:r['local_item_id'] for r in db.execute('SELECT source_item_id,local_item_id FROM item_origins WHERE origin=?',(origin,))}
            if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='field_locks'").fetchone():
                for source_item,local_item in item_map.items():
                    for field_lock in src.execute('SELECT field,locked_at,reason FROM field_locks WHERE item_id=?',(source_item,)):
                        db.execute('INSERT OR IGNORE INTO field_locks(item_id,field,locked_at,reason) VALUES (?,?,?,?)',(local_item,field_lock['field'],field_lock['locked_at'],field_lock['reason']))
            for obs in src.execute('SELECT * FROM observations'):
                if obs['item_id'] not in item_map: continue
                if db.execute("SELECT 1 FROM import_entity_origins WHERE origin=? AND entity_type='observation' AND source_id=?",(origin,obs['id'])).fetchone(): continue
                obs_id=mapped_id('observation',obs['id'],'observations')
                dst_rel=import_asset(obs['image'])
                source_photo=src.execute('SELECT * FROM photos WHERE id=?',(obs['photo_id'],)).fetchone()
                if not source_photo: raise ValueError('Source observation references missing photo: '+obs['photo_id'])
                photo_link=db.execute("SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type='photo' AND source_id=?",(origin,obs['photo_id'])).fetchone()
                photo_id=photo_link['local_id'] if photo_link else mapped_id('photo',obs['photo_id'],'photos')
                if not photo_link:
                    db.execute('INSERT INTO photos(id,source,sha256,state,destination,claim_token,error,width,height,frame_count,perceptual_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(photo_id,'import:'+origin+'/'+source_photo['source'],source_photo['sha256'],'archived','',source_photo['claim_token'],None,source_photo['width'],source_photo['height'],source_photo['frame_count'],source_photo['perceptual_hash']))
                db.execute('INSERT INTO observations(id,photo_id,item_id,frame,box,image,association,duplicate_confidence,notes) VALUES (?,?,?,?,?,?,?,?,?)',(obs_id,photo_id,item_map[obs['item_id']],obs['frame'],obs['box'],dst_rel,obs['association'],obs['duplicate_confidence'],obs['notes']))
                for detail in src.execute('SELECT * FROM detail_assets WHERE observation_id=?',(obs['id'],)):
                    detail_id=detail['id']
                    if db.execute('SELECT 1 FROM detail_assets WHERE id=?',(detail_id,)).fetchone():
                        detail_id=uid(); conflicts.append({'entity_type':'detail_asset','source_id':detail['id'],'remapped_to':detail_id,'reason':'local detail UUID already exists'})
                    detail_path=import_asset(detail['path'])
                    if hashfile(inside(root/'Catalog',detail_path))!=detail['sha256']: raise ValueError('Source detail crop hash mismatch: '+detail['id'])
                    db.execute('INSERT INTO detail_assets(id,observation_id,frame,box,path,label,sha256,bytes,created) VALUES (?,?,?,?,?,?,?,?,?)',(detail_id,obs_id,detail['frame'],detail['box'],detail_path,detail['label'],detail['sha256'],detail['bytes'],detail['created']))
            if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='valuations'").fetchone():
                for origin_row in db.execute('SELECT source_item_id,local_item_id FROM item_origins WHERE origin=?',(origin,)).fetchall():
                    for val in src.execute('SELECT * FROM valuations WHERE item_id=?',(origin_row['source_item_id'],)):
                        if not db.execute("SELECT 1 FROM import_entity_origins WHERE origin=? AND entity_type='valuation' AND source_id=?",(origin,val['id'])).fetchone():
                            vals=dict(val); vals['id']=mapped_id('valuation',val['id'],'valuations'); vals['item_id']=origin_row['local_item_id']
                            if vals.get('observation_id'):
                                link=db.execute("SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type='observation' AND source_id=?",(origin,vals['observation_id'])).fetchone()
                                vals['observation_id']=link['local_id'] if link else None
                            cols=list(vals)
                            db.execute('INSERT INTO valuations('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',[vals[c] for c in cols])
                    for ev in src.execute('SELECT * FROM evidence WHERE item_id=?',(origin_row['source_item_id'],)):
                        if not db.execute("SELECT 1 FROM import_entity_origins WHERE origin=? AND entity_type='evidence' AND source_id=?",(origin,ev['id'])).fetchone():
                            vals=dict(ev); vals['id']=mapped_id('evidence',ev['id'],'evidence'); vals['item_id']=origin_row['local_item_id']
                            if vals.get('observation_id'):
                                link=db.execute("SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type='observation' AND source_id=?",(origin,vals['observation_id'])).fetchone()
                                vals['observation_id']=link['local_id'] if link else None
                            cols=list(vals)
                            db.execute('INSERT INTO evidence('+','.join(cols)+') VALUES ('+','.join('?' for _ in cols)+')',[vals[c] for c in cols])
            for origin_row in db.execute('SELECT source_item_id,local_item_id FROM item_origins WHERE origin=?',(origin,)).fetchall():
                for val in src.execute('SELECT * FROM valuations WHERE item_id=?',(origin_row['source_item_id'],)):
                    link=db.execute("SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type='valuation' AND source_id=?",(origin,val['id'])).fetchone()
                    if link and val['observation_id']:
                        obslink=db.execute("SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type='observation' AND source_id=?",(origin,val['observation_id'])).fetchone()
                        if obslink: db.execute('UPDATE valuations SET observation_id=? WHERE id=?',(obslink['local_id'],link['local_id']))
                for audit_row in src.execute('SELECT * FROM audit WHERE item_id=?',(origin_row['source_item_id'],)):
                    if db.execute('SELECT 1 FROM import_audit_origins WHERE origin=? AND source_audit_id=?',(origin,audit_row['id'])).fetchone(): continue
                    photo_link=db.execute("SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type='photo' AND source_id=?",(origin,audit_row['photo_id'])).fetchone() if audit_row['photo_id'] else None
                    cur=db.execute('INSERT INTO audit(item_id,photo_id,action,detail,created) VALUES (?,?,?,?,?)',(origin_row['local_item_id'],photo_link['local_id'] if photo_link else None,audit_row['action'],js({'import_origin':origin,'source_audit_id':audit_row['id'],'source_detail':audit_row['detail']}),audit_row['created']))
                    db.execute('INSERT INTO import_audit_origins VALUES (?,?,?)',(origin,audit_row['id'],cur.lastrowid))
            if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='item_aliases'").fetchone():
                for alias in src.execute('SELECT * FROM item_aliases'):
                    if alias['alias_id'] in item_map and alias['item_id'] in item_map:
                        db.execute('INSERT OR IGNORE INTO item_aliases(alias_id,item_id,reason,created) VALUES (?,?,?,?)',(item_map[alias['alias_id']],item_map[alias['item_id']],alias['reason'],alias['created']))
            if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='merge_members'").fetchone():
                for member in src.execute('SELECT * FROM merge_members'):
                    if member['source_id'] not in item_map or member['target_id'] not in item_map: continue
                    id_map=db.execute('SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type=? AND source_id=?',(origin,member['entity_type'],member['entity_id'])).fetchone()
                    if not id_map: continue
                    merge_id='import-'+hashlib.sha256(origin.encode()).hexdigest()[:12]+':'+member['merge_id']
                    db.execute('INSERT OR IGNORE INTO merge_members VALUES (?,?,?,?,?)',(merge_id,member['entity_type'],id_map['local_id'],item_map[member['source_id']],item_map[member['target_id']]))
            if src.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='valuation_comparables'").fetchone():
                for comp in src.execute('SELECT * FROM valuation_comparables'):
                    if db.execute('SELECT 1 FROM import_comparable_origins WHERE origin=? AND source_id=?',(origin,comp['id'])).fetchone(): continue
                    val_link=db.execute("SELECT local_id FROM import_entity_origins WHERE origin=? AND entity_type='valuation' AND source_id=?",(origin,comp['valuation_id'])).fetchone()
                    if not val_link or comp['item_id'] not in item_map: continue
                    collision=db.execute('SELECT 1 FROM valuation_comparables WHERE id=?',(comp['id'],)).fetchone(); local_id=comp['id'] if not collision else uid()
                    if collision: conflicts.append({'entity_type':'comparable','source_id':comp['id'],'remapped_to':local_id,'reason':'local comparable UUID already exists'})
                    db.execute('INSERT INTO import_comparable_origins VALUES (?,?,?)',(origin,comp['id'],local_id))
                    db.execute('INSERT INTO valuation_comparables(id,valuation_id,item_id,source_url,sale_basis,original_amount,currency,quantity,sold_at,fx_rate,fx_source_url,normalized_unit_cents,adjusted_unit_cents,adjustment_notes,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(local_id,val_link['local_id'],item_map[comp['item_id']],comp['source_url'],comp['sale_basis'],comp['original_amount'],comp['currency'],comp['quantity'],comp['sold_at'],comp['fx_rate'],comp['fx_source_url'],comp['normalized_unit_cents'],comp['adjusted_unit_cents'],comp['adjustment_notes'],comp['observed_at']))
            backfill_taxonomy(db)
        return {'origin':origin,'items_imported':imported,'conflicts':conflicts}
    finally: src.close()

def review_queue(root):
    db=sqlite3.connect(f'file:{(root/"Catalog/Vault.sqlite").as_posix()}?mode=ro',uri=True); db.row_factory=sqlite3.Row
    try: return [dict(r) for r in db.execute('SELECT id,name,category,type,confidence,review,pending_research FROM items WHERE active=1 AND (review=1 OR pending_research=1) ORDER BY created,id')]
    finally: db.close()

def resolve_review(root,item_id,reason='agent review complete'):
    with open_catalog(root) as db:
        if not db.execute('SELECT 1 FROM items WHERE id=? AND active=1',(item_id,)).fetchone(): raise ValueError('Active item not found')
        with db:
            db.execute('UPDATE items SET review=0,updated=CURRENT_TIMESTAMP WHERE id=?',(item_id,))
            db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(item_id,'review_resolved',js({'reason':reason})))
        return {'item_id':item_id,'review':False}

def private_learning(category=None,limit=100):
    data_home=Path(os.environ.get('VAULT_DATA_HOME',Path.home()/'.local'/'share'/'vault')).expanduser()
    path=data_home/'corrections'/'corrections.jsonl'
    if not path.is_file(): return []
    out=[]
    for line in path.read_text(encoding='utf-8').splitlines()[-max(1,min(int(limit),1000)):]:
        try: row=json.loads(line)
        except (ValueError,TypeError): continue
        if category is None or row.get('category','').casefold()==category.casefold(): out.append(row)
    return out

def record_learning_rule(category,correction_id,rule,positive_cues=None,negative_cues=None):
    """Store a private, explicitly provisional rule grounded in a local user correction."""
    if not isinstance(category,str) or not category.strip() or len(category)>120: raise ValueError('A short category is required')
    if not isinstance(correction_id,str) or not correction_id.strip(): raise ValueError('A local correction ID is required')
    if not isinstance(rule,str) or not 20<=len(rule.strip())<=1000: raise ValueError('Rule must contain 20..1000 characters')
    def cues(values,label):
        values=values or []
        if not isinstance(values,list) or len(values)>10 or any(not isinstance(x,str) or not x.strip() or len(x)>250 for x in values): raise ValueError(label+' must be up to 10 concise strings')
        return [x.strip() for x in values]
    data_home=Path(os.environ.get('VAULT_DATA_HOME',Path.home()/'.local'/'share'/'vault')).expanduser()
    corrections=data_home/'corrections'/'corrections.jsonl'
    source=None
    if corrections.is_file():
        for line in corrections.read_text(encoding='utf-8').splitlines():
            try: candidate=json.loads(line)
            except (ValueError,TypeError): continue
            if candidate.get('id')==correction_id: source=candidate; break
    if not source: raise ValueError('Correction ID is not present in this private data home')
    if source.get('category','').casefold()!=category.strip().casefold(): raise ValueError('Rule category must match its correction category')
    record={'id':uid(),'correction_id':correction_id,'category':category.strip(),'rule':rule.strip(),'positive_cues':cues(positive_cues,'positive_cues'),'negative_cues':cues(negative_cues,'negative_cues'),'status':'candidate','created':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
    path=data_home/'knowledge'/'rules.jsonl'; path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('a',encoding='utf-8') as f: f.write(js(record)+'\n'); f.flush(); os.fsync(f.fileno())
    return record

def private_learning_rules(category=None,limit=100):
    data_home=Path(os.environ.get('VAULT_DATA_HOME',Path.home()/'.local'/'share'/'vault')).expanduser(); path=data_home/'knowledge'/'rules.jsonl'
    if not path.is_file(): return []
    out=[]
    for line in path.read_text(encoding='utf-8').splitlines()[-max(1,min(int(limit),1000)):]:
        try: row=json.loads(line)
        except (ValueError,TypeError): continue
        if category is None or row.get('category','').casefold()==category.casefold(): out.append(row)
    return out

def queue_research(root,item_ids=None,force=False):
    with open_catalog(root) as db:
        rows=db.execute('SELECT id,name,category,type,subtype,metadata FROM items WHERE active=1 AND pending_research=1' if not item_ids else 'SELECT id,name,category,type,subtype,metadata FROM items WHERE active=1 AND id IN ('+','.join('?' for _ in item_ids)+')',item_ids or ()).fetchall()
        out=[]
        for r in rows:
            prior=db.execute('SELECT status,attempts FROM research_queue WHERE item_id=?',(r['id'],)).fetchone()
            if prior and prior['status']=='failed' and prior['attempts']>=5 and not force:
                out.append({'item_id':r['id'],'status':'failed','attempts':prior['attempts'],'instruction':'Retry limit reached; use retry-research --force after resolving the reported network/source problem.'}); continue
            if force: db.execute("INSERT INTO research_queue(item_id,status,attempts) VALUES (?,'pending',0) ON CONFLICT(item_id) DO UPDATE SET status='pending',attempts=0,last_error=NULL,updated=CURRENT_TIMESTAMP",(r['id'],))
            else: db.execute("INSERT INTO research_queue(item_id,status) VALUES (?,'pending') ON CONFLICT(item_id) DO UPDATE SET status=CASE WHEN research_queue.status='complete' THEN 'pending' ELSE research_queue.status END,updated=CURRENT_TIMESTAMP",(r['id'],))
            material='|'.join(str(r[k] or '') for k in ('category','type','subtype','name','metadata')).casefold(); key='item:'+hashlib.sha256(material.encode('utf-8')).hexdigest()
            cache=db.execute('SELECT result_json,source_urls FROM research_cache WHERE cache_key=? AND expires>CURRENT_TIMESTAMP',(key,)).fetchone()
            out.append({'item_id':r['id'],'name':r['name'],'category':r['category'],'type':r['type'],'status':'cached' if cache else 'pending','cache_key':key,'cached_result':json.loads(cache['result_json']) if cache else None,'instruction':'Use a valid unexpired cache result if suitable; otherwise search Google/eBay first, escalate to category specialists, then record actual evidence and valuation. Leave price NULL without adequate evidence.'})
        return out

def research_failed(root,item_id,reason):
    if not isinstance(reason,str) or not reason.strip(): raise ValueError('Failure reason is required')
    with open_catalog(root) as db:
        if not db.execute('SELECT 1 FROM items WHERE id=? AND active=1',(item_id,)).fetchone(): raise ValueError('Active item not found')
        with db:
            db.execute("INSERT INTO research_queue(item_id,status,attempts,last_error) VALUES (?,'pending',1,?) ON CONFLICT(item_id) DO UPDATE SET attempts=research_queue.attempts+1,last_error=excluded.last_error,status=CASE WHEN research_queue.attempts+1>=5 THEN 'failed' ELSE 'pending' END,updated=CURRENT_TIMESTAMP",(item_id,reason[:1000]))
            db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(item_id,'research_failed',js({'reason':reason[:1000]})))
        row=db.execute('SELECT status,attempts FROM research_queue WHERE item_id=?',(item_id,)).fetchone()
        return {'item_id':item_id,'status':row['status'],'attempts':row['attempts'],'last_error':reason[:1000]}

def research_snapshot(root,item_ids=None):
    db=sqlite3.connect(f'file:{(root/"Catalog/Vault.sqlite").as_posix()}?mode=ro',uri=True); db.row_factory=sqlite3.Row
    try:
        sql='SELECT id,name,category,type,subtype,metadata,primary_image,pending_research FROM current_inventory'
        params=()
        if item_ids: sql+=' WHERE id IN ('+','.join('?' for _ in item_ids)+')'; params=tuple(item_ids)
        else: sql+=' WHERE pending_research=1'
        out=[]
        for row in db.execute(sql+' ORDER BY id',params):
            material='|'.join(str(row[k] or '') for k in ('category','type','subtype','name','metadata')).casefold(); key='item:'+hashlib.sha256(material.encode('utf-8')).hexdigest()
            cache=db.execute('SELECT result_json,source_urls,expires FROM research_cache WHERE cache_key=? AND expires>CURRENT_TIMESTAMP',(key,)).fetchone()
            out.append({**dict(row),'cache_key':key,'cached_result':json.loads(cache['result_json']) if cache else None,'cached_urls':json.loads(cache['source_urls']) if cache else [],'cache_expires':cache['expires'] if cache else None})
        return {'mode':'research-only','catalog_mutated':False,'items':out}
    finally: db.close()

def rescan_snapshot(root,item_id):
    root=Path(root).resolve(); db=sqlite3.connect(f'file:{(root/"Catalog/Vault.sqlite").as_posix()}?mode=ro',uri=True); db.row_factory=sqlite3.Row
    try:
        item=db.execute('SELECT id,name,category,type,primary_image FROM items WHERE id=? AND active=1',(item_id,)).fetchone()
        if not item: raise ValueError('Active item not found')
        photos=[]
        for row in db.execute('SELECT DISTINCT p.id,p.sha256,p.destination,o.frame,o.box FROM observations o JOIN photos p ON p.id=o.photo_id WHERE o.item_id=? ORDER BY p.created',(item_id,)):
            src=inside(root,row['destination'])
            if not src.is_file() or hashfile(src)!=row['sha256']: continue
            photos.append({'photo_id':row['id'],'path':str(src),'frame':row['frame'],'box':json.loads(row['box'])})
        return {'item':dict(item),'original_photographs':photos,'instruction':'Reinspect archived source images and relevant frames; this is read-only. Record any corrections through the audited item command. Reuse current records only when visual evidence confirms them.'}
    finally: db.close()

def cache_research(root,key,result,urls,ttl_days=30):
    if not isinstance(key,str) or not key.strip(): raise ValueError('Cache key required')
    if type(ttl_days) is not int or not 1<=ttl_days<=365: raise ValueError('Cache TTL must be 1..365 days')
    if not isinstance(urls,list) or any(not url_ok(u) for u in urls): raise ValueError('Cache URLs must be public HTTP(S) URLs')
    with open_catalog(root) as db:
        expires=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(time.time()+ttl_days*86400))
        db.execute('INSERT INTO research_cache VALUES (?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET result_json=excluded.result_json,source_urls=excluded.source_urls,created=CURRENT_TIMESTAMP,expires=excluded.expires',(key,js(result),js(urls),time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime()),expires))

def get_cached_research(root,key):
    with open_catalog(root) as db:
        row=db.execute("SELECT result_json,source_urls FROM research_cache WHERE cache_key=? AND expires>CURRENT_TIMESTAMP",(key,)).fetchone()
        if row: return {'result':json.loads(row[0]),'urls':json.loads(row[1]),'cache_hit':True}
        return None

def research_key_for_item(root,item_id):
    with open_catalog(root) as db:
        row=db.execute('SELECT name,category,type,subtype,metadata FROM items WHERE id=?',(item_id,)).fetchone()
        if not row: raise ValueError('Item not found')
        material='|'.join(str(row[k] or '') for k in ('category','type','subtype','name','metadata')).casefold()
        return 'item:'+hashlib.sha256(material.encode('utf-8')).hexdigest()

def cache_item_research(root,item_id,result,ttl_days=30):
    if not isinstance(result,dict) or not isinstance(result.get('evidence',[]),list): raise ValueError('Cached research must use the research result schema')
    urls=[]
    for evidence in result.get('evidence',[]):
        if not isinstance(evidence,dict) or not url_ok(evidence.get('url')): raise ValueError('Invalid cached research evidence URL')
        urls.append(evidence['url'])
    key=research_key_for_item(root,item_id); cache_research(root,key,result,urls,ttl_days)
    return {'cache_key':key,'expires_in_days':ttl_days,'source_count':len(set(urls))}

def record_research(root,item_id,result):
    """Persist host-agent research as evidence and append-only valuation history."""
    if not isinstance(result,dict): raise ValueError('Research result must be an object')
    evidence=result.get('evidence',[]); val=result.get('valuation',{})
    if not isinstance(evidence,list) or not isinstance(val,dict): raise ValueError('Evidence must be an array and valuation an object')
    activity=validate_research_activity(result.get('research_activity',{}))
    queries=activity['queries']; visits=activity['visited_pages']
    for e in evidence:
        if not isinstance(e,dict) or not url_ok(e.get('url')) or e.get('kind') not in ('identity','valuation'): raise ValueError('Invalid research evidence URL or kind')
    comparables=validate_comparables(val.get('comparables',[]),evidence)
    est,low,high,spec=(money(val.get(k)) for k in ('estimate_cents','low_cents','high_cents','speculative_cents'))
    source=val.get('source_url'); basis=val.get('basis','unavailable')
    if est is not None and (not url_ok(source) or basis not in ('sold','dealer','asking','retail') or not any(e['url']==source and e['kind']=='valuation' for e in evidence)): raise ValueError('Supported valuation requires matching URL and basis')
    if est is None and (low is not None or high is not None): raise ValueError('Range requires estimate')
    if est is not None and ((low is not None and low>est) or (high is not None and high<est)): raise ValueError('Invalid valuation range')
    conf=val.get('confidence')
    if conf is not None: score(conf)
    methodology,rationale=validate_valuation_method(val,est,comparables)
    with open_catalog(root) as db:
        item=db.execute('SELECT id,name,category,type,subtype,metadata FROM items WHERE id=? AND active=1',(item_id,)).fetchone()
        if not item: raise ValueError('Active item not found')
        with db:
            for e in evidence: db.execute('INSERT INTO evidence(id,item_id,url,kind,description) VALUES (?,?,?,?,?)',(uid(),item_id,e['url'],e['kind'],e.get('description')))
            for query in queries: db.execute('INSERT INTO research_runs(id,item_id,query,source,visited_url,cache_hit) VALUES (?,?,?,?,NULL,0)',(uid(),item_id,query['query'],query['source']))
            for visit in visits: db.execute('INSERT INTO research_runs(id,item_id,query,source,visited_url,cache_hit) VALUES (?,?,?,?,?,?)',(uid(),item_id,visit['query'],visit['source'],visit['url'],int(visit['cache_hit'])))
            valuation_id=uid()
            db.execute('INSERT INTO valuations(id,item_id,estimate_cents,low_cents,high_cents,speculative_cents,source_url,basis,confidence,methodology,rationale) VALUES (?,?,?,?,?,?,?,?,?,?,?)',(valuation_id,item_id,est,low,high,spec,source if est is not None else None,basis,conf,methodology,rationale))
            save_comparables(db,item_id,valuation_id,comparables)
            # Research was attempted, but an unsupported/absent estimate remains eligible for
            # later revaluation; evidence-backed or explicitly speculative results clear it.
            db.execute('UPDATE items SET pending_research=?,updated=CURRENT_TIMESTAMP WHERE id=?',(int(est is None and spec is None),item_id))
            db.execute("INSERT INTO research_queue(item_id,status,attempts,last_error,updated) VALUES (?,'complete',1,NULL,CURRENT_TIMESTAMP) ON CONFLICT(item_id) DO UPDATE SET status='complete',attempts=research_queue.attempts+1,last_error=NULL,updated=CURRENT_TIMESTAMP",(item_id,))
            db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(item_id,'research_recorded',js({'evidence_count':len(evidence),'comparable_count':len(comparables),'basis':basis,'supported':est is not None})))
            material='|'.join(str(item[k] or '') for k in ('category','type','subtype','name','metadata')).casefold(); cache_key='item:'+hashlib.sha256(material.encode('utf-8')).hexdigest()
            urls=list(dict.fromkeys(e['url'] for e in evidence)); created=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime()); expires=time.strftime('%Y-%m-%d %H:%M:%S',time.gmtime(time.time()+30*86400))
            db.execute('INSERT INTO research_cache(cache_key,result_json,source_urls,created,expires) VALUES (?,?,?,?,?) ON CONFLICT(cache_key) DO UPDATE SET result_json=excluded.result_json,source_urls=excluded.source_urls,created=excluded.created,expires=excluded.expires',(cache_key,js(result),js(urls),created,expires))
        return {'item_id':item_id,'valuation_recorded':est is not None,'evidence_count':len(evidence),'comparable_count':len(comparables),'pending_research':est is None and spec is None}

def add_observation_result(root,item_id,field,value,reason):
    if field not in ('name','category','type','subtype','condition','metadata','confidence'): raise ValueError('Unsupported correction field')
    with open_catalog(root) as db:
        if not db.execute('SELECT 1 FROM items WHERE id=?',(item_id,)).fetchone(): raise ValueError('Unknown item')
        db.execute('CREATE TABLE IF NOT EXISTS corrections(id TEXT PRIMARY KEY,item_id TEXT,field TEXT,old_value TEXT,new_value TEXT,reason TEXT,created TEXT DEFAULT CURRENT_TIMESTAMP)')
        old=db.execute('SELECT '+field+' FROM items WHERE id=?',(item_id,)).fetchone()[0]
        if db.execute('SELECT 1 FROM field_locks WHERE item_id=? AND field=?',(item_id,field)).fetchone(): raise ValueError('Field locked')
        category=db.execute('SELECT category FROM items WHERE id=?',(item_id,)).fetchone()[0]
        correction={'id':uid(),'catalog':str(db.execute("select value from catalog_meta where key='catalog_uuid'").fetchone()[0]),'item_id':item_id,'category':category,'field':field,'old_value':old,'new_value':value,'reason':reason,'created':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime())}
        with db:
            db.execute(f'UPDATE items SET {field}=?,updated=CURRENT_TIMESTAMP WHERE id=?',(js(value) if field=='metadata' else value,item_id))
            if field in ('category','type','subtype'):
                current=db.execute('SELECT category,type,subtype FROM items WHERE id=?',(item_id,)).fetchone()
                ensure_item_taxonomy(db,item_id,current['category'],current['type'],current['subtype'])
            db.execute('INSERT INTO field_locks(item_id,field,reason) VALUES (?,?,?)',(item_id,field,reason))
            db.execute('INSERT INTO corrections(id,item_id,field,old_value,new_value,reason) VALUES (?,?,?,?,?,?)',(correction['id'],item_id,field,str(old),str(value),reason))
            db.execute('INSERT INTO audit(item_id,action,detail) VALUES (?,?,?)',(item_id,'correction',js({'field':field,'reason':reason})))
            db.execute('UPDATE items SET review=1 WHERE category=(SELECT category FROM items WHERE id=?)',(item_id,))
        data_home=Path(os.environ.get('VAULT_DATA_HOME',Path.home()/'.local'/'share'/'vault')).expanduser()
        corr=data_home/'corrections'/'corrections.jsonl'; corr.parent.mkdir(parents=True,exist_ok=True)
        with corr.open('a',encoding='utf-8') as f: f.write(js(correction)+'\n'); f.flush(); os.fsync(f.fileno())
        return {'item_id':item_id,'field':field,'correction_id':correction['id'],'locked':True,'category_rule_update':'local correction recorded; use a provisional private learning rule only when the error reason generalizes'}

def export_catalog(root,fmt,output):
    rows=read_inventory(root); output=Path(output); output.parent.mkdir(parents=True,exist_ok=True)
    if fmt=='json': output.write_text(js({'schema_version':1,'items':rows}),encoding='utf-8')
    elif fmt=='csv':
        with output.open('w',newline='',encoding='utf-8-sig') as f:
            w=csv.DictWriter(f,fieldnames=list(rows[0]) if rows else INVENTORY_FIELDS); w.writeheader()
            for row in rows:
                safe={k:("'"+str(v) if isinstance(v,str) and v[:1] in ('=','+','-','@') else v) for k,v in row.items()}; w.writerow(safe)
    elif fmt=='html':
        import html
        import base64, mimetypes
        cards=[]
        for r in rows:
            img=html.escape(str(r.get('primary_image') or ''),quote=True)
            image=''
            if img:
                path=inside(root/'Catalog',img)
                if path.is_file(): image='data:'+ (mimetypes.guess_type(path.name)[0] or 'application/octet-stream')+';base64,'+base64.b64encode(path.read_bytes()).decode('ascii')
            link=r.get('source_url')
            a=(' <a rel="noopener noreferrer" href="'+html.escape(link,quote=True)+'">valuation evidence</a>') if isinstance(link,str) and url_ok(link) else ''
            title=html.escape(str(r['name']),quote=True); estimate=r.get('estimate_cents')
            method=html.escape(str(r.get('methodology') or 'unavailable')); rationale=html.escape(str(r.get('rationale') or ''))
            cards.append(f'<article data-name="{title.lower()}" data-value="{estimate if estimate is not None else -1}"><h2>{title}</h2><p>{html.escape(str(r["category"]))} · {html.escape(str(r["type"]))}</p>'+(f'<img loading="lazy" alt="item crop" src="{image}">' if image else '<p>Image unavailable</p>')+f'<p>Estimated cents: {estimate}</p><p>Method: {method}; comparables: {r.get("comparable_count",0)}</p><p>{rationale}</p>'+a+'</article>')
        output.write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Vault catalog</title><label>Filter <input id="q" type="search"></label><label>Sort <select id="sort"><option value="name">Name</option><option value="value">Value</option></select></label><main>'+''.join(cards)+'</main><script>const q=document.getElementById("q"),s=document.getElementById("sort"),m=document.querySelector("main");function update(){const a=[...m.children];for(const x of a)x.hidden=!x.innerText.toLowerCase().includes(q.value.toLowerCase());a.sort((x,y)=>s.value==="name"?x.dataset.name.localeCompare(y.dataset.name):Number(y.dataset.value)-Number(x.dataset.value)).forEach(x=>m.append(x))}q.oninput=update;s.onchange=update;</script></html>',encoding='utf-8')
    elif fmt in ('xls','xlsx'):
        keys=list(rows[0]) if rows else ['id','name']
        if fmt=='xls':
            import xlwt, tempfile
            fields=keys+['image','valuation_link']
            if len(fields)>256: raise ValueError('Legacy XLS limit is 256 columns')
            wb=xlwt.Workbook(); chunks=[rows[i:i+XLS_MAX_DATA_ROWS] for i in range(0,len(rows),XLS_MAX_DATA_ROWS)] or [[]]
            for si,chunk in enumerate(chunks):
                ws=wb.add_sheet('Inventory' if si==0 else f'Inventory_{si+1}')
                for col,k in enumerate(fields): ws.write(0,col,k)
                for ri,r in enumerate(chunk,1):
                    for ci,k in enumerate(keys):
                        value=r.get(k)
                        if value is not None: ws.write(ri,ci,value if isinstance(value,(int,float)) else str(value)[:32767])
                    url=str(r.get('source_url') or '').replace('"','""')
                    ws.write(ri,len(keys)+1,xlwt.Formula('HYPERLINK("%s","evidence")'%url) if url_ok(r.get('source_url')) else '')
                    if r.get('primary_image'):
                        source=inside(root/'Catalog',r['primary_image'])
                        if source.is_file():
                            fd,bmp_name=tempfile.mkstemp(suffix='.bmp'); os.close(fd); bmp=Path(bmp_name)
                            try:
                                with Image.open(source) as im: im.convert('RGB').save(bmp)
                                ws.insert_bitmap(str(bmp),ri,len(keys))
                            finally: bmp.unlink(missing_ok=True)
            wb.save(str(output))
        else:
            from openpyxl import Workbook
            from openpyxl.drawing.image import Image as XLImage
            image_streams=[]
            wb=Workbook(); chunks=[rows[i:i+XLSX_MAX_DATA_ROWS] for i in range(0,len(rows),XLSX_MAX_DATA_ROWS)] or [[]]
            for si,chunk in enumerate(chunks):
                ws=wb.active if si==0 else wb.create_sheet()
                ws.title='Inventory' if si==0 else f'Inventory_{si+1}'
                fields=keys+['image','valuation_link']; ws.append(fields)
                for ri,r in enumerate(chunk,2):
                    ws.append([r.get(k) for k in keys]+['',''])
                    if r.get('source_url') and url_ok(r['source_url']):
                        cell=ws.cell(ri,len(keys)+2); cell.value='evidence'; cell.hyperlink=r['source_url']; cell.style='Hyperlink'
                    if r.get('primary_image'):
                        source=inside(root/'Catalog',r['primary_image'])
                        if source.is_file():
                            stream=io.BytesIO(source.read_bytes()); image_streams.append(stream)
                            img=XLImage(stream); img.width=min(img.width,140); img.height=min(img.height,180); ws.add_image(img,ws.cell(ri,len(keys)+1).coordinate); ws.row_dimensions[ri].height=100
            wb.save(output)
            for stream in image_streams: stream.close()
    else: raise ValueError('Unsupported export format')
    return output

def main():
    p=argparse.ArgumentParser(description=__doc__); p.add_argument('--root',type=Path,default=Path.cwd()); sub=p.add_subparsers(dest='cmd',required=True)
    for n in ('claim','resume','check','summary','query','doctor','dry-run'): sub.add_parser(n)
    q=sub.add_parser('filter'); q.add_argument('--category'); q.add_argument('--type'); q.add_argument('--name'); q.add_argument('--review',type=int); q.add_argument('--pending-research',type=int); q.add_argument('--confidence-min',type=float); q.add_argument('--confidence-max',type=float); q.add_argument('--value-min-cents',type=int); q.add_argument('--value-max-cents',type=int); q.add_argument('--basis'); q.add_argument('--created-after'); q.add_argument('--created-before'); q.add_argument('--has-image',type=int); q.add_argument('--limit',type=int,default=500)
    c=sub.add_parser('commit'); c.add_argument('manifest',type=Path)
    n=sub.add_parser('normalize'); n.add_argument('id'); n.add_argument('output',type=Path); n.add_argument('--frame',type=int,default=0)
    detect=sub.add_parser('propose-crops'); detect.add_argument('image',type=Path)
    preview=sub.add_parser('preview-crops'); preview.add_argument('photo_id'); preview.add_argument('--claim-token',required=True); preview.add_argument('--regions',type=Path,required=True); preview.add_argument('--output-dir',type=Path,required=True)
    b=sub.add_parser('backup'); b.add_argument('--output',type=Path)
    restore=sub.add_parser('restore'); restore.add_argument('--from',dest='backup',type=Path,required=True)
    rebind=sub.add_parser('rebind'); rebind.add_argument('--scanned-root',type=Path,required=True)
    e=sub.add_parser('export'); e.add_argument('--format',choices=('csv','json','html','xls','xlsx'),required=True); e.add_argument('--output',type=Path,required=True)
    m=sub.add_parser('item'); m.add_argument('action',choices=('add','edit','delete','restore','unlock','correct')); m.add_argument('--id'); m.add_argument('--field'); m.add_argument('--value'); m.add_argument('--reason',default='user request')
    mg=sub.add_parser('merge'); mg.add_argument('source'); mg.add_argument('target'); mg.add_argument('--undo',action='store_true')
    sp=sub.add_parser('split'); sp.add_argument('item_id'); sp.add_argument('observation_ids',nargs='+'); sp.add_argument('--reason',default='user split distinct physical items')
    imp=sub.add_parser('import'); imp.add_argument('source_root',type=Path)
    review=sub.add_parser('review'); review.add_argument('--resolve'); review.add_argument('--reason',default='agent review complete')
    learning=sub.add_parser('learning'); learning.add_argument('--category'); learning.add_argument('--limit',type=int,default=100)
    learning_rules=sub.add_parser('learning-rules'); learning_rules.add_argument('--category'); learning_rules.add_argument('--limit',type=int,default=100)
    learn=sub.add_parser('learn-rule'); learn.add_argument('--category',required=True); learn.add_argument('--correction-id',required=True); learn.add_argument('--rule',required=True); learn.add_argument('--positive-cue',action='append',default=[]); learn.add_argument('--negative-cue',action='append',default=[])
    ta=sub.add_parser('taxonomy-alias'); ta.add_argument('--kind',choices=('category','type','subtype'),required=True); ta.add_argument('--name',required=True); ta.add_argument('--alias',required=True); ta.add_argument('--category'); ta.add_argument('--parent-type')
    run=sub.add_parser('run'); run.add_argument('action',choices=('start','finish','list')); run.add_argument('--id'); run.add_argument('--agent'); run.add_argument('--model'); run.add_argument('--interrupted',action='store_true'); run.add_argument('--limit',type=int,default=50)
    retry=sub.add_parser('retry-research'); retry.add_argument('--force',action='store_true')
    rf=sub.add_parser('research-failed'); rf.add_argument('item_id'); rf.add_argument('--reason',required=True)
    research=sub.add_parser('research-only'); research.add_argument('--item-id',action='append'); research.add_argument('--query',dest='research_query',action='append')
    rc=sub.add_parser('research-cache'); rc.add_argument('--item-id',required=True); rc.add_argument('--put',type=Path); rc.add_argument('--ttl-days',type=int,default=30)
    rr=sub.add_parser('record-research'); rr.add_argument('item_id'); rr.add_argument('result',type=Path)
    rv=sub.add_parser('revalue'); rv.add_argument('--item-id',action='append')
    rs=sub.add_parser('rescan'); rs.add_argument('--item-id',required=True)
    a=p.parse_args(); root=a.root.resolve()
    if a.cmd=='dry-run': result={'files':[str(f.relative_to(root)) for f in files(root)],'mutated':False}
    elif a.cmd=='propose-crops': result=propose_card_regions(a.image)
    elif a.cmd=='preview-crops': result=preview_crops(root,a.photo_id,a.claim_token,json.loads(a.regions.read_text(encoding='utf-8')).get('items'),a.output_dir)
    elif a.cmd=='export': result={'exported':str(export_catalog(root,a.format,a.output)),'format':a.format}
    elif a.cmd=='backup':
        with open_catalog(root): pass
        result={'backup':str(backup_catalog(root,a.output))}
    elif a.cmd=='restore':
        with open_catalog(root): pass
        result=restore_catalog(root,a.backup)
    elif a.cmd=='rebind': result=rebind_scanned(root,a.scanned_root)
    elif a.cmd=='item':
        val=json.loads(a.value) if a.value and a.value.startswith('{') else a.value
        result=add_observation_result(root,a.id,a.field,val,a.reason) if a.action=='correct' else {'item_id':mutate_item(root,a.action,a.id,a.field,val,a.reason)}
    elif a.cmd=='merge':
        merge_items(root,a.source,a.target,undo=a.undo); result={'merged':not a.undo}
    elif a.cmd=='split': result=split_item(root,a.item_id,a.observation_ids,a.reason)
    elif a.cmd=='import': result=import_catalog(root,a.source_root)
    elif a.cmd=='review': result=resolve_review(root,a.resolve,a.reason) if a.resolve else review_queue(root)
    elif a.cmd=='learning': result=private_learning(a.category,a.limit)
    elif a.cmd=='learning-rules': result=private_learning_rules(a.category,a.limit)
    elif a.cmd=='learn-rule': result=record_learning_rule(a.category,a.correction_id,a.rule,a.positive_cue,a.negative_cue)
    elif a.cmd=='taxonomy-alias': result=add_taxonomy_alias(root,a.kind,a.name,a.alias,a.category,a.parent_type)
    elif a.cmd=='run': result=start_scan_run(root,a.agent,a.model) if a.action=='start' else finish_scan_run(root,a.id,a.interrupted) if a.action=='finish' and a.id else list_scan_runs(root,a.limit) if a.action=='list' else (_ for _ in ()).throw(ValueError('run finish requires --id'))
    elif a.cmd=='research-cache':
        key=research_key_for_item(root,a.item_id)
        result=cache_item_research(root,a.item_id,json.loads(a.put.read_text(encoding='utf-8')),a.ttl_days) if a.put else {'cache_key':key,'cached':get_cached_research(root,key)}
    elif a.cmd=='retry-research': result=queue_research(root,force=a.force)
    elif a.cmd=='research-failed': result=research_failed(root,a.item_id,a.reason)
    elif a.cmd=='research-only':
        result=research_snapshot(root,a.item_id)
    elif a.cmd=='revalue': result=research_snapshot(root,a.item_id)
    elif a.cmd=='rescan': result=rescan_snapshot(root,a.item_id)
    elif a.cmd=='record-research': result=record_research(root,a.item_id,json.loads(a.result.read_text(encoding='utf-8')))
    elif a.cmd=='doctor':
        result=doctor(root)
    elif a.cmd=='filter': result=query_inventory(root,{k.replace('-','_'):v for k,v in vars(a).items() if k in ('category','type','name','review','pending_research','confidence_min','confidence_max','value_min_cents','value_max_cents','basis','created_after','created_before','has_image') and v is not None},a.limit)
    elif a.cmd in ('query','summary'):
        rows=read_inventory(root); result=rows if a.cmd=='query' else catalog_summary(root)
    else:
        with open_catalog(root) as db:
            if a.cmd=='claim': result=claim(root,db)
            elif a.cmd=='resume': result={'warnings':recover(root,db)}
            elif a.cmd=='check': result=check_catalog(root,db)
            elif a.cmd=='normalize': normalize(root,db,a.id,a.output,a.frame); result={'normalized':str(a.output),'frame':a.frame}
            else: result=commit(root,db,json.loads(a.manifest.read_text(encoding='utf-8')))
    print(js(result))
if __name__=='__main__':
    try: main()
    except Exception as e: print(js({'error':str(e),'type':type(e).__name__}),file=sys.stderr); sys.exit(1)
