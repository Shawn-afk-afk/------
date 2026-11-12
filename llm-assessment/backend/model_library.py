"""Admin-only public model acquisition and chunked local weight uploads.

HF is metadata only. Runtime APIs download and run locally; there is no cloud
inference client, payment integration, remote-code loader, or user token input.
"""
import base64,hashlib,json,re,shutil,struct,threading,time,urllib.parse,urllib.request
from storage import db,uid,encode,decode,audit,DB_PATH
import model_slots as slots

STOP=threading.Event()
CHUNK=1024*1024
MAX_BYTES=32*1024**3
LOCK=threading.Lock()

def initialize(c):
    c.executescript('''
    CREATE TABLE IF NOT EXISTS model_uploads(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,name TEXT NOT NULL,size INTEGER NOT NULL,received INTEGER NOT NULL DEFAULT 0,status TEXT NOT NULL,sha256 TEXT,created_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS model_upload_chunks(upload_id TEXT NOT NULL REFERENCES model_uploads(id),offset INTEGER NOT NULL,data BLOB NOT NULL,PRIMARY KEY(upload_id,offset));
    CREATE TABLE IF NOT EXISTS model_acquisitions(id TEXT PRIMARY KEY,owner_id TEXT NOT NULL,request_json TEXT NOT NULL,status TEXT NOT NULL,progress TEXT NOT NULL,completed_bytes INTEGER NOT NULL DEFAULT 0,total_bytes INTEGER NOT NULL DEFAULT 0,result_json TEXT,error TEXT,created_at REAL NOT NULL);
    ''')

def repo_id(value):
    slots.check(isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',value) and '..' not in value,'請輸入 Hugging Face 的 owner/repository')
    return value

def hf_request(path):
    # Fixed host; no credentials, inference endpoints, arbitrary URLs or redirects.
    return slots.request('https://huggingface.co/api/models'+path,timeout=20)

def hf_search(term):
    slots.check(isinstance(term,str) and 1<=len(term.strip())<=100,'請輸入模型搜尋文字')
    rows=hf_request('?'+urllib.parse.urlencode({'search':term.strip(),'filter':'gguf','limit':12,'sort':'downloads','direction':-1}))
    return [{'id':r.get('id',r.get('modelId')),'downloads':r.get('downloads',0),'license':next((t[8:] for t in r.get('tags',[]) if t.startswith('license:')),None)} for r in rows if not r.get('private') and not r.get('gated')]

def hf_detail(repo):
    repo=repo_id(repo);r=hf_request('/'+repo+'?blobs=true')
    slots.check(not r.get('private') and not r.get('gated'),'此模型需要授權或登入；目前只提供無需登入的公開模型')
    files=[]
    for f in r.get('siblings',[]):
        name=f.get('rfilename','')
        # One GGUF file, excluding projector-only and split shards.
        if re.fullmatch(r'[A-Za-z0-9_.-]+\.gguf',name,re.I) and not re.search(r'mmproj|\d{5}-of-\d{5}',name,re.I):
            files.append({'name':name,'size':f.get('size') or (f.get('lfs') or {}).get('size',0),'sha256':(f.get('lfs') or {}).get('sha256')})
    return {'id':repo,'revision':r.get('sha'),'license':(r.get('cardData') or {}).get('license'),'files':files,'url':'https://huggingface.co/'+repo}

def safe_model(value):
    slots.check(isinstance(value,str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.:/-]{0,179}',value) and '..' not in value and 'cloud' not in value.lower(),'請使用本機模型名稱，不能使用 cloud 模型或任意網址')
    slots.check('://' not in value and not value.startswith(('http:','https:')),'模型名稱不能是網址')
    return value

def upload_chunks(upload_id):
    offset=0
    while True:
        with db() as c:r=c.execute('SELECT data FROM model_upload_chunks WHERE upload_id=? AND offset=?',(upload_id,offset)).fetchone()
        if not r:return
        data=bytes(r['data']);yield data;offset+=len(data)

def validate_weight(name,size,prefix):
    if name.lower().endswith('.gguf'):
        slots.check(len(prefix)>=24 and prefix[:4]==b'GGUF' and struct.unpack_from('<I',prefix,4)[0] in (2,3),'檔案不是有效 GGUF 標頭')
    elif name.lower().endswith('.safetensors'):
        slots.check(len(prefix)>=8,'Safetensors 標頭不完整')
        n=struct.unpack_from('<Q',prefix)[0]
        slots.check(2<=n<=CHUNK-8 and n+8<size and len(prefix)>=n+8,'Safetensors 標頭大小不合法')
        header=json.loads(prefix[8:8+n]);slots.check(isinstance(header,dict),'Safetensors 標頭需為 object')
        for key,item in header.items():
            if key=='__metadata__':continue
            slots.check(isinstance(item,dict) and isinstance(item.get('data_offsets'),list) and len(item['data_offsets'])==2,'Safetensors tensor 欄位不完整')
            start,end=item['data_offsets'];slots.check(type(start) is int and type(end) is int and 0<=start<=end<=size-8-n,'Safetensors tensor 範圍不合法')
    else:
        slots.check(name=='adapter_config.json' and size<=65536,'只接受 GGUF、Safetensors 或 adapter_config.json')
        slots.check(isinstance(json.loads(prefix),dict),'Adapter 設定需為 JSON object')

def queue_job(c,u,request):
    slots.check(c.execute("SELECT COUNT(*) FROM model_acquisitions WHERE status IN ('queued','running')").fetchone()[0]<4,'模型工作佇列已滿，請等待目前工作完成')
    jid=uid();c.execute('INSERT INTO model_acquisitions(id,owner_id,request_json,status,progress,created_at) VALUES(?,?,?,?,?,?)',(jid,u['id'],encode(request),'queued','等待主機處理',time.time()));audit(c,u['id'],'model_acquisition_queued',jid,request)
    return {'id':jid,'status':'queued'}

def update(jid,progress,completed=0,total=0):
    with db() as c:c.execute('UPDATE model_acquisitions SET progress=?,completed_bytes=?,total_bytes=? WHERE id=?',(str(progress)[:300],completed,total,jid))

def stream_ollama(jid,url,payload):
    req=urllib.request.Request(url,data=encode({**payload,'stream':True}).encode(),headers={'Content-Type':'application/json'})
    success=False
    with urllib.request.build_opener(slots.NoRedirect).open(req,timeout=300) as response:
        for line in response:
            if not line.strip():continue
            r=json.loads(line);slots.check(not r.get('error'),str(r.get('error'))[:300]);update(jid,r.get('status','下載中'),int(r.get('completed',0)),int(r.get('total',0)))
            success=r.get('status')=='success'
    slots.check(success,'模型服務未回報下載／匯入成功')

def register(u,request,model):
    config={'provider':request['runtime'],'endpoint':request['endpoint'],'model':model,'vision':False,'source_kind':request.get('source_kind','base'),'base_model':request.get('base_model',''),'adapter_note':'','reasoning':'medium'}
    if config['provider']=='ollama':
        shown=slots.request(config['endpoint']+'/api/show',{'model':model},timeout=20)
        slots.check(not shown.get('remote_host') and not shown.get('remote_model'),'不能使用遠端／雲端模型')
        config['vision']='vision' in shown.get('capabilities',[])
    pid=uid()
    with db() as c:c.execute('INSERT INTO model_profiles VALUES(?,?,?,?)',(pid,model,encode(config),time.time()));audit(c,u,'local_model_registered',pid)
    return {'profile_id':pid,'model':model,'note':'已下載／匯入本機，尚未切換模型槽；請先核對來源'}

def process(job):
    request=decode(job['request_json']);jid=job['id'];runtime=request['runtime'];url=slots.endpoint(request['endpoint'])
    try:
        if request['kind']=='import':
            with db() as c:weight=dict(c.execute('SELECT * FROM model_uploads WHERE id=?',(request['upload_id'],)).fetchone())
            digest='sha256:'+weight['sha256'];update(jid,'傳送已驗證權重到本機 Ollama')
            blob=urllib.request.Request(url+'/api/blobs/'+digest,data=upload_chunks(weight['id']),headers={'Content-Type':'application/octet-stream','Content-Length':str(weight['size'])})
            with urllib.request.build_opener(slots.NoRedirect).open(blob,timeout=300) as response:response.read()
            model=request['model'];payload={'model':model,'files':{weight['name']:digest}}
            stream_ollama(jid,url+'/api/create',payload)
        elif runtime=='ollama':
            model=request['model'];stream_ollama(jid,url+'/api/pull',{'model':model})
        else:
            payload={'model':request['model']}
            if request.get('quantization'):payload['quantization']=request['quantization']
            r=slots.request(url.removesuffix('/v1')+'/api/v1/models/download',payload,timeout=30,headers=slots.lm_headers())
            deadline=time.monotonic()+24*3600
            while r.get('status') not in ('already_downloaded','completed','failed'):
                slots.check(time.monotonic()<deadline,'LM Studio 下載監控逾時；請在主機查看進度')
                slots.check(r.get('job_id'),'LM Studio 沒有回傳下載工作 ID')
                update(jid,r.get('status','下載中'),int(r.get('downloaded_bytes',0)),int(r.get('total_size_bytes',0)))
                if STOP.wait(2):raise slots.SlotError('服務停止，LM Studio 可能仍在下載；請檢查主機')
                r=slots.request(url.removesuffix('/v1')+'/api/v1/models/download/status/'+urllib.parse.quote(r['job_id'],safe=''),timeout=20,headers=slots.lm_headers())
            slots.check(r.get('status')!='failed','LM Studio 模型下載失敗')
            # Download identifiers and inference IDs can differ. Do not invent one.
            result={'note':'LM Studio 已下載。請列舉本機模型，將服務實際回傳的模型 ID 登錄為來源。'}
            with db() as c:c.execute("UPDATE model_acquisitions SET status='completed',progress=?,result_json=? WHERE id=?",('本機下載完成',encode(result),jid))
            return
        result=register(job['owner_id'],request,model)
        with db() as c:c.execute("UPDATE model_acquisitions SET status='completed',progress=?,result_json=? WHERE id=?",('本機模型已就緒，等待核對與切換',encode(result),jid))
    except Exception as exc:
        with db() as c:c.execute("UPDATE model_acquisitions SET status='failed',progress='未完成',error=? WHERE id=?",(str(exc)[:500],jid))

def worker():
    with db() as c:c.execute("UPDATE model_acquisitions SET status='failed',error='服務重新啟動；請檢查本機下載狀態後重試' WHERE status='running'")
    while not STOP.is_set():
        with db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT * FROM model_acquisitions WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
            if r:c.execute("UPDATE model_acquisitions SET status='running' WHERE id=?",(r['id'],))
        if r:process(dict(r))
        else:STOP.wait(1)

def routes(handler,path,b,args,u,write):
    if path=='/api/admin/models' and not write:
        with db() as c:
            uploads=[dict(r) for r in c.execute('SELECT * FROM model_uploads ORDER BY created_at DESC LIMIT 50')]
            jobs=[{**dict(r),'request':decode(r['request_json']),'result':decode(r['result_json']) if r['result_json'] else None} for r in c.execute('SELECT * FROM model_acquisitions ORDER BY created_at DESC LIMIT 30')]
        return handler.send({'uploads':uploads,'jobs':jobs,'chunk_size':CHUNK,'max_upload_bytes':MAX_BYTES})
    if path=='/api/admin/models/search' and not write:return handler.send({'models':hf_search(args.get('q',[''])[0])})
    if path=='/api/admin/models/hf' and not write:return handler.send(hf_detail(args.get('repo',[''])[0]))
    if path=='/api/admin/models/list' and write:
        runtime=b.get('runtime');slots.check(runtime in ('ollama','lmstudio','openai_local'),'執行來源不支援')
        config={'provider':runtime,'endpoint':slots.endpoint(b.get('endpoint',''))}
        return handler.send({'models':slots.available(config)})
    if path=='/api/admin/models/download' and write:
        runtime=b.get('runtime');slots.check(runtime in ('ollama','lmstudio'),'下載需使用本機 Ollama 或 LM Studio')
        request={'kind':'download','runtime':runtime,'endpoint':slots.endpoint(b.get('endpoint',''))}
        if b.get('source')=='huggingface':
            detail=hf_detail(b.get('repo'));filename=b.get('filename');f=next((f for f in detail['files'] if f['name']==filename),None);slots.check(f,'請先選擇公開模型庫中的單檔 GGUF')
            slots.check(not f['size'] or shutil.disk_usage(DB_PATH.parent).free>f['size']+1024**3,'主機磁碟空間不足')
            request.update(repo=detail['id'],revision=detail['revision'],filename=filename,license=detail['license'],size=f['size'])
            if runtime=='ollama':request['model']=safe_model('hf.co/'+detail['id']+':'+filename)
            else:request['model']=detail['url']+'/blob/main/'+filename
        else:
            slots.check(b.get('source')=='ollama' and runtime=='ollama','此來源與下載引擎不相容')
            model=safe_model(b.get('model'));slots.check(re.fullmatch(r'(?:[A-Za-z0-9_-]+/)?[A-Za-z0-9_.-]+(?::[A-Za-z0-9_.-]+)?',model),'只接受 Ollama Library 名稱；Hugging Face 請使用公開模型查詢流程');request['model']=model
        with db() as c:return handler.send(queue_job(c,u,request))
    if path=='/api/admin/models/upload/start' and write:
        name=b.get('filename','');size=b.get('size')
        slots.check(isinstance(name,str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',name) and '..' not in name and (name.lower().endswith(('.gguf','.safetensors')) or name=='adapter_config.json'),'請選擇 GGUF、Safetensors 或 adapter_config.json；檔名只用英數、底線與連字號')
        slots.check(type(size) is int and 1<=size<=MAX_BYTES and (name!='adapter_config.json' or size<=65536),'模型大小超過限制')
        with LOCK,db() as c:
            reserved=c.execute("SELECT COALESCE(SUM(size-received),0) FROM model_uploads WHERE status='uploading'").fetchone()[0]
            slots.check(shutil.disk_usage(DB_PATH.parent).free>size+reserved+1024**3,'主機磁碟空間不足，請先釋出空間')
            iid=uid();c.execute('INSERT INTO model_uploads(id,owner_id,name,size,status,created_at) VALUES(?,?,?,?,?,?)',(iid,u['id'],name,size,'uploading',time.time()));audit(c,u['id'],'model_upload_started',iid)
        return handler.send({'id':iid,'chunk_size':CHUNK})
    if path=='/api/admin/models/upload/chunk' and write:
        try:data=base64.b64decode(b.get('data',''),validate=True)
        except Exception:raise slots.SlotError('上傳區塊編碼不合法')
        slots.check(0<len(data)<=CHUNK and type(b.get('offset')) is int,'上傳區塊大小或位置不合法')
        with LOCK,db() as c:
            c.execute('BEGIN IMMEDIATE');r=c.execute('SELECT * FROM model_uploads WHERE id=? AND owner_id=?',(b.get('id'),u['id'])).fetchone()
            slots.check(r and r['status']=='uploading','此上傳不存在或已完成')
            offset=b['offset']
            if offset<r['received']:
                old=c.execute('SELECT data FROM model_upload_chunks WHERE upload_id=? AND offset=?',(r['id'],offset)).fetchone();slots.check(old and bytes(old['data'])==data,'重試區塊與先前資料不同');return handler.send({'received':offset+len(data)})
            slots.check(offset==r['received'] and offset+len(data)<=r['size'],'上傳位置不連續或超出檔案大小')
            c.execute('INSERT INTO model_upload_chunks VALUES(?,?,?)',(r['id'],offset,data));c.execute('UPDATE model_uploads SET received=received+? WHERE id=?',(len(data),r['id']))
        return handler.send({'received':offset+len(data)})
    if path=='/api/admin/models/upload/finish' and write:
        with LOCK:
            with db() as c:r=c.execute('SELECT * FROM model_uploads WHERE id=? AND owner_id=?',(b.get('id'),u['id'])).fetchone()
            if r and r['status']=='stored':return handler.send({'ok':True,'sha256':r['sha256'],'status':'stored'})
            slots.check(r and r['status']=='uploading' and r['received']==r['size'],'權重尚未完整上傳')
            digest=hashlib.sha256();prefix=b''
            for chunk in upload_chunks(r['id']):
                if not prefix:prefix=chunk
                digest.update(chunk)
            try:validate_weight(r['name'],r['size'],prefix)
            except (ValueError,TypeError,struct.error):raise slots.SlotError('權重格式驗證失敗，不能匯入')
            with db() as c:c.execute("UPDATE model_uploads SET status='stored',sha256=? WHERE id=?",(digest.hexdigest(),r['id']));audit(c,u['id'],'model_upload_verified',r['id'])
        return handler.send({'ok':True,'sha256':digest.hexdigest(),'status':'stored'})
    if path=='/api/admin/models/import' and write:
        with db() as c:
            r=c.execute("SELECT * FROM model_uploads WHERE id=? AND status='stored'",(b.get('upload_id'),)).fetchone()
            slots.check(r and r['name'].lower().endswith('.gguf'),'自動匯入僅支援完整 GGUF；Safetensors 與設定保留供相容的本機載入器使用')
            kind=b.get('source_kind','base');slots.check(kind=='base','新版 Ollama 不再支援直接掛載 LoRA；請使用合併後的完整 GGUF，或另接相容的本機載入器')
            request={'kind':'import','runtime':'ollama','endpoint':slots.endpoint(b.get('endpoint','')),'upload_id':r['id'],'model':safe_model(b.get('model')),'source_kind':kind}
            slots.check(request['model'] not in slots.available({'provider':'ollama','endpoint':request['endpoint']}),'此模型名稱已存在，請使用新名稱避免覆蓋')
            return handler.send(queue_job(c,u,request))
    raise slots.SlotError('找不到模型管理操作')
