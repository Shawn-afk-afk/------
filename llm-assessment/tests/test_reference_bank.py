import os
import sys
import unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import storage,runner

class ReferenceBank(unittest.TestCase):
    def test_every_original_question_has_private_guide(self):
        with storage.db() as c:rows=c.execute("SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE q.id LIKE 'ZJU-%' AND v.version=1").fetchall()
        self.assertEqual(len(rows),61)
        for row in rows:
            q=storage.question(row,True);g=q['answer']['teaching_guide']
            self.assertIn(g['reading']['chapter'],(1,2));self.assertTrue(g['steps']);self.assertGreater(len(g['reference_answer']),70)
            self.assertNotIn('answer',storage.question(row,False))
            if q['kind']=='python':self.assertTrue(g['reference_code'])
    @unittest.skipUnless(os.environ.get('ASSESSMENT_TEST_WSL')=='1','Real WSL reference checks are opt-in')
    def test_all_reference_programs_pass_public_and_hidden_cases(self):
        with storage.db() as c:rows=[row for row in storage.latest_questions(c) if row['kind']=='python']
        for row in rows:
            q=storage.question(row,True)
            with self.subTest(title=q['title']):
                result=runner.run(q['answer']['teaching_guide']['reference_code'],q['tests'],hidden=True)
                self.assertEqual(result['status'],'completed',result)
                self.assertEqual(result['passed'],result['total'],result)
