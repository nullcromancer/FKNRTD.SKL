import sys,tempfile,unittest
from pathlib import Path
from PIL import Image,ImageDraw
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts'))
import vault

class ProposalTests(unittest.TestCase):
 def test_nine_card_geometry(self):
  p=Path(tempfile.mktemp(suffix='.png')); im=Image.new('RGB',(900,1200),'#333'); d=ImageDraw.Draw(im)
  for y in range(3):
   for x in range(3): d.rectangle((x*290+20,y*390+20,x*290+260,y*390+360),fill='white',outline='black',width=5)
  im.save(p); result=vault.propose_card_regions(p); self.assertTrue(result['available']); self.assertEqual(len(result['regions']),9)
 def test_partial_and_irregular(self):
  p=Path(tempfile.mktemp(suffix='.png')); im=Image.new('RGB',(700,900),'#555'); d=ImageDraw.Draw(im)
  d.rectangle((40,50,260,360),fill='white',outline='black',width=6); d.rectangle((300,100,520,410),fill='white',outline='black',width=6)
  d.polygon([(140,480),(370,450),(410,780),(170,800)],fill='white',outline='black')
  im.save(p); regions=vault.propose_card_regions(p)['regions']; self.assertGreaterEqual(len(regions),2)

if __name__=='__main__': unittest.main()
