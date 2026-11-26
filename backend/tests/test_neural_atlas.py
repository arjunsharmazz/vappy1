import json
from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from app.services.neural_avatar.atlas import generate_atlas, POSES


class AtlasTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(); self.path=Path(self.temp.name)/'poses.png'
        yy,xx=np.mgrid[:160,:140]
        source=np.stack([xx+70,yy+30,xx//2+80],axis=-1).astype(np.uint8)
        self.state={'image':source,'mouth_mask':np.ones((160,140),np.float32),'mask':np.ones((160,140),np.float32)}
        self.meta={'face_box':{'x':20,'y':15,'width':100,'height':120},'landmarks':{
            'mouth':{'x':70,'y':110,'width':40,'height':14},
            'left_eye':{'x':48,'y':55,'width':20,'height':9},
            'right_eye':{'x':93,'y':55,'width':20,'height':9}}}
        class Engine:
            def render(inner,prepared,control):
                return np.minimum(prepared['image'].astype(np.int16)+15,255).astype(np.uint8)
        self.engine=Engine()
    def tearDown(self): self.temp.cleanup()
    def test_local_masks_dimensions_and_manifest(self):
        events=[]
        result=generate_atlas(self.engine,self.state,self.meta,self.path,lambda:None,lambda i,n:events.append((i,n)))
        self.assertEqual(events[-1],(len(POSES),len(POSES)))
        self.assertEqual(len(result['entries']),len(POSES)+1)
        self.assertEqual(json.loads(self.path.with_suffix('.json').read_text())['rect'],result['rect'])
        atlas=cv2.imread(str(self.path),cv2.IMREAD_UNCHANGED)
        self.assertEqual(atlas.shape,(((len(POSES)+4)//4)*512,2048,4))
        def alpha(kind,x,y):
            index=next(e['index'] for e in result['entries'] if e['kind']==kind)
            r=result['rect']; u=int((x-r['x'])/r['width']*512);v=int((y-r['y'])/r['height']*512)
            return atlas[(index//4)*512+v,(index%4)*512+u,3]
        self.assertEqual(alpha('mouth',70,55),0)
        self.assertGreater(alpha('mouth',70,110),200)
        self.assertEqual(alpha('blink',70,110),0)
        self.assertGreater(alpha('blink',48,55),200)
        # Eyebrow poses change the brow band only: never the mouth or the iris centre.
        self.assertGreater(alpha('brow',48,42),200)
        self.assertEqual(alpha('brow',70,110),0)
        self.assertEqual(alpha('brow',48,55),0)
        self.assertGreater(alpha('frown',70,42),100)
        self.assertGreater(alpha('laugh',70,110),200)
        self.assertFalse(self.path.with_suffix('.pending.png').exists())
    def test_cancellation_does_not_publish_partial_atlas(self):
        checks=[0]
        def check():
            checks[0]+=1
            if checks[0]>3: raise InterruptedError('cancel')
        with self.assertRaises(InterruptedError):
            generate_atlas(self.engine,self.state,self.meta,self.path,check,lambda *_:None)
        self.assertFalse(self.path.exists())
        self.assertFalse(self.path.with_suffix('.json').exists())

    def test_existing_poses_reused_without_inference(self):
        generate_atlas(self.engine,self.state,self.meta,self.path,lambda:None,lambda *_:None)
        class NoInference:
            def render(self,*_): raise AssertionError('Cached pose unexpectedly regenerated')
        other=self.path.with_name('upgraded.png')
        result=generate_atlas(NoInference(),self.state,self.meta,other,lambda:None,lambda *_:None,self.path)
        self.assertEqual(result['reused_poses'],len(POSES))
        np.testing.assert_array_equal(cv2.imread(str(self.path),-1),cv2.imread(str(other),-1))
