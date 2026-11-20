import sys, tempfile, unittest
from pathlib import Path
from unittest.mock import patch
import numpy as np
from PIL import Image
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault

class DecoderTests(unittest.TestCase):
 def test_heif_roundtrip(self):
  import pillow_heif
  with tempfile.TemporaryDirectory() as td:
   p=Path(td)/'sample.heic'
   pillow_heif.from_pillow(Image.new('RGB',(13,9),(25,120,210))).save(p)
   with vault.open_image(p) as im:
    self.assertEqual(im.size,(13,9)); self.assertEqual(im.convert('RGB').getpixel((4,4)),(25,120,210))
 def test_rawpy_adapter_returns_loaded_pillow_image(self):
  class Raw:
   def __enter__(self): return self
   def __exit__(self,*args): pass
   def postprocess(self): return np.full((7,11,3),70,dtype=np.uint8)
  fake=type('Rawpy',(),{'imread':staticmethod(lambda _:Raw())})
  with patch.dict(sys.modules,{'rawpy':fake}):
   with vault.open_image(Path('sample.cr2')) as im:
    self.assertEqual(im.size,(11,7)); self.assertEqual(im.getpixel((0,0)),(70,70,70))
 def test_claim_accepts_rawpy_extensions(self):
  with tempfile.TemporaryDirectory() as td:
   root=Path(td); (root/'Staging').mkdir(); (root/'Staging'/'sample.CR2').write_bytes(b'raw sample')
   with patch.object(vault,'open_image',return_value=Image.new('RGB',(20,15))) as decoder:
    with vault.open_catalog(root) as db:
     result=vault.claim(root,db)
     self.assertEqual(result['job']['state'],'claimed'); self.assertEqual((result['job']['width'],result['job']['height']),(20,15)); decoder.assert_called_once()

if __name__=='__main__': unittest.main()
