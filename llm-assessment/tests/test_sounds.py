import hashlib
import json
import unittest
import wave
from urllib.parse import quote
from pathlib import Path
import test_workflow as workflow
from test_workflow import Client

class SystemSounds(unittest.TestCase):
    @classmethod
    def setUpClass(cls):workflow.Workflow.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):workflow.Workflow.tearDownClass.__func__(cls)

    def test_preferences_isolation_validation_and_playable_assets(self):
        guest=Client(self.base);admin=Client(self.base);student=Client(self.base)
        guest.call('/api/sound-preferences',expected=401)
        admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'Sound QA'});admin.login('qa-admin')
        admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'Sound QA student'});student.login('qa-student')
        admin.call('/api/sound-preferences',{'enabled':False,'volume':12})
        student.call('/api/sound-preferences',{'enabled':True,'volume':60})
        self.assertEqual(admin.call('/api/sound-preferences'),{'enabled':False,'volume':12})
        for volume in (-1,101,True,'35'):
            admin.call('/api/sound-preferences',{'enabled':True,'volume':volume},400)
        admin.call('/api/sound-preferences',{'enabled':'true','volume':35},400)
        admin.call('/api/sound-preferences',{'enabled':True,'volume':35},403,csrf=False)
        admin.login('qa-admin');self.assertEqual(admin.call('/api/session')['user']['ui_volume'],12)
        root=Path(__file__).resolve().parents[1]/'static/vendor/win98-sounds'
        if not (root/'ding.wav').is_file():self.skipTest('原版系統音效需由使用者依授權自行準備；帳戶偏好已驗證')
        manifest=json.loads((root/'manifest.json').read_text('utf-8'))
        with guest.opener.open(self.base+'/vendor/win98-sounds/manifest.json') as response:self.assertEqual(json.load(response),manifest)
        originals={'chord.wav':97016,'ding.wav':80856,'notify.wav':119384,'start.wav':1192,'tada.wav':171100,'The Microsoft Sound.wav':693212}
        for item in manifest:
            data=(root/item['file']).read_bytes()
            self.assertEqual(hashlib.sha256(data).hexdigest(),item['sha256'])
            if item['file'] in originals:self.assertEqual(len(data),originals[item['file']])
            if item['file']=='start.wav':continue  # Archived ADPCM original; playback uses decoded PCM.
            with wave.open(str(root/item['file']),'rb') as audio:
                self.assertEqual(audio.getcomptype(),'NONE');self.assertGreater(audio.getnframes(),0)
            with guest.opener.open(self.base+'/vendor/win98-sounds/'+quote(item['file'])) as response:
                self.assertEqual(response.read(),data);self.assertIn('audio/',response.headers['Content-Type'])

if __name__=='__main__':unittest.main()
