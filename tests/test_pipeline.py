import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import numpy as np
from PIL import Image
from generar_video import prepare_phase,load_portrait,transition,timeline,build_scenes,srt_time,write_wav,RATE
import wave

class PipelineTests(unittest.TestCase):
    def test_pair_and_transition(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'basic').mkdir();(root/'realistic').mkdir()
            Image.new('RGB',(60,90),(220,30,20)).save(root/'basic'/'a.png')
            Image.new('RGB',(60,90),(20,30,220)).save(root/'realistic'/'b.png')
            item={'basic':'a.png','realistic':'b.png','color':[255,150,50]}
            phase=prepare_phase(item,root,(90,160))
            np.testing.assert_array_equal(transition(phase,0),phase['anime'])
            np.testing.assert_array_equal(transition(phase,1),phase['real'])
            self.assertGreater(int(phase['anime'][80,45,0]),int(phase['anime'][80,45,2]))
            self.assertGreater(int(phase['real'][80,45,2]),int(phase['real'][80,45,0]))
            self.assertFalse(np.array_equal(transition(phase,.5),phase['anime']))

    def test_small_source_scales_to_portrait(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'small.png'
            Image.new('RGB',(20,40),(230,30,20)).save(p)
            frame=load_portrait(p,(360,640),True,[255,150,50])
            # Un original pequeño debe ocupar la zona del personaje al exportar.
            self.assertGreater(int(frame[200,180,0]),200)
            self.assertGreater(int(frame[440,180,0]),200)

    def test_timeline_no_cumulative_drift_or_truncation(self):
        scenes=[{'text':f'escena {i}'} for i in range(100)]
        voices=[np.full(31003+i,.3,dtype=np.float32) for i in range(100)]
        audio,srt,duration=timeline(scenes,voices,24)
        self.assertEqual(len(audio),round(duration*RATE))
        for s,v in zip(scenes,voices):
            offset=round(s['start']*RATE)+round(.12*RATE)
            np.testing.assert_array_equal(audio[offset:offset+len(v)],v)
            self.assertLess(s['speech_end'],s['duration'])
        self.assertIn('00:00:00,120 -->',srt)

    def test_anime_real_sequence(self):
        cfg={'introduccion':'inicio','cierre':'fin','fases':[{'titulo':str(i),'narracion_anime':'a','narracion_real':'r'} for i in range(6)]}
        scenes=build_scenes(cfg)
        self.assertEqual([s['mode'] for s in scenes[1:-1]],['anime','real']*6)
        self.assertEqual([s['phase'] for s in scenes[1:-1]],[i for i in range(6) for _ in range(2)])

    def test_pool_collects_in_input_order(self):
        finished=[]
        def job(i):
            time.sleep(.08 if i==0 else .002)
            finished.append(i)
            return i
        with ThreadPoolExecutor(max_workers=3) as pool:
            result=list(pool.map(job,[0,1,2]))
        self.assertEqual(result,[0,1,2])
        self.assertNotEqual(finished,result)

    def test_srt_carry(self):
        self.assertEqual(srt_time(59.9996),'00:01:00,000')
        self.assertEqual(srt_time(3661.25),'01:01:01,250')

    def test_audio_length_and_clipping(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'test.wav';write_wav(p,np.full(RATE,2.0))
            with wave.open(str(p)) as f:
                self.assertEqual(f.getnframes(),RATE)
                self.assertEqual(np.frombuffer(f.readframes(RATE),dtype='<i2').min(),32767)

if __name__=='__main__':unittest.main()
