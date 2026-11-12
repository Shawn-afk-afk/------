import base64,hashlib,io,json,struct,unittest
from unittest.mock import patch
import test_workflow as workflow
from test_workflow import Client
import storage,model_library as library,model_slots

class ModelLibrary(unittest.TestCase):
    @classmethod
    def setUpClass(cls):workflow.Workflow.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):workflow.Workflow.tearDownClass.__func__(cls)

    def test_local_only_auth_upload_integrity_download_and_import(self):
        admin=Client(self.base);student=Client(self.base);guest=Client(self.base)
        guest.call('/api/admin/models',expected=401)
        admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'Model QA'});admin.login('qa-admin')
        admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'Model QA learner'});student.login('qa-student')
        student.call('/api/admin/models',expected=403)
        student.call('/api/admin/models/upload/start',{'filename':'test.gguf','size':24},403)
        admin.call('/api/admin/models/download',{'source':'ollama','runtime':'ollama','endpoint':'https://example.com','model':'tiny:1b'},400)
        admin.call('/api/admin/models/download',{'source':'ollama','runtime':'ollama','endpoint':'http://127.0.0.1:11434','model':'model:cloud'},400)
        admin.call('/api/admin/models/download',{'source':'ollama','runtime':'huggingface_cloud','endpoint':'http://127.0.0.1:11434','model':'model'},400)
        admin.call('/api/admin/models/upload/start',{'filename':'../evil.gguf','size':24},400)
        admin.call('/api/admin/models/upload/start',{'filename':'model.pkl','size':24},400)
        admin.call('/api/admin/models/upload/start',{'filename':'test.gguf','size':24},403,csrf=False)
        data=b'GGUF'+struct.pack('<IQQ',3,0,0)
        iid=admin.call('/api/admin/models/upload/start',{'filename':'test.gguf','size':len(data)})['id']
        encoded=base64.b64encode(data).decode();chunk={'id':iid,'offset':0,'data':encoded}
        admin.call('/api/admin/models/upload/chunk',{**chunk,'offset':1},400)
        self.assertEqual(admin.call('/api/admin/models/upload/chunk',chunk)['received'],len(data))
        self.assertEqual(admin.call('/api/admin/models/upload/chunk',chunk)['received'],len(data))
        admin.call('/api/admin/models/upload/chunk',{**chunk,'data':base64.b64encode(data+b'x').decode()},400)
        done=admin.call('/api/admin/models/upload/finish',{'id':iid});self.assertEqual(done['sha256'],hashlib.sha256(data).hexdigest())
        self.assertEqual(b''.join(library.upload_chunks(iid)),data)
        admin.call('/api/admin/models/import',{'upload_id':iid,'endpoint':'http://127.0.0.1:11434','model':'test','source_kind':'lora'},400)
        with patch.object(model_slots,'available',return_value=[]):
            jid=admin.call('/api/admin/models/import',{'upload_id':iid,'endpoint':'http://127.0.0.1:11434','model':'test-upload:qa'})['id']
        with storage.db() as c:job=dict(c.execute('SELECT * FROM model_acquisitions WHERE id=?',(jid,)).fetchone())
        calls=[]
        class Opener:
            def open(self,req,timeout):
                calls.append(req.full_url)
                if '/api/blobs/' in req.full_url:
                    self_data=b''.join(req.data);assert self_data==data
                    return io.BytesIO(b'')
                self_payload=json.loads(req.data);assert self_payload['files']=={'test.gguf':'sha256:'+done['sha256']}
                return io.BytesIO(b'{"status":"success"}\n')
        with patch.object(library.urllib.request,'build_opener',return_value=Opener()),patch.object(model_slots,'request',return_value={'capabilities':['completion']}):library.process(job)
        self.assertTrue(all(url.startswith('http://127.0.0.1:11434/') for url in calls))
        saved=admin.call('/api/admin/models');completed=next(j for j in saved['jobs'] if j['id']==jid)
        self.assertEqual(completed['status'],'completed');self.assertTrue(completed['result']['profile_id'])
        request={'source':'huggingface','runtime':'ollama','endpoint':'http://127.0.0.1:11434','repo':'example/public-model','filename':'model.Q4.gguf'}
        with patch.object(library,'hf_request',return_value={'private':False,'gated':False,'sha':'abc','cardData':{'license':'apache-2.0'},'siblings':[{'rfilename':'model.Q4.gguf','size':123}]}):
            hfjob=admin.call('/api/admin/models/download',request)['id']
        with storage.db() as c:hfrow=dict(c.execute('SELECT * FROM model_acquisitions WHERE id=?',(hfjob,)).fetchone())
        self.assertEqual(storage.decode(hfrow['request_json'])['model'],'hf.co/example/public-model:model.Q4.gguf')
        with patch.object(library,'hf_request',return_value={'private':False,'gated':'auto'}):admin.call('/api/admin/models/download',request,400)
        # Failed runtime requests never create an activated model or a fake success.
        with patch.object(library,'stream_ollama',side_effect=RuntimeError('incompatible architecture')):library.process(hfrow)
        self.assertEqual(next(j for j in admin.call('/api/admin/models')['jobs'] if j['id']==hfjob)['status'],'failed')

    def test_lmstudio_native_download_contract(self):
        # No model download is performed; enforce official local job endpoints.
        with storage.db() as c:
            jid=library.queue_job(c,{'id':'lms-test'},{'kind':'download','runtime':'lmstudio','endpoint':'http://127.0.0.1:1234','model':'https://huggingface.co/example/repo/blob/main/model.gguf'})['id']
        with storage.db() as c:job=dict(c.execute('SELECT * FROM model_acquisitions WHERE id=?',(jid,)).fetchone())
        calls=[]
        def request(url,data=None,**kwargs):
            calls.append((url,data));return {'status':'downloading','job_id':'local-job'} if data else {'status':'completed'}
        with patch.object(model_slots,'request',side_effect=request),patch.object(library.STOP,'wait',return_value=False):library.process(job)
        self.assertEqual(calls[0][0],'http://127.0.0.1:1234/api/v1/models/download')
        self.assertEqual(calls[1][0],'http://127.0.0.1:1234/api/v1/models/download/status/local-job')

if __name__=='__main__':unittest.main()
