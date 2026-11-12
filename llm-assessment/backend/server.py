"""Standalone, dependency-free HTTP application. Run through a TLS ngrok endpoint."""
import argparse
import datetime as dt
import hashlib
import hmac
import json
import mimetypes
import math
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.parse
import urllib.request
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from pathlib import Path
import analysis
import runner
import collab
import model_slots
import model_library
import exam_studio
import dense_rag
from storage import db,initialize,uid,encode,decode,question,latest_questions,hash_input,audit,DB_PATH

STATIC=Path(__file__).resolve().parents[1]/'static'
MAX_BODY=12_000_000
SESSION_SECONDS=8*3600
def now(): return dt.datetime.now(dt.timezone.utc).isoformat()

class ApiError(Exception):
    def __init__(self,status,message): self.status=status;self.message=message

def require(condition,message,status=400):
    if not condition: raise ApiError(status,message)

def hash_password(password):
    require(isinstance(password,str) and 10<=len(password)<=256,'密碼需 10–256 個字元')
    salt=secrets.token_hex(16)
    digest=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),600000).hex()
    return f'pbkdf2$600000${salt}${digest}'

def verify_password(password,value):
    try:
        _,iterations,salt,digest=value.split('$')
        actual=hashlib.pbkdf2_hmac('sha256',password.encode(),salt.encode(),int(iterations)).hex()
        return hmac.compare_digest(actual,digest)
    except Exception:return False

def valid_email(value):
    require(isinstance(value,str) and 3<=len(value)<=180 and re.fullmatch(r'[A-Za-z0-9@._+\-]+',value),'帳號只能使用英數、@、點、底線或連字號')
    return value.lower()

def validate_question(q):
    kinds={'short_answer','formula_puzzle','ordering','matching','python','calculation','selection','grid','case_proposal','ai_collab_canvas'}
    require(q.get('kind') in kinds,'題型不支援')
    require(isinstance(q.get('prompt'),str) and 5<=len(q['prompt'])<=20000,'題幹長度不合法')
    require(isinstance(q.get('title'),str) and 1<=len(q['title'])<=200,'題目標題不合法')
    require(isinstance(q.get('answer',{}).get('expected_elements'),list) and bool(q['answer']['expected_elements']),'缺少必要答案要點')
    rubric=q.get('rubric',{}); criteria=rubric.get('criteria',[])
    require(1<=len(criteria)<=12,'需要 1–12 個評分分項')
    ids=[]
    for r in criteria:
        require(isinstance(r.get('id'),str) and r['id'] not in ids,'分項 ID 必須唯一')
        ids.append(r['id'])
        require(type(r.get('max_level')) is int and r['max_level']==3,'目前分項使用 0–3 級')
        require(type(r.get('points')) in (int,float) and math.isfinite(r['points']) and 0<r['points']<=1000,'分項配分不合法')
        require(set(r.get('levels',{}))=={'0','1','2','3'},'需完整 0–3 級描述')
    require(abs(sum(r['points'] for r in criteria)-rubric.get('total_points',0))<1e-5,'分項配分加總不符')
    if q['kind']=='python':
        t=q.get('tests',{})
        require(re.fullmatch(r'[A-Za-z_]\w*',t.get('function','')) is not None,'需指定實作函式')
        require(bool(t.get('public')) and bool(t.get('hidden')),'需公開及隱藏測試')
        for case in t['public']+t['hidden']:
            require(isinstance(case.get('args'),list) and ('expected' in case or 'raises' in case),'測試案例格式錯誤')
    require(isinstance(q.get('payload'),dict),'互動設定需為 JSON object')
    if q['kind']=='ai_collab_canvas':
        require(isinstance(q['payload'].get('independent_prompt'),str) and len(q['payload']['independent_prompt'])>=10,'AI 白板題需有獨立遷移問題')
        require(type(q['payload'].get('max_turns')) is int and 1<=q['payload']['max_turns']<=6,'AI 提示回合需為 1–6')
    objective=q['answer'].get('objective')
    if objective:
        require(isinstance(objective,dict) and objective.get('type') in ('choice','choices','order','mapping','grid'),'客觀答案類型不合法')
        expected=objective.get('expected');payload=q['payload'];kind=objective['type']
        if kind in ('choice','choices'):
            options=payload.get('options',[])
            require(isinstance(options,list) and 2<=len(options)<=12 and all(isinstance(o,dict) and isinstance(o.get('id'),str) and isinstance(o.get('label'),str) for o in options),'需提供 2–12 個合法選項')
            ids=[o['id'] for o in options];require(len(ids)==len(set(ids)),'選項 ID 不可重複')
            require(type(payload.get('multiple')) is bool and payload['multiple']==(kind=='choices'),'單複選設定與答案不符')
            selected=expected if kind=='choices' else [expected]
            require(isinstance(selected,list) and bool(selected) and all(isinstance(x,str) and x in ids for x in selected) and len(selected)==len(set(selected)),'選項答案不合法')
        elif kind=='order':require(isinstance(expected,list) and expected and sorted(expected)==sorted(payload.get('cards',[])),'排序答案需涵蓋全部卡片')
        elif kind=='mapping':require(isinstance(expected,dict) and set(expected)==set(payload.get('left',[])) and all(v in payload.get('right',[]) for v in expected.values()),'配對答案與候選不符')
        else:require(isinstance(expected,list) and len(expected)==3 and all(isinstance(row,list) and len(row)==3 and all(type(v) is int and v in (0,1) for v in row) for row in expected),'遮罩答案需為 3×3 的 0／1 矩陣')

def add_version(c,q,actor,qid=None):
    validate_question(q)
    skill=q.get('skill_id') or q.get('analysis_metadata',{}).get('target_skill')
    require(c.execute('SELECT 1 FROM skills WHERE id=?',(skill,)).fetchone(),'技能不存在')
    require(c.execute('SELECT 1 FROM sources WHERE id=?',(q.get('source_id'),)).fetchone(),'教材來源不存在')
    if not qid:
        qid='CUSTOM-'+uid()[:8];c.execute('INSERT INTO questions VALUES(?,?)',(qid,skill))
    version=c.execute('SELECT COALESCE(MAX(version),0)+1 FROM question_versions WHERE question_id=?',(qid,)).fetchone()[0]
    vid=f'{qid}-v{version}'
    fields=[vid,qid,version,q['title'],q['kind'],q['prompt'],q['source_id'],q.get('source_locator',''),q.get('scope','chapter_core'),q.get('difficulty_design','standard')]
    fields += [encode(q.get(k,{})) for k in ['payload','answer','rubric','analysis_metadata','runtime','tests']]
    fields += ['draft',None,None]
    c.execute('INSERT INTO question_versions VALUES('+','.join('?' for _ in fields)+')',fields)
    audit(c,actor,'question_version_created',vid)
    return vid

class Handler(BaseHTTPRequestHandler):
    server_version='LLMAssessment/1.0'
    def log_message(self,fmt,*args):
        # Don't log passwords, cookies, bodies, or CSRF values.
        print(f'{self.client_address[0]} {self.command} {urllib.parse.urlsplit(self.path).path} {args[1] if len(args)>1 else ""}')

    def send(self,value,status=200,cookie=None,content_type='application/json; charset=utf-8',extra=None):
        data=value if isinstance(value,(bytes,bytearray)) else encode(value).encode() if content_type.startswith('application/json') else value
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('X-Frame-Options','DENY' if not self.path.startswith('/sandbox') else 'SAMEORIGIN')
        policy="default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-src 'self'; worker-src 'self' blob:; object-src 'none'; base-uri 'none'; form-action 'self'; frame-ancestors 'self'"
        if self.path.startswith('/sandbox'):
            policy="default-src 'none'; script-src 'self' blob: https://cdn.jsdelivr.net/pyodide/v314.0.7/full/ 'wasm-unsafe-eval'; connect-src https://cdn.jsdelivr.net/pyodide/v314.0.7/full/; worker-src blob:; frame-ancestors 'self'; base-uri 'none'"
        self.send_header('Content-Security-Policy',policy)
        if cookie:self.send_header('Set-Cookie',cookie)
        for k,v in (extra or {}).items():self.send_header(k,v)
        self.end_headers();self.wfile.write(data)

    def payload(self):
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:raise ApiError(400,'Content-Length 錯誤')
        require(0<length<=MAX_BODY,'請求大小超過限制',413)
        require(self.headers.get('Content-Type','').split(';')[0]=='application/json','請使用 JSON',415)
        try:
            value=json.loads(self.rfile.read(length))
            require(isinstance(value,dict),'JSON 需為 object')
            return value
        except (ValueError,UnicodeError):raise ApiError(400,'JSON 格式錯誤')

    def identity(self,optional=False):
        cookie=SimpleCookie()
        try:cookie.load(self.headers.get('Cookie',''))
        except Exception:pass
        token=cookie.get('assessment_session')
        if token:
            with db() as c:
                row=c.execute('SELECT u.*,s.csrf FROM sessions s JOIN users u ON u.id=s.user_id WHERE s.token_hash=? AND s.expires>? AND u.disabled=0',(hashlib.sha256(token.value.encode()).hexdigest(),time.time())).fetchone()
            if row:return dict(row)
        if optional:return None
        raise ApiError(401,'請先登入')

    def admin(self):
        u=self.identity();require(u['role']=='admin','僅管理者可操作',403);return u

    def csrf(self,u):
        require(hmac.compare_digest(self.headers.get('X-CSRF-Token',''),u['csrf']),'請重新登入後再操作',403)

    def origin(self):
        origin=self.headers.get('Origin')
        if origin:
            require(urllib.parse.urlsplit(origin).netloc==self.headers.get('Host'),'來源不符',403)
        require(self.headers.get('Sec-Fetch-Site','same-origin') not in ('cross-site',),'不接受跨站寫入',403)

    def learner_task(self,c,aid,u,create=False):
        learner=c.execute('SELECT id FROM learners WHERE user_id=?',(u['id'],)).fetchone()
        require(learner is not None,'此帳戶沒有組員身份',403)
        a=c.execute("SELECT a.* FROM assignments a JOIN assignment_recipients r ON r.assignment_id=a.id WHERE a.id=? AND r.learner_id=? AND a.status='published'",(aid,learner['id'])).fetchone()
        require(a is not None,'找不到已分配的評量',404)
        submission=c.execute('SELECT * FROM submissions WHERE assignment_id=? AND learner_id=?',(aid,learner['id'])).fetchone()
        if create and not submission:
            sid=uid();at=uid()
            c.execute('INSERT INTO submissions(id,assignment_id,learner_id,status,created_at) VALUES(?,?,?,?,?)',(sid,aid,learner['id'],'in_progress',now()))
            c.execute('INSERT INTO attempts VALUES(?,?,?,?)',(at,sid,encode({'mode':a['mode'],'support':decode(a['settings_json'])}),encode({'assignment_id':aid})))
            submission=c.execute('SELECT * FROM submissions WHERE id=?',(sid,)).fetchone()
        return dict(a),dict(submission) if submission else None

    def task_response(self,c,a,s):
        snapshots=[decode(r['question_json']) for r in c.execute('SELECT question_json FROM assignment_snapshots WHERE assignment_id=? ORDER BY position',(a['id'],))]
        response={};attempt=None
        if s:
            attempt=c.execute('SELECT * FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1',(s['id'],)).fetchone()
            response={r['question_version_id']:decode(r['response_json']) for r in c.execute('SELECT * FROM responses WHERE attempt_id=?',(attempt['id'],))}
        public=[]
        for snap in snapshots:
            q=question(snap['question'],private=False)
            public.append({'question':q,'points':snap['points'],'position':snap['position']})
        return {'assignment':a,'submission':s,'attempt_id':attempt['id'] if attempt else None,'items':public,'responses':response}

    def do_GET(self):self.handle_request(False)
    def do_POST(self):self.handle_request(True)

    def handle_request(self,write):
        try:
            url=urllib.parse.urlsplit(self.path);path=url.path
            args=urllib.parse.parse_qs(url.query)
            if not path.startswith('/api/'):
                require(not write,'不支援的方法',405)
                name=urllib.parse.unquote(path.lstrip('/')) or 'index.html'
                require(name in {'index.html','app.js','guide.js','canvas.js','studio.js','rag.js','models.js','i18n.js','translations.js','sounds.js','app.css','retro.css','sandbox.html','sandbox.js','worker.mjs','favicon.svg'} or name.startswith(('vendor/pyodide/','vendor/98/','vendor/win98-sounds/')),'找不到頁面',404)
                target=(STATIC/name).resolve()
                require(target.is_relative_to(STATIC.resolve()) and target.is_file(),'找不到檔案',404)
                ctype=mimetypes.guess_type(name)[0] or 'application/octet-stream'
                return self.send(target.read_bytes(),content_type=ctype+('; charset=utf-8' if ctype.startswith('text/') or ctype in ['application/javascript'] else ''))
            body=self.payload() if write else {}
            if write:self.origin()
            if path=='/api/health':return self.send({'status':'ok','version':analysis.VERSION})
            if path=='/api/session' and not write:
                u=self.identity(optional=True)
                with db() as c:setup=c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]==0
                return self.send({'user':{k:u[k] for k in ['id','role','display_name','email','ui_locale','ui_sounds','ui_volume']} if u else None,'csrf':u['csrf'] if u else None,'setup_required':setup})
            if path=='/api/setup' and write:
                host=self.headers.get('Host','').split(':')[0]
                require(host in ('127.0.0.1','localhost') and self.client_address[0] in ('127.0.0.1','::1'),'首次管理者設定僅限本機入口',403)
                email=valid_email(body.get('email',''));password=hash_password(body.get('password',''));name=body.get('name','管理者')
                require(isinstance(name,str) and 1<=len(name)<=80,'姓名長度不合法')
                with db() as c:
                    c.execute('BEGIN IMMEDIATE')
                    require(c.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]==0,'管理者已建立',409)
                    user=uid();c.execute('INSERT INTO users(id,role,display_name,password_hash,email) VALUES(?,?,?,?,?)',(user,'admin',name,password,email))
                    audit(c,user,'setup',user)
                return self.send({'ok':True})
            if path=='/api/login' and write:
                email=valid_email(body.get('email',''));password=body.get('password','')
                require(isinstance(password,str) and len(password)<=256,'密碼不合法')
                key=hashlib.sha256((email+'|'+self.client_address[0]).encode()).hexdigest()
                with db() as c:
                    limit=c.execute('SELECT * FROM login_limits WHERE key=?',(key,)).fetchone()
                    require(not limit or limit['failures']<8 or time.time()-limit['updated']>300,'嘗試次數過多，請 5 分鐘後再試',429)
                    u=c.execute('SELECT * FROM users WHERE email=? AND disabled=0',(email,)).fetchone()
                    if not u or not verify_password(password,u['password_hash']):
                        c.execute('INSERT INTO login_limits VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET failures=failures+1,updated=excluded.updated',(key,1,time.time()));c.commit()
                        raise ApiError(401,'帳號或密碼錯誤')
                    c.execute('DELETE FROM login_limits WHERE key=?',(key,));token=secrets.token_urlsafe(32);csrf=secrets.token_urlsafe(24)
                    c.execute('DELETE FROM sessions WHERE expires<?',(time.time(),))
                    c.execute('INSERT INTO sessions VALUES(?,?,?,?)',(hashlib.sha256(token.encode()).hexdigest(),u['id'],csrf,time.time()+SESSION_SECONDS))
                secure='; Secure' if os.environ.get('ASSESSMENT_PUBLIC_HTTPS')=='1' else ''
                return self.send({'ok':True},cookie=f'assessment_session={token}; HttpOnly; SameSite=Lax; Path=/; Max-Age={SESSION_SECONDS}'+secure)
            u=self.identity()
            if write:self.csrf(u)
            if path=='/api/preferences':
                if not write:return self.send({'locale':u['ui_locale']})
                locale=body.get('locale');require(locale in ('zh-TW','en','ja','es'),'語言偏好不支援')
                with db() as c:c.execute('UPDATE users SET ui_locale=? WHERE id=?',(locale,u['id']))
                return self.send({'ok':True,'locale':locale})
            if path=='/api/sound-preferences':
                if not write:return self.send({'enabled':bool(u['ui_sounds']) if u['ui_sounds'] is not None else None,'volume':u['ui_volume']})
                enabled=body.get('enabled');volume=body.get('volume')
                require(type(enabled) is bool and type(volume) is int and 0<=volume<=100,'音效偏好不合法')
                with db() as c:c.execute('UPDATE users SET ui_sounds=?,ui_volume=? WHERE id=?',(int(enabled),volume,u['id']))
                return self.send({'ok':True,'enabled':enabled,'volume':volume})
            if path=='/api/logout' and write:
                with db() as c:c.execute('DELETE FROM sessions WHERE user_id=? AND csrf=?',(u['id'],u['csrf']))
                return self.send({'ok':True},cookie='assessment_session=; HttpOnly; SameSite=Lax; Path=/; Max-Age=0')
            if path=='/api/password' and write:
                require(verify_password(body.get('old_password',''),u['password_hash']),'原密碼錯誤',403)
                value=hash_password(body.get('password',''))
                with db() as c:
                    c.execute('UPDATE users SET password_hash=? WHERE id=?',(value,u['id']));c.execute('DELETE FROM sessions WHERE user_id=?',(u['id'],))
                    audit(c,u['id'],'password_changed',u['id'])
                return self.send({'ok':True})
            if path=='/api/canvas/image' and not write:
                with db() as c:row=c.execute('SELECT p.image,l.user_id FROM canvas_snapshots p JOIN attempts t ON t.id=p.attempt_id JOIN submissions s ON s.id=t.submission_id JOIN learners l ON l.id=s.learner_id WHERE p.id=?',(args.get('id',[''])[0],)).fetchone()
                require(row and (u['role']=='admin' or row['user_id']==u['id']),'無法存取白板圖片',403)
                return self.send(row['image'],content_type='image/png')
            if path.startswith('/api/admin/'):
                require(u['role']=='admin','僅管理者可操作',403)
                return self.admin_routes(path,body,args,u,write)
            if path=='/api/tasks' and not write:
                with db() as c:
                    rows=c.execute("SELECT a.*,s.id submission_id,s.status submission_status FROM assignments a JOIN assignment_recipients r ON r.assignment_id=a.id JOIN learners l ON l.id=r.learner_id LEFT JOIN submissions s ON s.assignment_id=a.id AND s.learner_id=l.id WHERE l.user_id=? AND a.status='published' ORDER BY a.created_at DESC",(u['id'],)).fetchall()
                    return self.send({'tasks':[dict(r) for r in rows]})
            m=re.fullmatch(r'/api/tasks/([^/]+)(?:/(start|save|submit|practice|canvas-state|canvas-save|canvas-turn|canvas-finish))?',path)
            if m:
                aid,action=m.groups()
                with db() as c:
                    a,s=self.learner_task(c,aid,u,create=write and action=='start')
                    if not write and not action:return self.send(self.task_response(c,a,s))
                    if action=='canvas-state':
                        require(s,'請先開始評量')
                        attempt=c.execute('SELECT * FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1',(s['id'],)).fetchone()
                        return self.send(collab.handle(c,a,s,attempt,action,body,args,write))
                    require(write and s,'請先開始評量')
                    if action=='start':return self.send(self.task_response(c,a,s))
                    require(s['status']=='in_progress','已繳交，請管理者重新開放',409)
                    attempt=c.execute('SELECT * FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1',(s['id'],)).fetchone()
                    due=decode(attempt['context_json']).get('revision_due_at',a.get('due_at'))
                    if due:require(dt.datetime.now(dt.timezone.utc)<=dt.datetime.fromisoformat(due),'已超過繳交期限',409)
                    if action in ('canvas-save','canvas-turn','canvas-finish'):return self.send(collab.handle(c,a,s,attempt,action,body,args,write))
                    if action in ('save','practice'):
                        vid=body.get('question_version_id');snap=c.execute('SELECT question_json FROM assignment_snapshots WHERE assignment_id=? AND json_extract(question_json,\'$.question.id\')=?',(aid,vid)).fetchone()
                        require(snap is not None,'題目不在分配卷內',403)
                        if action=='practice':
                            require(decode(a['settings_json']).get('allow_practice',a['mode']=='practice'),'此卷不開放試跑',403)
                            q=decode(snap['question_json'])['question'];require(q['kind']=='python','非實作題')
                            require(len(body.get('code',''))<=50000,'程式過長')
                            result=runner.run(body.get('code',''),q['tests'],hidden=False)
                            c.execute('INSERT INTO practice_runs(id,learner_id,question_version_id,code_hash,result_json) VALUES(?,?,?,?,?)',(uid(),s['learner_id'],vid,hash_input(body.get('code','')),encode(result)))
                            return self.send(result)
                        response=body.get('response');require(isinstance(response,dict) and len(encode(response))<=100000,'作答格式錯誤')
                        require(set(response)<= {'text','code','interaction','proposal','canvas'},'未知作答欄位')
                        if 'canvas' in response:
                            require(decode(snap['question_json'])['question']['kind']=='ai_collab_canvas','非白板題不得提交白板資料')
                            collab.validate_response(c,response,attempt['id'],vid)
                        require(all(isinstance(response.get(k,''),str) for k in ('text','code')),'文字與程式需為字串')
                        require(all(isinstance(response.get(k,{}),dict) for k in ('interaction','proposal')),'互動與方案需為 object')
                        require(all(isinstance(v,str) for v in response.get('proposal',{}).values()),'方案欄位需為文字')
                        inter=response.get('interaction',{})
                        require(all(isinstance(inter[k],list) and all(isinstance(v,str) for v in inter[k]) for k in ('order','top_k','top_p','choices') if k in inter),'排序與候選項格式錯誤')
                        if 'choice' in inter:require(isinstance(inter['choice'],str),'單選格式錯誤')
                        if 'mapping' in inter:require(isinstance(inter['mapping'],dict) and all(isinstance(v,str) for v in inter['mapping'].values()),'配對格式錯誤')
                        if 'grid' in inter:require(isinstance(inter['grid'],list) and len(inter['grid'])<=20 and all(isinstance(row,list) and len(row)<=20 and all(type(v) is int and v in (0,1) for v in row) for row in inter['grid']),'矩陣格式錯誤')
                        c.execute('INSERT INTO responses(id,attempt_id,question_version_id,response_json,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(attempt_id,question_version_id) DO UPDATE SET response_json=excluded.response_json,updated_at=excluded.updated_at',(uid(),attempt['id'],vid,encode(response),now()))
                        event=body.get('event')
                        if event:
                            rid=c.execute('SELECT id FROM responses WHERE attempt_id=? AND question_version_id=?',(attempt['id'],vid)).fetchone()['id']
                            c.execute('INSERT INTO interaction_events VALUES(?,?,?)',(uid(),rid,encode({'event':str(event)[:80],'timestamp':now()})))
                        return self.send({'ok':True,'saved_at':now()})
                    if action=='submit':
                        require(not c.execute("SELECT 1 FROM canvas_turns WHERE attempt_id=? AND status IN ('queued','running')",(attempt['id'],)).fetchone(),'請等待白板 AI 工作完成後繳交',409)
                        for row in c.execute('SELECT question_json FROM assignment_snapshots WHERE assignment_id=?',(aid,)):
                            snapshot_question=decode(row['question_json'])['question']
                            if snapshot_question['kind']=='ai_collab_canvas':require(c.execute("SELECT 1 FROM canvas_progress WHERE attempt_id=? AND question_version_id=? AND phase='independent'",(attempt['id'],snapshot_question['id'])).fetchone(),'白板題請先完成協作並進入獨立作答',409)
                        c.execute("UPDATE submissions SET status='submitted',submitted_at=? WHERE id=?",(now(),s['id']))
                        values=[dict(r) for r in c.execute('SELECT question_version_id,response_json FROM responses WHERE attempt_id=? ORDER BY question_version_id',(attempt['id'],))]
                        jid=uid();c.execute('INSERT INTO analysis_jobs(id,attempt_id,input_hash,analyzer_version,status,created_at) VALUES(?,?,?,?,?,?)',(jid,attempt['id'],hash_input(values),analysis.VERSION,'queued',time.time()))
                        audit(c,u['id'],'submitted',s['id'])
                        return self.send({'ok':True,'job_id':jid})
                raise ApiError(404,'找不到操作')
            if path=='/api/reports' and not write:
                with db() as c:
                    rows=c.execute('SELECT p.id,p.submission_id,p.report_json,a.title FROM published_reports p JOIN submissions s ON s.id=p.submission_id JOIN learners l ON l.id=s.learner_id JOIN assignments a ON a.id=s.assignment_id WHERE l.user_id=? AND p.rowid=(SELECT MAX(p2.rowid) FROM published_reports p2 WHERE p2.submission_id=p.submission_id) ORDER BY p.rowid DESC',(u['id'],)).fetchall()
                    return self.send({'reports':[{'id':r['id'],'submission_id':r['submission_id'],'title':r['title'],'report':decode(r['report_json'])} for r in rows]})
            raise ApiError(404,'找不到 API')
        except ApiError as exc:self.send({'error':exc.message},exc.status)
        except collab.CollabError as exc:self.send({'error':exc.message},exc.status)
        except (model_slots.SlotError,exam_studio.ExamError,dense_rag.RagError) as exc:self.send({'error':str(exc)},400)
        except sqlite3.IntegrityError:self.send({'error':'資料已存在或關聯不合法'},409)
        except (KeyError,TypeError,ValueError):self.send({'error':'欄位不完整或格式錯誤'},400)
        except (BrokenPipeError,ConnectionResetError):pass
        except Exception as exc:
            print('API error:',type(exc).__name__,str(exc)[:200]);self.send({'error':'服務發生錯誤，請稍後再試'},500)

    def admin_routes(self,path,b,args,u,write):
        if path.startswith('/api/admin/models'):return model_library.routes(self,path,b,args,u,write)
        if path.startswith('/api/admin/model-slots'):return model_slots.routes(self,path,b,u,write)
        if path.startswith('/api/admin/exam/'):return exam_studio.routes(self,path,b,args,u,write)
        if path=='/api/admin/collab-settings':
            if not write:return self.send({'config':collab.settings(),'models':analysis.models(),'endpoint':analysis.OLLAMA_URL})
            model=b.get('model');require(isinstance(model,str) and 1<=len(model)<=180 and ':cloud' not in model.lower(),'需使用本機模型')
            try:
                req=urllib.request.Request(analysis.OLLAMA_URL+'/api/show',data=encode({'model':model}).encode(),headers={'Content-Type':'application/json'})
                with urllib.request.urlopen(req,timeout=5) as r:capabilities=json.load(r).get('capabilities',[])
            except Exception:raise ApiError(503,'本機模型尚未就緒')
            require('vision' in capabilities,'白板模型必須支援图像')
            with db() as c:
                c.execute("DELETE FROM model_roles WHERE role='vision'")
                c.execute("INSERT INTO app_meta VALUES('collab_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encode({'model':model,'enabled':bool(b.get('enabled',True))}),));audit(c,u['id'],'collab_settings','settings')
            return self.send({'ok':True})
        canvas_match=re.fullmatch(r'/api/admin/submissions/([^/]+)/canvas',path)
        if canvas_match and not write:
            with db() as c:
                require(c.execute('SELECT 1 FROM submissions WHERE id=?',(canvas_match[1],)).fetchone(),'作答不存在',404)
                snapshots=[dict(row) for row in c.execute("SELECT p.id,p.attempt_id,p.question_version_id,p.created_at,json_array_length(p.scene_json,'$.elements') element_count FROM canvas_snapshots p JOIN attempts t ON t.id=p.attempt_id WHERE t.submission_id=? ORDER BY p.created_at",(canvas_match[1],))]
                turns=[dict(row) for row in c.execute('SELECT v.* FROM canvas_turns v JOIN attempts t ON t.id=v.attempt_id WHERE t.submission_id=? ORDER BY v.created_at',(canvas_match[1],))]
                progress=[dict(row) for row in c.execute('SELECT p.* FROM canvas_progress p JOIN attempts t ON t.id=p.attempt_id WHERE t.submission_id=?',(canvas_match[1],))]
            return self.send({'snapshots':snapshots,'turns':turns,'progress':progress})
        if path=='/api/admin/dashboard':
            with db() as c:
                counts={key:c.execute(sql).fetchone()[0] for key,sql in {'questions':'SELECT COUNT(*) FROM questions','approved':"SELECT COUNT(*) FROM question_versions WHERE review_status='approved'",'learners':'SELECT COUNT(*) FROM learners','assignments':'SELECT COUNT(*) FROM assignments','submissions':"SELECT COUNT(*) FROM submissions WHERE status!='in_progress'",'pending':"SELECT COUNT(*) FROM analysis_jobs WHERE status IN ('queued','running')"}.items()}
                jobs=[dict(r) for r in c.execute('SELECT j.*,a.title,u.display_name FROM analysis_jobs j JOIN attempts t ON t.id=j.attempt_id JOIN submissions s ON s.id=t.submission_id JOIN assignments a ON a.id=s.assignment_id JOIN learners l ON l.id=s.learner_id JOIN users u ON u.id=l.user_id ORDER BY j.created_at DESC LIMIT 20')]
            available_models=analysis.models();config=analysis.settings()
            return self.send({'counts':counts,'jobs':jobs,'models':available_models,'ai':config,'model_ready':config.get('model') in available_models,'runner':runner.availability()})
        if path=='/api/admin/questions' and not write:
            with db() as c:
                rows=[question(r,True) for r in latest_questions(c)]
                sources=[dict(r) for r in c.execute('SELECT id,path,content_kind,source_status FROM sources')]
                skills=[dict(r) for r in c.execute('SELECT * FROM skills')]
            return self.send({'questions':rows,'sources':sources,'skills':skills})
        if path=='/api/admin/questions' and write:
            with db() as c:vid=add_version(c,b,u['id'])
            return self.send({'id':vid})
        m=re.fullmatch(r'/api/admin/questions/([^/]+)/(approve|reject|version|reference-run)',path)
        if m and write:
            vid,action=m.groups()
            with db() as c:
                row=c.execute('SELECT * FROM question_versions WHERE id=?',(vid,)).fetchone();require(row,'題目不存在',404)
                if action=='reference-run':
                    q=question(row,True);code=q['answer'].get('teaching_guide',{}).get('reference_code')
                    require(q['kind']=='python' and isinstance(code,str) and code,'此題沒有參考程式')
                    return self.send(runner.run(code,q['tests'],hidden=True))
                if action=='version':return self.send({'id':add_version(c,b,u['id'],row['question_id'])})
                if action=='approve':
                    approved_question=question(row,True);validate_question(approved_question)
                    guide=approved_question['answer'].get('teaching_guide',{})
                    require(isinstance(guide,dict) and bool(guide.get('reference_answer')) and bool(guide.get('steps')),'核准前請補齊詳解與解題步驟')
                    require(guide.get('reading',{}).get('chapter') in (1,2),'核准前請標明第一章或第二章的閱讀依據')
                    if approved_question['kind']=='python':require(bool(guide.get('reference_code')),'實作題核准前請補齊參考程式')
                c.execute('UPDATE question_versions SET review_status=?,reviewed_by=?,reviewed_at=? WHERE id=?',('approved' if action=='approve' else 'rejected',u['id'],now(),vid))
                audit(c,u['id'],'question_'+action,vid)
            return self.send({'ok':True})
        if path=='/api/admin/learners':
            with db() as c:
                if not write:return self.send({'learners':[dict(r) for r in c.execute('SELECT l.id,l.user_id,u.email,u.display_name,u.disabled FROM learners l JOIN users u ON u.id=l.user_id ORDER BY u.display_name')]})
                name=b.get('name','');require(isinstance(name,str) and 1<=len(name)<=80,'請輸入組員姓名')
                email=valid_email(b.get('email',''));pwd=hash_password(b.get('password',''));user=uid();learner=uid()
                c.execute('INSERT INTO users(id,role,display_name,password_hash,email) VALUES(?,?,?,?,?)',(user,'learner',name,pwd,email));c.execute('INSERT INTO learners VALUES(?,?,?)',(learner,user,'{}'));audit(c,u['id'],'learner_created',learner)
            return self.send({'id':learner})
        m=re.fullmatch(r'/api/admin/learners/([^/]+)/(reset|disable)',path)
        if m and write:
            with db() as c:
                row=c.execute('SELECT user_id FROM learners WHERE id=?',(m[1],)).fetchone();require(row,'組員不存在',404)
                if m[2]=='reset':c.execute('UPDATE users SET password_hash=? WHERE id=?',(hash_password(b.get('password','')),row['user_id']))
                else:c.execute('UPDATE users SET disabled=? WHERE id=?',(1 if b.get('disabled',True) else 0,row['user_id']))
                c.execute('DELETE FROM sessions WHERE user_id=?',(row['user_id'],));audit(c,u['id'],'learner_'+m[2],m[1])
            return self.send({'ok':True})
        if path=='/api/admin/assignments':
            with db() as c:
                if not write:
                    rows=[]
                    for r in c.execute('SELECT * FROM assignments ORDER BY created_at DESC'):
                        item=dict(r);item['item_count']=c.execute('SELECT COUNT(*) FROM assignment_items WHERE assignment_id=?',(r['id'],)).fetchone()[0];item['recipient_count']=c.execute('SELECT COUNT(*) FROM assignment_recipients WHERE assignment_id=?',(r['id'],)).fetchone()[0];rows.append(item)
                    return self.send({'assignments':rows})
                title=b.get('title','');require(isinstance(title,str) and 1<=len(title)<=150,'請輸入卷名')
                mode=b.get('mode','assessment');require(mode in ('practice','assessment'),'模式錯誤')
                items=b.get('items',[]);recipients=b.get('recipients',[])
                require(1<=len(items)<=60 and len({x['id'] for x in items})==len(items),'選題需 1–60 題且不可重複')
                require(1<=len(recipients)<=200 and len(set(recipients))==len(recipients),'需分配至少一位組員且不可重複')
                options={'auto_publish':bool(b.get('auto_publish',True)),'publish_code_ai':bool(b.get('publish_code_ai',False)),'allow_practice':bool(b.get('allow_practice',mode=='practice')),'allow_browser':bool(b.get('allow_browser',True)),'support_note':str(b.get('support_note',''))[:500]}
                due=b.get('due_at') or None
                if due:
                    parsed=dt.datetime.fromisoformat(due);require(parsed.tzinfo is not None,'期限需含時區');due=parsed.astimezone(dt.timezone.utc).isoformat()
                aid=uid();c.execute('INSERT INTO assignments(id,owner_id,mode,status,settings_json,title,created_at,due_at) VALUES(?,?,?,?,?,?,?,?)',(aid,u['id'],mode,'published',encode(options),title,now(),due))
                for pos,item in enumerate(items,1):
                    row=c.execute('SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE v.id=?',(item['id'],)).fetchone()
                    require(row and row['review_status']=='approved','只能分配已核准題目')
                    points=item.get('points',12);require(type(points) in (int,float) and 0<points<=1000,'配分錯誤')
                    q=question(row,True);c.execute('INSERT INTO assignment_items VALUES(?,?,?,?)',(aid,item['id'],pos,points));c.execute('INSERT INTO assignment_snapshots VALUES(?,?,?)',(aid,pos,encode({'question':q,'points':points,'position':pos})))
                for learner in recipients:
                    require(c.execute('SELECT 1 FROM learners l JOIN users u ON u.id=l.user_id WHERE l.id=? AND u.disabled=0',(learner,)).fetchone(),'組員不存在或已停用')
                    c.execute('INSERT INTO assignment_recipients VALUES(?,?)',(aid,learner))
                audit(c,u['id'],'assignment_published',aid,{'items':len(items),'recipients':len(recipients)})
            return self.send({'id':aid})
        if path=='/api/admin/submissions' and not write:
            with db() as c:
                rows=[]
                for r in c.execute('SELECT s.*,a.title,u.display_name FROM submissions s JOIN assignments a ON a.id=s.assignment_id JOIN learners l ON l.id=s.learner_id JOIN users u ON u.id=l.user_id ORDER BY s.created_at DESC'):
                    item=dict(r);run=c.execute('SELECT ar.result_json,ar.id FROM analysis_runs ar JOIN analysis_jobs j ON j.id=ar.job_id JOIN attempts t ON t.id=j.attempt_id WHERE t.id=(SELECT id FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1) ORDER BY ar.rowid DESC LIMIT 1',(r['id'],)).fetchone()
                    item['result']=decode(run['result_json']) if run else None;item['run_id']=run['id'] if run else None
                    manual=c.execute('SELECT result_json FROM manual_adjustments WHERE submission_id=? AND attempt_id=(SELECT id FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1) ORDER BY revision DESC LIMIT 1',(r['id'],r['id'])).fetchone()
                    if manual:item['result']=decode(manual['result_json'])
                    item['published']=bool(c.execute('SELECT 1 FROM published_reports WHERE submission_id=?',(r['id'],)).fetchone());rows.append(item)
            return self.send({'submissions':rows})
        m=re.fullmatch(r'/api/admin/submissions/([^/]+)(?:/(review|retry|reopen))?',path)
        if m:
            sid,action=m.groups()
            with db() as c:
                s=c.execute('SELECT * FROM submissions WHERE id=?',(sid,)).fetchone();require(s,'作答不存在',404)
                run=c.execute('SELECT ar.* FROM analysis_runs ar JOIN analysis_jobs j ON j.id=ar.job_id JOIN attempts t ON t.id=j.attempt_id WHERE t.id=(SELECT id FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1) ORDER BY ar.rowid DESC LIMIT 1',(sid,)).fetchone()
                if not write:
                    a=c.execute('SELECT * FROM assignments WHERE id=?',(s['assignment_id'],)).fetchone()
                    data=self.task_response(c,dict(a),dict(s));data['result']=decode(run['result_json']) if run else None;data['run_id']=run['id'] if run else None
                    data['original_ai_result']=data['result']
                    manual=c.execute('SELECT result_json FROM manual_adjustments WHERE submission_id=? AND attempt_id=(SELECT id FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1) ORDER BY revision DESC LIMIT 1',(sid,sid)).fetchone()
                    if manual:data['result']=decode(manual['result_json'])
                    # Management can inspect full snapshot and expected answers.
                    data['private_items']=[decode(x['question_json']) for x in c.execute('SELECT question_json FROM assignment_snapshots WHERE assignment_id=? ORDER BY position',(s['assignment_id'],))]
                    data['review_history']=[dict(x) for x in c.execute('SELECT * FROM manual_adjustments WHERE submission_id=? ORDER BY revision',(sid,))]
                    return self.send(data)
                if action=='reopen':
                    require(not c.execute("SELECT 1 FROM canvas_turns v JOIN attempts t ON t.id=v.attempt_id WHERE t.submission_id=? AND v.status IN ('queued','running')",(sid,)).fetchone(),'請先等待白板 AI 工作完成',409)
                    require(not c.execute("SELECT 1 FROM analysis_jobs j JOIN attempts t ON t.id=j.attempt_id WHERE t.submission_id=? AND j.status IN ('queued','running')",(sid,)).fetchone(),'請先等待正在執行的分析完成',409)
                    c.execute("UPDATE submissions SET status='in_progress' WHERE id=?",(sid,))
                    prior=c.execute('SELECT id,context_json,snapshot_json FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
                    context=decode(prior['context_json']);context['revision_due_at']=None
                    new=uid();c.execute('INSERT INTO attempts VALUES(?,?,?,?)',(new,sid,encode(context),prior['snapshot_json']))
                    for r in c.execute('SELECT * FROM responses WHERE attempt_id=?',(prior['id'],)).fetchall():
                        c.execute('INSERT INTO responses(id,attempt_id,question_version_id,response_json,updated_at) VALUES(?,?,?,?,?)',(uid(),new,r['question_version_id'],r['response_json'],now()))
                    collab.clone_attempt(c,prior['id'],new)
                    audit(c,u['id'],'submission_reopened',sid);return self.send({'ok':True})
                if action=='retry':
                    require(s['status']!='in_progress','請等待組員繳交後再分析',409)
                    attempt=c.execute('SELECT id FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()
                    running=c.execute("SELECT 1 FROM analysis_jobs WHERE attempt_id=? AND status IN ('queued','running')",(attempt['id'],)).fetchone();require(not running,'已有分析正在進行',409)
                    jid=uid();c.execute('INSERT INTO analysis_jobs(id,attempt_id,input_hash,analyzer_version,status,created_at) VALUES(?,?,?,?,?,?)',(jid,attempt['id'],hash_input({'retry':jid,'attempt':attempt['id']}),analysis.VERSION,'queued',time.time()));audit(c,u['id'],'analysis_retry',sid)
                    return self.send({'ok':True})
                require(action=='review' and run,'尚無分析可覆核')
                require(s['status']!='in_progress','請等待組員繳交修訂後再覆核',409)
                attempt_id=c.execute('SELECT id FROM attempts WHERE submission_id=? ORDER BY rowid DESC LIMIT 1',(sid,)).fetchone()['id']
                manual=c.execute('SELECT result_json FROM manual_adjustments WHERE submission_id=? AND attempt_id=? ORDER BY revision DESC LIMIT 1',(sid,attempt_id)).fetchone()
                result=decode(manual['result_json'] if manual else run['result_json']);levels=b.get('levels',{});note=str(b.get('note',''))[:4000]
                for item in result['items']:
                    for r in item['criteria']:
                        key=item['question_version_id']+':'+r['id']
                        level=levels.get(key,r['level']);require(type(level) is int and level in range(4),'全部分項需有 0–3 級評分')
                        r.setdefault('original_level',r['level']);r['level']=level;r['points']=round(r['max_points']*level/r['max_level'],4);r['method']='human_review';r['status']='scored'
                    item['complete']=True;item['score']=round(sum(x['points'] for x in item['criteria'])/item['raw_max']*item['assigned_points'],2)
                result.update({'complete':True,'score':round(sum(x['score'] for x in result['items']),2),'source':'人工覆核／調整','review_note':note,'reviewed_at':now()})
                revision=c.execute('SELECT COALESCE(MAX(revision),0)+1 FROM manual_adjustments WHERE submission_id=?',(sid,)).fetchone()[0]
                c.execute('INSERT INTO manual_adjustments(id,submission_id,reviewer_id,revision,result_json,attempt_id) VALUES(?,?,?,?,?,?)',(uid(),sid,u['id'],revision,encode(result),attempt_id))
                decision=uid();c.execute('INSERT INTO review_decisions VALUES(?,?,?,?)',(decision,run['id'],u['id'],encode({'levels':levels,'note':note,'revision':revision})))
                if b.get('publish',True):
                    c.execute('INSERT INTO published_reports VALUES(?,?,?,?)',(uid(),sid,decision,encode(result)));analysis.recommendations(c,s['learner_id'],result)
                audit(c,u['id'],'manual_review',sid,{'revision':revision})
            return self.send({'ok':True})
        if path=='/api/admin/settings':
            if not write:return self.send({'ai':analysis.settings(),'models':analysis.models(),'runner':runner.availability()})
            model=b.get('model','');require(isinstance(model,str) and len(model)<=100,'模型名称不合法')
            require(':cloud' not in model.lower(),'請選擇免費本機模型，不接受雲端模型')
            reasoning=b.get('reasoning','medium');require(reasoning in ('low','medium','high'),'推理程度不合法')
            config={'model':model,'enabled':bool(b.get('enabled',True)),'reasoning':reasoning}
            with db() as c:
                c.execute("DELETE FROM model_roles WHERE role='grading'")
                c.execute("INSERT INTO app_meta VALUES('ai_settings',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(encode(config),));audit(c,u['id'],'settings_changed','ai',config)
            return self.send({'ok':True})
        if path=='/api/admin/overview' and not write:
            with db() as c:
                report_rows=c.execute('SELECT s.learner_id,a.mode,a.settings_json,p.report_json FROM published_reports p JOIN submissions s ON s.id=p.submission_id JOIN assignments a ON a.id=s.assignment_id WHERE p.rowid=(SELECT MAX(p2.rowid) FROM published_reports p2 WHERE p2.submission_id=p.submission_id) ORDER BY p.rowid').fetchall()
                names={r['id']:r['display_name'] for r in c.execute('SELECT l.id,u.display_name FROM learners l JOIN users u ON u.id=l.user_id')}
                groups={};seen=set()
                for row in reversed(report_rows):
                    report=decode(row['report_json'])
                    for item in report['items']:
                        options=decode(row['settings_json']);support=encode({k:options.get(k) for k in ('allow_practice','allow_browser','support_note')})
                        fingerprint=(row['learner_id'],row['mode'],support,item['question_version_id'])
                        if fingerprint in seen:continue
                        seen.add(fingerprint)
                        key=(row['learner_id'],row['mode'],support,item['skill_id'],item.get('kind'),item.get('difficulty_design'),item.get('rubric_fingerprint'));g=groups.setdefault(key,{'learner':names[row['learner_id']],'learner_id':row['learner_id'],'mode':row['mode'],'skill':item['skill_id'],'kind':item.get('kind'),'difficulty':item.get('difficulty_design'),'support':options.get('support_note',''),'allow_practice':options.get('allow_practice'),'allow_browser':options.get('allow_browser'),'rubric_fingerprint':item.get('rubric_fingerprint'),'met':0,'count':0,'unknown':0})
                        if not item['complete']:g['unknown']+=1
                        else:g['count']+=1;g['met']+=int(all(x['level']>=2 for x in item['criteria']))
                return self.send({'overview':list(groups.values()),'recommendations':[dict(r) for r in c.execute('SELECT r.*,v.title,u.display_name FROM recommendations r JOIN question_versions v ON v.id=r.question_version_id JOIN learners l ON l.id=r.learner_id JOIN users u ON u.id=l.user_id ORDER BY r.rowid DESC LIMIT 100')]})
        if path=='/api/admin/export' and not write:
            require(args.get('format',['json'])[0]=='json','匯出格式不支援')
            with db() as c:
                package={'format':'llm-assessment-bank-v1','exported_at':now(),'questions':[question(r,True) for r in latest_questions(c)],'skills':[dict(r) for r in c.execute('SELECT * FROM skills')],'sources':[dict(r) for r in c.execute('SELECT id,path,sha256,content_kind,source_status FROM sources')],'rules':[dict(r) for r in c.execute('SELECT * FROM analysis_rules')]}
            return self.send(package,extra={'Content-Disposition':'attachment; filename="llm-assessment-bank.json"'})
        if path=='/api/admin/import' and write:
            require(b.get('format')=='llm-assessment-bank-v1','匯入格式不符')
            require(isinstance(b.get('questions'),list) and len(b['questions'])<=100,'一次匯入最多100題')
            with db() as c:
                ids=[add_version(c,q,u['id']) for q in b['questions']]
                audit(c,u['id'],'bank_import','questions',{'count':len(ids)})
            return self.send({'count':len(ids)})
        if path=='/api/admin/audit' and not write:
            with db() as c:rows=[dict(r) for r in c.execute('SELECT * FROM audit_events ORDER BY rowid DESC LIMIT 100')]
            return self.send({'events':rows})
        if path=='/api/admin/source' and not write:
            with db() as c:row=c.execute('SELECT * FROM sources WHERE id=?',(args.get('id',[''])[0],)).fetchone()
            require(row,'來源不存在',404)
            if row['content_kind']=='.pdf':return self.send(row['content'],content_type='application/pdf',extra={'Content-Disposition':'inline; filename="source.pdf"'})
            return self.send({'path':row['path'],'content':row['content'].decode('utf-8'),'status':row['source_status']})
        raise ApiError(404,'找不到管理 API')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--host',default='127.0.0.1');parser.add_argument('--port',type=int,default=8765);parser.add_argument('--no-worker',action='store_true');parser.add_argument('--no-grading',action='store_true');args=parser.parse_args()
    initialize()
    if not args.no_worker:
        if not args.no_grading:threading.Thread(target=analysis.worker,daemon=True).start()
        threading.Thread(target=collab.worker,daemon=True).start()
        threading.Thread(target=exam_studio.worker,daemon=True).start()
        threading.Thread(target=dense_rag.worker,daemon=True).start()
        threading.Thread(target=model_library.worker,daemon=True).start()
    http=ThreadingHTTPServer((args.host,args.port),Handler)
    print(f'Local: http://{args.host}:{args.port}',flush=True)
    try:http.serve_forever()
    except KeyboardInterrupt:pass
    finally:dense_rag.STOP.set();model_library.STOP.set();analysis.STOP.set();collab.STOP.set();exam_studio.STOP.set();http.server_close()

if __name__=='__main__':main()
