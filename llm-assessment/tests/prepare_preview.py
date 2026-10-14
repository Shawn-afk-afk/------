"""Explicit QA fixture in .runtime/qa.sqlite3; never seeds live users or assignments."""
import sqlite3
import sys
import urllib.request
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import storage,server
from test_workflow import Client

root=Path(__file__).resolve().parents[1]
target=root/'.runtime/qa.sqlite3'
if target.exists():raise SystemExit('QA fixture already exists; use its separate QA server.')
with sqlite3.connect(storage.DB_PATH) as src,sqlite3.connect(target) as dst:src.backup(dst)
src.close();dst.close()
storage.DB_PATH=target;storage.initialize()
http=server.ThreadingHTTPServer(('127.0.0.1',0),server.Handler)
import threading
threading.Thread(target=http.serve_forever,daemon=True).start()
admin=Client(f'http://127.0.0.1:{http.server_port}')
admin.call('/api/setup',{'email':'qa-admin','password':'QA-only-password123!','name':'測試管理者'})
admin.login('qa-admin')
learner=admin.call('/api/admin/learners',{'email':'qa-student','password':'QA-only-password123!','name':'測試組員'})['id']
questions=admin.call('/api/admin/questions')['questions']
for q in questions:admin.call('/api/admin/questions/'+q['id']+'/approve',{})
ids=[next(q['id'] for q in questions if q['kind']==kind) for kind in ('formula_puzzle','matching','python','case_proposal')]
admin.call('/api/admin/assignments',{'title':'QA 測試卷：概念、程式與改善方案','mode':'practice','items':[{'id':x,'points':12} for x in ids],'recipients':[learner],'allow_practice':True,'auto_publish':False})
http.shutdown();http.server_close()
print('Created isolated preview fixture:',target)
