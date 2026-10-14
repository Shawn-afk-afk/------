"""Local model profiles, role selection, and portable inference transport."""
import os,json,time,urllib.request,urllib.parse,urllib.error,re
from storage import db,uid,encode,decode,audit

DEFAULT_URL=os.environ.get('ASSESSMENT_OLLAMA_URL','http://127.0.0.1:11434').rstrip('/')
class SlotError(ValueError):pass
def check(ok,message):
    if not ok:raise SlotError(message)
def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS model_profiles(id TEXT PRIMARY KEY,name TEXT NOT NULL,config_json TEXT NOT NULL,created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS model_roles(role TEXT PRIMARY KEY,profile_id TEXT NOT NULL REFERENCES model_profiles(id));''')
    for pid,name,model,vision in [('gemma-12b','Gemma 4 12B · 原始模型','gemma4:12b-it-q4_K_M',True),('gpt-oss-20b','GPT OSS 20B · 推理批改','gpt-oss:20b',False)]:
        c.execute('INSERT OR IGNORE INTO model_profiles VALUES(?,?,?,?)',(pid,name,encode({'provider':'ollama','endpoint':DEFAULT_URL,'model':model,'vision':vision,'source_kind':'base','base_model':model,'adapter_note':'','reasoning':'medium'}),time.time()))
    # Existing teacher choices remain effective until explicitly bound to a slot.
    c.execute("INSERT OR IGNORE INTO model_roles VALUES('generation','gemma-12b')")

def selected(role,fallback=None):
    with db() as c:r=c.execute('SELECT p.* FROM model_roles r JOIN model_profiles p ON p.id=r.profile_id WHERE r.role=?',(role,)).fetchone()
    if not r:return fallback
    return {**(fallback or {}),**decode(r['config_json']),'profile_id':r['id'],'profile_name':r['name']}

def endpoint(value):
    u=urllib.parse.urlsplit(value)
    check(u.scheme in ('http','https') and u.hostname in ('localhost','127.0.0.1','::1') and not u.username and not u.password and not u.query and not u.fragment,'目前僅接受本機 localhost／127.0.0.1 模型服務網址')
    check(u.path.rstrip('/') in ('','/v1'),'接口路徑需為根目錄或 /v1')
    return value.rstrip('/')

class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self,*args,**kwargs):raise SlotError('模型接口不能重新導向其他網址')
def request(url,data=None,timeout=5,headers=None):
    req=urllib.request.Request(url,data=encode(data).encode() if data is not None else None,headers={'Content-Type':'application/json',**(headers or {})})
    with urllib.request.build_opener(NoRedirect).open(req,timeout=timeout) as response:return json.load(response)

def lm_headers():
    token=os.environ.get('ASSESSMENT_LMSTUDIO_TOKEN','')
    return {'Authorization':'Bearer '+token} if token else {}

def available(config):
    url=endpoint(config['endpoint'])
    if config['provider']=='ollama':
        return [m['name'] for m in request(url+'/api/tags').get('models',[]) if 'cloud' not in m['name'].lower() and not m.get('remote_host') and not m.get('remote_model')]
    if config['provider']=='lmstudio':
        return [m['id'] for m in request(url.removesuffix('/v1')+'/v1/models',headers=lm_headers()).get('data',[]) if 'cloud' not in m['id'].lower()]
    return [m['id'] for m in request(url.removesuffix('/v1')+'/v1/models').get('data',[])]

def verify(config):
    check(config['model'] in available(config),'此來源尚未提供指定模型；先啟動或載入模型後再切換')
    if config['provider']=='ollama':
        shown=request(config['endpoint']+'/api/show',{'model':config['model']})
        check(not shown.get('remote_host') and not shown.get('remote_model'),'模型來源必須在本機執行')
        caps=shown.get('capabilities',[])
        check(not config['vision'] or 'vision' in caps,'指定模型未提供視覺能力')
    elif config['provider']=='omni_local':
        models=request(config['endpoint'].removesuffix('/v1')+'/v1/models').get('data',[])
        capabilities=next((m.get('capabilities',[]) for m in models if m.get('id')==config['model']),[])
        check(not config['vision'] or 'vision' in capabilities,'原生接口未提供圖像能力')
    return True

def prepare_gpu(config):
    # Called inside the assessment's global inference lock. Only release this
    # application's own loopback-native adapter and registered Ollama models.
    with db() as c:profiles=[decode(r['config_json']) for r in c.execute('SELECT config_json FROM model_profiles')]
    if config.get('provider')=='omni_local':
        owned={p['model'] for p in profiles if p['provider']=='ollama'}
        try:running=request(DEFAULT_URL+'/api/ps').get('models',[])
        except urllib.error.URLError:running=[]
        for item in running:
            if item['name'] in owned:request(DEFAULT_URL+'/api/generate',{'model':item['name'],'keep_alive':0},timeout=60)
    elif config.get('provider','ollama')=='ollama':
        for url in {endpoint(p['endpoint']).removesuffix('/v1') for p in profiles if p['provider']=='omni_local'}:
            try:request(url+'/v1/unload',{},timeout=60)
            except urllib.error.HTTPError:raise SlotError('OmniEdu 原生模型仍忙碌，請稍後重試')
            except urllib.error.URLError:pass

def chat(body,config):
    config=config or {};prepare_gpu(config);provider=config.get('provider','ollama');url=endpoint(config.get('endpoint',DEFAULT_URL))
    if provider=='ollama':return request(url+'/api/chat',body,timeout=300)
    messages=[]
    for message in body['messages']:
        item={k:v for k,v in message.items() if k!='images'}
        if message.get('images'):
            item['content']=[{'type':'text','text':message['content']}]+[{'type':'image_url','image_url':{'url':'data:image/png;base64,'+v}} for v in message['images']]
        messages.append(item)
    payload={'model':body['model'],'messages':messages,'stream':False,'temperature':body.get('options',{}).get('temperature',0),'max_tokens':body.get('options',{}).get('num_predict',3000),'response_format':{'type':'json_object'}}
    raw=request(url.removesuffix('/v1')+'/v1/chat/completions',payload,timeout=300,headers=lm_headers()) if provider=='lmstudio' else request(url.removesuffix('/v1')+'/v1/chat/completions',payload,timeout=300)
    return {'model':raw.get('model',body['model']),'message':raw['choices'][0]['message']}

def routes(handler,path,b,u,write):
    if path=='/api/admin/model-slots' and not write:
        with db() as c:
            profiles=[{**dict(r),'config':decode(r['config_json'])} for r in c.execute('SELECT * FROM model_profiles ORDER BY created_at')]
            roles={r['role']:r['profile_id'] for r in c.execute('SELECT * FROM model_roles')}
        import analysis,collab
        return handler.send({'profiles':profiles,'roles':roles,'effective':{'generation':selected('generation'),'vision':collab.settings(),'grading':analysis.settings()},'legacy_roles':['vision','grading']})
    if path=='/api/admin/model-slots' and write:
        name=b.get('name','').strip();check(1<=len(name)<=120,'請填模型來源名稱')
        provider=b.get('provider');check(provider in ('ollama','lmstudio','omni_local','openai_local'),'模型來源不支援')
        model=b.get('model','');check(isinstance(model,str) and re.fullmatch(r'[A-Za-z0-9_./:\-]{1,180}',model) and 'cloud' not in model.lower(),'請填本機模型名稱')
        kind=b.get('source_kind','base');check(kind in ('base','lora'),'來源類型不支援')
        config={'provider':provider,'endpoint':endpoint(b.get('endpoint',DEFAULT_URL)),'model':model,'vision':bool(b.get('vision')),'source_kind':kind,'base_model':str(b.get('base_model',''))[:180],'adapter_note':str(b.get('adapter_note',''))[:1000],'reasoning':b.get('reasoning','medium')}
        check(config['reasoning'] in ('low','medium','high'),'推理程度不支援')
        pid=uid()
        with db() as c:c.execute('INSERT INTO model_profiles VALUES(?,?,?,?)',(pid,name,encode(config),time.time()));audit(c,u['id'],'model_profile_created',pid)
        return handler.send({'id':pid,'status':'registered_not_activated'})
    if path=='/api/admin/model-slots/activate' and write:
        role=b.get('role');check(role in ('generation','vision','grading'),'模型槽不存在')
        with db() as c:r=c.execute('SELECT * FROM model_profiles WHERE id=?',(b.get('profile_id'),)).fetchone()
        check(r,'模型來源不存在');config=decode(r['config_json']);check(role!='vision' or config['vision'],'白板模型槽需要視覺能力')
        verify(config)
        with db() as c:c.execute('INSERT INTO model_roles VALUES(?,?) ON CONFLICT(role) DO UPDATE SET profile_id=excluded.profile_id',(role,r['id']));audit(c,u['id'],'model_role_changed',role,{'profile_id':r['id']})
        return handler.send({'ok':True})
    if path=='/api/admin/model-slots/probe' and write:
        with db() as c:r=c.execute('SELECT * FROM model_profiles WHERE id=?',(b.get('profile_id'),)).fetchone()
        check(r,'模型來源不存在');config=decode(r['config_json']);verify(config)
        return handler.send({'ok':True,'models':available(config),'note':'模型列舉及能力已核對；LoRA 品質與實際多模態支援需試跑'})
    raise SlotError('找不到模型槽操作')
