import json,threading,unittest,urllib.request,urllib.error
from http.server import ThreadingHTTPServer
import test_workflow
import omni_server,model_slots,storage
from unittest.mock import patch

class OmniBridge(unittest.TestCase):
    def test_loopback_protocol_and_no_browser_or_streaming_access(self):
        class FakeEngine:
            model=None
            def generate(self,body):return {'model':omni_server.MODEL_ID,'choices':[{'message':{'role':'assistant','content':'local test'}}]}
            def unload(self):self.model=None
        server=ThreadingHTTPServer(('127.0.0.1',0),omni_server.Handler);server.engine=FakeEngine()
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start();base=f'http://127.0.0.1:{server.server_port}'
        def call(path,body=None,origin=None):
            headers={'Content-Type':'application/json'}
            if origin:headers['Origin']=origin
            req=urllib.request.Request(base+path,data=json.dumps(body).encode() if body is not None else None,headers=headers)
            try:
                with urllib.request.urlopen(req) as r:return r.status,json.load(r)
            except urllib.error.HTTPError as e:return e.code,json.load(e)
        try:
            self.assertEqual(call('/v1/models')[1]['data'][0]['id'],omni_server.MODEL_ID)
            payload={'model':omni_server.MODEL_ID,'stream':False,'messages':[{'role':'user','content':'test'}]}
            self.assertEqual(call('/v1/chat/completions',payload)[0],200)
            self.assertEqual(call('/v1/chat/completions',payload,'https://example.com')[0],403)
            self.assertEqual(call('/v1/chat/completions',{**payload,'stream':True})[0],400)
            self.assertEqual(call('/v1/chat/completions',{**payload,'model':'gemma4:12b'})[0],400)
            self.assertEqual(call('/v1/unload',{})[0],200)
        finally:server.shutdown();server.server_close();thread.join()

    def test_native_gpu_handoff_only_releases_registered_website_models(self):
        class FakeRow(dict):pass
        class FakeDB:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def execute(self,*args):return [{'config_json':storage.encode({'provider':'ollama','model':'gpt-oss:20b'})}]
        calls=[]
        def request(url,data=None,**kwargs):
            calls.append((url,data));return {'models':[{'name':'gpt-oss:20b'},{'name':'another-app:latest'}]} if url.endswith('/api/ps') else {}
        with patch.object(model_slots,'db',return_value=FakeDB()),patch.object(model_slots,'request',side_effect=request):model_slots.prepare_gpu({'provider':'omni_local'})
        self.assertEqual(len(calls),2);self.assertEqual(calls[1][1],{'model':'gpt-oss:20b','keep_alive':0})

if __name__=='__main__':unittest.main()
