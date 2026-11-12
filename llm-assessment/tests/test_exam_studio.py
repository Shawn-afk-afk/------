import copy,io,json,sys,unittest,zipfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import test_workflow as workflow
from test_workflow import Client
import storage,exam_studio,model_slots,dense_rag

class StudioWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow.Workflow.setUpClass.__func__(cls)
        cls.emb=patch.object(dense_rag,'embed',side_effect=lambda texts,query=False:[[1.0,0.0] for text in texts]);cls.emb.start()
        cls.ident=patch.object(dense_rag,'identity',return_value='qa-embedding-v1');cls.ident.start()
    @classmethod
    def tearDownClass(cls):
        cls.emb.stop();cls.ident.stop();workflow.Workflow.tearDownClass.__func__(cls)
    def test_authenticated_generate_edit_export_and_bank_drafts(self):
        admin=Client(self.base);student=Client(self.base)
        admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'測試管理者'});admin.login('qa-admin')
        admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'測試學生'});student.login('qa-student')
        student.call('/api/admin/exam/materials',expected=403)
        student.call('/api/admin/model-slots',expected=403)
        with storage.db() as c:
            source=c.execute("SELECT id FROM sources WHERE id LIKE 'ch2-%'").fetchone()[0]
            text='模型的訓練輸入使用遮罩處理，預測目標應保存原始詞元，而非覆寫後的遮罩符號。'
            exam_studio.store_material(c,'MLM test',text,'LLM',source_id=source,locator='第二章 2.3；隔離測試材料',mid='book-2.3')
        request={'metadata':{'title':'測試考卷','subject':'LLM'},'unit_ids':['book-2.3'],'sections_config':[{'section_title':'概念','section_type':'CHOICE','question_count':1,'score_per_question':6}]}
        jid=admin.call('/api/admin/exam/generate',request)['id']
        with storage.db() as c:job=dict(c.execute('SELECT * FROM exam_jobs WHERE id=?',(jid,)).fetchone())
        snapshot=storage.decode(job['request_json']);self.assertEqual(snapshot['profile']['model'],'gemma4:12b-it-q4_K_M')
        generated={'questions':[{'stem':'Which target preserves the original token?','options':{'A':'Original token','B':'Mask symbol','C':'Padding','D':'Random token'},'answer':'A','explanation':'標籤應保持原始詞元，否則學到遮罩符號而無法復原內容。','source_unit_id':'book-2.3','source_excerpt':text}]}
        with patch.object(exam_studio,'llm_json',return_value=generated):exam_studio.process(job)
        details=admin.call('/api/admin/exam/jobs/'+jid);self.assertEqual(details['result']['metadata']['total_score'],6)
        wrong=copy.deepcopy(details['result']);wrong['sections'][0]['questions'][0]['source_excerpt']='這段文字不在第一／二章原始來源內'
        admin.call('/api/admin/exam/jobs/'+jid+'/save',{'exam':wrong},400)
        admin.call('/api/admin/exam/jobs/'+jid+'/save',{'exam':details['result']})
        exports=admin.call('/api/admin/exam/jobs/'+jid+'/export',{})['files'];self.assertEqual(len(exports),3)
        for f in exports:
            with admin.opener.open(self.base+'/api/admin/exam/download?id='+f['id']) as r:data=r.read()
            with zipfile.ZipFile(io.BytesIO(data)) as doc:self.assertIn('word/document.xml',doc.namelist())
            student.call('/api/admin/exam/download?id='+f['id'],expected=403)
        ids=admin.call('/api/admin/exam/jobs/'+jid+'/import-bank',{})['ids'];self.assertEqual(len(ids),1)
        q=next(q for q in admin.call('/api/admin/questions')['questions'] if q['id']==ids[0])
        self.assertEqual(q['review_status'],'draft');self.assertEqual(q['payload']['options'][0]['label'],'Original token')
        self.assertEqual(q['answer']['objective']['expected'],'A')
        admin.call('/api/admin/exam/jobs/'+jid+'/import-bank',{},400)
        # Reuse upstream chart generation and verify its PNG survives in DOCX.
        material=admin.call('/api/admin/exam/materials',{'title':'English lesson','subject':'English','text':'Unit 1\nThe happy child walks to school. The sad child stays at home.\nWe learn happy, sad, good and bad.'})['id']
        english={'metadata':{'title':'English chart','subject':'English'},'unit_ids':[material],'sections_config':[{'section_title':'Choices','section_type':'CHOICE','question_count':1,'score_per_question':2}]}
        ej=admin.call('/api/admin/exam/generate',english)['id']
        def getjob(j):
            with storage.db() as c:return dict(c.execute('SELECT * FROM exam_jobs WHERE id=?',(j,)).fetchone())
        eq={'stem':'Which word describes the child?','options':dict(zip('ABCD',['happy','sad','good','bad'])),'answer':'A','explanation':'依據題幹情境判斷語意，選擇 happy。'}
        with patch.object(exam_studio,'llm_json',return_value={'questions':[eq]}):exam_studio.process(getjob(ej))
        imagejob=admin.call('/api/admin/exam/jobs/'+ej+'/image',{'section_index':0,'question_index':0})['id']
        with patch.object(exam_studio,'llm_json',return_value=copy.deepcopy(eq)):exam_studio.process(getjob(imagejob))
        image_result=admin.call('/api/admin/exam/jobs/'+imagejob)['result'];self.assertTrue(image_result['sections'][0]['questions'][0]['image_data'])
        image_exports=admin.call('/api/admin/exam/jobs/'+imagejob+'/export',{})['files']
        with admin.opener.open(self.base+'/api/admin/exam/download?id='+image_exports[0]['id']) as r:
            with zipfile.ZipFile(io.BytesIO(r.read())) as doc:self.assertTrue(any(n.startswith('word/media/') for n in doc.namelist()))
        textjob=admin.call('/api/admin/exam/jobs/'+imagejob+'/text',{'section_index':0,'question_index':0})['id']
        with patch.object(exam_studio,'llm_json',return_value=copy.deepcopy(eq)):exam_studio.process(getjob(textjob))
        self.assertNotIn('image_data',admin.call('/api/admin/exam/jobs/'+textjob)['result']['sections'][0]['questions'][0])
        # Source registration can precede the future LoRA upload; it cannot activate an absent model.
        profile=admin.call('/api/admin/model-slots',{'name':'我的 LoRA','provider':'ollama','endpoint':'http://127.0.0.1:11434','model':'gemma4-my-lora:v1','source_kind':'lora','vision':True})['id']
        with patch.object(model_slots,'available',return_value=[]):admin.call('/api/admin/model-slots/activate',{'role':'generation','profile_id':profile},400)
        self.assertEqual(model_slots.selected('generation')['profile_id'],'gemma-12b')
        with patch.object(model_slots,'available',return_value=['gemma4-my-lora:v1']),patch.object(model_slots,'request',return_value={'capabilities':['vision']}):
            admin.call('/api/admin/model-slots/activate',{'role':'generation','profile_id':profile})
        self.assertEqual(model_slots.selected('generation')['model'],'gemma4-my-lora:v1')
        self.assertEqual(snapshot['profile']['model'],'gemma4:12b-it-q4_K_M')

class StudioValidation(unittest.TestCase):
    def test_source_segment_reference_is_bound_to_frozen_material(self):
        text='遮罩語言模型的預測目標需要保留原始詞元內容。'
        request={'metadata':{'title':'test','subject':'LLM'},'profile':{},'sections_config':[{'section_title':'test','section_type':'CHOICE','question_count':1,'score_per_question':6}],'materials':[{'id':'book-2.3','text':text,'locator':'第二章','source_id':'ch2-test'}],'source_segments':[{'source_ref':'S0','source_unit_id':'book-2.3','text':text}]}
        exam={'sections':[{'questions':[{'stem':'Which label is correct?','options':dict(zip('ABCD',['Original','Masked','Padding','Random'])),'answer':'A','explanation':'應使用未被遮罩的原始 token 作為監督目標。','source_unit_id':'book-2.3','source_ref':'S0'}]}]}
        result=exam_studio.validate_exam(copy.deepcopy(exam),request);self.assertEqual(result['sections'][0]['questions'][0]['source_excerpt'],text)
        exam['sections'][0]['questions'][0]['source_ref']='S99'
        with self.assertRaises(exam_studio.ExamError):exam_studio.validate_exam(exam,request)

    def test_local_endpoints_and_cloud_models(self):
        for url in ['http://example.com','http://127.0.0.1@evil.com','http://127.0.0.1:80/secret','http://localhost/?token=x']:
            with self.assertRaises(model_slots.SlotError):model_slots.endpoint(url)
        self.assertEqual(model_slots.endpoint('http://127.0.0.1:8080/v1'),'http://127.0.0.1:8080/v1')
    def test_openai_local_images_and_response_mapping(self):
        captured={}
        def fake(url,data=None,timeout=5):captured.update(url=url,data=data);return {'model':'my-lora','choices':[{'message':{'content':'{"ok":true}'}}]}
        with patch.object(model_slots,'request',side_effect=fake):
            result=model_slots.chat({'model':'my-lora','messages':[{'role':'user','content':'看圖','images':['AA==']}],'options':{'num_predict':100}}, {'provider':'openai_local','endpoint':'http://127.0.0.1:8080/v1'})
        self.assertEqual(captured['url'],'http://127.0.0.1:8080/v1/chat/completions');self.assertEqual(captured['data']['messages'][0]['content'][1]['image_url']['url'],'data:image/png;base64,AA==');self.assertEqual(result['message']['content'],'{"ok":true}')
    def test_invalid_counts_and_upload_paths(self):
        with self.assertRaises(exam_studio.ExamError):exam_studio.validated_sections([{'section_type':'CHOICE','question_count':100,'score_per_question':2}])
        with self.assertRaises(exam_studio.ExamError):exam_studio.upload_data({'filename':'malware.exe','data':'AAAA'})
        with self.assertRaises(exam_studio.ExamError):exam_studio.extract('.txt',b'\x81')

if __name__=='__main__':unittest.main()
