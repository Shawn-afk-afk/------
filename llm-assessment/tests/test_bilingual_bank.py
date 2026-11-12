import sys
import unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import storage,server,analysis,revise_bank

class BilingualProfile(unittest.TestCase):
    def test_latest_authored_scope_language_and_concept_profile(self):
        with storage.db() as c:questions=[storage.question(row,True) for row in storage.latest_questions(c) if row['question_id'].startswith('ZJU-')]
        self.assertEqual(len(questions),61)
        self.assertEqual(sum(q['payload'].get('language')=='en' for q in questions),31)
        self.assertFalse(any(q['kind'] in ('calculation','formula_puzzle') for q in questions))
        self.assertGreaterEqual(sum(bool(q['payload'].get('reading_code')) for q in questions),15)
        for q in questions:
            server.validate_question(q)
            self.assertIn(q['answer']['teaching_guide']['reading']['chapter'],(1,2))
            if q['payload'].get('language')=='en':
                self.assertFalse(any('\u4e00'<=char<='\u9fff' for char in q['prompt']))
                for option in q['payload'].get('options',[]):self.assertFalse(any('\u4e00'<=char<='\u9fff' for char in option['label']))
            if q['answer'].get('objective'):
                rule=q['answer']['objective']
                self.assertTrue(analysis.objective(q,{'interaction':{rule['type']:rule['expected']}})[0],q['title'])
    def test_revision_preview_is_idempotent_and_old_answers_survive(self):
        with storage.db() as c:
            old=c.execute("SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE v.id='ZJU-002-v1'").fetchone()
            latest=next(storage.question(row,True) for row in storage.latest_questions(c) if row['question_id']=='ZJU-002')
        self.assertEqual(storage.question(old,True)['kind'],'formula_puzzle')
        self.assertEqual(latest['kind'],'selection')
        self.assertEqual(latest['analysis_metadata']['content_revision'],revise_bank.REVISION)
    def test_ai_receives_reading_code_and_language_policy(self):
        with storage.db() as c:q=next(storage.question(row,True) for row in storage.latest_questions(c) if row['question_id']=='ZJU-022')
        self.assertIn('label = original[mask_index]',q['answer']['teaching_guide']['reference_answer'])
        self.assertNotIn('原 token「閱讀」',q['answer']['teaching_guide']['reference_answer'])
        captured={}
        def request(req,**kwargs):
            import json
            captured.update(json.loads(req.data))
            raise RuntimeError('intentional offline test')
        with patch.object(analysis.urllib.request,'urlopen',side_effect=request):analysis.ai_criteria(q,{'text':'目標應是 original[mask_index]'}, {})
        import json
        material=json.loads(captured['messages'][1]['content'])['question_material']
        self.assertEqual(material['reading_code'],q['payload']['reading_code'])
        self.assertIn('中英文',captured['messages'][0]['content'])
