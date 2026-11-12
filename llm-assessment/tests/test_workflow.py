"""End-to-end HTTP checks against a disposable copy; never changes the live database."""
import sys
import tempfile
import sqlite3
import threading
import unittest
import urllib.request
import urllib.error
import http.cookiejar
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import storage,server,analysis

class Client:
    def __init__(self,base):
        self.base=base; self.csrf=''
        self.opener=urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
    def call(self,path,body=None,expected=200,csrf=True,origin=None):
        headers={'Content-Type':'application/json'}
        if csrf:headers['X-CSRF-Token']=self.csrf
        if origin:headers['Origin']=origin
        req=urllib.request.Request(self.base+path,data=storage.encode(body).encode() if body is not None else None,headers=headers)
        try:
            with self.opener.open(req,timeout=15) as r:status=r.status;raw=r.read()
        except urllib.error.HTTPError as e:status=e.code;raw=e.read()
        assert status==expected,(path,status,raw)
        return storage.decode(raw)
    def login(self,email):
        self.call('/api/login',{'email':email,'password':'QA-only-password123!'})
        self.csrf=self.call('/api/session')['csrf']

def fake_ai(q,response,fixed,config=None):
    return ([{'id':r['id'],'level':2,'quote':'測試回答','reason':'依可見作答測試','feedback':'補充控制變因','method':'ai','status':'scored'} for r in q['rubric']['criteria'] if r['id'] not in fixed],None)

class Workflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp=tempfile.TemporaryDirectory();cls.original=storage.DB_PATH
        storage.DB_PATH=Path(cls.temp.name)/'test.sqlite3'
        with sqlite3.connect(cls.original) as src,sqlite3.connect(storage.DB_PATH) as dst:src.backup(dst)
        src.close();dst.close()
        # Keep the bank but reset activity only in this disposable test copy.
        assert storage.DB_PATH.parent==Path(cls.temp.name)
        with sqlite3.connect(storage.DB_PATH) as fixture:
            keep={'sources','skills','questions','question_versions','analysis_rules','documents'}
            tables=[r[0] for r in fixture.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
            for table in tables:
                if table not in keep:fixture.execute('DELETE FROM "'+table.replace('"','""')+'"')
            fixture.execute("UPDATE question_versions SET review_status='draft',reviewed_by=NULL,reviewed_at=NULL")
        fixture.close()
        storage.initialize()
        cls.http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
        cls.thread=threading.Thread(target=cls.http.serve_forever,daemon=True);cls.thread.start()
        cls.base=f'http://127.0.0.1:{cls.http.server_port}'
    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown();cls.http.server_close();storage.DB_PATH=cls.original;cls.temp.cleanup()
    def test_full_workflow_and_boundaries(self):
        admin=Client(self.base);learner=Client(self.base);other=Client(self.base)
        self.assertTrue(admin.call('/api/session')['setup_required'])
        admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'測試管理者'})
        admin.call('/api/setup',{'email':'duplicate','password':'QA-only-password123!'},409)
        admin.login('qa-admin')
        admin.call('/api/admin/learners',{'email':'badcsrf','password':'QA-only-password123!','name':'測試'},403,csrf=False)
        admin.call('/api/admin/learners',{'email':'badorigin','password':'QA-only-password123!','name':'測試'},403,origin='https://example.net')
        a=admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'測試組員'})['id']
        admin.call('/api/admin/learners',{'email':'qa-other','password':'QA-only-password123!','name':'另一組員'})
        learner.login('qa-student');other.login('qa-other')
        learner.call('/api/admin/questions',expected=403)
        questions=admin.call('/api/admin/questions')['questions']
        q=next(x for x in questions if x['question_id']=='ZJU-002')
        codeq=next(x for x in questions if x['kind']=='python')
        assignment={'title':'隔離測試評量','items':[{'id':q['id'],'points':12}],'recipients':[a],'auto_publish':True}
        admin.call('/api/admin/assignments',assignment,400)
        admin.call('/api/admin/questions/'+q['id']+'/approve',{})
        admin.call('/api/admin/questions/'+codeq['id']+'/approve',{})
        aid=admin.call('/api/admin/assignments',assignment)['id']
        other.call('/api/tasks/'+aid,expected=404)
        d=learner.call('/api/tasks/'+aid+'/start',{})
        pub=d['items'][0]['question']
        self.assertNotIn('answer',pub);self.assertNotIn('rubric',pub);self.assertNotIn('hidden',pub['tests'])
        sid=d['submission']['id']
        self.assertEqual(admin.call('/api/admin/dashboard')['counts']['submissions'],0)
        learner.call('/api/tasks/'+aid+'/save',{'question_version_id':q['id'],'response':{'interaction':{'order':5}}},400)
        response={'text':'測試回答：條件機率需要用聯合次數除以前綴次數。','interaction':{'order':['C(A,B)','/','C(A)'],'result':'0.25'}}
        if q['answer'].get('objective'):
            objective=q['answer']['objective'];response['interaction']={objective['type']:objective['expected']}
        learner.call('/api/tasks/'+aid+'/save',{'question_version_id':q['id'],'response':response})
        learner.call('/api/tasks/'+aid+'/practice',{'question_version_id':q['id'],'code':''},403)
        jid=learner.call('/api/tasks/'+aid+'/submit',{})['job_id']
        self.assertEqual(admin.call('/api/admin/dashboard')['counts']['submissions'],1)
        learner.call('/api/tasks/'+aid+'/save',{'question_version_id':q['id'],'response':response},409)
        with storage.db() as c:job=dict(c.execute('SELECT * FROM analysis_jobs WHERE id=?',(jid,)).fetchone())
        with patch.object(analysis,'ai_criteria',fake_ai):analysis.process(job)
        report=learner.call('/api/reports')['reports'][0]['report']
        self.assertTrue(report['complete']);self.assertEqual(report['items'][0]['criteria'][0]['method'],'rule')
        self.assertFalse(other.call('/api/reports')['reports'])
        review=admin.call('/api/admin/submissions/'+sid)
        original=review['result']['score']
        levels={q['id']+':'+r['id']:3 for r in review['result']['items'][0]['criteria']}
        admin.call('/api/admin/submissions/'+sid+'/review',{'levels':levels,'note':'人工確認改善方案','publish':True})
        reviewed=admin.call('/api/admin/submissions/'+sid)
        self.assertEqual(reviewed['result']['score'],12);self.assertEqual(reviewed['original_ai_result']['score'],original)
        self.assertEqual(learner.call('/api/reports')['reports'][0]['report']['score'],12)
        with patch.object(analysis,'ai_criteria',fake_ai):analysis.process(job)
        self.assertEqual(learner.call('/api/reports')['reports'][0]['report']['score'],12)
        self.assertTrue(admin.call('/api/admin/overview')['overview'])
        admin.call('/api/admin/settings',{'model':'example:cloud','enabled':True},400)
        admin.call('/api/admin/submissions/'+sid+'/reopen',{})
        admin.call('/api/admin/submissions/'+sid+'/retry',{},409)
        self.assertNotEqual(learner.call('/api/tasks/'+aid)['attempt_id'],d['attempt_id'])
        learner.call('/api/tasks/'+aid+'/save',{'question_version_id':q['id'],'response':response})
        revision_job=learner.call('/api/tasks/'+aid+'/submit',{})['job_id']
        with storage.db() as c:revision=dict(c.execute('SELECT * FROM analysis_jobs WHERE id=?',(revision_job,)).fetchone())
        with patch.object(analysis,'ai_criteria',fake_ai):analysis.process(revision)
        revised=admin.call('/api/admin/submissions/'+sid)
        self.assertEqual(revised['result']['score'],original)
        self.assertEqual(learner.call('/api/reports')['reports'][0]['report']['attempt_id'],revision['attempt_id'])
        # Assignment keeps approved immutable version even when bank creates a draft revision.
        edited=dict(q);edited['prompt']='新的題目文字，原分配不應改變。'
        version=admin.call('/api/admin/questions/'+q['id']+'/version',edited)['id']
        self.assertNotEqual(version,q['id'])
        self.assertEqual(learner.call('/api/tasks/'+aid)['items'][0]['question']['prompt'],q['prompt'])
        admin.call('/api/admin/learners/'+a+'/disable',{'disabled':True})
        learner.call('/api/tasks',expected=401)
        self.assertEqual(admin.call('/api/admin/export')['format'],'llm-assessment-bank-v1')
        with storage.db() as c:self.assertEqual(c.execute('PRAGMA integrity_check').fetchone()[0],'ok')

    def test_ai_rejects_fabricated_evidence(self):
        with storage.db() as c:q=storage.question(c.execute('SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id LIMIT 1').fetchone(),True)
        items=[{'id':r['id'],'level':3,'quote':'不存在的學生作答','reason':'偽造','feedback':'偽造'} for r in q['rubric']['criteria']]
        class Reply:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def read(self):return storage.encode({'message':{'content':storage.encode({'criteria':items})}}).encode()
        with patch.object(analysis.urllib.request,'urlopen',return_value=Reply()):
            result,error=analysis.ai_criteria(q,{'text':'真實作答'}, {})
        self.assertEqual(result,[]);self.assertIn('引文',error)

if __name__=='__main__':unittest.main(verbosity=2)
