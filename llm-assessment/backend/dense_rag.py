"""Small local Dense RAG: source offsets + normalized embeddings in SQLite."""
import hashlib,math,os,re,struct,threading,time
from storage import db,encode,decode
import model_slots

MODEL=os.environ.get('ASSESSMENT_EMBED_MODEL','embeddinggemma')
STOP=threading.Event();INDEX_LOCK=threading.Lock()
SIZE=800;OVERLAP=120
class RagError(ValueError):pass

def initialize(c):
    c.executescript('''CREATE TABLE IF NOT EXISTS rag_documents(material_id TEXT PRIMARY KEY REFERENCES exam_materials(id),text_hash TEXT NOT NULL,status TEXT NOT NULL,model TEXT NOT NULL,digest TEXT,dimensions INTEGER,chunk_count INTEGER NOT NULL DEFAULT 0,completed INTEGER NOT NULL DEFAULT 0,error TEXT,updated_at REAL NOT NULL);
    CREATE TABLE IF NOT EXISTS rag_chunks(id TEXT PRIMARY KEY,material_id TEXT NOT NULL REFERENCES exam_materials(id),start INTEGER NOT NULL,end INTEGER NOT NULL,text TEXT NOT NULL,locator TEXT NOT NULL,vector BLOB NOT NULL);
    CREATE INDEX IF NOT EXISTS rag_by_material ON rag_chunks(material_id);''')
    for row in c.execute('SELECT id,text FROM exam_materials WHERE archived=0').fetchall():enqueue(c,row['id'],row['text'])

def text_hash(text):return hashlib.sha256(text.encode()).hexdigest()

def enqueue(c,mid,text,force=False):
    old=c.execute('SELECT * FROM rag_documents WHERE material_id=?',(mid,)).fetchone();digest=text_hash(text)
    if old and old['text_hash']==digest and old['model']==MODEL and not force:return
    c.execute("INSERT INTO rag_documents(material_id,text_hash,status,model,updated_at) VALUES(?,?,'queued',?,?) ON CONFLICT(material_id) DO UPDATE SET text_hash=excluded.text_hash,status='queued',model=excluded.model,completed=0,error=NULL,updated_at=excluded.updated_at",(mid,digest,MODEL,time.time()))

def split(material):
    text=material['text'];result=[];start=0
    while start<len(text):
        end=min(len(text),start+SIZE)
        # Prefer a paragraph/sentence boundary while retaining exact source slices.
        if end<len(text):
            cut=max(text.rfind('\n',start+SIZE//2,end),text.rfind('。',start+SIZE//2,end),text.rfind('. ',start+SIZE//2,end))
            if cut>=start+SIZE//2:end=cut+1
        if text[start:end].strip():
            pages=re.findall(r'\[(?:章節 )?PDF 第 (\d+) 頁\]',text[:end])
            prior=re.findall(r'\[(?:章節 )?PDF 第 (\d+) 頁\]',text[:start])
            page=(f" · PDF 頁 {prior[-1] if prior else pages[0]}–{pages[-1]}" if pages else '')
            key='R'+hashlib.sha256((material['id']+':'+str(start)+':'+text_hash(text)).encode()).hexdigest()[:20]
            result.append({'source_ref':key,'source_unit_id':material['id'],'start':start,'end':end,'text':text[start:end],'locator':material['locator']+page+f' · 文字 {start+1}–{end}'})
        if end==len(text):break
        start=max(start+1,end-OVERLAP)
    return result

def identity():
    if 'cloud' in MODEL.lower():raise RagError('RAG 只接受本機 embedding 模型')
    for model in model_slots.request(model_slots.endpoint(model_slots.DEFAULT_URL).removesuffix('/v1')+'/api/tags').get('models',[]):
        if model['name'] in (MODEL,MODEL+':latest'):
            if model.get('remote_host') or model.get('remote_model'):raise RagError('不能使用遠端 embedding 模型')
            return model.get('digest',MODEL)
    raise RagError('本機 embedding 模型未安裝：請先執行 ollama pull '+MODEL)

def normalize(vector):
    if not isinstance(vector,list) or not vector or not all(type(v) in (int,float) and math.isfinite(v) for v in vector):raise RagError('向量格式不合法')
    norm=math.sqrt(sum(v*v for v in vector))
    if norm<=0:raise RagError('模型回傳零向量')
    return [v/norm for v in vector]

def embed(texts,query=False):
    import analysis
    inputs=[('task: search result | query: '+text if query else 'title: 教材 | text: '+text) for text in texts]
    # CPU embeddings avoid competing with the host's larger GPU inference models.
    with analysis.MODEL_LOCK:
        raw=model_slots.request(model_slots.endpoint(model_slots.DEFAULT_URL).removesuffix('/v1')+'/api/embed',{'model':MODEL,'input':inputs,'truncate':False,'keep_alive':'1m','options':{'num_gpu':0}},timeout=120)
    vectors=raw.get('embeddings',[])
    if len(vectors)!=len(texts):raise RagError('回傳向量數量與教材段落不符')
    result=[normalize(v) for v in vectors]
    if len({len(v) for v in result})!=1:raise RagError('向量維度不一致')
    return result

def index_material(mid):
    with INDEX_LOCK:
        with db() as c:
            row=c.execute('SELECT * FROM exam_materials WHERE id=? AND archived=0',(mid,)).fetchone()
            if not row:raise RagError('教材不存在或已封存')
            material=dict(row);enqueue(c,mid,material['text']);status=dict(c.execute('SELECT * FROM rag_documents WHERE material_id=?',(mid,)).fetchone())
        try:
            digest=identity()
            if status['status']=='ready' and status['digest']==digest:return
            parts=split(material)
            with db() as c:c.execute("UPDATE rag_documents SET status='running',completed=0,chunk_count=?,error=NULL,updated_at=? WHERE material_id=?",(len(parts),time.time(),mid))
            vectors=[]
            for offset in range(0,len(parts),8):
                vectors.extend(embed([p['text'] for p in parts[offset:offset+8]]))
                with db() as c:c.execute('UPDATE rag_documents SET completed=?,updated_at=? WHERE material_id=?',(len(vectors),time.time(),mid))
            if not vectors or len({len(v) for v in vectors})!=1:raise RagError('教材向量為空或維度不一致')
            with db() as c:
                current=c.execute('SELECT text,archived FROM exam_materials WHERE id=?',(mid,)).fetchone()
                if not current or current['archived'] or text_hash(current['text'])!=text_hash(material['text']):raise RagError('教材已改變，請重新建置')
                c.execute('DELETE FROM rag_chunks WHERE material_id=?',(mid,))
                for p,v in zip(parts,vectors):c.execute('INSERT INTO rag_chunks VALUES(?,?,?,?,?,?,?)',(p['source_ref'],mid,p['start'],p['end'],p['text'],p['locator'],struct.pack('<'+'f'*len(v),*v)))
                c.execute("UPDATE rag_documents SET status='ready',digest=?,dimensions=?,completed=?,updated_at=? WHERE material_id=?",(digest,len(vectors[0]),len(parts),time.time(),mid))
        except Exception as exc:
            with db() as c:c.execute("UPDATE rag_documents SET status='failed',error=?,updated_at=? WHERE material_id=?",(str(exc)[:400],time.time(),mid))
            raise RagError('教材向量建置失敗：'+str(exc)[:300]) from exc

def retrieve(materials,query,k=12,coverage=True):
    if not materials:raise RagError('請選擇教材')
    for material in materials:index_material(material['id'])
    query_vector=embed([query[:800]],query=True)[0];ranked=[]
    with db() as c:
        for material in materials:
            status=c.execute('SELECT * FROM rag_documents WHERE material_id=?',(material['id'],)).fetchone()
            if status['text_hash']!=text_hash(material['text']):raise RagError('教材快照與目前索引不同，請重新組卷')
            if status['dimensions']!=len(query_vector):raise RagError('檢索向量維度不同，請重建索引')
            for row in c.execute('SELECT * FROM rag_chunks WHERE material_id=?',(material['id'],)):
                vector=struct.unpack('<'+'f'*len(query_vector),row['vector']);score=sum(a*b for a,b in zip(query_vector,vector))
                ranked.append({'source_ref':row['id'],'source_unit_id':row['material_id'],'text':row['text'],'locator':row['locator'],'start':row['start'],'end':row['end'],'score':round(score,6)})
    ranked.sort(key=lambda item:(-item['score'],item['source_ref']))
    # Include at least one source from every selected unit, then fill by similarity.
    selected=[]
    if coverage:
        for material in materials:selected.append(next(r for r in ranked if r['source_unit_id']==material['id']))
    for row in ranked:
        if len(selected)>=(max(k,len(materials)) if coverage else k):break
        if row not in selected:selected.append(row)
    return sorted(selected,key=lambda item:-item['score'])

def worker():
    with db() as c:c.execute("UPDATE rag_documents SET status='queued' WHERE status='running'")
    while not STOP.is_set():
        with db() as c:row=c.execute("SELECT r.material_id FROM rag_documents r JOIN exam_materials m ON m.id=r.material_id WHERE r.status='queued' AND m.archived=0 ORDER BY r.updated_at LIMIT 1").fetchone()
        if row:
            try:index_material(row['material_id'])
            except Exception:pass  # Failure persisted; teacher can explicitly retry.
        else:STOP.wait(1)
