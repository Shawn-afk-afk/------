import base64
import json
import struct
import unittest
import zlib
from unittest.mock import patch
import test_workflow as workflow
from test_workflow import Client,fake_ai
import storage,collab,analysis

def white_png():
    def chunk(name,data):return struct.pack('>I',len(data))+name+data+struct.pack('>I',zlib.crc32(name+data)&0xffffffff)
    data=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',1200,800,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\x00'+b'\xff'*3600)*800))+chunk(b'IEND',b'')
    return 'data:image/png;base64,'+base64.b64encode(data).decode()

class CanvasWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):workflow.Workflow.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):workflow.Workflow.tearDownClass.__func__(cls)
    def test_canvas_stages_provenance_permissions_and_manual_release(self):
        admin=Client(self.base);student=Client(self.base);other=Client(self.base)
        admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'測試管理者'});admin.login('qa-admin')
        learner=admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'測試組員'})['id']
        admin.call('/api/admin/learners',{'email':'qa-other','password':'QA-only-password123!','name':'其他測試組員'})
        student.login('qa-student');other.login('qa-other')
        q=next(q for q in admin.call('/api/admin/questions')['questions'] if q['question_id']=='LAB-AI-001')
        admin.call('/api/admin/questions/'+q['id']+'/approve',{})
        aid=admin.call('/api/admin/assignments',{'title':'白板測試','items':[{'id':q['id'],'points':12}],'recipients':[learner],'auto_publish':True,'publish_code_ai':True})['id']
        task=student.call('/api/tasks/'+aid+'/start',{});self.assertNotIn('independent_prompt',task['items'][0]['question']['payload'])
        scene={'width':1200,'height':800,'elements':[{'type':'text','color':'#111111','size':24,'points':[[100,200]],'text':'label uses modified input'}]}
        body={'question_version_id':q['id'],'scene':scene,'image':white_png(),'initial_text':'初稿：label 應取原始 token。'}
        student.call('/api/tasks/'+aid+'/canvas-save',{**body,'image':'data:image/svg+xml;base64,AAAA'},400)
        snap=student.call('/api/tasks/'+aid+'/canvas-save',body)['snapshot_id']
        other.call('/api/canvas/image?id='+snap,expected=403)
        with student.opener.open(self.base+'/api/canvas/image?id='+snap) as image:self.assertTrue(image.read().startswith(b'\x89PNG'))
        state=student.call('/api/tasks/'+aid+'/canvas-state?question_version_id='+q['id']);self.assertIsNone(state['independent_prompt'])
        jid=student.call('/api/tasks/'+aid+'/canvas-turn',{'question_version_id':q['id'],'snapshot_id':snap,'message':'請問標籤資料流是否合理？'})['job_id']
        student.call('/api/tasks/'+aid+'/canvas-turn',{'question_version_id':q['id'],'snapshot_id':snap},409)
        student.call('/api/tasks/'+aid+'/canvas-finish',{'question_version_id':q['id']},409)
        captured={}
        reply={'observation':'白板標註 label uses modified input','question':'你如何確認 label 的資料來源？','uncertain':[],'boxes':[{'x':.1,'y':.1,'w':.2,'h':.1,'label':'資料來源'}]}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'model':'vision-test','message':{'content':json.dumps(reply)}}).encode()
        def fake(req,**kwargs):captured.update(json.loads(req.data));return Response()
        with storage.db() as c:job=dict(c.execute('SELECT * FROM canvas_turns WHERE id=?',(jid,)).fetchone())
        with patch.object(collab.urllib.request,'urlopen',side_effect=fake):collab.process(job)
        material=json.loads(captured['messages'][1]['content']);self.assertNotIn('independent_prompt',material['material']);self.assertNotIn('reference_answer',material)
        student.call('/api/tasks/'+aid+'/canvas-save',{**body,'initial_text':'偽造：AI 完成後才改寫的初稿'})
        initial=student.call('/api/tasks/'+aid+'/canvas-state?question_version_id='+q['id'])['initial_text'];self.assertEqual(initial,body['initial_text'])
        stage=student.call('/api/tasks/'+aid+'/canvas-finish',{'question_version_id':q['id']});self.assertEqual(stage['phase'],'independent');self.assertTrue(stage['independent_prompt'])
        student.call('/api/tasks/'+aid+'/canvas-turn',{'question_version_id':q['id'],'snapshot_id':snap},409)
        student.call('/api/tasks/'+aid+'/canvas-save',body,409)
        response={'text':'測試回答：我核對資料來源並修正 label。','canvas':{'snapshot_id':snap,'initial_text':'想覆寫初稿','confirmed_observation':'圖上的 label 指向修改過的資料','independent_text':'targets 需要位移，並忽略 padding loss。'}}
        student.call('/api/tasks/'+aid+'/save',{'question_version_id':q['id'],'response':response})
        self.assertEqual(student.call('/api/tasks/'+aid)['responses'][q['id']]['canvas']['initial_text'],body['initial_text'])
        analysis_job=student.call('/api/tasks/'+aid+'/submit',{})['job_id']
        with storage.db() as c:job=dict(c.execute('SELECT * FROM analysis_jobs WHERE id=?',(analysis_job,)).fetchone())
        with patch.object(analysis,'ai_criteria',fake_ai):analysis.process(job)
        self.assertFalse(student.call('/api/reports')['reports'])
        details=admin.call('/api/admin/submissions/'+task['submission']['id']);self.assertTrue(details['result']['needs_review'])
        history=admin.call('/api/admin/submissions/'+task['submission']['id']+'/canvas');self.assertEqual(len(history['turns']),1);self.assertGreaterEqual(len(history['snapshots']),2)
        other.call('/api/admin/submissions/'+task['submission']['id']+'/canvas',expected=403)
        admin.call('/api/admin/submissions/'+task['submission']['id']+'/reopen',{})
        restarted=student.call('/api/tasks/'+aid+'/canvas-state?question_version_id='+q['id']);self.assertEqual(restarted['phase'],'collaborative');self.assertNotEqual(restarted['snapshot_id'],snap)
        self.assertEqual(student.call('/api/tasks/'+aid)['responses'][q['id']]['canvas']['independent_text'],'')

class FeedbackValidation(unittest.TestCase):
    def test_grading_rejects_evidence_from_another_phase(self):
        q={'kind':'ai_collab_canvas','prompt':'test','answer':{'expected_elements':[]},'rubric':{'criteria':[{'id':'revision'}]}}
        response={'text':'我核對後修改了箭頭','canvas':{'initial_text':'這只是初稿'}}
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return json.dumps({'message':{'content':json.dumps({'criteria':[{'id':'revision','level':3,'quote':'這只是初稿','reason':'test','feedback':'test'}]})}}).encode()
        with patch.object(analysis.urllib.request,'urlopen',return_value=Response()):
            result,error=analysis.ai_criteria(q,response,{}, {'enabled':True,'model':'test'})
        self.assertEqual(result,[]);self.assertIn('錯誤的作答階段',error)

    def test_untrusted_coordinates_and_scene_are_rejected(self):
        with self.assertRaises(collab.CollabError):collab.validate_feedback({'observation':'text','question':'question','boxes':[{'x':0,'y':0,'w':2,'h':.1}]})
        with self.assertRaises(collab.CollabError):collab.validate_scene({'width':1200,'height':800,'elements':[{'type':'script','color':'#111111','size':3,'points':[[1,1]]}]})
        with self.assertRaises(collab.CollabError):collab.validate_scene({'width':1200,'height':800,'elements':[{'type':'pen','color':'#111111','size':3,'points':[[float('nan'),1]]}]})
