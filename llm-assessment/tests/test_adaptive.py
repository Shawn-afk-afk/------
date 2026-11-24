"""Regression checks for correction replay, binary scoring and evidence isolation."""
import copy
import sqlite3
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'backend'))
import adaptive
import analysis
import server
from storage import encode

class AdaptiveTests(unittest.TestCase):
    def setUp(self):
        self.c=sqlite3.connect(':memory:')
        self.c.row_factory=sqlite3.Row
        self.c.executescript('''CREATE TABLE submissions(id,learner_id,submitted_at);
            CREATE TABLE attempts(id,submission_id);
            CREATE TABLE analysis_jobs(attempt_id,created_at);
            CREATE TABLE published_reports(id,submission_id,report_json);''')
    def tearDown(self):
        self.c.close()
    def publish(self, number, success, condition='independent', question=None):
        sid=f's{number}';aid=f'a{number}'
        self.c.execute('INSERT INTO submissions VALUES(?,?,?)',(sid,'student',number))
        self.c.execute('INSERT INTO attempts VALUES(?,?)',(aid,sid))
        report={'attempt_id':aid,'evidence_condition':condition,'items':[{
            'question_id':question or f'q{number}','question_version_id':f'v{number}',
            'title':'事件順序','kind':'short_answer','skill_id':'sequence','complete':True,
            'criteria':[{'level':int(success),'max_level':1,'quote':'作答證據'}]}]}
        self.c.execute('INSERT INTO published_reports VALUES(?,?,?)',(str(number),sid,encode(report)))
        return report
    def test_replay_correction_and_duplicate_publication(self):
        self.publish(1,False);report=self.publish(2,False)
        state=adaptive.profiles(self.c,'student')[0]
        self.assertEqual(state['state'],'待補強')
        self.assertEqual(state['failures'],2)
        report['items'][0]['criteria'][0]['level']=1
        self.c.execute('INSERT INTO published_reports VALUES(?,?,?)',('correction','s2',encode(report)))
        state=adaptive.profiles(self.c,'student')[0]
        self.assertEqual((state['successes'],state['failures']),(1,1))
        self.assertEqual(state['state'],'待驗證')
        self.c.execute('INSERT INTO published_reports VALUES(?,?,?)',('repeat','s2',encode(report)))
        self.assertEqual(adaptive.profiles(self.c,'student')[0]['mastery_probability'],state['mastery_probability'])
        self.assertEqual(adaptive.profiles(self.c,'another'),[])
    def test_supported_unknown_and_same_question_are_excluded(self):
        self.publish(1,True,'supported')
        self.publish(2,True,'unknown')
        self.publish(3,True,question='q1')
        state=adaptive.profiles(self.c,'student')[0]
        self.assertEqual(state['successes'],0)
        self.assertEqual(state['state'],'待驗證')
        self.assertTrue(all(e['excluded_reason'] for e in state['evidence']))
    def test_reopened_attempt_keeps_original_independent_evidence(self):
        report=self.publish(1,False)
        self.c.execute('INSERT INTO attempts VALUES(?,?)',('reopened','s1'))
        report['attempt_id']='reopened'
        report['items'][0]['criteria'][0]['level']=1
        self.c.execute('INSERT INTO published_reports VALUES(?,?,?)',('revision','s1',encode(report)))
        state=adaptive.profiles(self.c,'student')[0]
        self.assertEqual((state['successes'],state['failures']),(0,1))
        self.assertEqual(len(state['evidence']),2)

    def test_two_successes_and_new_failure(self):
        self.publish(1,True);self.publish(2,True)
        self.assertEqual(adaptive.profiles(self.c,'student')[0]['state'],'本輪獨立驗證通過')
        self.publish(3,False)
        self.assertEqual(adaptive.profiles(self.c,'student')[0]['state'],'待確認')
    def test_recommendations_refresh_and_stop_after_verification(self):
        self.c.executescript("""CREATE TABLE recommendations(id,learner_id,question_version_id,reason_json,review_status);
            CREATE TABLE assignment_items(assignment_id,question_version_id);
            CREATE TABLE assignment_recipients(assignment_id,learner_id);
            CREATE TABLE questions(id,skill_id);
            CREATE TABLE question_versions(id,question_id,review_status,version,rubric_json);""")
        self.c.execute('INSERT INTO questions VALUES(?,?)',('next','sequence'))
        self.c.execute('INSERT INTO question_versions VALUES(?,?,?,?,?)',('next-v1','next','approved',1,encode({'criteria':[{}]})))
        self.publish(1,True)
        adaptive.refresh_recommendations(self.c,'student')
        adaptive.refresh_recommendations(self.c,'student')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0],1)
        self.publish(2,True)
        adaptive.refresh_recommendations(self.c,'student')
        self.assertEqual(self.c.execute('SELECT COUNT(*) FROM recommendations').fetchone()[0],0)

    def test_binary_grading_and_validation(self):
        q={'id':'v','question_id':'q','version':2,'title':'選擇題','kind':'selection',
           'prompt':'請選出正確的選項','payload':{'multiple':True,'options':[{'id':'A','label':'甲'},{'id':'B','label':'乙'}]},'skill_id':'sequence','analysis_metadata':{},
           'answer':{'expected_elements':['A'],'objective':{'type':'choices','expected':['A']}},
           'rubric':{'total_points':2,'criteria':[{'id':'one','name':'正確選擇','max_level':1,'points':2,'levels':{'0':'未達成','1':'達成'}}]}}
        server.validate_question(q)
        with patch.object(analysis,'ai_criteria',return_value=([],None)):
            result=analysis.grade(q,{'interaction':{'choices':['A']}})
        self.assertEqual(result['raw_points'],2)
        self.assertEqual(result['criteria'][0]['level'],1)
        self.assertTrue(adaptive.achieved(result['criteria'][0]))
        bad=copy.deepcopy(q);bad['rubric']['criteria'][0]['max_level']=2
        with self.assertRaises(server.ApiError):server.validate_question(bad)

if __name__=='__main__': unittest.main()
