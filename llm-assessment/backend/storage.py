"""Database migrations and immutable question snapshots."""
import contextlib
import hashlib
import json
import os
import sqlite3
import uuid
from pathlib import Path

BASE = Path(__file__).resolve().parent
DB_PATH = Path(os.environ.get('ASSESSMENT_DB', str(BASE/'assessment.sqlite3')))

def uid(): return str(uuid.uuid4())
def encode(v): return json.dumps(v, ensure_ascii=False, separators=(',', ':'))
def decode(v): return json.loads(v)

@contextlib.contextmanager
def db():
    c=sqlite3.connect(DB_PATH, timeout=15)
    c.row_factory=sqlite3.Row
    c.execute('PRAGMA foreign_keys=ON')
    try:
        yield c
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally: c.close()

def initialize():
    if not DB_PATH.exists():
        raise RuntimeError('先執行 build_draft_bank.py 建立題庫。')
    with db() as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.executescript('''
        CREATE TABLE IF NOT EXISTS app_meta(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS sessions(token_hash TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES users(id),csrf TEXT NOT NULL,expires REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS login_limits(key TEXT PRIMARY KEY,failures INTEGER NOT NULL,updated REAL NOT NULL);
        CREATE TABLE IF NOT EXISTS audit_events(id TEXT PRIMARY KEY,actor_id TEXT,event TEXT NOT NULL,entity TEXT NOT NULL,detail_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS practice_runs(id TEXT PRIMARY KEY,learner_id TEXT REFERENCES learners(id),question_version_id TEXT REFERENCES question_versions(id),code_hash TEXT NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS manual_adjustments(id TEXT PRIMARY KEY,submission_id TEXT NOT NULL REFERENCES submissions(id),reviewer_id TEXT NOT NULL REFERENCES users(id),revision INTEGER NOT NULL,result_json TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE IF NOT EXISTS assignment_snapshots(assignment_id TEXT NOT NULL REFERENCES assignments(id),position INTEGER NOT NULL,question_json TEXT NOT NULL,PRIMARY KEY(assignment_id,position));
        ''')
        extras={
         'users':[('email',"TEXT"),('disabled','INTEGER NOT NULL DEFAULT 0'),('ui_locale','TEXT'),('ui_sounds','INTEGER'),('ui_volume','INTEGER')],
         'assignments':[('title',"TEXT NOT NULL DEFAULT ''"),('created_at','TEXT'),('due_at','TEXT')],
         'submissions':[('created_at','TEXT'),('submitted_at','TEXT')],
         'analysis_jobs':[('created_at','REAL'),('started_at','REAL'),('error','TEXT'),('retries','INTEGER NOT NULL DEFAULT 0')],
         'responses':[('updated_at','TEXT')],
         'manual_adjustments':[('attempt_id','TEXT REFERENCES attempts(id)')],
        }
        for table,cols in extras.items():
            existing={r['name'] for r in c.execute(f'PRAGMA table_info({table})')}
            for name,definition in cols:
                if name not in existing: c.execute(f'ALTER TABLE {table} ADD COLUMN {name} {definition}')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS users_email ON users(email)')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_submission ON submissions(assignment_id,learner_id)')
        c.execute('CREATE UNIQUE INDEX IF NOT EXISTS one_response ON responses(attempt_id,question_version_id)')
        c.execute("INSERT OR IGNORE INTO app_meta VALUES('schema_version','2')")
        from collab import initialize as initialize_canvas
        initialize_canvas(c)
        from model_slots import initialize as initialize_slots
        from exam_studio import initialize as initialize_exams
        initialize_slots(c)
        initialize_exams(c)
        from dense_rag import initialize as initialize_rag
        initialize_rag(c)
        from model_library import initialize as initialize_model_library
        initialize_model_library(c)

def audit(c, actor, event, entity, detail=None):
    c.execute('INSERT INTO audit_events(id,actor_id,event,entity,detail_json) VALUES(?,?,?,?,?)',(uid(),actor,event,entity,encode(detail or {})))

def question(row, private=False):
    q=dict(row)
    for key in ['payload','answer','rubric','analysis_metadata','runtime','tests']:
        field=key+'_json'
        if field in q: q[key]=decode(q.pop(field))
    if not private:
        for key in ['answer','rubric','analysis_metadata','reviewed_by','reviewed_at']:
            q.pop(key,None)
        tests=q.get('tests',{})
        q['tests']={key:val for key,val in tests.items() if key!='hidden'}
        if q.get('kind')=='ai_collab_canvas':q['payload'].pop('independent_prompt',None)
    return q

def latest_questions(c):
    return c.execute('SELECT v.*,q.skill_id FROM question_versions v JOIN questions q ON q.id=v.question_id WHERE v.version=(SELECT MAX(v2.version) FROM question_versions v2 WHERE v2.question_id=v.question_id) ORDER BY v.question_id').fetchall()

def hash_input(value): return hashlib.sha256(encode(value).encode()).hexdigest()
