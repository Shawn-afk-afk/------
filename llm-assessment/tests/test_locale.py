import unittest
import test_workflow as workflow
from test_workflow import Client

class LocalePreferences(unittest.TestCase):
    @classmethod
    def setUpClass(cls):workflow.Workflow.setUpClass.__func__(cls)
    @classmethod
    def tearDownClass(cls):workflow.Workflow.tearDownClass.__func__(cls)
    def test_locale_authentication_validation_and_account_isolation(self):
        guest=Client(self.base);admin=Client(self.base);student=Client(self.base)
        guest.call('/api/preferences',expected=401)
        admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'管理者'});admin.login('qa-admin')
        self.assertIsNone(admin.call('/api/preferences')['locale'])
        admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'管理者'});student.login('qa-student')
        for locale in ('zh-TW','en','ja','es'):
            self.assertEqual(admin.call('/api/preferences',{'locale':locale})['locale'],locale)
            self.assertEqual(admin.call('/api/session')['user']['ui_locale'],locale)
        student.call('/api/preferences',{'locale':'ja'})
        self.assertEqual(admin.call('/api/preferences')['locale'],'es')
        admin.call('/api/preferences',{'locale':'fr'},400)
        admin.call('/api/preferences',{'locale':'en'},403,csrf=False)
        self.assertEqual(admin.call('/api/preferences')['locale'],'es')
        admin.login('qa-admin');self.assertEqual(admin.call('/api/session')['user']['ui_locale'],'es')
        for asset in ('i18n.js','translations.js'):
            with guest.opener.open(self.base+'/'+asset) as response:self.assertEqual(response.status,200)

if __name__=='__main__':unittest.main()
