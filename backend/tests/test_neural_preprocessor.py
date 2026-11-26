from pathlib import Path
import tempfile
import unittest
import cv2
import numpy as np
from app.services.neural_avatar.preprocessor import prepare_image,paste_frame

class NeuralPreprocessorTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
        self.path=self.root/'source.png';yy,xx=np.mgrid[:180,:220]
        cv2.imwrite(str(self.path),np.stack([xx%180+30,yy%150+30,(xx+yy)%150+40],axis=-1).astype(np.uint8))
        self.meta={'face_box':{'x':40,'y':20,'width':130,'height':140},'landmarks':{'left_eye':{'x':80,'y':65},'right_eye':{'x':135,'y':70}}}
    def tearDown(self):self.temp.cleanup()
    def test_cache_and_original(self):
        original=self.path.read_bytes()
        first,key,hit=prepare_image(self.path,self.meta,self.root/'neural');self.assertFalse(hit)
        second,key2,hit=prepare_image(self.path,self.meta,self.root/'neural');self.assertTrue(hit)
        self.assertEqual(key,key2);np.testing.assert_array_equal(first['crop'],second['crop'])
        self.meta['landmarks']['left_eye']['y']+=2
        _,key3,hit=prepare_image(self.path,self.meta,self.root/'neural');self.assertFalse(hit);self.assertNotEqual(key,key3)
        self.assertEqual(original,self.path.read_bytes())
    def test_background_is_bit_identical(self):
        state,_,_=prepare_image(self.path,self.meta,self.root/'neural');output=paste_frame(state['crop'],state)
        exterior=state['mask']==0;np.testing.assert_array_equal(output[exterior],state['image'][exterior])
    def test_reject_corrupted_output(self):
        state,_,_=prepare_image(self.path,self.meta,self.root/'neural')
        for bad in [np.zeros((256,256,3),np.uint8),np.full((256,256,3),np.nan)]:
            with self.assertRaises(ValueError):paste_frame(bad,state)
