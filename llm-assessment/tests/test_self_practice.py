"""Exercises the existing login and material library through the practice endpoints."""
import unittest
from unittest.mock import patch

import test_workflow as workflow
from test_workflow import Client, storage
import self_practice

PASS = 'QA-only-password123!'
QUOTE = '光合作用利用光能把二氧化碳與水轉為醣類。'


class SelfPracticeWorkflow(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        workflow.Workflow.setUpClass()

    @classmethod
    def tearDownClass(cls):
        workflow.Workflow.tearDownClass()

    def test_share_generate_submit_and_revoke(self):
        admin = Client(workflow.Workflow.base)
        admin.call('/api/setup', {'email': 'qa-admin', 'password': PASS, 'name': '測試教師'})
        admin.login('qa-admin')
        for email in ('qa-student', 'qa-other'):
            admin.call('/api/admin/learners', {'email': email, 'password': PASS, 'name': email})
        student = Client(workflow.Workflow.base)
        student.login('qa-student')
        other = Client(workflow.Workflow.base)
        other.login('qa-other')
        with storage.db() as c:
            c.execute("""INSERT INTO exam_materials(id,title,subject,text,index_json,locator,created_at)
                         VALUES('material','光合作用','Chinese',?,'{}','教師教材',1)""", (QUOTE * 3,))
        share = '/api/admin/exam/share-practice-material'
        self.assertEqual(student.call('/api/self-practice')['materials'], [])
        payload = {'material_id': 'material', 'topic': '光合作用', 'count': 3}
        student.call('/api/self-practice', payload, 404)
        student.call(share, {'id': 'material', 'shared': True}, 403)
        admin.call(share, {'id': 'material', 'shared': True})
        self.assertTrue(admin.call('/api/admin/exam/materials')['materials'][0]['practice_shared'])
        self.assertEqual(set(student.call('/api/self-practice')['materials'][0]), {'id', 'title', 'subject'})

        def model_reply(request, profile):
            data = storage.decode(request['messages'][1]['content'])
            questions = [{
                'stem': f'光合作用練習題 {i}', 'options': ['光能', '磁力', '壓力', '震動'],
                'correct': 0, 'explanation': '教材說明此過程利用光能。',
                'source_ref': data['passages'][0]['source_ref'], 'quote': QUOTE,
            } for i in range(data['count'])]
            return {'message': {'content': storage.encode({'questions': questions})}}

        with patch.object(self_practice.model_slots, 'chat', side_effect=model_reply):
            quiz_id = student.call('/api/self-practice', payload)['id']
        path = '/api/self-practice/' + quiz_id
        quiz = student.call(path)
        self.assertEqual(set(quiz['questions'][0]), {'stem', 'options'})
        self.assertFalse(student.call('/api/self-practice')['history'][0]['completed'])
        other.call(path, expected=404)
        other.call(path, {'answers': [0, 0, 0]}, 404)
        student.call(path, {'answers': [0, 0]}, 400)
        answers = [q['options'].index('光能') for q in quiz['questions']]
        result = student.call(path, {'answers': answers})
        self.assertEqual(result['score'], 3)
        self.assertEqual(result['questions'][0]['quote'], QUOTE)
        self.assertEqual(student.call(path, {'answers': [0, 0, 0]}), result)
        admin.call(share, {'id': 'material', 'shared': False})
        student.call(path, expected=404)
        self.assertEqual(student.call('/api/self-practice')['history'], [])

    def test_model_output_requires_verbatim_source(self):
        question = {
            'stem': '這是什麼過程？', 'options': ['光合', '呼吸', '蒸散', '發酵'],
            'correct': 0, 'explanation': '參考教材', 'source_ref': 'source',
            'quote': '這段引文不存在於原始教材',
        }
        with self.assertRaises(ValueError):
            self_practice.verify_questions([question], [{'source_ref': 'source', 'text': QUOTE}], 1)
