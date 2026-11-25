"""Verify the published-pack bridge and the student visibility boundary."""
import base64
import unittest

import test_workflow as workflow
from test_workflow import Client
import storage


def published_pack():
    return {
        'format': 'ai-teaching-resource-pack', 'packageVersion': 1, 'schemaVersion': '3.0.0',
        'manifest': {'scope': 'one-published-version', 'sourceScope': 'published-chunks-only',
                     'attachments': 'none', 'studentData': False, 'inputMode': 'source'},
        'resources': [{'id': 'resource', 'latestPublishedVersionId': 'version', 'type': 'tieredPractice',
                       'currentDraftId': None}],
        'versions': [{'versionNo': 1, 'content': {
            'id': 'version', 'resourceId': 'resource', 'resourceType': 'tieredPractice', 'title': '地圖方向練習',
            'blocks': [
                {'type': 'paragraph', 'visibility': 'student', 'data': {'text': '判讀地圖前，請先找出指北標示。'}},
                {'type': 'paragraph', 'visibility': 'teacher', 'data': {'text': 'PRIVATE_PARAGRAPH'}},
                {'type': 'teacherNote', 'visibility': 'teacher', 'data': {'text': 'PRIVATE_NOTE'}},
                {'type': 'questionSet', 'visibility': 'both', 'data': {'questionIds': ['fill', 'upload']}},
            ],
            'questions': [
                {'id': 'upload', 'type': 'upload', 'prompt': '上傳手繪地圖。', 'rubric': 'PRIVATE_RUBRIC'},
                {'id': 'fill', 'type': 'fillBlank', 'prompt': '看圖填寫方位。',
                 'blanks': [{'id': 'direction', 'label': '第一格', 'answers': ['PRIVATE_ANSWER']}]},
            ],
        }}],
        'chunks': [{'text': 'PRIVATE_SOURCE'}],
    }


def request(pack, action='preview', subject='Geography'):
    return {'action': action, 'subject': subject,
            'data': base64.b64encode(storage.encode(pack).encode()).decode()}


class TeachingPackWorkflow(unittest.TestCase):
    setUpClass = classmethod(workflow.Workflow.setUpClass.__func__)
    tearDownClass = classmethod(workflow.Workflow.tearDownClass.__func__)

    def test_import_and_read_only_after_explicit_sharing(self):
        admin, student, anonymous = [Client(self.base) for _ in range(3)]
        password = 'QA-only-password123!'
        admin.call('/api/setup', {'email': 'qa-admin', 'password': password, 'name': '測試管理者'})
        admin.login('qa-admin')
        admin.call('/api/admin/learners', {'email': 'qa-student', 'password': password, 'name': '測試學生'})
        student.login('qa-student')
        pack = published_pack()
        endpoint = '/api/admin/exam/teaching-pack'
        student.call(endpoint, request(pack), expected=403)
        admin.call(endpoint, request(pack), expected=403, csrf=False)
        admin.call(endpoint, request(pack, 'import', 'LLM'), expected=400)
        preview = admin.call(endpoint, request(pack))
        self.assertEqual(preview['question_count'], 2)
        self.assertIn('第一格：＿＿＿', preview['text'])
        self.assertLess(preview['text'].index('看圖填寫方位'), preview['text'].index('上傳手繪地圖'))
        self.assertNotIn('PRIVATE_', preview['text'])
        self.assertEqual(admin.call('/api/admin/exam/materials')['materials'], [])

        imported = admin.call(endpoint, request(pack, 'import'))
        material_id = imported['id']
        self.assertFalse(imported['existing'])
        self.assertEqual(admin.call(endpoint, request(pack, 'import')), {'id': material_id, 'existing': True})
        materials = admin.call('/api/admin/exam/materials')['materials']
        self.assertEqual([m['id'] for m in materials], [material_id])
        self.assertEqual(materials[0]['rag_status'], 'queued')
        read_path = '/api/self-practice/materials/' + material_id
        anonymous.call(read_path, expected=401)
        student.call(read_path, expected=404)
        admin.call('/api/admin/exam/share-practice-material', {'id': material_id, 'shared': True})
        self.assertTrue(student.call('/api/self-practice')['materials'][0]['has_handout'])
        self.assertEqual(student.call(read_path)['text'], preview['text'])
        admin.call('/api/admin/exam/share-practice-material', {'id': material_id, 'shared': False})
        student.call(read_path, expected=404)
        admin.call('/api/admin/exam/share-practice-material', {'id': material_id, 'shared': True})
        admin.call('/api/admin/exam/archive-material', {'id': material_id})
        student.call(read_path, expected=404)
        admin.call(endpoint, request(pack, 'import'), expected=400)

    def test_invalid_or_private_packs_are_rejected(self):
        import teaching_pack

        pack = published_pack()
        pack['manifest']['studentData'] = True
        with self.assertRaises(ValueError):
            teaching_pack.read(request(pack)['data'])
        pack['manifest']['studentData'] = False
        pack['versions'][0]['content']['blocks'][-1]['data']['questionIds'] = ['missing']
        with self.assertRaises(ValueError):
            teaching_pack.read(request(pack)['data'])
        with self.assertRaises(ValueError):
            teaching_pack.read('not valid base64')
