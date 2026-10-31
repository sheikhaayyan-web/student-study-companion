import os
import tempfile
import unittest
from unittest.mock import patch

_TEST_DATA = tempfile.TemporaryDirectory()
os.environ["TALIB_DB_PATH"] = os.path.join(_TEST_DATA.name, "integration.sqlite3")
os.environ["TALIB_GENERATED_DIR"] = os.path.join(_TEST_DATA.name, "exports")

from fastapi.testclient import TestClient

from backend.app import app
from backend.services import auth_service
from backend.services import quiz_engine, syllabus_parser
from backend.services.quiz_engine import NORMALIZATION_15_MCQS


class AuthenticationFlowTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(app)
        self.external_ai_patches = [
            patch.object(quiz_engine, "genai_client", None),
            patch.object(syllabus_parser, "genai_client", None),
        ]
        for active_patch in self.external_ai_patches:
            active_patch.start()
        self.email = f"student-{os.urandom(8).hex()}@example.test"
        self.password = "Correct horse battery staple 42!"

    def tearDown(self):
        for active_patch in self.external_ai_patches:
            active_patch.stop()

    def signup(self, client=None):
        target = client or self.client
        response = target.post("/api/auth/signup", json={
            "email": self.email,
            "password": self.password,
            "name": "Test Student",
            "level": "bachelors",
        })
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["user"]

    @staticmethod
    def make_pdf(text):
        stream = f"BT /F1 12 Tf 40 200 Td ({text}) Tj ET".encode("ascii")
        objects = [
            b"<< /Type /Catalog /Pages 2 0 R >>",
            b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
            b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 300 300] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
            b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
            b"<< /Length " + str(len(stream)).encode("ascii") + b" >>\nstream\n" + stream + b"\nendstream",
        ]
        pdf = bytearray(b"%PDF-1.4\n")
        offsets = [0]
        for index, obj in enumerate(objects, start=1):
            offsets.append(len(pdf))
            pdf.extend(f"{index} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
        xref_offset = len(pdf)
        pdf.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode("ascii"))
        for offset in offsets[1:]:
            pdf.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
        pdf.extend(f"trailer\n<< /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF".encode("ascii"))
        return bytes(pdf)

    def test_account_progress_and_session_persist_across_clients(self):
        self.assertEqual(self.client.get("/api/dashboard").status_code, 401)
        user = self.signup()

        dashboard = self.client.get("/api/dashboard").json()
        self.assertEqual(dashboard["profile"]["user_id"], user["id"])
        self.assertEqual(dashboard["courses"], [])
        self.assertEqual(dashboard["stats"]["study_hours"], 0)
        self.assertEqual(dashboard["stats"]["streak_days"], 0)
        self.assertEqual(dashboard["stats"]["quiz_attempts_count"], 0)

        profile = self.client.post("/api/profile", json={
            "name": "Saved Student",
            "institution": "Example University",
            "degree_major": "Computer Science",
            "current_semester": 3,
            "language": "ur",
        })
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["profile"]["preferred_language"], "ur")

        syllabus = self.client.post("/api/syllabus/upload", json={
            "course_name": "Database Systems",
            "content": "Module 1: Foundations\nNormalization and functional dependencies",
        })
        self.assertEqual(syllabus.status_code, 200, syllabus.text)
        dashboard = self.client.get("/api/dashboard?user_id=somebody-else").json()
        self.assertEqual(len(dashboard["courses"]), 1)
        topic = dashboard["topics"][0]

        quiz = self.client.post("/api/quiz/session", json={
            "topic": topic["title"], "topic_id": topic["id"]
        })
        self.assertEqual(quiz.status_code, 200, quiz.text)
        self.assertNotIn("correct_index", quiz.json()["questions"][0])
        self.assertNotIn("explanation", quiz.json()["questions"][0])
        answers = {str(item["id"]): item["correct_index"] for item in NORMALIZATION_15_MCQS}
        result = self.client.post("/api/quiz/submit", json={
            "session_id": quiz.json()["session_id"], "answers": answers
        })
        self.assertEqual(result.status_code, 200, result.text)
        self.assertTrue(result.json()["passed"])

        token = self.client.cookies.get("talib_session")
        refreshed_client = TestClient(app)
        refreshed_client.cookies.set("talib_session", token)
        restored = refreshed_client.get("/api/dashboard").json()
        self.assertEqual(restored["profile"]["name"], "Saved Student")
        self.assertEqual(restored["stats"]["quiz_attempts_count"], 1)
        self.assertEqual(restored["stats"]["passed_quizzes_count"], 1)
        self.assertEqual(restored["stats"]["quiz_mastery_pct"], 100)
        self.assertEqual(restored["courses"][0]["completed_topics"], 1)

        refreshed_client.post("/api/auth/logout")
        self.assertEqual(refreshed_client.get("/api/dashboard").status_code, 401)

    def test_accounts_cannot_read_or_submit_for_another_users_topic(self):
        self.signup()
        course = self.client.post("/api/syllabus/upload", json={
            "course_name": "Private Course", "content": "Chapter 1: Private Topic\nPrivate course first topic"
        })
        self.assertEqual(course.status_code, 200, course.text)
        topic_id = self.client.get("/api/dashboard").json()["topics"][0]["id"]

        other_client = TestClient(app)
        other_email = f"other-{os.urandom(8).hex()}@example.test"
        response = other_client.post("/api/auth/signup", json={
            "email": other_email, "password": self.password, "name": "Other Student"
        })
        self.assertEqual(response.status_code, 201, response.text)
        denied = other_client.post("/api/quiz/session", json={
            "topic": "Private Topic", "topic_id": topic_id
        })
        self.assertEqual(denied.status_code, 404)
        self.assertEqual(other_client.get("/api/dashboard").json()["courses"], [])

    def test_password_reset_invalidates_old_sessions_and_is_one_time(self):
        self.signup()
        with patch.object(auth_service, "email_is_configured", return_value=True), patch.object(auth_service, "_send_reset_email") as send_email:
            request = self.client.post("/api/auth/forgot-password", json={"email": self.email})
        self.assertEqual(request.status_code, 200, request.text)
        token = send_email.call_args.args[1]
        reset = self.client.post("/api/auth/reset-password", json={
            "token": token, "password": "New correct horse battery 73!"
        })
        self.assertEqual(reset.status_code, 200, reset.text)
        self.assertIsNone(self.client.get("/api/auth/me").json()["user"])
        self.assertEqual(self.client.post("/api/auth/reset-password", json={
            "token": token, "password": "Another correct horse battery 84!"
        }).status_code, 400)
        login = self.client.post("/api/auth/login", json={
            "email": self.email, "password": "New correct horse battery 73!"
        })
        self.assertEqual(login.status_code, 200, login.text)

    def test_duplicate_email_and_short_password_are_rejected(self):
        self.signup()
        duplicate = self.client.post("/api/auth/signup", json={
            "email": self.email, "password": self.password, "name": "Duplicate"
        })
        self.assertEqual(duplicate.status_code, 409)
        short_password = self.client.post("/api/auth/signup", json={
            "email": f"short-{os.urandom(8).hex()}@example.test",
            "password": "short",
            "name": "Short Password",
        })
        self.assertEqual(short_password.status_code, 422)

    def test_repeated_failed_logins_are_throttled(self):
        self.signup()
        for _ in range(10):
            failed = self.client.post("/api/auth/login", json={"email": self.email, "password": "Wrong password value"})
            self.assertEqual(failed.status_code, 401)
        limited = self.client.post("/api/auth/login", json={"email": self.email, "password": self.password})
        self.assertEqual(limited.status_code, 429)
        self.assertEqual(limited.headers["retry-after"], "900")

    def test_focus_activity_cannot_be_forged_or_used_across_accounts(self):
        self.signup()
        started = self.client.post("/api/activity/focus/start", json={"duration_seconds": 1500})
        self.assertEqual(started.status_code, 200, started.text)
        session_id = started.json()["session_id"]
        too_early = self.client.post("/api/activity/focus/complete", json={"session_id": session_id})
        self.assertEqual(too_early.status_code, 409)
        self.assertEqual(self.client.get("/api/dashboard").json()["stats"]["study_hours"], 0)

        other_client = TestClient(app)
        other_client.post("/api/auth/signup", json={
            "email": f"other-{os.urandom(8).hex()}@example.test",
            "password": self.password,
            "name": "Other Student",
        })
        denied = other_client.post("/api/activity/focus/complete", json={"session_id": session_id})
        self.assertEqual(denied.status_code, 404)

    def test_studio_draft_and_exports_are_saved_per_account(self):
        self.signup()
        saved = self.client.put("/api/studio/draft", json={
            "topic": "Relational databases", "content": "# Relational databases\n\n## Overview\nStudent-authored draft text."
        })
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(self.client.get("/api/studio/draft").json()["topic"], "Relational databases")

        export = self.client.post("/api/studio/export/docx", json={
            "topic": "Relational databases", "content": "A saved and editable assignment draft."
        })
        self.assertEqual(export.status_code, 200, export.text)
        self.assertEqual(self.client.get(export.json()["download_url"]).status_code, 200)

        other_client = TestClient(app)
        other_client.post("/api/auth/signup", json={
            "email": f"other-{os.urandom(8).hex()}@example.test",
            "password": self.password,
            "name": "Other Student",
        })
        self.assertEqual(other_client.get("/api/studio/draft").json(), {"topic": "", "content": ""})
        self.assertEqual(other_client.get(export.json()["download_url"]).status_code, 404)

    def test_uploaded_documents_are_saved_and_private(self):
        self.signup()
        upload = self.client.post("/api/library/documents", files={
            "file": ("study-notes.pdf", self.make_pdf("Relational normalization example"), "application/pdf")
        })
        self.assertEqual(upload.status_code, 201, upload.text)
        document_id = upload.json()["id"]
        self.assertEqual(upload.json()["page_count"], 1)
        self.assertEqual(self.client.get("/api/library/documents").json()[0]["id"], document_id)

        other_client = TestClient(app)
        other_client.post("/api/auth/signup", json={
            "email": f"other-{os.urandom(8).hex()}@example.test",
            "password": self.password,
            "name": "Other Student",
        })
        denied = other_client.post("/api/library/ask", json={
            "document_id": document_id, "question": "Explain normalization"
        })
        self.assertEqual(denied.status_code, 404)


if __name__ == "__main__":
    unittest.main()
