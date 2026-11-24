"""Writing Studio concurrency, access control, and tutor boundaries over HTTP."""
import base64
import importlib.util
import threading
import time
import unittest
from unittest.mock import patch

import test_workflow
from test_workflow import Client
import writing
from storage import db


@unittest.skipUnless(importlib.util.find_spec("pycrdt"), "install requirements-writing.txt")
class WritingStudio(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        test_workflow.Workflow.setUpClass.__func__(cls)
        cls.owner = Client(cls.base)
        cls.editor = Client(cls.base)
        cls.stranger = Client(cls.base)
        cls.owner.call("/api/setup", {"email": "owner", "name": "主持人", "password": "QA-only-password123!"})
        cls.owner.login("owner")
        for account, client in (("editor", cls.editor), ("stranger", cls.stranger)):
            cls.owner.call("/api/admin/learners", {"email": account, "name": account, "password": "QA-only-password123!"})
            client.login(account)

    @classmethod
    def tearDownClass(cls):
        test_workflow.Workflow.tearDownClass.__func__(cls)

    def create_room(self, **settings):
        room = {"title": "月台", "mode": "themed", "prompt": "以一封晚到的信開場", "target": 250, "policy": "called", "suggestion_limit": 4}
        room.update(settings)
        root = self.owner.call("/api/writing/rooms", room)["id"]
        path = "/api/writing/rooms/" + root
        first = self.owner.call(path)["docs"][0]["id"]
        return room, path, first

    def test_teacher_publishes_private_paragraph_assignments(self):
        path = "/api/writing/teacher"
        self.editor.call(path, expected=403)
        students = [client.call("/api/session")["user"]["id"] for client in (self.editor, self.stranger)]
        settings = {
            "title": "一段話寫雨景", "mode": "paragraph", "prompt": "寫出觀察到的景象。",
            "policy": "called", "distribution": "individual",
        }
        self.owner.call(path, {**settings, "students": []}, expected=400)
        assignment = self.owner.call(path, {**settings, "students": students})["id"]
        listing = self.owner.call(path)["assignments"]
        self.assertEqual(next(row for row in listing if row["id"] == assignment)["student_count"], 2)
        result = self.owner.call(path + "?room=" + assignment)
        rooms = {student["student_id"]: student["room_id"] for student in result["students"]}
        self.assertNotEqual(rooms[students[0]], rooms[students[1]])
        target = "/api/writing/rooms/"
        received = self.editor.call(target + rooms[students[0]])
        self.assertEqual(received["room"]["mode"], "paragraph")
        self.assertEqual(received["docs"][0]["title"], "段落作答")
        self.editor.call(target + rooms[students[1]], expected=404)
        self.editor.call(target + assignment, expected=404)
        self.owner.call(target + assignment + "/settings", {**settings, "target": 130})
        self.assertEqual(self.editor.call(target + rooms[students[0]])["room"]["target"], 130)

        group = self.owner.call(path, {**settings, "distribution": "group", "students": students})["id"]
        self.assertEqual(self.editor.call(target + group)["docs"], self.stranger.call(target + group)["docs"])

    def test_guided_topic_submission_feedback_and_revision(self):
        from pycrdt import Doc, Text

        generated = {
            "title": "下雨的一刻", "situation": "雨落在放學路上。", "task": "用一段寫下你看到的變化。",
            "steps": ["先選一個細節。", "找一句能帶出主旨的句子。"], "checks": ["每句都圍繞同一個觀察嗎？"],
        }
        parameters = {"instruction": "引導學生以雨景為主題", "mode": "themed"}
        with patch.object(writing, "teacher_model", return_value=generated) as model:
            self.editor.call("/api/writing/generate-topic", parameters, expected=403)
            topic = self.owner.call("/api/writing/generate-topic", parameters)
        model.assert_called_once()
        self.assertIn("引導步驟", topic["prompt"])
        self.assertIn("自我檢查", topic["prompt"])

        student = self.editor.call("/api/session")["user"]["id"]
        assign = "/api/writing/teacher"
        assignment = self.owner.call(assign, {
            **topic, "mode": "themed", "policy": "called", "distribution": "individual", "students": [student],
        })["id"]
        room_id = self.owner.call(assign + "?room=" + assignment)["students"][0]["room_id"]
        path = "/api/writing/rooms/" + room_id
        chapter = self.editor.call(path)["docs"][0]["id"]
        self.editor.call(path + "/submit", {"doc": chapter, "version": 0}, expected=400)
        document = Doc()
        text = document.get("body", type=Text)
        text += "雨水把路燈的光拖成一條線。"
        sync = self.editor.call(path + "/sync", {"doc": chapter, "update": base64.b64encode(document.get_update()).decode()})
        sent = self.editor.call(path + "/submit", {"doc": chapter, "version": sync["version"]})["submission"]
        self.assertEqual(self.editor.call(path + "/submit", {"doc": chapter, "version": sync["version"]})["submission"]["id"], sent["id"])
        self.editor.call(path + "/sync", {"doc": chapter, "update": base64.b64encode(document.get_update()).decode()}, expected=409)

        review = "/api/writing/review"
        self.editor.call(review + "?id=" + sent["id"], expected=403)
        record = self.owner.call(review + "?id=" + sent["id"])["submission"]
        self.assertEqual(record["snapshot"]["drafts"][0]["body"], str(text))
        with patch.object(writing, "teacher_model", return_value={"score": 79, "feedback": "再寫清楚人物的位置。"}):
            draft = self.owner.call("/api/writing/draft-review", {"id": sent["id"]})
        self.assertEqual(draft["score"], 79)
        self.assertIsNone(self.editor.call(path)["submission"]["score"])
        self.owner.call(review, {"id": sent["id"], "score": 83, "feedback": "可以用一句話收束觀察。"})
        self.assertEqual(self.editor.call(path)["submission"]["score"], 83)
        self.owner.call(review, {"id": sent["id"], "action": "reopen"})
        self.assertIsNotNone(self.editor.call(path)["submission"]["reopened_at"])
        text += " 我沿著光走回家。"
        sync = self.editor.call(path + "/sync", {"doc": chapter, "update": base64.b64encode(document.get_update()).decode()})
        revised = self.editor.call(path + "/submit", {"doc": chapter, "version": sync["version"]})["submission"]
        self.assertEqual(revised["revision"], 2)
        self.assertEqual(self.owner.call(review + "?id=" + sent["id"])["submission"]["snapshot"], record["snapshot"])

    def test_permissions_simultaneous_edits_and_version_restore(self):
        from pycrdt import Doc, Text

        _, path, first = self.create_room()
        self.stranger.call(path, expected=404)
        self.editor.call(path + "/sync", {"doc": first, "update": "AAA="}, expected=404)
        self.owner.call(path + "/invite", {"account": "editor"}, csrf=False, expected=403)
        self.owner.call(path + "/invite", {"account": "editor"})
        self.editor.call(path + "/invite", {"account": "stranger"}, expected=403)
        chapter = self.editor.call(path + "/chapter", {"title": "轉折"})["id"]
        self.assertIn(chapter, [file["id"] for file in self.owner.call(path)["docs"]])

        def local_update(fragment):
            doc = Doc()
            text = doc.get("body", type=Text)
            text += fragment
            return base64.b64encode(doc.get_update()).decode("ascii")

        updates = [local_update("那封信"), local_update("來晚了")]
        barrier = threading.Barrier(2)
        responses = []

        def submit(client, value):
            barrier.wait()
            responses.append(client.call(path + "/sync", {"doc": first, "update": value}))

        workers = [threading.Thread(target=submit, args=(client, value)) for client, value in zip((self.owner, self.editor), updates)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual(len(responses), 2)
        shared = self.owner.call(path + "?doc=" + first)["shared"]
        merged = Doc()
        merged.apply_update(base64.b64decode(shared["state"]))
        text = merged.get("body", type=Text)
        self.assertIn(str(text), {"那封信來晚了", "來晚了那封信"})
        repeated = self.owner.call(path + "/sync", {"doc": first, "update": updates[0]})
        self.assertEqual(repeated["version"], shared["version"])
        self.owner.call(path + "/sync", {"doc": first, "update": "////"}, expected=400)

        version = self.owner.call(path + "/snapshot", {"doc": first, "label": "小組初稿"})["id"]
        text += "。"
        self.editor.call(path + "/sync", {"doc": first, "update": base64.b64encode(merged.get_update()).decode("ascii")})
        comparison = self.owner.call(f"{path}/version?doc={first}&id={version}")
        self.assertEqual(comparison["current"], comparison["saved"] + "。")
        self.editor.call(path + "/restore", {"doc": first, "id": version, "version": comparison["version"]}, expected=403)
        self.owner.call(path + "/restore", {"doc": first, "id": version, "version": comparison["version"] - 1}, expected=409)
        self.owner.call(path + "/restore", {"doc": first, "id": version, "version": comparison["version"]})
        restored = self.owner.call(f"{path}/version?doc={first}&id={version}")
        self.assertEqual(restored["current"], comparison["saved"])

    def test_tutor_length_on_demand_and_opt_in_observation(self):
        room, path, first = self.create_room()
        with patch.object(writing, "assist", return_value={"text": "躲進樹林接著。再來"}):
            reply = self.owner.call(path + "/complete", {"doc": first, "before": "於是他只好"})
        self.assertEqual(reply["text"], "躲進樹林")
        with patch.object(writing, "assist") as assist:
            self.assertEqual(self.owner.call(path + "/complete", {"doc": first, "before": "他已經走了。"}), {"text": ""})
            assist.assert_not_called()
        self.owner.call(path + "/message", {"text": "先討論寄信的人是誰", "doc": first})
        with patch.object(writing, "assist") as assist:
            writing.tutor_step()
            assist.assert_not_called()

        self.owner.call(path + "/message", {"text": "@助教 請示範幾個字", "doc": first})
        result = {"action": "speak", "reply": "靠，這封信拖得夠久。開頭要先讓誰看到？", "example": "郵差終於來了"}
        with patch.object(writing, "assist", return_value=result):
            writing.tutor_step()
        conversation = self.owner.call(path)["messages"]
        self.assertEqual(conversation[-1]["example"], "郵差終於")
        self.assertEqual(conversation[-2]["tutor_status"], "done")
        self.owner.call(path + "/message", {"text": "@助教 這個轉折需要補線索嗎？不用示範"})
        with patch.object(writing, "assist", return_value=result):
            writing.tutor_step()
        self.assertEqual(self.owner.call(path)["messages"][-1]["example"], "")

        self.owner.call(path + "/settings", {**room, "policy": "active"})
        self.owner.call(path + "/message", {"text": "我們卡在兩種結局，誰都說不服誰", "doc": first})
        room_id = path.split("/")[-1]
        with db() as c:
            c.execute("UPDATE writing_rooms SET activity=? WHERE id=?", (time.time() - 15, room_id))
            c.execute("UPDATE writing_rooms SET checked_activity=0 WHERE id=?", (room_id,))
        self.assertFalse(writing.should_speak(
            {**result, "reply": "看起來你們卡在結局。", "evidence": "卡在兩種結局"},
            {"drafts": [], "discussion": [{"kind": "human", "body": "我們卡在兩種結局"}]},
        ))
        with patch.object(writing, "assist", return_value={**result, "evidence": "卡在兩種結局"}):
            writing.tutor_step()
        self.assertEqual(self.owner.call(path)["messages"][-1]["kind"], "observation")

        self.owner.call(path + "/pause", {})
        with patch.object(writing, "assist") as assist:
            writing.tutor_step()
            assist.assert_not_called()
        self.owner.call(path + "/message", {"text": "@助教 可以看一下嗎？"})
        self.owner.call(path + "/settings", {**room, "policy": "off"})
        self.assertEqual(self.owner.call(path)["messages"][-1]["tutor_status"], "cancelled")
        self.assertFalse(self.owner.call(path + "/message", {"text": "@助教 你在嗎？"})["queued"])
        self.owner.call(path + "/complete", {"doc": first, "before": "於是他只好"}, expected=409)

    def test_teacher_material_range_and_student_workspaces(self):
        text = "雨停後，港口的商販把篷布收回倉庫，孩子在防波堤邊等第一盞漁燈亮起。這段後面是教師自己的延伸筆記。"
        excerpt = "孩子在防波堤邊等第一盞漁燈亮起。"
        material = self.owner.call("/api/admin/exam/materials", {
            "title": "港口觀察", "subject": "Chinese", "text": text,
        })["id"]
        detail = "/api/writing/material?id=" + material
        self.assertEqual(self.owner.call(detail)["text"], text)
        self.editor.call(detail, expected=403)
        policy = {"title": "港口練習", "mode": "themed", "policy": "called"}
        references = [{"material_id": material, "excerpt": excerpt}]
        self.editor.call("/api/writing/rooms", {**policy, "references": references}, expected=403)
        self.editor.call("/api/writing/rooms", policy, expected=403)
        personal = self.editor.call("/api/writing/rooms", {"title": "我的草稿", "policy": "off"})["id"]
        personal_path = "/api/writing/rooms/" + personal
        self.assertEqual(self.editor.call(personal_path)["room"]["mode"], "free")
        self.editor.call(personal_path + "/invite", {"account": "stranger"}, expected=403)
        self.editor.call(personal_path + "/settings", {**policy, "references": references}, expected=403)

        self.owner.call("/api/writing/rooms", {
            **policy, "references": [{"material_id": material, "excerpt": "教材沒有這句話"}],
        }, expected=400)
        room_id = self.owner.call("/api/writing/rooms", {**policy, "references": references})["id"]
        path = "/api/writing/rooms/" + room_id
        self.editor.call(path, expected=404)
        self.owner.call(path + "/invite", {"account": "editor"})
        state = self.editor.call(path)
        self.assertEqual(state["room"]["references"][0]["excerpt"], excerpt)
        self.assertNotIn("教師自己的延伸筆記", str(state))
        self.editor.call(path + "/settings", policy, expected=403)
        with db() as c:
            room = writing.access(c, room_id, {"id": state["people"][0]["id"]})
            self.assertEqual(writing.context_for(c, room)["materials"][0]["excerpt"], excerpt)
        self.owner.call("/api/admin/exam/archive-material", {"id": material})
        self.owner.call(detail, expected=404)
        self.owner.call(path + "/settings", {**policy, "references": references})
        self.assertEqual(self.editor.call(path)["room"]["references"][0]["excerpt"], excerpt)
