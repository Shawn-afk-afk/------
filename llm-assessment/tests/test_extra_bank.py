import copy
import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import storage,analysis,server

class AdditionalQuestions(unittest.TestCase):
    def test_all_twenty_questions_and_private_answers(self):
        with storage.db() as c:
            rows=c.execute("SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE q.id LIKE 'ZJU-EX-%' AND version=1").fetchall()
        self.assertEqual(len(rows),20)
        for row in rows:
            q=storage.question(row,True);server.validate_question(q)
            objective=q['answer']['objective'];response={'interaction':{objective['type']:objective['expected']}}
            self.assertTrue(analysis.objective(q,response)[0],q['title'])
            self.assertFalse(analysis.objective(q,{'interaction':{}})[0],q['title'])
            public=storage.question(row,False)
            self.assertNotIn('answer',public);self.assertNotIn('objective',public['payload'])
            self.assertIn(q['answer']['teaching_guide']['reading']['chapter'],(1,2))
    def test_multiselect_rejects_extras_duplicates_and_awards_rule_points(self):
        with storage.db() as c:
            rows=c.execute("SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE q.id LIKE 'ZJU-EX-%'").fetchall()
        q=next(storage.question(row,True) for row in rows if storage.question(row,True)['payload'].get('multiple'))
        correct=q['answer']['objective']['expected']
        self.assertFalse(analysis.objective(q,{'interaction':{'choices':correct+correct[:1]}})[0])
        self.assertFalse(analysis.objective(q,{'interaction':{'choices':correct+['D']}})[0])
        ai=[{'id':'reasoning','level':3,'quote':'測試理由','reason':'測試','feedback':'測試','method':'ai','status':'scored'}]
        with patch.object(analysis,'ai_criteria',return_value=(ai,None)):
            grade=analysis.grade(q,{'interaction':{'choices':list(reversed(correct))},'text':'測試理由'})
        self.assertEqual(grade['criteria'][0]['method'],'rule');self.assertEqual(grade['raw_points'],12)
        invalid=copy.deepcopy(q);invalid['answer']['objective']['expected']=['NOT_AN_OPTION']
        with self.assertRaises(server.ApiError):server.validate_question(invalid)
