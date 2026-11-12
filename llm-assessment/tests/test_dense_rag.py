import unittest
from unittest.mock import patch
import test_workflow as workflow
from test_workflow import Client
import storage,dense_rag

class DenseRag(unittest.TestCase):
    @classmethod
    def setUpClass(cls):workflow.Workflow.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):workflow.Workflow.tearDownClass.__func__(cls)

    def test_auto_queue_dense_ranking_sources_isolation_failure_and_archive(self):
        admin=Client(self.base);student=Client(self.base)
        admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'RAG QA'});admin.login('qa-admin')
        admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'RAG learner'});student.login('qa-student')
        student.call('/api/admin/exam/rag-status',expected=403)
        text='[PDF 第 4 頁]\nPreserve the original token as the label before replacing the input with a mask. This separates the prediction target from the modified input.'
        relevant=admin.call('/api/admin/exam/materials',{'title':'Targets','subject':'English','text':text})['id']
        irrelevant=admin.call('/api/admin/exam/materials',{'title':'Weather','subject':'English','text':'Rain and snow are weather conditions. The forecast helps us choose suitable clothing and plan a walk.'})['id']
        status=admin.call('/api/admin/exam/rag-status')['documents'];self.assertTrue(all(s['status']=='queued' for s in status))
        admin.call('/api/admin/exam/rag-search',{'query':'避免標籤污染','unit_ids':[relevant]},400)
        calls=[]
        def embeddings(texts,query=False):
            calls.append((texts,query))
            # Controlled model outputs test vector ranking independently of words.
            return [[1.,0.] if query or 'Preserve' in t else [0.,1.] for t in texts]
        with patch.object(dense_rag,'embed',side_effect=embeddings),patch.object(dense_rag,'identity',return_value='test-model-v1'):
            dense_rag.index_material(relevant);dense_rag.index_material(irrelevant)
            rows=admin.call('/api/admin/exam/materials')['materials'];self.assertTrue(all(m['rag_status']=='ready' for m in rows))
            result=admin.call('/api/admin/exam/rag-search',{'query':'避免標籤污染','unit_ids':[relevant,irrelevant]})['results']
            self.assertEqual(result[0]['source_unit_id'],relevant);self.assertAlmostEqual(result[0]['score'],1.)
            self.assertEqual(result[0]['text'],text[result[0]['start']:result[0]['end']]);self.assertIn('PDF 頁',result[0]['locator'])
            isolated=admin.call('/api/admin/exam/rag-search',{'query':'避免標籤污染','unit_ids':[irrelevant]})['results']
            self.assertTrue(all(p['source_unit_id']==irrelevant for p in isolated))
            count=len(calls);dense_rag.index_material(relevant);self.assertEqual(len(calls),count)  # Ready index reused.
            admin.call('/api/admin/exam/rag-rebuild',{'id':relevant},403,csrf=False)
            admin.call('/api/admin/exam/rag-rebuild',{'id':relevant})
            with patch.object(dense_rag,'embed',side_effect=RuntimeError('local model unavailable')):
                with self.assertRaises(dense_rag.RagError):dense_rag.index_material(relevant)
            failed=next(s for s in admin.call('/api/admin/exam/rag-status')['documents'] if s['material_id']==relevant)
            self.assertEqual(failed['status'],'failed');self.assertIn('local model unavailable',failed['error'])
            admin.call('/api/admin/exam/rag-search',{'query':'targets','unit_ids':[relevant]},400)
            admin.call('/api/admin/exam/rag-rebuild',{'id':relevant});dense_rag.index_material(relevant)
            admin.call('/api/admin/exam/archive-material',{'id':relevant})
            admin.call('/api/admin/exam/rag-search',{'query':'targets','unit_ids':[relevant]},400)

    def test_chunk_overlap_exact_offsets_and_invalid_embedding_rejected(self):
        text=('中文教材與code snippet。\n'*140)+'[PDF 第 9 頁]\nEnd.'
        chunks=dense_rag.split({'id':'fixture','text':text,'locator':'test source'})
        self.assertGreater(len(chunks),2);self.assertEqual(chunks[0]['start'],0);self.assertEqual(chunks[-1]['end'],len(text))
        for item in chunks:self.assertEqual(item['text'],text[item['start']:item['end']])
        for a,b in zip(chunks,chunks[1:]):self.assertLess(b['start'],a['end'])
        for bad in ([0.,0.],[float('nan')],[float('inf')],[]):
            with self.assertRaises(dense_rag.RagError):dense_rag.normalize(bad)

if __name__=='__main__':unittest.main()
