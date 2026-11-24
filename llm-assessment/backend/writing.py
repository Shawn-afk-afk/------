"""Writing rooms, durable collaborative text, and local tutoring."""
import base64
import binascii
import re
import threading
import time

import analysis
import model_slots
from storage import db, decode, encode, uid
from writing_prompt import GLOBAL_PROMPT

STOP = threading.Event()
MAX_TEXT = 100_000
MAX_STATE_BYTES = 750_000
OBSERVE_DELAY = 9
OBSERVE_GAP = 75
SPEAK_GAP = 180
MAX_REFERENCES = 5
MAX_EXCERPT = 3000
POLICIES = {"off", "called", "active"}
EXAMPLE_ACTION = r"(?:示範|代擬|續寫|接寫|改寫|幫我寫|寫一[句段]|給我一[句段]|接下一[句段]|接下去|舉例)"


class WritingError(Exception):
    def __init__(self, status, message):
        self.status = status
        self.message = message


def require(condition, message, status=400):
    if not condition:
        raise WritingError(status, message)


def initialize(c):
    c.executescript("""
    CREATE TABLE IF NOT EXISTS writing_rooms(
        id TEXT PRIMARY KEY, owner_id TEXT NOT NULL REFERENCES users(id),
        title TEXT NOT NULL, mode TEXT NOT NULL, prompt TEXT NOT NULL,
        target INTEGER NOT NULL, suggestion_limit INTEGER NOT NULL, policy TEXT NOT NULL,
        activity REAL NOT NULL DEFAULT 0, checked_activity REAL NOT NULL DEFAULT 0,
        checked_at REAL NOT NULL DEFAULT 0, spoken_at REAL NOT NULL DEFAULT 0,
        paused_until REAL NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS writing_members(
        room_id TEXT NOT NULL REFERENCES writing_rooms(id),
        user_id TEXT NOT NULL REFERENCES users(id), PRIMARY KEY(room_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS writing_references(
        room_id TEXT NOT NULL REFERENCES writing_rooms(id),
        material_id TEXT NOT NULL, title TEXT NOT NULL, subject TEXT NOT NULL,
        locator TEXT NOT NULL, excerpt TEXT NOT NULL,
        PRIMARY KEY(room_id,material_id)
    );
    CREATE TABLE IF NOT EXISTS writing_docs(
        id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES writing_rooms(id),
        title TEXT NOT NULL, version INTEGER NOT NULL DEFAULT 0,
        state BLOB NOT NULL DEFAULT X'0000', body TEXT NOT NULL DEFAULT '', edited_at REAL NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS writing_docs_room ON writing_docs(room_id);
    CREATE TABLE IF NOT EXISTS writing_presence(
        room_id TEXT NOT NULL REFERENCES writing_rooms(id),
        user_id TEXT NOT NULL REFERENCES users(id), doc_id TEXT NOT NULL REFERENCES writing_docs(id),
        active_at REAL NOT NULL, cursor TEXT NOT NULL DEFAULT '', PRIMARY KEY(room_id,user_id)
    );
    CREATE TABLE IF NOT EXISTS writing_messages(
        seq INTEGER PRIMARY KEY, room_id TEXT NOT NULL REFERENCES writing_rooms(id),
        user_id TEXT REFERENCES users(id), kind TEXT NOT NULL, body TEXT NOT NULL,
        doc_id TEXT REFERENCES writing_docs(id), quote TEXT NOT NULL DEFAULT '',
        example TEXT NOT NULL DEFAULT '', created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS writing_messages_room ON writing_messages(room_id,seq);
    CREATE TABLE IF NOT EXISTS writing_versions(
        id TEXT PRIMARY KEY, doc_id TEXT NOT NULL REFERENCES writing_docs(id),
        user_id TEXT NOT NULL REFERENCES users(id), label TEXT NOT NULL,
        body TEXT NOT NULL, created_at REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS writing_versions_doc ON writing_versions(doc_id,created_at);
    CREATE TABLE IF NOT EXISTS writing_jobs(
        id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES writing_rooms(id),
        message_seq INTEGER NOT NULL UNIQUE REFERENCES writing_messages(seq),
        status TEXT NOT NULL DEFAULT 'queued', created_at REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS writing_submissions(
        id TEXT PRIMARY KEY, room_id TEXT NOT NULL REFERENCES writing_rooms(id),
        student_id TEXT NOT NULL REFERENCES users(id), revision INTEGER NOT NULL,
        snapshot TEXT NOT NULL, submitted_at REAL NOT NULL, reopened_at REAL,
        score INTEGER, feedback TEXT, reviewed_at REAL,
        UNIQUE(room_id,revision)
    );
    """)
    if "cursor" not in {row["name"] for row in c.execute("PRAGMA table_info(writing_presence)")}:
        c.execute("ALTER TABLE writing_presence ADD COLUMN cursor TEXT NOT NULL DEFAULT ''")
    if "edited_at" not in {row["name"] for row in c.execute("PRAGMA table_info(writing_docs)")}:
        c.execute("ALTER TABLE writing_docs ADD COLUMN edited_at REAL NOT NULL DEFAULT 0")
    room_columns = {row["name"] for row in c.execute("PRAGMA table_info(writing_rooms)")}
    if "assignment_id" not in room_columns:
        c.execute("ALTER TABLE writing_rooms ADD COLUMN assignment_id TEXT REFERENCES writing_rooms(id)")
    if "distribution" not in room_columns:
        c.execute("ALTER TABLE writing_rooms ADD COLUMN distribution TEXT NOT NULL DEFAULT 'group'")
    c.execute("CREATE INDEX IF NOT EXISTS writing_assignment_rooms ON writing_rooms(assignment_id)")


def field(value, limit, name, optional=False):
    require(isinstance(value, str), f"{name}需為文字")
    value = value.strip()
    require(len(value) <= limit and (value or optional), f"{name}需為 {'0' if optional else '1'}–{limit} 字")
    return value


def room_options(body, has_references=False):
    mode, policy = body.get("mode"), body.get("policy")
    target, limit = body.get("target", 0), body.get("suggestion_limit", 120)
    require(isinstance(mode, str) and mode in {"free", "themed", "paragraph"}, "選擇寫作方式")
    require(isinstance(policy, str) and policy in POLICIES, "選擇助教設定")
    require(type(target) is int and 0 <= target <= MAX_TEXT, "目標字數需為 0–100000")
    require(type(limit) is int and 0 <= limit <= 1000, "生成字數上限需為 0–1000")
    prompt = field(body.get("prompt", ""), 6000, "題目與要求", optional=True)
    require(mode == "free" or prompt or has_references, "請填題目與要求，或選用教材範圍")
    return (
        field(body.get("title"), 100, "作品名稱"), mode, prompt,
        target, limit, policy,
    )


def room_references(c, room_id):
    return [dict(row) for row in c.execute("""
        SELECT material_id,title,subject,locator,excerpt FROM writing_references
        WHERE room_id=? ORDER BY rowid
    """, (room_id,))]


def library_material(c, material_id):
    require(isinstance(material_id, str) and 1 <= len(material_id) <= 180, "請選擇教材")
    material = c.execute("""
        SELECT id,title,subject,locator,text FROM exam_materials WHERE id=? AND archived=0
    """, (material_id,)).fetchone()
    require(material, "教材找不到或已封存", 404)
    return dict(material)


def select_references(c, room_id, body, user):
    existing = {row["material_id"]: row for row in room_references(c, room_id)}
    if "references" not in body:
        return list(existing.values())
    require(user["role"] == "admin", "由教師設定教材範圍", 403)
    requested = body["references"]
    require(isinstance(requested, list) and len(requested) <= MAX_REFERENCES, "最多選用五份教材")
    references = {}
    for item in requested:
        require(isinstance(item, dict), "教材格式不正確")
        material_id = field(item.get("material_id"), 180, "教材識別碼")
        excerpt = field(item.get("excerpt"), MAX_EXCERPT, "教材片段").replace("\r\n", "\n")
        require(material_id not in references, "每份教材請選擇一段範圍")
        saved = existing.get(material_id)
        if saved and saved["excerpt"] == excerpt:
            references[material_id] = saved
            continue
        material = library_material(c, material_id)
        require(excerpt in material["text"].replace("\r\n", "\n"), "所選範圍需與教材原文相符")
        references[material_id] = {
            "material_id": material_id, "title": material["title"], "subject": material["subject"],
            "locator": material["locator"], "excerpt": excerpt,
        }
    return list(references.values())


def save_references(c, room_id, references):
    c.execute("DELETE FROM writing_references WHERE room_id=?", (room_id,))
    c.executemany("""
        INSERT INTO writing_references(room_id,material_id,title,subject,locator,excerpt)
        VALUES(?,?,?,?,?,?)
    """, [
        (room_id, ref["material_id"], ref["title"], ref["subject"], ref["locator"], ref["excerpt"])
        for ref in references
    ])


def writing_settings(c, room_id, body, user, current=None):
    references = select_references(c, room_id, body, user)
    if user["role"] != "admin":
        baseline = current or {"mode": "free", "prompt": "", "target": 0, "suggestion_limit": 120}
        for key in ("mode", "prompt", "target", "suggestion_limit"):
            require(key not in body or body[key] == baseline[key], "由教師設定寫作題目與要求", 403)
        body = {**body, **{key: baseline[key] for key in ("mode", "prompt", "target", "suggestion_limit")}}
    return room_options(body, bool(references)), references


def create_room(c, owner_id, options, references, students=(), assignment_id=None, distribution="group"):
    room_id = uid()
    c.execute("""
        INSERT INTO writing_rooms(id,owner_id,title,mode,prompt,target,suggestion_limit,policy,assignment_id,distribution)
        VALUES(?,?,?,?,?,?,?,?,?,?)
    """, (room_id, owner_id, *options, assignment_id, distribution))
    c.executemany("INSERT INTO writing_members VALUES(?,?)", [(room_id, member) for member in (owner_id, *students)])
    title = "段落作答" if options[1] == "paragraph" else "初稿"
    c.execute("INSERT INTO writing_docs(id,room_id,title) VALUES(?,?,?)", (uid(), room_id, title))
    save_references(c, room_id, references)
    return room_id


def assigned_students(c, owner, room_id, student_ids):
    require(isinstance(student_ids, list) and 1 <= len(student_ids) <= 150
            and all(isinstance(student_id, str) for student_id in student_ids), "請選擇至少一位學生")
    student_ids = list(dict.fromkeys(student_ids))
    for student_id in student_ids:
        require(c.execute("SELECT 1 FROM users WHERE id=? AND role='learner' AND disabled=0",
                          (student_id,)).fetchone(), "所選學生已停用或不存在", 404)
    room = c.execute("SELECT * FROM writing_rooms WHERE id=? AND owner_id=? AND assignment_id IS NULL",
                     (room_id, owner)).fetchone()
    require(room, "找不到寫作題目", 404)
    if room["distribution"] == "group":
        c.executemany("INSERT OR IGNORE INTO writing_members VALUES(?,?)", [(room_id, student_id) for student_id in student_ids])
        return
    existing = {r[0] for r in c.execute("""
        SELECT m.user_id FROM writing_rooms r JOIN writing_members m ON m.room_id=r.id
        WHERE r.assignment_id=? AND m.user_id!=r.owner_id
    """, (room_id,))}
    options = tuple(room[key] for key in ("title", "mode", "prompt", "target", "suggestion_limit", "policy"))
    refs = room_references(c, room_id)
    for student_id in student_ids:
        if student_id not in existing:
            create_room(c, owner, options, refs, (student_id,), room_id, "individual")


def teacher_workspace(c, user, body, args, write):
    require(user["role"] == "admin", "寫作出題僅供教師使用", 403)
    owner = user["id"]
    room_id = body.get("room") if write else args.get("room", [""])[0]
    if write:
        c.execute("BEGIN IMMEDIATE")
        if not room_id:
            distribution = body.get("distribution", "individual")
            require(distribution in ("individual", "group"), "請選擇作答方式")
            options, refs = writing_settings(c, "", body, user)
            room_id = create_room(c, owner, options, refs, distribution=distribution)
        assigned_students(c, owner, room_id, body.get("students"))
        return {"id": room_id}
    if not room_id:
        rows = c.execute("""
            SELECT r.id,r.title,r.mode,r.distribution,
                (SELECT count(DISTINCT m.user_id) FROM writing_members m
                 JOIN writing_rooms a ON a.id=m.room_id
                 WHERE m.user_id!=r.owner_id AND (a.id=r.id OR a.assignment_id=r.id)) AS student_count
            FROM writing_rooms r WHERE r.owner_id=? AND r.assignment_id IS NULL ORDER BY r.rowid DESC
        """, (owner,))
        return {"assignments": [dict(row) for row in rows]}
    room = c.execute("SELECT * FROM writing_rooms WHERE id=? AND owner_id=? AND assignment_id IS NULL",
                     (room_id, owner)).fetchone()
    require(room, "找不到寫作題目", 404)
    roster = c.execute("""
        SELECT u.id AS student_id,u.display_name,u.email,a.id AS room_id
        FROM writing_members m JOIN users u ON u.id=m.user_id JOIN writing_rooms a ON a.id=m.room_id
        WHERE m.user_id!=a.owner_id AND (a.id=? OR a.assignment_id=?)
        ORDER BY u.display_name,u.email
    """, (room_id, room_id))
    return {
        "assignment": {key: room[key] for key in ("id", "title", "mode", "prompt", "target", "suggestion_limit", "policy", "distribution")},
        "references": room_references(c, room_id),
        "students": [dict(row) for row in roster],
        "submissions": [dict(row) for row in c.execute("""
            SELECT s.id,s.room_id,s.revision,s.submitted_at,s.reopened_at,s.reviewed_at,s.score,
                   u.display_name
            FROM writing_submissions s JOIN writing_rooms r ON s.room_id=r.id
            JOIN users u ON u.id=s.student_id
            WHERE r.id=? OR r.assignment_id=?
            ORDER BY s.submitted_at DESC
        """, (room_id, room_id))],
    }


def access(c, room_id, user):
    room = c.execute("""
        SELECT r.* FROM writing_rooms r JOIN writing_members m ON m.room_id=r.id
        WHERE r.id=? AND m.user_id=?
    """, (room_id, user["id"])).fetchone()
    require(room, "找不到作品或尚未受邀", 404)
    return room


def latest_submission(c, room_id):
    return c.execute("""
        SELECT id,revision,submitted_at,reopened_at,score,feedback,reviewed_at
        FROM writing_submissions WHERE room_id=? ORDER BY revision DESC LIMIT 1
    """, (room_id,)).fetchone()


def require_editable(c, room_id):
    submission = latest_submission(c, room_id)
    require(not submission or submission["reopened_at"] is not None,
            "作品已繳交，請等老師開放修訂", 409)


def submit_assignment(c, room, user, body):
    require(user["role"] == "learner" and user["id"] != room["owner_id"], "此作品無須繳交", 403)
    prior = latest_submission(c, room["id"])
    if prior and prior["reopened_at"] is None:
        return {"submission": dict(prior)}
    doc = document(c, room["id"], body.get("doc"))
    require(body.get("version") == doc["version"], "稿件有新修改，請同步後再繳交", 409)
    drafts = [dict(row) for row in c.execute("""
        SELECT title,body FROM writing_docs WHERE room_id=? ORDER BY rowid
    """, (room["id"],))]
    require(any(draft["body"].strip() for draft in drafts), "請先寫入正文再繳交")
    snapshot = {
        "title": room["title"], "prompt": room["prompt"], "mode": room["mode"],
        "target": room["target"], "drafts": drafts, "references": room_references(c, room["id"]),
    }
    c.execute("""
        INSERT INTO writing_submissions(id,room_id,student_id,revision,snapshot,submitted_at)
        VALUES(?,?,?,?,?,?)
    """, (uid(), room["id"], user["id"], prior["revision"] + 1 if prior else 1, encode(snapshot), time.time()))
    return {"submission": dict(latest_submission(c, room["id"]))}


def owned_submission(c, user, submission_id):
    require(user["role"] == "admin", "寫作批改僅供教師使用", 403)
    row = c.execute("""
        SELECT s.*, u.display_name, r.distribution FROM writing_submissions s
        JOIN writing_rooms r ON r.id=s.room_id JOIN users u ON u.id=s.student_id
        WHERE s.id=? AND r.owner_id=?
    """, (submission_id, user["id"])).fetchone()
    require(row, "找不到繳交稿件", 404)
    return row


def review_assignment(user, body, args, write):
    submission_id = body.get("id") if write else args.get("id", [""])[0]
    with db() as c:
        if write:
            c.execute("BEGIN IMMEDIATE")
        row = owned_submission(c, user, submission_id)
        if not write:
            data = dict(row)
            data["snapshot"] = decode(data["snapshot"])
            return {"submission": data}
        require(row["reopened_at"] is None, "此版本已開放修訂", 409)
        if body.get("action") == "reopen":
            c.execute("UPDATE writing_submissions SET reopened_at=? WHERE id=?", (time.time(), row["id"]))
        else:
            score = body.get("score")
            require(type(score) is int and 0 <= score <= 100, "分數需為 0–100 的整數")
            feedback = field(body.get("feedback"), 5000, "批改回饋")
            c.execute("UPDATE writing_submissions SET score=?,feedback=?,reviewed_at=? WHERE id=?",
                      (score, feedback, time.time(), row["id"]))
    return {"ok": True}


def document(c, room_id, doc_id):
    doc = c.execute("SELECT * FROM writing_docs WHERE room_id=? AND id=?", (room_id, doc_id)).fetchone()
    require(doc, "找不到篇章", 404)
    return doc


def doc_payload(doc):
    return {
        "id": doc["id"], "title": doc["title"], "version": doc["version"],
        "state": base64.b64encode(doc["state"]).decode("ascii"),
    }


def get_ydoc(doc):
    try:
        from pycrdt import Doc, Text
    except ImportError as exc:
        raise WritingError(503, "寫作共編需安裝 requirements-writing.txt") from exc
    state = Doc()
    state.apply_update(doc["state"])
    return state, state.get("body", type=Text)


def update_document(c, room, doc, body, user):
    data = body.get("update")
    require(data is None or isinstance(data, str) and len(data) <= MAX_STATE_BYTES * 2, "同步內容過長")
    cursor = body.get("cursor", "")
    require(isinstance(cursor, str) and len(cursor) <= 120 and re.fullmatch(r"[A-Za-z0-9+/=]*", cursor),
            "游標格式不正確")
    now = time.time()
    if data:
        require_editable(c, room["id"])
        ydoc, text = get_ydoc(doc)
        try:
            update = base64.b64decode(data, validate=True)
            ydoc.apply_update(update)
        except (ValueError, RuntimeError, binascii.Error) as exc:
            raise WritingError(400, "同步內容格式不正確") from exc
        write_document(c, room["id"], doc, ydoc, str(text), now)
    c.execute("""
        INSERT INTO writing_presence(room_id,user_id,doc_id,active_at,cursor) VALUES(?,?,?,?,?)
        ON CONFLICT(room_id,user_id) DO UPDATE SET doc_id=excluded.doc_id,
            active_at=excluded.active_at,cursor=excluded.cursor
    """, (room["id"], user["id"], doc["id"], now, cursor))
    return doc_payload(document(c, room["id"], doc["id"]))


def write_document(c, room_id, doc, ydoc, text, now):
    state = ydoc.get_update()
    require(len(text) <= MAX_TEXT and len(state) <= MAX_STATE_BYTES, "篇章已達容量上限，請新增篇章", 413)
    if state != doc["state"]:
        c.execute("""
            UPDATE writing_docs SET state=?,body=?,version=version+1,edited_at=? WHERE id=?
        """, (state, text, now if text != doc["body"] else doc["edited_at"], doc["id"]))
        if text != doc["body"]:
            c.execute("UPDATE writing_rooms SET activity=? WHERE id=?", (now, room_id))


def messages(c, room_id, limit=120):
    return [dict(row) for row in c.execute("""
        SELECT seq, COALESCE(u.display_name,'寫作助教') author, w.user_id, w.kind,
               w.body,w.quote,w.example,w.doc_id,w.created_at,j.status AS tutor_status
        FROM writing_messages w LEFT JOIN users u ON u.id=w.user_id
        LEFT JOIN writing_jobs j ON j.message_seq=w.seq
        WHERE w.room_id=? ORDER BY seq DESC LIMIT ?
    """, (room_id, limit))][::-1]


def room_state(c, room, user, args):
    room_id = room["id"]
    docs = [dict(row) for row in c.execute("SELECT id,title,version FROM writing_docs WHERE room_id=? ORDER BY rowid", (room_id,))]
    people = [dict(row) for row in c.execute("""
        SELECT u.id,u.display_name,p.doc_id,p.cursor FROM writing_members m
        JOIN users u ON u.id=m.user_id AND u.disabled=0
        LEFT JOIN writing_presence p ON p.room_id=m.room_id AND p.user_id=m.user_id AND p.active_at>?
        WHERE m.room_id=? ORDER BY m.rowid
    """, (time.time()-20, room_id))]
    doc_id = args.get("doc", [""])[0]
    current = document(c, room_id, doc_id) if doc_id else None
    version = args.get("version", [""])[0]
    shared = doc_payload(current) if current and str(current["version"]) != version else None
    return_data = {name: room[name] for name in (
        "id", "title", "mode", "prompt", "target", "suggestion_limit", "policy", "paused_until"
    )}
    submission = latest_submission(c, room_id)
    return {
        "room": {**return_data, "owner": room["owner_id"] == user["id"], "references": room_references(c, room_id),
                 "can_submit": user["role"] == "learner" and user["id"] != room["owner_id"],
                 "distribution": room["distribution"]},
        "submission": dict(submission) if submission else None,
        "docs": docs, "shared": shared, "people": people, "messages": messages(c, room_id),
    }


def post_message(c, room, user, body):
    text = field(body.get("text"), 2000, "訊息")
    doc_id = body.get("doc")
    doc = document(c, room["id"], doc_id) if doc_id else None
    quote = field(body.get("quote", ""), 450, "引用", optional=True)
    require(not quote or doc, "引用需要指定篇章")
    now = time.time()
    cursor = c.execute("""
        INSERT INTO writing_messages(room_id,user_id,kind,body,doc_id,quote,created_at)
        VALUES(?,?,'human',?,?,?,?)
    """, (room["id"], user["id"], text, doc_id, quote, now))
    seq = cursor.lastrowid
    c.execute("UPDATE writing_rooms SET activity=? WHERE id=?", (now, room["id"]))
    queued = "@助教" in text and room["policy"] != "off"
    if queued:
        c.execute("""
            INSERT INTO writing_jobs(id,room_id,message_seq,created_at) VALUES(?,?,?,?)
        """, (uid(), room["id"], seq, now))
    return {"seq": seq, "queued": queued}


def snapshot(c, doc, user, label):
    version = uid()
    c.execute("INSERT INTO writing_versions VALUES(?,?,?,?,?,?)", (
        version, doc["id"], user["id"], label, doc["body"], time.time()
    ))
    return version


def version_action(c, room, doc, user, action, body, args):
    if action == "versions":
        return {"versions": [dict(row) for row in c.execute("""
            SELECT v.id,v.label,v.created_at,u.display_name FROM writing_versions v
            JOIN users u ON u.id=v.user_id WHERE doc_id=? ORDER BY v.rowid DESC LIMIT 80
        """, (doc["id"],))]}
    if action == "snapshot":
        return {"id": snapshot(c, doc, user, field(body.get("label"), 80, "版本名稱"))}
    version_id = args.get("id", [""])[0] if action == "version" else body.get("id")
    version = c.execute("SELECT * FROM writing_versions WHERE id=? AND doc_id=?", (version_id, doc["id"])).fetchone()
    require(version, "找不到這個版本", 404)
    if action == "version":
        return {"label": version["label"], "saved": version["body"], "current": doc["body"], "version": doc["version"]}
    require(room["owner_id"] == user["id"], "由作品主持人還原共同稿件", 403)
    require_editable(c, room["id"])
    require(body.get("version") == doc["version"], "篇章已有新修改，請重新比對", 409)
    if version["body"] != doc["body"]:
        snapshot(c, doc, user, "還原前的稿件")
        ydoc, text = get_ydoc(doc)
        with ydoc.transaction():
            text.clear()
            text += version["body"]
        write_document(c, room["id"], doc, ydoc, str(text), time.time())
    return doc_payload(document(c, room["id"], doc["id"]))


def room_action(c, room, user, action, body, args, write):
    room_id = room["id"]
    if action == "state" and not write:
        return room_state(c, room, user, args)
    if action in {"versions", "version", "snapshot", "restore", "sync"}:
        require(write == (action in {"snapshot", "restore", "sync"}), "不支援的方法", 405)
        doc = document(c, room_id, body.get("doc") if write else args.get("doc", [""])[0])
        if action == "sync":
            return update_document(c, room, doc, body, user)
        return version_action(c, room, doc, user, action, body, args)
    require(write, "不支援的方法", 405)
    if action == "submit":
        return submit_assignment(c, room, user, body)
    if action == "message":
        return post_message(c, room, user, body)
    if action == "pause":
        until = time.time() + 600
        c.execute("UPDATE writing_rooms SET paused_until=? WHERE id=?", (until, room_id))
        return {"paused_until": until}
    if action == "chapter":
        require_editable(c, room_id)
        doc_id = uid()
        c.execute("INSERT INTO writing_docs(id,room_id,title) VALUES(?,?,?)", (
            doc_id, room_id, field(body.get("title"), 100, "篇章名稱")
        ))
        return {"id": doc_id}
    require(room["owner_id"] == user["id"], "由作品主持人設定", 403)
    if action == "settings":
        options, references = writing_settings(c, room_id, body, user, room)
        copies = [room_id, *(child["id"] for child in c.execute(
            "SELECT id FROM writing_rooms WHERE assignment_id=?", (room_id,)
        ))]
        c.execute("""
            UPDATE writing_rooms SET title=?,mode=?,prompt=?,target=?,suggestion_limit=?,policy=?,
              paused_until=0,checked_activity=activity WHERE id=? OR assignment_id=?
        """, (*options, room_id, room_id))
        if "references" in body:
            for copy_id in copies:
                save_references(c, copy_id, references)
        if body["policy"] == "off":
            c.executemany("UPDATE writing_jobs SET status='cancelled' WHERE room_id=? AND status IN ('queued','running')",
                          [(copy_id,) for copy_id in copies])
        return {"ok": True}
    if action == "invite":
        require(user["role"] == "admin", "由教師邀請共同作者", 403)
        account = field(body.get("account"), 180, "帳號").lower()
        member = c.execute("SELECT id,display_name FROM users WHERE email=? AND disabled=0", (account,)).fetchone()
        require(member, "找不到可加入的帳號", 404)
        c.execute("INSERT OR IGNORE INTO writing_members VALUES(?,?)", (room_id, member["id"]))
        return {"name": member["display_name"]}
    raise WritingError(404, "找不到寫作操作")


def routes(path, body, args, user, write):
    if path == "/api/writing/review":
        return review_assignment(user, body, args, write)
    if path in {"/api/writing/generate-topic", "/api/writing/draft-review"}:
        require(write, "不支援的方法", 405)
        require(user["role"] == "admin", "這項功能僅供教師使用", 403)
        if path.endswith("/generate-topic"):
            return generate_topic(user, body)
        return draft_review(user, body)
    if path == "/api/writing/teacher":
        with db() as c:
            return teacher_workspace(c, user, body, args, write)
    if path == "/api/writing/material":
        require(not write, "不支援的方法", 405)
        require(user["role"] == "admin", "教材庫僅供教師使用", 403)
        with db() as c:
            return library_material(c, args.get("id", [""])[0])
    if path == "/api/writing/rooms":
        with db() as c:
            if not write:
                return {"rooms": [dict(row) for row in c.execute("""
                    SELECT r.id,r.title,r.mode,r.policy,r.owner_id= ? AS owner
                    FROM writing_rooms r JOIN writing_members m ON r.id=m.room_id
                    WHERE m.user_id=? ORDER BY r.rowid DESC
                """, (user["id"], user["id"]))]}
            options, references = writing_settings(c, "", body, user)
            room_id = create_room(c, user["id"], options, references)
            return {"id": room_id}
    match = re.fullmatch(r"/api/writing/rooms/([0-9a-f-]{36})(?:/([a-z]+))?", path)
    require(match, "找不到寫作操作", 404)
    room_id, action = match.groups()
    if action == "complete" and write:
        return complete(room_id, user, body)
    with db() as c:
        if write:
            c.execute("BEGIN IMMEDIATE")
        return room_action(c, access(c, room_id, user), user, action or "state", body, args, write)


def teacher_model(prompt, data):
    config = model_slots.writing_profile()
    require(config, "請先設定寫作助教的本機模型", 503)
    request = {
        "model": config["model"], "stream": False, "format": "json", "think": False,
        "options": {"temperature": 0.45, "num_predict": 1600},
        "messages": [{"role": "system", "content": prompt}, {"role": "user", "content": encode(data)}],
    }
    try:
        with analysis.MODEL_LOCK:
            result = decode(model_slots.chat(request, config)["message"]["content"])
    except Exception as exc:
        raise WritingError(503, "本機模型未就緒或沒有回傳可用內容") from exc
    require(isinstance(result, dict), "模型回傳格式錯誤，請重試", 502)
    return result


def generate_topic(user, body):
    instruction = field(body.get("instruction"), 5000, "出題提示詞")
    mode = body.get("mode")
    require(mode in ("themed", "paragraph"), "請選主題式或段落寫作")
    room_id = body.get("room") or ""
    with db() as c:
        if room_id:
            require(access(c, room_id, user)["owner_id"] == user["id"], "由出題教師產生題目", 403)
        refs = select_references(c, room_id, body, user)
    result = teacher_model(
        """用臺灣繁體中文為教師起草引導式寫作題。依教師要求和指定教材設計一個具體情境與可作答的任務。
        列出由構思到動筆、最後到自我檢查的短引導。引導應該是問題或提示，不直接提供可照抄的答案。
        段落寫作聚焦一個段落可達成的任務。主題式寫作可以給開放題。只根據提供的教材片段引用來源。
        回傳 JSON，欄位 title、situation、task 均為字串，steps、checks 均為 1–5 個字串的清單。""",
        {
            "mode": mode, "teacher_instruction": instruction, "target": body.get("target", 0),
            "materials": [{"title": ref["title"], "excerpt": ref["excerpt"][:1200]} for ref in refs],
        },
    )
    title = field(result.get("title"), 100, "生成題名")
    situation = field(result.get("situation"), 1000, "寫作情境")
    task = field(result.get("task"), 1500, "寫作任務")
    lines = [f"寫作情境\n{situation}", f"寫作任務\n{task}"]
    for key, heading in (("steps", "引導步驟"), ("checks", "自我檢查")):
        values = result.get(key)
        require(isinstance(values, list) and 1 <= len(values) <= 5, f"模型沒有提供可用的{heading}", 502)
        items = [field(value, 300, heading) for value in values]
        lines.append(heading + "\n" + "\n".join(f"{index}. {item}" for index, item in enumerate(items, 1)))
    return {"title": title, "prompt": "\n\n".join(lines)}


def draft_review(user, body):
    with db() as c:
        submitted = owned_submission(c, user, body.get("id"))
        require(submitted["reopened_at"] is None, "此版本已開放修訂", 409)
        snapshot = decode(submitted["snapshot"])
    text = "\n\n".join(f"{doc['title']}\n{doc['body']}" for doc in snapshot["drafts"])
    result = teacher_model(
        """你提供教師一份待覆核的寫作批改建議。依原題要求與實際稿件，討論內容切題、結構及語句表達。
        回饋要引用稿件中實際存在的短句，說明一項具體優點和一項可執行的修訂。只根據提供的稿件。
        回傳 JSON，score 為 0–100 整數，feedback 為臺灣繁體中文回饋。""",
        {
            "title": snapshot["title"], "prompt": snapshot["prompt"], "target": snapshot["target"],
            "materials": [{"title": ref["title"], "excerpt": ref["excerpt"][:850]} for ref in snapshot["references"]],
            "draft": text[:12000],
        },
    )
    score = result.get("score")
    require(type(score) is int and 0 <= score <= 100, "模型未提供可用分數", 502)
    return {"score": score, "feedback": field(result.get("feedback"), 5000, "模型回饋"), "partial": len(text) > 12000}


def assist(room, kind, context, limit, lock=True, job_id=None):
    config = model_slots.writing_profile()
    require(config, "請先在知序設定寫作助教的本機模型", 503)
    data = {
        "kind": kind, "mode": room["mode"], "direction": room["prompt"],
        "target_length": room["target"], "example_limit": limit, **context,
    }
    payload = {
        "model": config["model"], "stream": False, "format": "json", "think": False,
        "options": {"temperature": 0.45 if kind == "inline" else 0.7, "num_predict": 130 if kind == "inline" else 1400},
        "messages": [{"role": "system", "content": GLOBAL_PROMPT}, {"role": "user", "content": encode(data)}],
    }
    require(analysis.MODEL_LOCK.acquire(blocking=lock), "本機模型正忙，可稍後再試", 429)
    try:
        with db() as c:
            current = c.execute("SELECT * FROM writing_rooms WHERE id=?", (room["id"],)).fetchone()
            require(current and current["policy"] != "off", "助教已關閉", 409)
            if job_id:
                job = c.execute("SELECT status FROM writing_jobs WHERE id=?", (job_id,)).fetchone()
                require(job and job["status"] == "running", "這次呼叫已取消", 409)
            if kind == "observe":
                require(current["policy"] == "active" and current["activity"] == room["activity"]
                        and current["paused_until"] <= time.time(), "這次觀察已失效", 409)
            if kind == "inline":
                require(current["suggestion_limit"] > 0, "這個房間已關閉行內續寫", 409)
        response = model_slots.chat(payload, config)
        result = decode(response["message"]["content"])
        require(isinstance(result, dict), "助教回傳格式錯誤", 502)
        return result
    except WritingError:
        raise
    except Exception as exc:
        raise WritingError(503, "本機模型未就緒或沒有回傳可用內容") from exc
    finally:
        analysis.MODEL_LOCK.release()


def complete(room_id, user, body):
    with db() as c:
        room = access(c, room_id, user)
        require_editable(c, room_id)
        require(room["policy"] != "off", "這個房間已關閉助教", 409)
        doc = document(c, room_id, body.get("doc"))
        references = tutor_references(c, room_id, 320)
    before = body.get("before")
    require(isinstance(before, str) and 1 <= len(before) <= 2400, "請先寫一些上文")
    limit = min(8, room["suggestion_limit"])
    if not limit or re.search(r"[\n。？！?.!]\s*$", before):
        return {"text": ""}
    result = assist(room, "inline", {"chapter": doc["title"], "before_cursor": before, "materials": references}, limit, lock=False)
    suggestion = result.get("text", "")
    if not isinstance(suggestion, str):
        return {"text": ""}
    suggestion = re.split(r"[\r\n。！？.!?]", suggestion, maxsplit=1)[0].rstrip()
    with db() as c:
        latest = access(c, room_id, user)
        if latest["policy"] == "off":
            return {"text": ""}
        limit = min(limit, latest["suggestion_limit"])
    return {"text": suggestion[:limit]}


def tutor_references(c, room_id, excerpt_limit):
    return [
        {"title": ref["title"], "locator": ref["locator"], "excerpt": ref["excerpt"][:excerpt_limit]}
        for ref in room_references(c, room_id)
    ]


def context_for(c, room, requested=None):
    room_id = room["id"]
    docs = c.execute("""
        SELECT title,body FROM writing_docs WHERE room_id=?
        ORDER BY id= ? DESC,edited_at DESC,rowid DESC LIMIT 4
    """, (room_id, requested["doc_id"] if requested else "")).fetchall()
    return {
        "materials": tutor_references(c, room_id, 850),
        "drafts": [{"title": d["title"], "text": d["body"][-1600:]} for d in docs],
        "discussion": [
            {"author": m["author"], "kind": m["kind"], "body": m["body"][:500], "quote": m["quote"]}
            for m in messages(c, room_id, 10)
        ],
        "request": {"body": requested["body"], "quote": requested["quote"]} if requested else None,
    }


def should_speak(result, context):
    evidence = result.get("evidence")
    if result.get("action") != "speak" or not isinstance(evidence, str) or len(evidence.strip()) < 4:
        return False
    reply = result.get("reply")
    if not isinstance(reply, str) or not reply.rstrip().endswith(("？", "?")):
        return False
    sources = [d["text"] for d in context["drafts"]] + [m["body"] for m in context["discussion"] if m["kind"] == "human"]
    return any(evidence in source for source in sources)


def requested_example(message):
    text = message.split("@助教", 1)[-1]
    if re.search(r"(?:不用|不必|不要|無須|請別|別)[^。！？\n]{0,8}" + EXAMPLE_ACTION, text):
        return False
    return bool(re.search(EXAMPLE_ACTION, text) or re.search(r"\b(?:continue|rewrite|draft|give an example)\b", text, re.I))


def publish_tutor(c, room_id, result, kind, limit):
    reply = field(result.get("reply"), 1000, "助教回覆")
    example = result.get("example", "")
    example = example.strip()[:limit] if isinstance(example, str) and kind == "tutor" else ""
    c.execute("""
        INSERT INTO writing_messages(room_id,kind,body,example,created_at) VALUES(?,?,?,?,?)
    """, (room_id, kind, reply, example, time.time()))


def tutor_step():
    now = time.time()
    with db() as c:
        c.execute("BEGIN IMMEDIATE")
        job = c.execute("SELECT * FROM writing_jobs WHERE status='queued' ORDER BY created_at LIMIT 1").fetchone()
        if job:
            room = c.execute("SELECT * FROM writing_rooms WHERE id=?", (job["room_id"],)).fetchone()
            if room["policy"] == "off":
                c.execute("UPDATE writing_jobs SET status='cancelled' WHERE id=?", (job["id"],))
                return
            c.execute("UPDATE writing_jobs SET status='running' WHERE id=?", (job["id"],))
            requested = c.execute("SELECT * FROM writing_messages WHERE seq=?", (job["message_seq"],)).fetchone()
            context = context_for(c, room, requested)
        else:
            room = c.execute("""
                SELECT * FROM writing_rooms WHERE policy='active' AND activity>checked_activity
                    AND activity BETWEEN ? AND ? AND checked_at<=? AND spoken_at<=? AND paused_until<=?
                ORDER BY activity LIMIT 1
            """, (now-900, now-OBSERVE_DELAY, now-OBSERVE_GAP, now-SPEAK_GAP, now)).fetchone()
            if not room:
                return
            c.execute("UPDATE writing_rooms SET checked_activity=activity,checked_at=? WHERE id=?", (now, room["id"]))
            context = context_for(c, room)
    try:
        limit = room["suggestion_limit"] if job and requested_example(requested["body"]) else 0
        result = assist(room, "called" if job else "observe", context, limit, job_id=job["id"] if job else None)
        with db() as c:
            c.execute("BEGIN IMMEDIATE")
            latest = c.execute("SELECT * FROM writing_rooms WHERE id=?", (room["id"],)).fetchone()
            if job:
                status = c.execute("SELECT status FROM writing_jobs WHERE id=?", (job["id"],)).fetchone()["status"]
                if latest["policy"] != "off" and status == "running":
                    publish_tutor(c, room["id"], result, "tutor", min(limit, latest["suggestion_limit"]))
                    c.execute("UPDATE writing_jobs SET status='done' WHERE id=?", (job["id"],))
            elif (latest["policy"] == "active" and latest["activity"] == room["activity"]
                  and latest["paused_until"] <= time.time() and should_speak(result, context)):
                publish_tutor(c, room["id"], result, "observation", 0)
                c.execute("UPDATE writing_rooms SET spoken_at=? WHERE id=?", (time.time(), room["id"]))
    except WritingError:
        if job:
            with db() as c:
                c.execute("UPDATE writing_jobs SET status='failed' WHERE id=? AND status='running'", (job["id"],))


def worker():
    with db() as c:
        c.execute("UPDATE writing_jobs SET status='queued' WHERE status='running'")
    while not STOP.wait(1.25):
        tutor_step()
